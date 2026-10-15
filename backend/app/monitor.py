"""Public release and issue observations; source claims are never test verdicts."""
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from sqlalchemy import select, update

from .models import MonitorEvent, MonitorRun, MonitorState, WatchProject, utcnow
from .sources import SourceError, RateLimited, validate_repo
from .watch import WatchService


def fetch_page(source, name, kind, since=None, page=1):
    validate_repo(name)
    params = {'per_page': 30} if kind == 'release' else dict(
        per_page=100, state='all', sort='updated', direction='asc', since=since.isoformat(), page=page)
    response = source._get(f'https://api.github.com/repos/{name}/' + ('releases' if kind == 'release' else 'issues'), params=params)
    try:
        raw = response.json()
        if not isinstance(raw, list):
            raise ValueError('expected list')
        items = []
        for row in raw:
            if not isinstance(row, dict):
                raise ValueError('expected object')
            if kind == 'issue' and 'pull_request' in row:
                continue
            if kind == 'release' and row.get('draft') is True:
                continue
            source_id = row['id']
            if type(source_id) is not int or source_id <= 0:
                raise ValueError('invalid id')
            if kind == 'release':
                if row.get('draft') is not False or type(row.get('prerelease')) is not bool:
                    raise ValueError('invalid release flags')
                tag = row['tag_name']
                if not isinstance(tag, str) or not tag:
                    raise ValueError('missing tag')
                title = row.get('name') or tag
                status = 'prerelease' if row['prerelease'] else 'published'
                url, labels, date = f'https://github.com/{name}/releases/tag/{quote(tag, safe="")}', [], row['published_at']
            else:
                if row['state'] not in ('open', 'closed') or type(row['number']) is not int or row['number'] <= 0:
                    raise ValueError('invalid issue')
                title, status = row['title'], row['state']
                url, date = f'https://github.com/{name}/issues/{row["number"]}', row['updated_at']
                labels = sorted({label['name'] for label in row['labels']})
                if not all(isinstance(label, str) for label in labels):
                    raise ValueError('invalid labels')
            body = row.get('body') or ''
            if not isinstance(title, str) or not isinstance(body, str):
                raise ValueError('invalid text')
            source_at = datetime.fromisoformat(date.replace('Z', '+00:00'))
            if source_at.tzinfo is None:
                raise ValueError('date requires timezone')
            items.append(dict(kind=kind, source_id=source_id, title=title, body=body,
                              url=url, status=status, labels=labels, source_at=source_at))
        return items, 'next' in response.links
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise SourceError('GitHub 动态格式异常，保留已保存记录和同步进度') from exc


def save_events(session, project_id, items, baseline):
    now = utcnow()
    for item in items:
        event = session.scalar(select(MonitorEvent).where(
            MonitorEvent.project_id == project_id, MonitorEvent.kind == item['kind'],
            MonitorEvent.source_id == item['source_id']).with_for_update())
        changed = event is None or any(getattr(event, key) != item[key] for key in ('title', 'body', 'status', 'labels'))
        if event is None:
            event = MonitorEvent(project_id=project_id, **item, history=[], unread=not baseline)
            session.add(event)
        if changed:
            event.history = (event.history + [dict(at=now.isoformat(), status=item['status'],
                title=item['title'], change='baseline' if baseline and not event.history else 'observed')])[-20:]
            event.changed_at = now
            if not baseline:
                event.unread = True
        for key, value in item.items():
            setattr(event, key, value)
        session.flush()


