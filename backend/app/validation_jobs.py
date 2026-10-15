"""Persistent release checks; Docker execution belongs to the host worker only."""
import argparse
from datetime import timedelta
import json
import re
import secrets
import sys
from urllib.parse import unquote, urlsplit

from sqlalchemy import select, text

from .models import MonitorEvent, ValidationJob, ValidationTracking, ValidationWorkerState, WatchProject, utcnow
from .validation_import import validate_result

SOURCE = 'source-smoke-v1'
SCRAPY = 'scrapy-pagination-v1'


def release_version(event, name):
    url = urlsplit(event.url)
    prefix = f'/{name}/releases/tag/'
    if url.scheme != 'https' or url.netloc != 'github.com' or not url.path.startswith(prefix):
        return None
    tag = unquote(url.path[len(prefix):])
    return tag if 0 < len(tag) <= 100 and not any(ord(c) < 32 or ord(c) == 127 for c in tag) else None


def enqueue(sessions):
    with sessions.begin() as session:
        session.execute(text('SELECT pg_advisory_xact_lock(719436525)'))
        projects = session.scalars(select(WatchProject).where(WatchProject.followed.is_(True), WatchProject.hidden.is_(False))).all()
        for project in projects:
            tracking = session.get(ValidationTracking, project.id)
            statement = select(MonitorEvent).where(MonitorEvent.project_id == project.id,
                MonitorEvent.kind == 'release', MonitorEvent.status == 'published').order_by(MonitorEvent.source_at.desc(), MonitorEvent.id.desc())
            if tracking:
                statement = statement.where(MonitorEvent.changed_at >= tracking.started_at)
            else:
                # Keep waiting for a first successful release sync before establishing the baseline.
                if session.scalar(statement.limit(1)) is None:
                    continue
                tracking = ValidationTracking(project_id=project.id)
                session.add(tracking)
                statement = statement.limit(2)
            for event in session.scalars(statement):
                version = release_version(event, project.full_name)
                if version is None:
                    continue
                suites = [SOURCE, SCRAPY] if project.full_name.lower() == 'scrapy/scrapy' else [SOURCE]
                for suite in suites:
                    if session.scalar(select(ValidationJob.id).where(ValidationJob.event_id == event.id, ValidationJob.suite == suite)):
                        continue
                    session.add(ValidationJob(project_id=project.id,event_id=event.id,full_name=project.full_name,
                        version=version,source_url=event.url,source_at=event.source_at,suite=suite))


def claim(sessions):
    now = utcnow()
    with sessions.begin() as session:
        # Serialize lease recovery and claim across host processes without holding a lock while testing.
        session.execute(text('SELECT pg_advisory_xact_lock(719436525)'))
        worker=session.get(ValidationWorkerState,1)
        if worker is None:
            session.add(ValidationWorkerState(id=1,last_seen=now))
        else:
            worker.last_seen=now
        jobs = session.scalars(select(ValidationJob).where(ValidationJob.status.in_(['queued','running','error']))
            .order_by(ValidationJob.source_at,ValidationJob.id).with_for_update()).all()
        github_cooling=any(job.error=='GitHubRateLimited' and job.retry_at and job.retry_at>now for job in jobs)
        for job in jobs:
            project = session.get(WatchProject,job.project_id)
            if not project.followed or project.hidden:
                job.status, job.error = 'cancelled', '项目已取消关注或隐藏'
                job.lease_token = None
                continue
            if job.status == 'running':
                if job.lease_until and job.lease_until > now:
                    continue
                job.status, job.error = 'error', '执行租约超时'
            if job.attempts >= 3 or (job.retry_at and job.retry_at > now):
                continue
            if job.suite == SOURCE and github_cooling:
                continue
            job.status, job.attempts = 'running', job.attempts + 1
            job.lease_token, job.lease_until = secrets.token_hex(24), now + timedelta(minutes=30)
            job.retry_at, job.error, job.finished_at = None, None, None
            return {key: getattr(job,key) for key in ('id','lease_token','project_id','full_name','version','source_url','suite')}
    return None


def leased(session, job_id, token):
    job = session.scalar(select(ValidationJob).where(ValidationJob.id == job_id).with_for_update())
    if not job or job.status != 'running' or not secrets.compare_digest(job.lease_token or '',token) or job.lease_until <= utcnow():
        raise ValueError('任务租约失效')
    project = session.scalar(select(WatchProject).where(WatchProject.id == job.project_id).with_for_update())
    if not project.followed or project.hidden:
        raise ValueError('项目已取消关注或隐藏')
    return job


def checked_result(job, result):
    if not isinstance(result,dict) or result.get('suite') != job.suite or result.get('status') not in ('passed','failed','unsupported'):
        raise ValueError('无效结果类型')
    evidence, metrics = result.get('evidence'), result.get('metrics')
    if not isinstance(evidence,dict) or not isinstance(metrics,dict):
        raise ValueError('缺少证据和指标')
    if not re.fullmatch(r'[a-f0-9]{64}',str(evidence.get('fixture_sha256',''))) or not re.fullmatch(r'\d+\.\d+\.\d+',str(evidence.get('python',''))):
        raise ValueError('缺少任务或运行环境指纹')
    if job.suite == SOURCE:
        if (evidence.get('full_name') != job.full_name or evidence.get('version') != job.version
                or not re.fullmatch(r'[a-f0-9]{40}',str(evidence.get('commit_sha','')))
                or not re.fullmatch(r'[a-f0-9]{64}',str(evidence.get('archive_sha256','')))
                or evidence.get('scope') != 'source'):
            raise ValueError('源码证据不匹配项目或版本')
        checked, failed = metrics.get('checked_files'), metrics.get('failed_files')
        if type(checked) is not int or type(failed) is not int or not 0 <= failed <= checked <= 5000:
            raise ValueError('无效基础检查计数')
        expected = 'unsupported' if checked == 0 else 'failed' if failed else 'passed'
        if result['status'] != expected:
            raise ValueError('判定与检查指标不一致')
    else:
        if job.full_name.lower() != 'scrapy/scrapy':
            raise ValueError('功能任务与项目不匹配')
        version = job.version.removeprefix('v')
        validate_result(dict(version=version,suite=SCRAPY,status=result['status'],metrics=metrics,evidence=evidence))
    json.dumps(result,allow_nan=False)
    return result


