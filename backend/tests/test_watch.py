from datetime import datetime, timedelta, timezone
import os
import unittest
from unittest.mock import patch
import httpx

from fastapi.testclient import TestClient
from sqlalchemy import select, func

from app import sources
from tests import test_storage as storage
from tests.test_storage import metadata


class WatchRulesTests(unittest.TestCase):
    def test_discovery_merges_matches_and_reports_incomplete_queries(self):
        from app.watch import discover_projects
        from tests.test_sources import search_item
        requests = []
        def respond(request):
            requests.append(request)
            self.assertIn('fork:false archived:false', request.url.params['q'])
            item = {**search_item(), 'fork': False, 'archived': False}
            return httpx.Response(200, json={'incomplete_results': len(requests) == 1,
                                            'total_count': 1, 'items': [item]})
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            rows, errors = discover_projects(sources.GitHubSource(client))
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]['reasons']), 6)
        self.assertEqual(len(errors), 1)
        self.assertEqual(len(requests), 12)

    def test_private_repo_is_rejected_even_with_token(self):
        from tests.test_sources import search_item
        with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={**search_item(), 'private': True}))) as client:
            with self.assertRaises(sources.SourceError):
                sources.GitHubSource(client, 'secret').repository('o/repo1', public_only=True)

    def test_repository_input_restricts_host_and_path(self):
        from app.watch import repository_name
        for value in ('octo/alpha', 'https://github.com/octo/alpha', 'https://github.com/octo/alpha.git/'):
            self.assertEqual(repository_name(value), 'octo/alpha')
        for value in ('http://localhost/x/y', 'https://github.com.evil/x/y',
                      'https://u@github.com/x/y', 'https://github.com/x/y/issues',
                      'https://github.com/x/y?token=a', '../repo', 'https://github.com:444/x/y'):
            with self.subTest(value=value), self.assertRaises(sources.SourceError):
                repository_name(value)

    def test_growth_uses_older_baseline_with_six_hour_tolerance(self):
        from app.watch import growth_metrics
        now = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)
        samples = [dict(stars=80, fetched_at=now-timedelta(days=7, hours=6)),
                   dict(stars=110, fetched_at=now-timedelta(hours=24)),
                   dict(stars=115, fetched_at=now-timedelta(hours=23)),
                   dict(stars=100, fetched_at=now)]
        result = growth_metrics(samples, now)
        self.assertEqual(result['growth_24h']['delta'], -10)
        self.assertEqual(result['growth_7d']['delta'], 20)
        self.assertEqual(result['growth_7d']['start'], samples[0]['fetched_at'])
        self.assertFalse(result['stale'])

    def test_missing_baseline_and_stale_never_become_zero(self):
        from app.watch import growth_metrics, ranking_key
        now = datetime(2026, 10, 14, tzinfo=timezone.utc)
        result = growth_metrics([dict(stars=5, fetched_at=now-timedelta(hours=13))], now)
        self.assertIsNone(result['growth_24h'])
        self.assertIsNone(result['growth_7d'])
        self.assertTrue(result['stale'])
        recent = dict(id=1, stars=100, stale=False, growth_7d={'delta': -1})
        stale = dict(id=2, stars=200, stale=True, growth_7d={'delta': 99})
        missing = dict(id=3, stars=300, stale=False, growth_7d=None)
        self.assertEqual(sorted([missing, stale, recent], key=lambda x: ranking_key(x, 'growth_7d')), [recent, stale, missing])
        for offset in (timedelta(hours=30, seconds=1), timedelta(hours=23)):
            samples = [dict(stars=1, fetched_at=now-offset), dict(stars=5, fetched_at=now)]
            self.assertIsNone(growth_metrics(samples, now)['growth_24h'])


