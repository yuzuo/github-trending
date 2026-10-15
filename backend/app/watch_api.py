from collections import defaultdict
from datetime import datetime, timedelta
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator
from sqlalchemy import select, func

from .models import WatchProject, WatchRun, WatchSample, MonitorEvent, MonitorState, MonitorRun, utcnow
from .sources import RateLimited, SourceError
from .watch import CAPACITY, WatchConflict, active_count, capacity_lock, growth_metrics, ranking_key


class AddProject(BaseModel):
    model_config = ConfigDict(extra='forbid')
    repository: str = Field(min_length=3, max_length=350, strict=True)


class EditProject(BaseModel):
    model_config = ConfigDict(extra='forbid')
    followed: StrictBool | None = None
    hidden: StrictBool | None = None
    review_status: Literal['pending', 'reviewing', 'reviewed', 'dismissed'] | None = None
    rating: StrictInt | None = Field(default=None, ge=1, le=5)
    notes: str | None = Field(default=None, max_length=20000, strict=True)

    @model_validator(mode='after')
    def no_null_except_rating(self):
        if any(getattr(self, key) is None for key in self.model_fields_set - {'rating'}):
            raise ValueError('仅评分允许设为空')
        return self


class EmptyBody(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ReadEvent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    changed_at: datetime


def project_items(session, projects):
    if not projects:
        return []
    samples = defaultdict(list)
    earliest = min(p.fetched_at for p in projects) - timedelta(days=8)
    for row in session.scalars(select(WatchSample).where(
            WatchSample.project_id.in_([p.id for p in projects]), WatchSample.fetched_at >= earliest).order_by(WatchSample.fetched_at)):
        samples[row.project_id].append(dict(stars=row.stars, fetched_at=row.fetched_at))
    now, items = utcnow(), []
    for project in projects:
        details = {key: value for key, value in project.details.items() if key != 'readme_original'}
        items.append({**details, **{key: getattr(project, key) for key in (
            'id', 'full_name', 'fetched_at', 'manual', 'followed', 'hidden', 'review_status',
            'rating', 'notes', 'discovered_by', 'last_error')}, **growth_metrics(samples[project.id], now)})
    return items


def watch_router(service, monitor, attention):
    router = APIRouter(prefix='/api/watch', tags=['采集项目观察'])

    def protect_write(request: Request):
        if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
            raise HTTPException(415, '请使用 application/json')
        configured = urlsplit(service.settings.app_origin)
        port = f':{configured.port}' if configured.port else ''
        allowed = {service.settings.app_origin, f'{configured.scheme}://localhost{port}', f'{configured.scheme}://127.0.0.1{port}'}
        if ((request.headers.get('origin') and request.headers['origin'] not in allowed)
                or request.headers.get('sec-fetch-site') == 'cross-site'):
            raise HTTPException(403, '不允许跨站修改观察项目')

    def detail(project_id):
        with service.sessions() as session:
            project = session.get(WatchProject, project_id)
            if project is None:
                raise HTTPException(404, '观察项目不存在')
            item = project_items(session, [project])[0]
            item['readme_original'] = project.details.get('readme_original')
            item['history'] = [dict(stars=s.stars, fetched_at=s.fetched_at) for s in session.scalars(
                select(WatchSample).where(WatchSample.project_id == project_id).order_by(
                    WatchSample.fetched_at.desc()).limit(100))]
            return item

    @router.get('/projects')
    def projects(q: str = Query('', max_length=200), language: str = Query('', max_length=100),
                 view: Literal['all', 'following', 'pending', 'hidden'] = 'all',
                 sort: Literal['growth_7d', 'growth_24h', 'stars'] = 'growth_7d'):
        with service.sessions() as session:
            statement = select(WatchProject).where(WatchProject.hidden.is_(view == 'hidden'))
            rows = session.scalars(statement).all()
            languages = sorted({p.details['language'] for p in rows if p.details.get('language')})
            if view == 'following':
                rows = [p for p in rows if p.followed]
            elif view == 'pending':
                rows = [p for p in rows if p.review_status == 'pending']
            if q.strip():
                term = q.strip().casefold()
                rows = [p for p in rows if term in (p.full_name + ' ' + (p.details.get('description') or '')).casefold()]
            if language:
                rows = [p for p in rows if p.details.get('language') == language]
            items = sorted(project_items(session, rows), key=lambda item: ranking_key(item, sort))
            return dict(items=items, languages=languages, active_count=active_count(session), limit=CAPACITY)

    @router.get('/projects/{project_id}')
    def get_project(project_id: int):
        return detail(project_id)

    @router.post('/projects', status_code=201, dependencies=[Depends(protect_write)])
    def add_project(body: AddProject):
        try:
            project_id = service.add_project(body.repository)
        except WatchConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except RateLimited as exc:
            raise HTTPException(429, str(exc)) from exc
        except SourceError as exc:
            raise HTTPException(422, str(exc)) from exc
        return detail(project_id)

    @router.patch('/projects/{project_id}', dependencies=[Depends(protect_write)])
    def edit_project(project_id: int, body: EditProject):
        with service.sessions.begin() as session:
            capacity_lock(session)
            project = session.get(WatchProject, project_id)
            if project is None:
                raise HTTPException(404, '观察项目不存在')
            changes = body.model_dump(exclude_unset=True)
            if project.hidden and changes.get('hidden') is False and active_count(session) >= CAPACITY:
                raise HTTPException(409, '监测项目已达 200 个，请先隐藏其他项目')
            for key, value in changes.items():
                setattr(project, key, value)
        return detail(project_id)

    @router.post('/refresh', status_code=202, dependencies=[Depends(protect_write)])
    def refresh(body: EmptyBody):
        if not service.start():
            raise HTTPException(409, '采集正在执行或 GitHub 处于限流冷却期，请稍后重试')
        return {'status': 'accepted'}

    @router.get('/run')
    def run():
        with service.sessions() as session:
            latest = session.scalar(select(WatchRun).order_by(WatchRun.id.desc()))
            return {c.name: getattr(latest, c.name) for c in WatchRun.__table__.columns
                    if c.name != 'discovery_progress'} if latest else None

    @router.get('/monitor')
    def monitor_status():
        with service.sessions() as session:
            latest = session.scalar(select(MonitorRun).order_by(MonitorRun.id.desc()))
            rows = session.execute(select(WatchProject, MonitorState).outerjoin(MonitorState).where(
                WatchProject.followed.is_(True), WatchProject.hidden.is_(False)).order_by(WatchProject.full_name)).all()
            return dict(run={c.name: getattr(latest, c.name) for c in MonitorRun.__table__.columns} if latest else None,
                        schedule_enabled=service.settings.schedule_enabled, cooldown_until=service.collector.cooldown(),
                        projects=[dict(id=p.id, full_name=p.full_name, checked_at=s.checked_at if s else None,
                            releases_checked_at=s.releases_checked_at if s else None,
                            issue_page=s.issue_page if s else 1, last_error=s.last_error if s else None) for p, s in rows])

    @router.post('/monitor/refresh', status_code=202, dependencies=[Depends(protect_write)])
    def refresh_monitor(body: EmptyBody):
        if not monitor.start(force=True):
            raise HTTPException(409, '采集正在执行或 GitHub 处于限流冷却期，请稍后重试')
        return {'status': 'accepted'}

    @router.get('/events')
    def events(project_id: int | None = None, kind: Literal['all', 'release', 'issue'] = 'all',
               unread: bool = False, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0, le=100000)):
        with service.sessions() as session:
            filters = [WatchProject.hidden.is_(False)]
            filters.append(WatchProject.id == project_id if project_id is not None else WatchProject.followed.is_(True))
            if kind != 'all':
                filters.append(MonitorEvent.kind == kind)
            query = select(MonitorEvent, WatchProject.full_name).join(WatchProject).where(*filters)
            unread_count = session.scalar(select(func.count()).select_from(MonitorEvent).join(WatchProject).where(*filters, MonitorEvent.unread.is_(True)))
            if unread:
                query = query.where(MonitorEvent.unread.is_(True))
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            rows = session.execute(query.order_by(MonitorEvent.changed_at.desc(), MonitorEvent.id.desc()).offset(offset).limit(limit)).all()
            return dict(items=[{**{c.name: getattr(event, c.name) for c in MonitorEvent.__table__.columns},
                               'full_name': name, 'verification': 'unverified'} for event, name in rows],
                        total=total, unread_count=unread_count)

    @router.post('/events/{event_id}/read', dependencies=[Depends(protect_write)])
    def read_event(event_id: int, body: ReadEvent):
        with service.sessions.begin() as session:
            event = session.scalar(select(MonitorEvent).where(MonitorEvent.id == event_id).with_for_update())
            if event is None:
                raise HTTPException(404, '动态不存在')
            if event.changed_at != body.changed_at:
                raise HTTPException(409, '动态已有新变化，请刷新后再标为已读')
            event.unread = False
        return {'status': 'read'}

    from .attention_api import register_attention
    register_attention(router, attention, protect_write, EmptyBody)
    return router
