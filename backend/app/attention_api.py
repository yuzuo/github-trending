from typing import Literal
from datetime import timedelta

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from .attention import fingerprint, profile_data
from .models import AnalysisRun, EventAnalysis, MonitorEvent, ProjectProfile, ValidationResult, WatchProject, utcnow


class ProfileBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    usage_status: Literal['evaluating', 'using'] = 'evaluating'
    version: str = Field(default='', max_length=100, strict=True)
    scenario: str = Field(default='', max_length=2000, strict=True)
    capabilities: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def valid_context(self):
        self.version, self.scenario = self.version.strip(), self.scenario.strip()
        if self.usage_status == 'using' and not self.version:
            raise ValueError('使用中项目需要填写版本')
        if any(not item.strip() or len(item) > 100 for item in self.capabilities):
            raise ValueError('每项关注能力应为 1～100 字')
        self.capabilities = list(dict.fromkeys(item.strip() for item in self.capabilities))
        return self


def register_attention(router, service, protect_write, empty_body):
    @router.get('/validation-jobs')
    def validation_jobs():
        from .validation_jobs import overview
        return overview(service.sessions)

    @router.post('/validation-jobs/{job_id}/retry', dependencies=[Depends(protect_write)])
    def retry_validation(job_id: int, body: empty_body):
        from .validation_jobs import retry
        try:
            retry(service.sessions,job_id)
        except ValueError as exc:
            raise HTTPException(409,str(exc)) from exc
        return {'status':'queued'}

    @router.put('/profiles/{project_id}', dependencies=[Depends(protect_write)])
    def edit_profile(project_id: int, body: ProfileBody):
        with service.sessions.begin() as session:
            project = session.scalar(select(WatchProject).where(WatchProject.id == project_id).with_for_update())
            if project is None:
                raise HTTPException(404, '项目不存在')
            profile = session.get(ProjectProfile, project_id)
            if profile is None:
                profile = ProjectProfile(project_id=project_id)
                session.add(profile)
            for key, value in body.model_dump().items():
                setattr(profile, key, value)
            profile.updated_at = utcnow()
            session.flush()
            return profile_data(profile)

    @router.post('/analyze', status_code=202, dependencies=[Depends(protect_write)])
    def start_analysis(body: empty_body):
        if not service.settings.translation_enabled:
            raise HTTPException(409, '未配置模型服务，请配置现有 TRANSLATION_* 模型参数')
        if not service.start(force=True):
            raise HTTPException(409, '其他任务正在执行，请稍后重试')
        return {'status': 'accepted'}

    @router.get('/attention')
    def attention(project_id: int | None = None,
                  category: Literal['all', 'feature', 'breaking', 'bug', 'fix', 'other'] = 'all',
                  include_all: bool = False, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0, le=100000)):
        with service.sessions() as session:
            profiles = [dict(**profile_data(profile, project.id), full_name=project.full_name) for project, profile in session.execute(
                select(WatchProject, ProjectProfile).outerjoin(ProjectProfile).where(WatchProject.followed.is_(True),
                WatchProject.hidden.is_(False)).order_by(WatchProject.full_name))]
            statement = select(MonitorEvent, WatchProject.full_name, ProjectProfile, EventAnalysis).join(
                WatchProject, WatchProject.id == MonitorEvent.project_id).outerjoin(
                ProjectProfile, ProjectProfile.project_id == MonitorEvent.project_id).outerjoin(
                EventAnalysis, EventAnalysis.event_id == MonitorEvent.id).where(
                WatchProject.followed.is_(True), WatchProject.hidden.is_(False))
            if project_id is not None:
                statement = statement.where(MonitorEvent.project_id == project_id)
            rows = session.execute(statement.order_by(MonitorEvent.changed_at.desc(), MonitorEvent.id.desc())).all()
            items = []
            for event, name, profile, analysis in rows:
                state = 'pending' if service.settings.translation_enabled else 'unconfigured'
                if analysis:
                    state = analysis.status if analysis.fingerprint == fingerprint(event, profile) else 'stale'
                    if state == 'ready' and analysis.analyzed_at < utcnow()-timedelta(hours=6):
                        state = 'stale'
                advice = dict(analysis.result) if analysis else {}
                if not include_all and (state != 'ready' or advice.get('priority') not in ('high', 'medium')):
                    continue
                if category != 'all' and advice.get('category') != category:
                    continue
                advice.update(status=state, error=analysis.error if analysis else None,
                              model=analysis.model if analysis else None, analyzed_at=analysis.analyzed_at if analysis else None,
                              warnings=analysis.warnings if analysis else [])
                items.append(dict(id=event.id, project_id=event.project_id, full_name=name, kind=event.kind, title=event.title,
                    url=event.url, status=event.status, changed_at=event.changed_at, unread=event.unread, analysis=advice,
                    evidence=analysis.evidence if analysis else [], related_events=[], verification='unverified'))
            items.sort(key=lambda item: {'high': 0, 'medium': 1, 'low': 2}.get(item['analysis'].get('priority'), 3))
            total = len(items)
            items = items[offset:offset+limit]
            for item in items:
                urls = [e['url'] for e in item['evidence'] if e.get('url')]
                related = session.scalars(select(MonitorEvent).where(MonitorEvent.project_id == item['project_id'],
                    MonitorEvent.id != item['id'], MonitorEvent.url.in_(urls))).all()
                item['related_events'] = [dict(id=e.id, title=e.title, url=e.url, kind=e.kind) for e in related]
            latest = session.scalar(select(AnalysisRun).order_by(AnalysisRun.id.desc()))
            return dict(items=items, total=total, profiles=profiles, analysis_enabled=service.settings.translation_enabled,
                        running=bool(latest and latest.status == 'running'),
                        run={c.name: getattr(latest, c.name) for c in AnalysisRun.__table__.columns} if latest else None)

    @router.get('/validations')
    def validations(project_id: int):
        from .validation_import import compare_results
        with service.sessions() as session:
            rows = session.scalars(select(ValidationResult).where(ValidationResult.project_id == project_id)
                .order_by(ValidationResult.id.desc()).limit(50)).all()
            items = [{c.name: getattr(row, c.name) for c in ValidationResult.__table__.columns if c.name != 'digest'} for row in rows]
            return dict(items=items, comparison=compare_results(items))
