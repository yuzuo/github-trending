from datetime import date, datetime, timezone
from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Repository(Base):
    __tablename__ = 'repositories'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    full_name: Mapped[str] = mapped_column(String(300), index=True)
    html_url: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    description_zh: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(100))
    license: Mapped[str | None] = mapped_column(String(100))
    default_branch: Mapped[str] = mapped_column(Text)
    stars: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    readme_path: Mapped[str | None] = mapped_column(Text)
    readme_original: Mapped[str | None] = mapped_column(Text)
    readme_zh: Mapped[str | None] = mapped_column(Text)
    readme_hash: Mapped[str | None] = mapped_column(String(64))
    translated_hash: Mapped[str | None] = mapped_column(String(64))
    translation_status: Mapped[str] = mapped_column(String(24), default='pending')
    translation_error: Mapped[str | None] = mapped_column(Text)


class SnapshotColumns:
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey('repositories.id'), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    trending_rank: Mapped[int] = mapped_column(Integer)
    daily_stars: Mapped[int | None] = mapped_column(BigInteger)
    stars: Mapped[int] = mapped_column(BigInteger)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SearchSnapshot(SnapshotColumns, Base):
    __tablename__ = 'search_snapshots'
    __table_args__ = (UniqueConstraint('repository_id', 'date', name='uq_search_repository_date'),)
    details: Mapped[dict | None] = mapped_column(JSONB)
    details_origin: Mapped[str] = mapped_column(String(24), default='captured', server_default='captured')


class TrendingSnapshot(SnapshotColumns, Base):
    __tablename__ = 'trending_snapshots'
    __table_args__ = (UniqueConstraint('repository_id', 'date', name='uq_trending_repository_date'),)
    details: Mapped[dict | None] = mapped_column(JSONB)
    details_origin: Mapped[str] = mapped_column(String(24), default='captured', server_default='captured')


SNAPSHOT_MODELS = {'search': SearchSnapshot, 'trending': TrendingSnapshot}


class CollectionRun(Base):
    __tablename__ = 'collection_runs'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    source: Mapped[str] = mapped_column(String(24), default='search', server_default='search')
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), default='running')
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    items: Mapped[list | None] = mapped_column(JSONB)


class WatchProject(Base):
    __tablename__ = 'watch_projects'
    __table_args__ = (CheckConstraint('rating BETWEEN 1 AND 5', name='watch_rating_range'),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    full_name: Mapped[str] = mapped_column(String(300), index=True)
    details: Mapped[dict] = mapped_column(JSONB)
    discovered_by: Mapped[list] = mapped_column(JSONB, default=list)
    manual: Mapped[bool] = mapped_column(Boolean, default=False)
    followed: Mapped[bool] = mapped_column(Boolean, default=False)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    review_status: Mapped[str] = mapped_column(String(24), default='pending')
    rating: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str] = mapped_column(Text, default='')
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_error: Mapped[str | None] = mapped_column(Text)


class WatchRun(Base):
    __tablename__ = 'watch_runs'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), default='running')
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discovery_done: Mapped[bool] = mapped_column(Boolean, default=False)
    discovery_progress: Mapped[dict] = mapped_column(JSONB, default=dict)
    cycle_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WatchSample(Base):
    __tablename__ = 'watch_samples'
    __table_args__ = (UniqueConstraint('project_id', 'run_id', name='uq_watch_project_run'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('watch_projects.id'), index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey('watch_runs.id'))
    stars: Mapped[int] = mapped_column(BigInteger)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class MonitorState(Base):
    __tablename__ = 'monitor_states'
    project_id: Mapped[int] = mapped_column(ForeignKey('watch_projects.id'), primary_key=True)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    releases_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    issue_since: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    scan_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    issue_page: Mapped[int] = mapped_column(Integer, default=1)
    last_error: Mapped[str | None] = mapped_column(Text)


class MonitorEvent(Base):
    __tablename__ = 'monitor_events'
    __table_args__ = (UniqueConstraint('project_id', 'kind', 'source_id', name='uq_monitor_source'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('watch_projects.id'), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    source_id: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24))
    labels: Mapped[list] = mapped_column(JSONB, default=list)
    source_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    unread: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    history: Mapped[list] = mapped_column(JSONB, default=list)


class MonitorRun(Base):
    __tablename__ = 'monitor_runs'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), default='running')
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProjectProfile(Base):
    __tablename__ = 'project_profiles'
    project_id: Mapped[int] = mapped_column(ForeignKey('watch_projects.id'), primary_key=True)
    usage_status: Mapped[str] = mapped_column(String(16), default='evaluating')
    version: Mapped[str] = mapped_column(String(100), default='')
    scenario: Mapped[str] = mapped_column(Text, default='')
    capabilities: Mapped[list] = mapped_column(JSONB, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EventAnalysis(Base):
    __tablename__ = 'event_analyses'
    event_id: Mapped[int] = mapped_column(ForeignKey('monitor_events.id'), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default='pending')
    result: Mapped[dict] = mapped_column(JSONB, default=dict)
    evidence: Mapped[list] = mapped_column(JSONB, default=list)
    warnings: Mapped[list] = mapped_column(JSONB, default=list)
    model: Mapped[str] = mapped_column(String(200), default='')
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    error: Mapped[str | None] = mapped_column(Text)


class AnalysisRun(Base):
    __tablename__ = 'analysis_runs'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), default='running')
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)


class ValidationResult(Base):
    __tablename__ = 'validation_results'
    __table_args__ = (UniqueConstraint('project_id', 'digest', name='uq_validation_digest'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('watch_projects.id'), index=True)
    version: Mapped[str] = mapped_column(String(100))
    suite: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(24))
    metrics: Mapped[dict] = mapped_column(JSONB)
    evidence: Mapped[dict] = mapped_column(JSONB)
    digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
