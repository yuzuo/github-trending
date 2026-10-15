from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import logging
import json
import threading
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select, text, update

from .models import CollectionRun, SNAPSHOT_MODELS, Repository, WatchRun, MonitorRun, utcnow
from .sources import GitHubSource, RateLimited, SourceError
from .translation import Translator
from .history import save_trending_repository, translation_complete


TIMEZONE = ZoneInfo('Asia/Shanghai')
LOCK_KEY = 719436520
logger = logging.getLogger(__name__)


def save_repository(sessions, metadata, original, readme_path, row, day, translator):
    if row.get('source') == 'trending':
        return save_trending_repository(sessions, metadata, original, readme_path, row, day, translator)
    now = utcnow()
    source = row.get('source', 'search')
    digest = sha256(original.encode()).hexdigest() if original is not None else None
    with sessions.begin() as session:
        Snapshot = SNAPSHOT_MODELS[source]
        snapshot = session.scalar(select(Snapshot).where(Snapshot.repository_id == metadata['id'], Snapshot.date == day))
        if snapshot is not None:
            return True
        repo = session.get(Repository, metadata['id'])
        if repo is None:
            repo = Repository(**metadata, first_fetched_at=now,
                              translation_status='unconfigured' if source == 'trending' else 'not_required')
            session.add(repo)
            description_changed = True
        else:
            description_changed = repo.description != metadata['description']
            for key, value in metadata.items():
                setattr(repo, key, value)
        needs_translation = (description_changed or repo.translated_hash != digest
                             or repo.translation_status not in ('translated', 'missing')
                             or bool(metadata['description'] and not repo.description_zh))
        repo.last_fetched_at, repo.readme_original = now, original
        repo.readme_path, repo.readme_hash = readme_path, digest
        if source == 'search' and needs_translation and (repo.readme_zh or repo.description_zh):
            repo.translation_status = 'stale'
        Snapshot = SNAPSHOT_MODELS[source]
        snapshot = session.scalar(select(Snapshot).where(Snapshot.repository_id == repo.id,
                                  Snapshot.date == day))
        if snapshot is None:
            snapshot = Snapshot(repository_id=repo.id, date=day)
            session.add(snapshot)
        snapshot.daily_stars = row['daily_stars'] if source == 'trending' else None
        snapshot.trending_rank = row.get('rank', row.get('trending_rank'))
        snapshot.stars, snapshot.fetched_at = metadata['stars'], now
        session.flush()
        snapshot.details = {column.name: value.isoformat() if isinstance(value, datetime) else value
                            for column in Repository.__table__.columns
                            for value in [getattr(repo, column.name)]}
        snapshot.details.update(description_zh=None, readme_zh=None, translated_hash=None,
                                translation_status='not_required', translation_error=None)

    return True


