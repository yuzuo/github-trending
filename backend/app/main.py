import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import date
import logging
from urllib.parse import urlsplit
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .collector import Collector
from .config import Settings
from .database import database, initialize_database
from .models import CollectionRun, SNAPSHOT_MODELS, Repository
from .watch import WatchService
from .watch_api import watch_router
from .monitor import MonitorService
from .attention import AttentionService


def serialize(model):
    return {column.name: getattr(model, column.name) for column in model.__table__.columns}


async def schedule(collector, watch=None, monitor=None, attention=None):
    startup = {'trending', 'search'}
    while True:
        try:
            if monitor and await asyncio.to_thread(monitor.due):
                await asyncio.to_thread(monitor.start)
            if attention and await asyncio.to_thread(attention.due):
                await asyncio.to_thread(attention.start)
            for kind in ('trending', 'search'):
                if await asyncio.to_thread(collector.due, startup=kind in startup, kind=kind):
                    if await asyncio.to_thread(collector.start, kind=kind):
                        startup.discard(kind)
                else:
                    startup.discard(kind)
            if watch and await asyncio.to_thread(watch.due):
                await asyncio.to_thread(watch.start)
        except Exception as exc:
            logging.getLogger(__name__).error('Scheduler check failed: %s', type(exc).__name__)
        await asyncio.sleep(30)


