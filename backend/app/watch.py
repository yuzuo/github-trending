"""Crawler discovery and observations, independent of the frozen daily boards."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import httpx
from sqlalchemy import func, select, text, update

from .collector import TIMEZONE
from .models import WatchProject, WatchRun, WatchSample, utcnow
from .sources import GitHubSource, RateLimited, SourceError, validate_repo

CAPACITY = 200
CAPACITY_LOCK = 719436522
DISCOVERY_QUERIES = ('topic:web-scraping', 'topic:crawler', 'topic:data-extraction',
                     '"web scraping" in:name,description', '爬虫 in:name,description', '数据采集 in:name,description')


def repository_name(value):
    value = value.strip()
    if '://' in value:
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or parsed.netloc.lower() != 'github.com'
                or parsed.query or parsed.fragment):
            raise SourceError('请输入公开 GitHub 仓库地址或 owner/repo')
        value = parsed.path.lstrip('/').rstrip('/')
    if value.endswith('.git'):
        value = value[:-4]
    validate_repo(value)
    return value


def growth_metrics(samples, now=None):
    now = now or utcnow()
    result = dict(growth_24h=None, growth_7d=None, stale=True)
    if not samples:
        return result
    samples = sorted(samples, key=lambda item: item['fetched_at'])
    latest = samples[-1]
    result['stale'] = now - latest['fetched_at'] > timedelta(hours=12)
    for key, hours in (('growth_24h', 24), ('growth_7d', 168)):
        target = latest['fetched_at'] - timedelta(hours=hours)
        baseline = next((s for s in reversed(samples)
                         if target - timedelta(hours=6) <= s['fetched_at'] <= target), None)
        if baseline:
            result[key] = dict(delta=latest['stars']-baseline['stars'],
                               start=baseline['fetched_at'], end=latest['fetched_at'])
    return result


def ranking_key(item, sort):
    if sort == 'stars':
        return (-item['stars'], item['id'])
    growth = item[sort]
    return (growth is None, item['stale'], -(growth['delta'] if growth else 0), -item['stars'], item['id'])


def json_metadata(metadata):
    return {key: value.isoformat() if isinstance(value, datetime) else value for key, value in metadata.items()}


def capacity_lock(session):
    session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': CAPACITY_LOCK})


def active_count(session):
    return session.scalar(select(func.count()).select_from(WatchProject).where(WatchProject.hidden.is_(False)))


def discover_projects(source, progress=None, checkpoint=None):
    progress = progress or {}
    candidates = {int(key): value for key, value in progress.get('candidates', {}).items()}
    completed, errors = set(progress.get('completed', [])), []
    for query in DISCOVERY_QUERIES:
        for sort, count in (('stars', 30), ('updated', 20)):
            key = f'{query}|{sort}'
            if key in completed:
                continue
            try:
                response = source._get('https://api.github.com/search/repositories', params={
                    'q': f'{query} is:public fork:false archived:false',
                    'sort': sort, 'order': 'desc', 'per_page': count})
                data = response.json()
                if (data.get('incomplete_results') is not False or not isinstance(data.get('items'), list)
                        or not isinstance(data.get('total_count'), int)
                        or len(data['items']) != min(count, data['total_count'])):
                    raise SourceError('发现查询结果不完整')
                batch = {}
                for raw in data['items']:
                    if raw.get('private') is not False or raw.get('fork') is not False or raw.get('archived') is not False:
                        raise SourceError('发现查询返回范围外项目')
                    info = source.repository_metadata(raw)
                    if info['id'] in batch:
                        raise SourceError('发现查询返回重复项目')
                    batch[info['id']] = json_metadata(info)
                for repo_id, info in batch.items():
                    previous = candidates.get(repo_id)
                    reasons = set(previous['reasons'] if previous else []) | {query}
                    candidates[repo_id] = dict(metadata=info, reasons=sorted(reasons))
                completed.add(key)
                if checkpoint:
                    checkpoint(dict(completed=sorted(completed), candidates=candidates))
            except RateLimited:
                raise
            except (SourceError, ValueError, KeyError, TypeError, AttributeError):
                errors.append(f'发现查询未完成：{query} / {sort}')
    return sorted(candidates.values(), key=lambda row: (-row['metadata']['stars'], row['metadata']['id'])), errors


class WatchService:
    def __init__(self, collector):
        self.collector = collector
        self.sessions, self.settings = collector.sessions, collector.settings

    @contextmanager
    def source(self, supplied=None):
        if supplied is not None:
            yield supplied
        else:
            with httpx.Client(timeout=30, follow_redirects=True) as client:
                yield GitHubSource(client, self.settings.github_token)

    def recover(self):
        with self.collector.lock() as acquired:
            if acquired:
                with self.sessions.begin() as session:
                    session.execute(update(WatchRun).where(WatchRun.status == 'running').values(
                        status='interrupted', finished_at=utcnow(), error='进程退出导致监测中断，可重新更新'))

    def due(self, now=None):
        now = now or utcnow()
        with self.sessions() as session:
            latest = session.scalar(select(WatchRun).order_by(WatchRun.id.desc()))
            if latest is None:
                return True
            if latest.status == 'running' or (latest.retry_at and latest.retry_at > now):
                return False
            hours = 1 if latest.status in ('partial', 'failed', 'interrupted') else 6
            return now >= latest.started_at + timedelta(hours=hours)

    def needs_discovery(self):
        midnight = utcnow().astimezone(TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
        with self.sessions() as session:
            return session.scalar(select(WatchRun.id).where(
                WatchRun.started_at >= midnight, WatchRun.discovery_done.is_(True)).limit(1)) is None

    def start(self):
        if self.collector.cooldown() or not self.collector.busy.acquire(blocking=False):
            return False
        try:
            with self.collector.lock() as acquired:
                if not acquired:
                    self.collector.busy.release()
                    return False
                with self.sessions.begin() as session:
                    run_id = self.new_run(session).id
            self.collector.executor.submit(self._background, run_id)
            return True
        except Exception:
            self.collector.busy.release()
            raise

    def _background(self, run_id):
        try:
            self.run(run_id=run_id)
        finally:
            self.collector.busy.release()

    def save_observation(self, info, original, path, run_id=None, reasons=(), manual=False):
        now = utcnow()
        with self.sessions.begin() as session:
            capacity_lock(session)
            project = session.get(WatchProject, info['id'])
            if project is not None and project.hidden:
                return False
            if project is None:
                if active_count(session) >= CAPACITY:
                    return False
                project = WatchProject(id=info['id'], full_name=info['full_name'], details={},
                                       discovered_by=[], manual=manual, followed=manual)
                session.add(project)
            if run_id is not None and session.scalar(select(WatchSample.id).where(
                    WatchSample.project_id == info['id'], WatchSample.run_id == run_id)):
                return True
            project.full_name = info['full_name']
            project.details = {**json_metadata(info), 'readme_original': original, 'readme_path': path}
            project.fetched_at, project.last_error = now, None
            project.discovered_by = sorted(set(project.discovered_by) | set(reasons))
            project.manual = project.manual or manual
            session.flush()
            session.add(WatchSample(project_id=info['id'], run_id=run_id, stars=info['stars'], fetched_at=now))
        return True

    def record_cooldown(self, exc):
        with self.sessions.begin() as session:
            session.add(WatchRun(status='failed', finished_at=utcnow(), failure_count=1,
                error=str(exc), retry_at=datetime.fromtimestamp(exc.retry_at, timezone.utc)))

    def add_project(self, name, source=None):
        name = repository_name(name)
        if self.collector.cooldown() or not self.collector.busy.acquire(blocking=False):
            raise WatchConflict('采集正在执行或 GitHub 处于冷却期，请稍后重试')
        try:
            with self.collector.lock() as acquired:
                if not acquired:
                    raise WatchConflict('采集正在执行，请稍后重试')
                with self.source(source) as github:
                    info = github.repository(name, public_only=True)
                    with self.sessions.begin() as session:
                        capacity_lock(session)
                        existing = session.get(WatchProject, info['id'])
                        if existing:
                            if existing.hidden:
                                raise WatchConflict('项目已隐藏，请在“已隐藏”列表恢复')
                            existing.manual, existing.followed = True, True
                            return existing.id
                        if active_count(session) >= CAPACITY:
                            raise WatchConflict('监测项目已达 200 个，请先隐藏无关项目')
                    original, path = github.readme(info['full_name'])
                    if not self.save_observation(info, original, path, manual=True, reasons=['手动添加']):
                        raise WatchConflict('监测名额已满或项目已隐藏，请刷新列表')
                    return info['id']
        except RateLimited as exc:
            self.record_cooldown(exc)
            raise
        finally:
            self.collector.busy.release()

    def run(self, source=None, run_id=None, discover=None):
        if run_id is None:
            with self.sessions.begin() as session:
                run_id = self.new_run(session).id
        success, failed, errors, retry_at, discovery_done = 0, 0, [], None, False
        try:
            with self.collector.lock() as acquired:
                if not acquired:
                    raise SourceError('其他采集任务正在执行，请稍后重试')
                with self.source(source) as github:
                    # Existing tracked projects have priority over newly discovered candidates.
                    with self.sessions() as session:
                        cycle_started_at = session.get(WatchRun, run_id).cycle_started_at
                        existing = session.scalars(select(WatchProject).where(WatchProject.hidden.is_(False)).order_by(
                            WatchProject.manual.desc(), WatchProject.followed.desc(), WatchProject.id)).all()
                    for project in existing:
                        if (project.fetched_at >= cycle_started_at and not project.last_error
                                and utcnow() - project.fetched_at < timedelta(hours=6)):
                            continue
                        try:
                            info = github.repository(project.full_name, public_only=True)
                            if info['id'] != project.id:
                                raise SourceError('仓库身份已变化，保留原项目资料')
                            original, path = github.readme(info['full_name'])
                            if self.save_observation(info, original, path, run_id):
                                success += 1
                        except RateLimited:
                            raise
                        except Exception as exc:
                            failed += 1
                            message = str(exc) if isinstance(exc, SourceError) else f'处理失败（{type(exc).__name__}）'
                            errors.append(f'{project.full_name}: {message}')
                            with self.sessions.begin() as session:
                                session.get(WatchProject, project.id).last_error = message
                        self.progress(run_id, success, failed)
                    should_discover = discover if discover is not None else self.needs_discovery()
                    if should_discover:
                        with self.sessions() as session:
                            progress = session.get(WatchRun, run_id).discovery_progress
                        def checkpoint(value):
                            with self.sessions.begin() as session:
                                session.get(WatchRun, run_id).discovery_progress = value
                        candidates, search_errors = discover_projects(github, progress, checkpoint)
                        errors.extend(search_errors)
                        failed += len(search_errors)
                        discovery_done = not search_errors
                        for candidate in candidates:
                            info = candidate['metadata']
                            with self.sessions.begin() as session:
                                project = session.get(WatchProject, info['id'])
                                if project:
                                    project.discovered_by = sorted(set(project.discovered_by) | set(candidate['reasons']))
                                    continue
                                if active_count(session) >= CAPACITY:
                                    break
                            try:
                                current = github.repository(info['full_name'], public_only=True)
                                if current['id'] != info['id']:
                                    raise SourceError('仓库身份已变化，请等待下次发现')
                                info = current
                                original, path = github.readme(info['full_name'])
                                if self.save_observation(info, original, path, run_id, candidate['reasons']):
                                    success += 1
                            except RateLimited:
                                discovery_done = False
                                raise
                            except Exception as exc:
                                discovery_done = False
                                failed += 1
                                message = str(exc) if isinstance(exc, SourceError) else f'处理失败（{type(exc).__name__}）'
                                errors.append(f"{info['full_name']}: {message}")
                            self.progress(run_id, success, failed)
        except RateLimited as exc:
            failed += 1
            retry_at = datetime.fromtimestamp(exc.retry_at, timezone.utc)
            errors.append(str(exc))
        except Exception as exc:
            failed += 1
            errors.append(str(exc) if isinstance(exc, SourceError) else f'监测失败（{type(exc).__name__}）')
        finally:
            with self.sessions.begin() as session:
                run = session.get(WatchRun, run_id)
                run.status = 'partial' if failed and success else 'failed' if failed else 'success'
                run.finished_at, run.success_count, run.failure_count = utcnow(), success, failed
                run.error, run.retry_at, run.discovery_done = '\n'.join(errors) or None, retry_at, discovery_done
        return run_id

    def progress(self, run_id, success, failed):
        with self.sessions.begin() as session:
            run = session.get(WatchRun, run_id)
            run.success_count, run.failure_count = success, failed

    def new_run(self, session):
        now = utcnow()
        previous = session.scalar(select(WatchRun).order_by(WatchRun.id.desc()))
        retry = previous and previous.status in ('partial', 'failed', 'interrupted')
        cycle = previous.cycle_started_at if retry else now
        midnight = now.astimezone(TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
        progress = session.scalar(select(WatchRun.discovery_progress).where(
            WatchRun.started_at >= midnight, WatchRun.discovery_progress != {}).order_by(WatchRun.id.desc()).limit(1)) or {}
        run = WatchRun(cycle_started_at=cycle, discovery_progress=progress)
        session.add(run)
        session.flush()
        return run


class WatchConflict(Exception):
    pass