class MonitorService:
    def __init__(self, collector):
        self.collector, self.sessions = collector, collector.sessions
        self.watch = WatchService(collector)

    def recover(self):
        with self.collector.lock() as acquired:
            if acquired:
                with self.sessions.begin() as session:
                    session.execute(update(MonitorRun).where(MonitorRun.status == 'running').values(
                        status='interrupted', finished_at=utcnow(), error='进程退出，下一轮从已保存分页继续'))

    def due(self):
        now = utcnow()
        with self.sessions() as session:
            latest = session.scalar(select(MonitorRun).order_by(MonitorRun.id.desc()))
            if latest and (latest.status == 'running' or (latest.retry_at and latest.retry_at > now)
                           or now < latest.started_at + timedelta(hours=1)):
                return False
            return session.scalar(select(WatchProject.id).outerjoin(MonitorState).where(
                WatchProject.followed.is_(True), WatchProject.hidden.is_(False),
                (MonitorState.checked_at.is_(None)) | (MonitorState.checked_at < now-timedelta(hours=6))).limit(1)) is not None

    def start(self, force=False):
        if self.collector.cooldown() or not self.collector.busy.acquire(blocking=False):
            return False
        try:
            with self.collector.lock() as acquired:
                if not acquired:
                    self.collector.busy.release()
                    return False
                with self.sessions.begin() as session:
                    run = MonitorRun()
                    session.add(run)
                    session.flush()
                    run_id = run.id
            self.collector.executor.submit(self._background, run_id, force)
            return True
        except Exception:
            self.collector.busy.release()
            raise

    def _background(self, run_id, force):
        try:
            self.run(run_id=run_id, force=force)
        finally:
            self.collector.busy.release()

    def check_project(self, project, source):
        info = source.repository(project.full_name, public_only=True)
        if info['id'] != project.id:
            raise SourceError('仓库身份已变化，保留历史动态')
        name = info['full_name']
        with self.sessions.begin() as session:
            state = session.get(MonitorState, project.id)
            if state is None:
                state = MonitorState(project_id=project.id, issue_since=utcnow()-timedelta(days=30))
                session.add(state)
            state.attempted_at = utcnow()
            if state.scan_started_at is None:
                state.scan_started_at = utcnow()
            session.flush()
            release_baseline = state.releases_checked_at is None
        # shortcut: poll the latest 30 releases; expand pagination if older release edits become required.
        releases, _ = fetch_page(source, name, 'release')
        with self.sessions.begin() as session:
            save_events(session, project.id, releases, release_baseline)
            session.get(MonitorState, project.id).releases_checked_at = utcnow()
        for _ in range(3):
            with self.sessions() as session:
                state = session.get(MonitorState, project.id)
            items, more = fetch_page(source, name, 'issue', state.issue_since, state.issue_page)
            with self.sessions.begin() as session:
                state = session.get(MonitorState, project.id)
                save_events(session, project.id, items, state.checked_at is None)
                if more:
                    state.issue_page += 1
                else:
                    # Overlap catches updates made while traversing a mutable GitHub list.
                    state.issue_since = state.scan_started_at - timedelta(minutes=5)
                    state.checked_at, state.scan_started_at, state.issue_page, state.last_error = utcnow(), None, 1, None
                    return True
        with self.sessions.begin() as session:
            session.get(MonitorState, project.id).last_error = '本轮分页预算已用完，下轮继续同步'
        return False

    def run(self, source=None, run_id=None, force=True):
        if run_id is None:
            with self.sessions.begin() as session:
                run = MonitorRun()
                session.add(run)
                session.flush()
                run_id = run.id
        success, failed, errors, retry_at = 0, 0, [], None
        try:
            with self.collector.lock() as acquired:
                if not acquired:
                    raise SourceError('其他采集任务正在执行')
                with self.sessions() as session:
                    query = select(WatchProject).outerjoin(MonitorState).where(
                        WatchProject.followed.is_(True), WatchProject.hidden.is_(False))
                    if not force:
                        query = query.where((MonitorState.checked_at.is_(None)) | (MonitorState.checked_at < utcnow()-timedelta(hours=6)))
                    projects = session.scalars(query.order_by(MonitorState.attempted_at.asc().nullsfirst(), WatchProject.id)).all()
                with self.watch.source(source) as github:
                    for project in projects:
                        with self.sessions() as session:
                            current = session.get(WatchProject, project.id)
                            if not current.followed or current.hidden:
                                continue
                        try:
                            if self.check_project(current, github):
                                success += 1
                            else:
                                failed += 1
                                errors.append(f'{project.full_name}: 分页未完成，下轮继续')
                        except Exception as exc:
                            message = str(exc) if isinstance(exc, SourceError) else f'动态检查失败（{type(exc).__name__}）'
                            with self.sessions.begin() as session:
                                state = session.get(MonitorState, project.id)
                                if state is None:
                                    state = MonitorState(project_id=project.id, issue_since=utcnow()-timedelta(days=30))
                                    session.add(state)
                                state.last_error, state.attempted_at = message, utcnow()
                            if isinstance(exc, RateLimited):
                                raise
                            failed += 1
                            errors.append(f'{project.full_name}: {message}')
                        with self.sessions.begin() as session:
                            run = session.get(MonitorRun, run_id)
                            run.success_count, run.failure_count = success, failed
        except Exception as exc:
            failed += 1
            errors.append(str(exc) if isinstance(exc, SourceError) else f'动态检查失败（{type(exc).__name__}）')
            if isinstance(exc, RateLimited):
                retry_at = datetime.fromtimestamp(exc.retry_at, timezone.utc)
        finally:
            with self.sessions.begin() as session:
                run = session.get(MonitorRun, run_id)
                run.status = 'partial' if failed else 'success'
                run.finished_at, run.success_count, run.failure_count = utcnow(), success, failed
                run.error, run.retry_at = '\n'.join(errors) or None, retry_at
        return run_id