class Collector:
    def __init__(self, engine, sessions, settings):
        self.engine, self.sessions, self.settings = engine, sessions, settings
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='collector')
        self.busy = threading.Lock()

    @contextmanager
    def lock(self):
        with self.engine.connect().execution_options(isolation_level='AUTOCOMMIT') as connection:
            acquired = connection.scalar(text('SELECT pg_try_advisory_lock(:key)'), {'key': LOCK_KEY})
            try:
                yield acquired
            finally:
                if acquired:
                    connection.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': LOCK_KEY})

    def recover(self):
        with self.lock() as acquired:
            if acquired:
                with self.sessions.begin() as session:
                    session.execute(update(CollectionRun).where(CollectionRun.status == 'running').values(
                        status='interrupted', finished_at=utcnow(), error='进程退出导致采集中断，可重新采集'))
                    session.execute(update(Repository).where(Repository.translation_status == 'pending').values(
                        translation_status='failed', translation_error='翻译因进程退出而中断，可重新采集'))

    def cooldown(self):
        with self.sessions() as session:
            values = [session.scalar(select(model.retry_at).where(model.retry_at > utcnow()).order_by(model.retry_at.desc()).limit(1))
                      for model in (CollectionRun, WatchRun, MonitorRun)]
            return max((value for value in values if value is not None), default=None)

    def start(self, kind='search'):
        if kind not in SNAPSHOT_MODELS:
            raise ValueError('Unknown source')
        if self.completed_today(kind=kind):
            return False
        if self.cooldown():
            return False
        if not self.busy.acquire(blocking=False):
            return False
        self.executor.submit(self._background, kind)
        return True

    def _background(self, kind):
        try:
            self.run(kind=kind)
        except Exception as exc:
            # Exception bodies can contain provider credentials or SQL parameters.
            logger.error('Collector failed: %s', type(exc).__name__)
        finally:
            self.busy.release()

    def completed_today(self, day=None, kind='trending'):
        day = day or utcnow().astimezone(TIMEZONE).date()
        with self.sessions() as session:
            complete = session.scalar(select(CollectionRun.id).where(CollectionRun.date == day,
                CollectionRun.source == kind, CollectionRun.status == 'success').limit(1)) is not None
            if kind == 'search':
                Snapshot = SNAPSHOT_MODELS[kind]
                if session.scalar(select(Snapshot.id).where(Snapshot.date == day, Snapshot.details_origin == 'legacy_backfill').limit(1)):
                    return True
            if complete and kind == 'trending' and self.settings.translation_enabled:
                Snapshot = SNAPSHOT_MODELS['trending']
                details = session.scalars(select(Snapshot.details).where(Snapshot.date == day)).all()
                return bool(details) and all(item and translation_complete(item) for item in details)
            return complete

    def due(self, now=None, startup=False, kind='search'):
        now = now or utcnow()
        local = now.astimezone(TIMEZONE)
        hour = self.settings.trending_collect_hour if kind == 'trending' else self.settings.collect_hour
        if local.hour < hour or self.completed_today(local.date(), kind):
            return False
        with self.sessions() as session:
            latest = session.scalar(select(CollectionRun).where(CollectionRun.date == local.date(), CollectionRun.source == kind).order_by(CollectionRun.id.desc()).limit(1))
            if latest and latest.status == 'running':
                return False
            if latest and latest.retry_at and latest.retry_at > now:
                return False
            if latest and latest.status in ('partial', 'failed', 'interrupted'):
                return now >= latest.started_at + timedelta(hours=1)
            if startup:
                return latest is None or (kind == 'trending' and not self.completed_today(local.date()))
            target = local.replace(hour=self.settings.trending_collect_hour if kind == 'trending' else self.settings.collect_hour, minute=0, second=0, microsecond=0)
            return local >= target and (latest is None or latest.started_at < target)

    def run(self, source=None, kind='search'):
        Snapshot = SNAPSHOT_MODELS[kind]
        with self.lock() as acquired:
            if not acquired:
                return False
            day = utcnow().astimezone(TIMEZONE).date()
            if self.completed_today(day, kind):
                return False
            with self.sessions.begin() as session:
                run = CollectionRun(date=day, source=kind)
                session.add(run)
                session.flush()
                run_id = run.id
            success, failed, errors, retry_at = 0, 0, [], None
            try:
                with httpx.Client(timeout=30, follow_redirects=True) as client:
                    source = source or GitHubSource(client, self.settings.github_token)
                    translator = Translator(client, self.settings.translation_base_url, self.settings.translation_model,
                                            self.settings.translation_api_key) if kind == 'trending' and self.settings.translation_enabled else None
                    with self.sessions() as session:
                        rows = session.scalar(select(CollectionRun.items).where(CollectionRun.date == day,
                            CollectionRun.source == kind, CollectionRun.items.is_not(None)).order_by(CollectionRun.id).limit(1))
                    if rows is None:
                        rows = source.search(self.settings.search_limit) if kind == 'search' else source.trending()
                    with self.sessions.begin() as session:
                        session.get(CollectionRun, run_id).items = json.loads(json.dumps(rows, default=lambda value: value.isoformat()))
                    for index, row in enumerate(rows):
                        try:
                            row = {**row, 'source': kind}
                            frozen = None
                            with self.sessions() as session:
                                frozen = session.scalar(select(Snapshot).where(Snapshot.date == day,
                                    Snapshot.details['full_name'].astext == row['full_name']))
                            if frozen is not None:
                                metadata = {'id': frozen.repository_id}
                                original, path = None, None
                            else:
                                metadata = row['metadata'] if kind == 'search' else source.repository(row['full_name'])
                                metadata = {key: datetime.fromisoformat(value) if key in ('created_at', 'updated_at', 'pushed_at') and isinstance(value, str) else value for key, value in metadata.items()}
                                original, path = source.readme(metadata['full_name'])
                            translated = save_repository(self.sessions, metadata, original, path, row, day, translator)
                            if translated:
                                success += 1
                            else:
                                failed += 1
                                errors.append(f"{row['full_name']}: 资料已保存，翻译失败")
                        except RateLimited as exc:
                            failed += len(rows) - index
                            retry_at = datetime.fromtimestamp(exc.retry_at, timezone.utc)
                            errors.append(str(exc))
                            break
                        except SourceError as exc:
                            failed += 1
                            errors.append(f"{row['full_name']}: {exc}")
                        except Exception as exc:
                            failed += 1
                            errors.append(f"{row['full_name']}: 处理失败（{type(exc).__name__}）")
                        with self.sessions.begin() as session:
                            run = session.get(CollectionRun, run_id)
                            run.success_count, run.failure_count = success, failed
            except RateLimited as exc:
                failed += 1
                retry_at = datetime.fromtimestamp(exc.retry_at, timezone.utc)
                errors.append(str(exc))
            except SourceError as exc:
                failed += 1
                errors.append(str(exc))
            except Exception as exc:
                failed += 1
                errors.append(f'采集失败（{type(exc).__name__}）')
            with self.sessions.begin() as session:
                run = session.get(CollectionRun, run_id)
                run.success_count, run.failure_count = success, failed
                run.status = 'partial' if failed and success else 'failed' if failed else 'success'
                run.error, run.retry_at = '\n'.join(errors) or None, retry_at
                run.finished_at = utcnow()
            return True

    def close(self):
        self.executor.shutdown(wait=True)