def create_app(settings=None, engine=None):
    settings = settings or Settings.from_env()
    if engine is None:
        engine, sessions = database(settings)
    else:
        sessions = sessionmaker(engine, expire_on_commit=False)
    collector = Collector(engine, sessions, settings)
    watch = WatchService(collector)
    monitor = MonitorService(collector)
    attention = AttentionService(collector)

    @asynccontextmanager
    async def lifespan(app):
        await asyncio.to_thread(initialize_database, engine)
        await asyncio.to_thread(collector.recover)
        await asyncio.to_thread(watch.recover)
        await asyncio.to_thread(monitor.recover)
        await asyncio.to_thread(attention.recover)
        task = asyncio.create_task(schedule(collector, watch, monitor, attention)) if settings.schedule_enabled else None
        yield
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await asyncio.to_thread(collector.close)
        engine.dispose()

    app = FastAPI(title='GitHub 开源观察', lifespan=lifespan, docs_url='/api/docs', openapi_url='/api/openapi.json', redoc_url=None)
    app.state.collector = collector
    app.state.watch = watch
    app.state.monitor = monitor
    app.state.attention = attention
    app.include_router(watch_router(watch, monitor, attention))
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost', '127.0.0.1', 'api', 'testserver', urlsplit(settings.app_origin).hostname])

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        logging.getLogger(__name__).error('Database request failed: %s', type(exc).__name__)
        return JSONResponse(status_code=503, content={'detail': '数据库暂时不可用，请稍后重试'})

    @app.get('/api/health')
    def health():
        with sessions() as session:
            session.execute(text('SELECT 1'))
        return {'status': 'ok'}

    @app.get('/api/dates')
    def dates(source: Literal['search', 'trending'] = 'search'):
        Snapshot = SNAPSHOT_MODELS[source]
        with sessions() as session:
            return session.scalars(select(Snapshot.date).distinct().order_by(Snapshot.date.desc())).all()

    @app.get('/api/repositories')
    def repositories(day: date | None = Query(None, alias='date'), q: str = Query('', max_length=200), language: str = Query('', max_length=100), source: Literal['search', 'trending'] = 'search'):
        Snapshot = SNAPSHOT_MODELS[source]
        with sessions() as session:
            day = day or session.scalar(select(func.max(Snapshot.date)))
            context = {'source': source, 'limit': settings.search_limit if source == 'search' else None}
            if day is None:
                return {'date': None, 'items': [], 'languages': [], **context}
            context['limit'] = session.scalar(select(func.count()).select_from(Snapshot).where(Snapshot.date == day)) if source == 'search' else None
            statement = select(Repository, Snapshot).join(Snapshot).where(Snapshot.date == day)
            name_field = Snapshot.details['full_name'].astext
            description_field = Snapshot.details['description'].astext
            chinese_field = Snapshot.details['description_zh'].astext
            language_field = Snapshot.details['language'].astext
            languages = session.scalars(select(language_field).select_from(Repository).join(Snapshot).where(
                Snapshot.date == day, language_field.is_not(None)).distinct().order_by(language_field)).all()
            if q.strip():
                value = q.strip()
                statement = statement.where(or_(name_field.icontains(value, autoescape=True),
                    description_field.icontains(value, autoescape=True), chinese_field.icontains(value, autoescape=True)))
            if language:
                statement = statement.where(language_field == language)
            sort = Snapshot.stars if source == 'search' else Snapshot.daily_stars
            statement = statement.order_by(sort.desc().nulls_last(), Snapshot.trending_rank)
            items = []
            for repo, snapshot in session.execute(statement):
                data = snapshot.details
                item = {key: data.get(key) for key in ['id', 'full_name', 'html_url', 'description', 'description_zh', 'language', 'license', 'translation_status']}
                item['details_origin'] = snapshot.details_origin
                item.update(stars=snapshot.stars, daily_stars=snapshot.daily_stars, rank=snapshot.trending_rank, trending_rank=snapshot.trending_rank, fetched_at=snapshot.fetched_at)
                items.append(item)
            return {'date': day, 'items': items, 'languages': languages, **context}

    @app.get('/api/repositories/{repository_id}')
    def repository(repository_id: int, day: date | None = Query(None, alias='date'), source: Literal['search', 'trending'] = 'search'):
        with sessions() as session:
            if source == 'trending' or day is not None:
                Snapshot = SNAPSHOT_MODELS[source]
                statement = select(Snapshot).where(Snapshot.repository_id == repository_id)
                if day is not None:
                    statement = statement.where(Snapshot.date == day)
                snapshot = session.scalar(statement.order_by(Snapshot.date.desc()).limit(1))
                if snapshot is None:
                    raise HTTPException(404, '该日期没有此项目的快照')
                item = {**snapshot.details, 'date': snapshot.date, 'source': source,
                        'stars': snapshot.stars, 'daily_stars': snapshot.daily_stars,
                        'rank': snapshot.trending_rank, 'fetched_at': snapshot.fetched_at,
                        'details_origin': snapshot.details_origin}
            else:
                repo = session.get(Repository, repository_id)
                if repo is None:
                    raise HTTPException(404, '项目不存在')
                item = serialize(repo)
            item['translation_stale'] = bool(item.get('readme_zh') is not None and (
                item.get('readme_hash') != item.get('translated_hash') or item.get('translation_status') != 'translated'))
            return item

    @app.get('/api/runs/latest')
    def latest_run(source: Literal['search', 'trending'] = 'search'):
        with sessions() as session:
            run = session.scalar(select(CollectionRun).where(CollectionRun.source == source).order_by(CollectionRun.id.desc()).limit(1))
            return serialize(run) if run else None

    @app.post('/api/collect', status_code=202)
    async def collect(request: Request, source: Literal['search', 'trending'] = 'search'):
        if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
            raise HTTPException(415, '请使用 application/json')
        origin = request.headers.get('origin')
        configured = urlsplit(settings.app_origin)
        port = f':{configured.port}' if configured.port else ''
        allowed_origins = {settings.app_origin, f'{configured.scheme}://localhost{port}',
                           f'{configured.scheme}://127.0.0.1{port}'}
        if origin and origin not in allowed_origins:
            raise HTTPException(403, '不允许跨站触发采集')
        if request.headers.get('sec-fetch-site') == 'cross-site':
            raise HTTPException(403, '不允许跨站触发采集')
        try:
            body = await request.json()
        except ValueError:
            raise HTTPException(400, 'JSON 格式错误')
        if body != {}:
            raise HTTPException(422, '请求内容应为 {}')
        if not await asyncio.to_thread(collector.start, kind=source):
            raise HTTPException(409, '今日榜单已完成、任务正在执行或 GitHub 处于限流冷却期；已完成记录不会覆盖')
        return {'status': 'accepted'}

    return app


app = create_app()