def complete(sessions, job_id, token, result):
    with sessions.begin() as session:
        job = leased(session,job_id,token)
        job.result = checked_result(job,result)
        job.status, job.finished_at, job.error = result['status'],utcnow(),None
        job.lease_token, job.lease_until = None,None


def fail(sessions, job_id, token, error, retry_after=None):
    with sessions.begin() as session:
        job = leased(session,job_id,token)
        job.status, job.error, job.finished_at = 'error', str(error)[:300], utcnow()
        job.retry_at = utcnow()+timedelta(minutes=60 if error == 'HTTPError' else 15) if job.attempts < 3 else None
        if error == 'GitHubRateLimited':
            if type(retry_after) is not int or not 60 <= retry_after <= 7200:
                raise ValueError('无效冷却时间')
            job.attempts=max(0,job.attempts-1)
            job.retry_at=utcnow()+timedelta(seconds=retry_after)
        job.lease_token, job.lease_until = None,None


def retry(sessions, job_id):
    with sessions.begin() as session:
        job = session.scalar(select(ValidationJob).where(ValidationJob.id == job_id).with_for_update())
        if not job or job.status not in ('error','cancelled'):
            raise ValueError('只能重试执行错误或取消的任务')
        project = session.get(WatchProject,job.project_id)
        if not project.followed or project.hidden:
            raise ValueError('请先关注该项目')
        job.status, job.attempts, job.retry_at, job.error = 'queued',0,None,None


def overview(sessions):
    with sessions() as session:
        projects = session.scalars(select(WatchProject).where(WatchProject.followed.is_(True),WatchProject.hidden.is_(False))
            .order_by(WatchProject.full_name)).all()
        jobs = session.scalars(select(ValidationJob).where(ValidationJob.project_id.in_([p.id for p in projects]))
            .order_by(ValidationJob.source_at.desc(),ValidationJob.id.desc())).all()
        groups, alerts, comparisons = {}, [], []
        for job in jobs:
            groups.setdefault((job.project_id,job.suite),[]).append(job)
        for (project_id,suite), group in groups.items():
            if len(group) < 2:
                continue
            new, old = group[:2]
            if new.status not in ('passed','failed') or old.status not in ('passed','failed'):
                continue
            a,b = new.result['evidence'],old.result['evidence']
            if any(a.get(key) != b.get(key) for key in ('fixture_sha256','python','architecture')):
                continue
            comparisons.append(dict(project_id=project_id,full_name=new.full_name,suite=suite,
                baseline_version=old.version,candidate_version=new.version,baseline_status=old.status,candidate_status=new.status,
                regression=old.status=='passed' and new.status=='failed'))
            if old.status == 'passed' and new.status == 'failed':
                alerts.append(dict(project_id=project_id,full_name=new.full_name,suite=suite,job_id=new.id,
                    baseline_version=old.version,candidate_version=new.version,kind='regression',
                    summary='源码基础检查出现退化，请查看具体文件；不代表采集能力退化。' if suite == SOURCE else '固定功能任务出现回归，建议复核后再升级。'))
        def public(job):
            return {key:getattr(job,key) for key in ('id','project_id','full_name','version','source_url','source_at','suite',
                'status','attempts','created_at','finished_at','lease_until','retry_at','error','result')}
        worker=session.get(ValidationWorkerState,1)
        return dict(worker_last_seen=worker.last_seen if worker else None,projects=[dict(project_id=p.id,full_name=p.full_name,
            functional_status='configured' if p.full_name.lower()=='scrapy/scrapy' else 'not_configured',
            latest=[public(group[0]) for (pid,_),group in groups.items() if pid==p.id]) for p in projects],
            jobs=[public(job) for job in jobs[:50]],alerts=alerts,comparisons=comparisons)


if __name__ == '__main__':
    from .config import Settings
    from .database import database
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['claim','complete','error','enqueue'])
    args=parser.parse_args()
    engine,sessions=database(Settings.from_env())
    try:
        if args.command=='claim':
            output=claim(sessions)
        elif args.command=='enqueue':
            enqueue(sessions); output={'status':'queued'}
        else:
            raw=sys.stdin.read(1_000_001)
            if len(raw)>1_000_000:
                raise ValueError('结果过大')
            data=json.loads(raw)
            if args.command=='complete':
                complete(sessions,data['id'],data['lease_token'],data['result'])
            else:
                fail(sessions,data['id'],data['lease_token'],data['error'],data.get('retry_after'))
            output={'status':'saved'}
        print(json.dumps(output,ensure_ascii=False))
    finally:
        engine.dispose()
