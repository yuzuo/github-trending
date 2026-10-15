from datetime import timedelta
import os
import unittest
from sqlalchemy import select
import test_storage as storage
from app.models import WatchProject, MonitorEvent, utcnow
from app.validation_jobs import enqueue, claim, complete, fail, overview


@unittest.skipUnless(os.getenv('TEST_DATABASE_URL'), 'Requires PostgreSQL test database')
class ValidationJobsTests(unittest.TestCase):
    setUp = storage.StorageTests.setUp
    tearDown = storage.StorageTests.tearDown

    def seed(self, name='owner/project'):
        with self.sessions.begin() as s:
            s.add(WatchProject(id=1,full_name=name,details={},followed=True))
            s.flush()
            for n in range(1,5):
                s.add(MonitorEvent(id=n,project_id=1,kind='release',source_id=n,title=f'v1.0.{n}',
                    body='',url=f'https://github.com/{name}/releases/tag/v1.0.{n}',status='published',
                    labels=[],source_at=utcnow()-timedelta(days=5-n)))

    def result(self, job, status='passed'):
        return dict(suite=job['suite'],status=status,metrics=dict(checked_files=2,failed_files=int(status=='failed')),
            evidence=dict(fixture_sha256='a'*64,python='3.12.12',scope='source',full_name=job['full_name'],
                version=job['version'],commit_sha='b'*40,archive_sha256='c'*64))

    def test_baseline_two_only_idempotent_and_future_release(self):
        from app.models import ValidationJob
        self.seed()
        enqueue(self.sessions); enqueue(self.sessions)
        with self.sessions() as s:
            self.assertEqual(len(s.scalars(select(ValidationJob)).all()),2)
        with self.sessions.begin() as s:
            s.add(MonitorEvent(id=5,project_id=1,kind='release',source_id=5,title='new',body='',
                url='https://github.com/owner/project/releases/tag/v1.0.5',status='published',labels=[],source_at=utcnow()))
            s.add(MonitorEvent(id=6,project_id=1,kind='release',source_id=6,title='pre',body='',
                url='https://github.com/owner/project/releases/tag/v2.0.0',status='prerelease',labels=[],source_at=utcnow()))
        enqueue(self.sessions)
        with self.sessions() as s:
            self.assertEqual(len(s.scalars(select(ValidationJob)).all()),3)

    def test_lease_retry_cancellation_and_stale_completion(self):
        from app.models import ValidationJob
        self.seed(); enqueue(self.sessions)
        first=claim(self.sessions)
        second=claim(self.sessions)
        self.assertNotEqual(first['id'],second['id'])
        self.assertIsNone(claim(self.sessions))
        with self.sessions.begin() as s:
            s.get(ValidationJob,first['id']).lease_until=utcnow()-timedelta(seconds=1)
        retried=claim(self.sessions)
        self.assertEqual(retried['id'],first['id'])
        with self.assertRaises(ValueError):
            complete(self.sessions,first['id'],first['lease_token'],self.result(first))
        with self.sessions.begin() as s:
            s.get(WatchProject,1).followed=False
        with self.assertRaises(ValueError):
            complete(self.sessions,retried['id'],retried['lease_token'],self.result(retried))

    def test_real_verdict_and_error_are_distinct(self):
        self.seed(); enqueue(self.sessions)
        older=claim(self.sessions)
        complete(self.sessions,older['id'],older['lease_token'],self.result(older))
        newer=claim(self.sessions)
        bad=self.result(newer); bad['metrics']['failed_files']=1
        with self.assertRaises(ValueError):
            complete(self.sessions,newer['id'],newer['lease_token'],bad)
        complete(self.sessions,newer['id'],newer['lease_token'],self.result(newer,'failed'))
        data=overview(self.sessions)
        self.assertEqual(data['alerts'][0]['kind'],'regression')
        self.assertEqual(data['projects'][0]['functional_status'],'not_configured')

    def test_scrapy_adds_functional_suite_without_limiting_other_projects(self):
        from app.models import ValidationJob
        self.seed('scrapy/scrapy'); enqueue(self.sessions)
        with self.sessions() as s:
            self.assertEqual({j.suite for j in s.scalars(select(ValidationJob))}, {'source-smoke-v1','scrapy-pagination-v1'})

    def test_error_has_backoff_and_never_becomes_regression(self):
        self.seed(); enqueue(self.sessions)
        job=claim(self.sessions)
        fail(self.sessions,job['id'],job['lease_token'],'TimeoutError')
        self.assertEqual(overview(self.sessions)['alerts'],[])
        next_job=claim(self.sessions)
        self.assertNotEqual(job['id'],next_job['id'])

    def test_api_retry_protects_origin_and_excludes_unfollowed_projects(self):
        from fastapi.testclient import TestClient
        from app.main import create_app
        from app.config import Settings
        self.seed(); enqueue(self.sessions)
        job=claim(self.sessions)
        fail(self.sessions,job['id'],job['lease_token'],'HTTPError')
        app=create_app(Settings(schedule_enabled=False),self.engine)
        with TestClient(app) as client:
            data=client.get('/api/watch/validation-jobs').json()
            self.assertIsNotNone(data['worker_last_seen'])
            path=f'/api/watch/validation-jobs/{job["id"]}/retry'
            self.assertEqual(client.post(path,json={},headers={'Origin':'https://evil.example'}).status_code,403)
            self.assertEqual(client.post(path,json={}).status_code,200)
            with self.sessions.begin() as s:
                s.get(WatchProject,1).followed=False
            self.assertEqual(client.get('/api/watch/validation-jobs').json()['projects'],[])

    def test_different_environment_never_claims_regression(self):
        self.seed(); enqueue(self.sessions)
        old=claim(self.sessions)
        complete(self.sessions,old['id'],old['lease_token'],self.result(old))
        new=claim(self.sessions)
        result=self.result(new,'failed')
        result['evidence']['python']='3.13.0'
        complete(self.sessions,new['id'],new['lease_token'],result)
        self.assertEqual(overview(self.sessions)['alerts'],[])

    def test_late_discovered_release_uses_observation_not_publication_time(self):
        from app.models import ValidationJob
        self.seed(); enqueue(self.sessions)
        with self.sessions.begin() as s:
            s.add(MonitorEvent(id=5,project_id=1,kind='release',source_id=5,title='late',body='',
                url='https://github.com/owner/project/releases/tag/v1.0.5',status='published',labels=[],
                source_at=utcnow()-timedelta(hours=2),changed_at=utcnow()))
        enqueue(self.sessions)
        with self.sessions() as s:
            self.assertIsNotNone(s.scalar(select(ValidationJob).where(ValidationJob.event_id==5)))

    def test_github_rate_limit_does_not_consume_attempts_or_claim_other_source_jobs(self):
        from app.models import ValidationJob
        self.seed(); enqueue(self.sessions)
        job=claim(self.sessions)
        fail(self.sessions,job['id'],job['lease_token'],'GitHubRateLimited',retry_after=120)
        self.assertIsNone(claim(self.sessions))
        with self.sessions.begin() as s:
            item=s.get(ValidationJob,job['id'])
            self.assertEqual(item.attempts,0)
            item.retry_at=utcnow()-timedelta(seconds=1)
        self.assertIsNotNone(claim(self.sessions))