@unittest.skipUnless(os.getenv('TEST_DATABASE_URL'), 'Requires dedicated PostgreSQL test database')
class WatchStorageTests(unittest.TestCase):
    setUp = storage.StorageTests.setUp
    tearDown = storage.StorageTests.tearDown

    def app(self):
        from app.main import create_app
        from app.config import Settings
        return create_app(Settings(schedule_enabled=False), self.engine)

    def test_add_review_hide_restore_and_duplicate(self):
        from app.models import WatchProject, WatchSample
        app = self.app()
        with TestClient(app) as client, patch('app.watch.GitHubSource.repository', return_value=metadata()), patch('app.watch.GitHubSource.readme', return_value=('# README', 'README.md')):
            response = client.post('/api/watch/projects', json={'repository': 'https://github.com/octo/alpha'})
            self.assertEqual(response.status_code, 201, response.text)
            self.assertEqual(response.json()['full_name'], 'octo/alpha')
            self.assertIsNone(response.json()['growth_7d'])
            self.assertEqual(client.post('/api/watch/projects', json={'repository': 'octo/alpha'}).status_code, 201)
            response = client.patch('/api/watch/projects/1', json={'review_status': 'reviewed', 'rating': 4, 'notes': '<script>literal</script>', 'followed': True})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(client.get('/api/watch/projects/1').json()['notes'], '<script>literal</script>')
            self.assertEqual(client.patch('/api/watch/projects/1', json={'rating': 6}).status_code, 422)
            self.assertEqual(client.patch('/api/watch/projects/1', json={'review_status': 'unknown'}).status_code, 422)
            self.assertEqual(client.patch('/api/watch/projects/1', json={'hidden': True}).status_code, 200)
            self.assertEqual(client.get('/api/watch/projects').json()['items'], [])
            self.assertEqual(len(client.get('/api/watch/projects?view=hidden').json()['items']), 1)
            self.assertEqual(client.patch('/api/watch/projects/1', json={'hidden': False}).status_code, 200)
            self.assertEqual(client.get('/api/watch/projects?view=following').json()['items'][0]['rating'], 4)
            self.assertEqual(client.post('/api/watch/projects', json={'repository':'https://evil.test/x/y'}).status_code, 422)
            self.assertEqual(client.patch('/api/watch/projects/1', json={'notes':'x'}, headers={'Origin':'https://evil.test'}).status_code, 403)
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(WatchProject)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(WatchSample)), 1)

    def test_refresh_samples_preserve_reviews_and_failures(self):
        from app.watch import WatchService
        from app.collector import Collector
        from app.config import Settings
        from app.models import WatchProject, WatchSample, WatchRun
        settings = Settings(schedule_enabled=False)
        collector = Collector(self.engine, self.sessions, settings)
        service = WatchService(collector)
        service.add_project('octo/alpha', source=FakeSource())
        with self.sessions.begin() as session:
            project = session.get(WatchProject, 1)
            project.notes = 'Keep me'
            project.followed = True
        service.run(source=FakeSource(stars=150), discover=False)
        service.run(source=FakeSource(fail=True), discover=False)
        with self.sessions() as session:
            project = session.get(WatchProject, 1)
            self.assertEqual(project.notes, 'Keep me')
            self.assertEqual(project.details['stars'], 150)
            self.assertTrue(project.last_error)
            self.assertEqual(session.scalar(select(func.count()).select_from(WatchSample)), 2)
            run = session.scalar(select(WatchRun).order_by(WatchRun.id.desc()))
            self.assertEqual(run.status, 'failed')
        collector.close()

    def test_capacity_restore_and_discovery_keep_hidden_projects(self):
        from app.models import WatchProject, WatchSample
        app = self.app()
        with TestClient(app) as client, patch('app.watch.GitHubSource.repository', return_value=metadata()), patch('app.watch.GitHubSource.readme', return_value=('# README', 'README.md')):
            self.assertEqual(client.post('/api/watch/projects', json={'repository':'octo/alpha'}).status_code, 201)
            client.patch('/api/watch/projects/1', json={'hidden': True})
            app.state.watch.run(source=FakeSource(), discover=False)
            with self.sessions() as session:
                self.assertTrue(session.get(WatchProject, 1).hidden)
                self.assertEqual(session.scalar(select(func.count()).select_from(WatchSample)), 1)
            with patch('app.watch_api.CAPACITY', 0):
                self.assertEqual(client.patch('/api/watch/projects/1', json={'hidden': False}).status_code, 409)
            self.assertTrue(client.get('/api/watch/projects/1').json()['hidden'])
            with patch('app.watch.CAPACITY', 0), patch('app.watch.GitHubSource.repository', return_value=metadata(2, 'octo/beta')):
                self.assertEqual(client.post('/api/watch/projects', json={'repository':'octo/beta'}).status_code, 409)

    def test_monitor_cooldown_is_shared_with_boards_and_recovers(self):
        from app.models import WatchRun, WatchSample
        from app.collector import Collector
        from app.config import Settings
        from app.watch import WatchService
        collector = Collector(self.engine, self.sessions, Settings(schedule_enabled=False))
        service = WatchService(collector)
        now = datetime.now(timezone.utc)
        with self.sessions.begin() as session:
            session.add(WatchRun(status='running'))
        service.recover()
        with self.sessions() as session:
            run = session.scalar(select(WatchRun))
            self.assertEqual(run.status, 'interrupted')
        self.assertFalse(service.due(now))
        self.assertTrue(service.due(now+timedelta(hours=2)))
        service.record_cooldown(sources.RateLimited((now+timedelta(hours=1)).timestamp()))
        self.assertFalse(service.start())
        self.assertFalse(collector.start(kind='search'))
        self.assertIsNotNone(collector.cooldown())
        with self.assertRaises(Exception):
            service.add_project('octo/alpha', FakeSource())
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(WatchSample)), 0)
        collector.close()

    def test_run_status_exists_before_worker_executes_and_respects_busy(self):
        app = self.app()
        with TestClient(app) as client, patch.object(app.state.collector.executor, 'submit') as submit:
            response = client.post('/api/watch/refresh', json={})
            self.assertEqual(response.status_code, 202)
            self.assertEqual(client.get('/api/watch/run').json()['status'], 'running')
            self.assertEqual(client.post('/api/watch/refresh', json={}).status_code, 409)
            submit.assert_called_once()
            app.state.collector.busy.release()

    def test_observation_run_id_is_idempotent_and_growth_api_uses_samples(self):
        from app.models import WatchRun, WatchSample
        app = self.app()
        with TestClient(app) as client:
            now = datetime.now(timezone.utc)
            with self.sessions.begin() as session:
                run = WatchRun(status='success', finished_at=now)
                session.add(run)
                session.flush()
                run_id = run.id
            app.state.watch.save_observation(metadata(stars=110), 'readme', 'README.md', run_id)
            app.state.watch.save_observation(metadata(stars=999), 'changed', 'README.md', run_id)
            with self.sessions.begin() as session:
                latest = session.scalar(select(WatchSample))
                session.add(WatchSample(project_id=1, stars=100, fetched_at=latest.fetched_at-timedelta(days=7)))
            item = client.get('/api/watch/projects').json()['items'][0]
            self.assertEqual(item['stars'], 110)
            self.assertEqual(item['growth_7d']['delta'], 10)
            self.assertEqual(client.get('/api/watch/projects?q=absent').json()['items'], [])
            self.assertEqual(len(client.get('/api/watch/projects?language=Python').json()['items']), 1)

    def test_discovery_resumes_after_rate_limit_without_repeating_completed_queries(self):
        from app.collector import Collector
        from app.config import Settings
        from app.watch import WatchService
        from app.models import WatchProject
        from tests.test_sources import search_item
        queries = []
        def respond(request):
            if request.url.path == '/search/repositories':
                queries.append((request.url.params['q'], request.url.params['sort']))
                if len(queries) == 11:
                    return httpx.Response(429, headers={'Retry-After':'60'})
                return httpx.Response(200, json={'incomplete_results':False, 'total_count':1,
                    'items':[{**search_item(), 'fork':False, 'archived':False}]})
            if request.url.path == '/repos/o/repo1':
                return httpx.Response(200, json=search_item())
            return httpx.Response(404)
        collector = Collector(self.engine, self.sessions, Settings(schedule_enabled=False))
        service = WatchService(collector)
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            source = sources.GitHubSource(client)
            service.run(source=source)
            service.run(source=source)
        self.assertEqual(len(queries), 13)
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(WatchProject)), 1)
        collector.close()

    def test_retry_skips_successful_projects_in_same_monitor_cycle(self):
        from app.collector import Collector
        from app.config import Settings
        from app.watch import WatchService
        from app.models import WatchProject, WatchSample
        collector = Collector(self.engine, self.sessions, Settings(schedule_enabled=False))
        service = WatchService(collector)
        service.save_observation(metadata(), '', None)
        service.save_observation(metadata(2, 'octo/beta'), '', None)
        class PartialSource(FakeSource):
            def repository(self, name, public_only=False):
                if name == 'octo/beta':
                    raise sources.SourceError('network')
                return metadata()
        service.run(source=PartialSource(), discover=False)
        class RetrySource(FakeSource):
            def repository(self, name, public_only=False):
                if name == 'octo/alpha':
                    raise AssertionError('Successful project must not be fetched on retry')
                return metadata(2, 'octo/beta')
        service.run(source=RetrySource(), discover=False)
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(WatchSample)), 4)
            self.assertIsNone(session.get(WatchProject, 1).last_error)
        collector.close()

    def test_persistent_failure_does_not_freeze_healthy_projects(self):
        from app.collector import Collector
        from app.config import Settings
        from app.watch import WatchService
        from app.models import WatchRun, WatchProject
        collector = Collector(self.engine, self.sessions, Settings(schedule_enabled=False))
        service = WatchService(collector)
        now = datetime.now(timezone.utc)
        service.save_observation(metadata(), '', None)
        with self.sessions.begin() as session:
            session.get(WatchProject, 1).fetched_at = now-timedelta(hours=7)
            session.add(WatchRun(status='partial', started_at=now-timedelta(hours=1),
                cycle_started_at=now-timedelta(days=2), finished_at=now))
        service.run(source=FakeSource(stars=999), discover=False)
        with self.sessions() as session:
            self.assertEqual(session.get(WatchProject, 1).details['stars'], 999)
        collector.close()

    def test_discovery_revalidates_public_visibility_before_readme(self):
        from app.collector import Collector
        from app.config import Settings
        from app.watch import WatchService
        from app.models import WatchProject
        from tests.test_sources import search_item
        readmes = []
        def respond(request):
            if request.url.path == '/search/repositories':
                return httpx.Response(200, json={'incomplete_results':False, 'total_count':1,
                    'items':[{**search_item(), 'fork':False, 'archived':False}]})
            if request.url.path.endswith('/readme'):
                readmes.append(request)
                return httpx.Response(404)
            return httpx.Response(200, json={**search_item(), 'private':True})
        collector = Collector(self.engine, self.sessions, Settings(schedule_enabled=False))
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            WatchService(collector).run(source=sources.GitHubSource(client, 'secret'))
        self.assertEqual(readmes, [])
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(WatchProject)), 0)
        collector.close()


class FakeSource:
    def __init__(self, stars=100, fail=False):
        self.stars, self.fail = stars, fail

    def repository(self, name, public_only=False):
        if self.fail:
            raise sources.SourceError('GitHub 网络请求失败')
        return metadata(stars=self.stars)

    def readme(self, name):
        return '# README', 'README.md'
