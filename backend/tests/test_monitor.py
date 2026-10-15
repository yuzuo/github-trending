from datetime import timedelta
import os
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from app.sources import GitHubSource, SourceError, RateLimited
from app.models import utcnow
from tests import test_storage as storage


def issue(state='open', title='Pagination fails', number=1):
    return dict(id=number, number=number, title=title, body='Steps to reproduce', state=state,
                state_reason='completed' if state == 'closed' else None, labels=[{'name': 'bug'}],
                updated_at=utcnow().isoformat(), created_at=utcnow().isoformat())


def release(draft=False):
    return dict(id=11, tag_name='v2.0', name='New extraction', body='Adds streaming',
                draft=draft, prerelease=False, published_at=utcnow().isoformat())


class MonitorSourceTests(unittest.TestCase):
    def test_filters_prs_and_drafts_and_uses_incremental_query(self):
        from app.monitor import fetch_page
        requests = []
        def respond(request):
            requests.append(request)
            rows = [issue(), {**issue(number=2), 'pull_request': {}}] if request.url.path.endswith('issues') else [release(), release(True)]
            return httpx.Response(200, json=rows, headers={'Link': '<https://api.github.com/next>; rel="next"'})
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            source = GitHubSource(client)
            rows, more = fetch_page(source, 'octo/alpha', 'issue', utcnow(), 2)
            self.assertEqual(len(rows), 1)
            self.assertTrue(more)
            self.assertEqual(requests[0].url.params['state'], 'all')
            self.assertEqual(requests[0].url.params['direction'], 'asc')
            self.assertEqual(requests[0].url.params['page'], '2')
            rows, _ = fetch_page(source, 'octo/alpha', 'release')
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['status'], 'published')
            self.assertEqual(rows[0]['url'], 'https://github.com/octo/alpha/releases/tag/v2.0')

    def test_bad_payload_does_not_advance(self):
        from app.monitor import fetch_page
        for payload in ({'message': 'bad'}, [issue(state='unexpected')], [{**issue(), 'updated_at': 'yesterday'}]):
            with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))) as client:
                with self.assertRaises(SourceError):
                    fetch_page(GitHubSource(client), 'octo/alpha', 'issue', utcnow())


class FakeSource:
    def __init__(self):
        self.issue = issue()
        self.release = release()
        self.pages = []
        self.fail_page = None
        self.more = False

    def repository(self, name, public_only=False):
        return storage.metadata()

    def _get(self, url, params=None):
        if url.endswith('/releases'):
            return httpx.Response(200, json=[self.release])
        self.pages.append(params['page'])
        if params['page'] == self.fail_page:
            raise RateLimited((utcnow() + timedelta(hours=1)).timestamp())
        return httpx.Response(200, json=[self.issue], headers={
            'Link': '<https://api.github.com/next>; rel="next"'} if self.more else {})


@unittest.skipUnless(os.getenv('TEST_DATABASE_URL'), 'Requires dedicated PostgreSQL test database')
class MonitorStorageTests(unittest.TestCase):
    setUp = storage.StorageTests.setUp
    tearDown = storage.StorageTests.tearDown

    def service(self):
        from app.collector import Collector
        from app.config import Settings
        from app.monitor import MonitorService
        from app.models import WatchProject
        collector = Collector(self.engine, self.sessions, Settings(schedule_enabled=False))
        self.addCleanup(collector.close)
        with self.sessions.begin() as session:
            session.add(WatchProject(id=1, full_name='octo/alpha', details={}, followed=True, notes='keep'))
        return MonitorService(collector)

    def test_baseline_dedup_close_reopen_and_new_release(self):
        from app.models import MonitorEvent, WatchProject
        service, source = self.service(), FakeSource()
        service.run(source=source)
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(MonitorEvent)), 2)
            self.assertFalse(any(e.unread for e in session.scalars(select(MonitorEvent))))
        service.run(source=source)
        source.issue = issue('closed')
        service.run(source=source)
        with self.sessions() as session:
            event = session.scalar(select(MonitorEvent).where(MonitorEvent.kind == 'issue'))
            self.assertEqual(event.status, 'closed')
            self.assertTrue(event.unread)
            self.assertEqual(len(event.history), 2)
            self.assertEqual(session.get(WatchProject, 1).notes, 'keep')
        source.issue = issue('open')
        source.release = {**release(), 'id': 12, 'tag_name': 'v3'}
        service.run(source=source)
        with self.sessions() as session:
            event = session.scalar(select(MonitorEvent).where(MonitorEvent.kind == 'issue'))
            self.assertEqual(event.status, 'open')
            self.assertEqual(len(event.history), 3)
            self.assertTrue(session.scalar(select(MonitorEvent).where(MonitorEvent.source_id == 12)).unread)

    def test_pagination_checkpoint_and_shared_cooldown(self):
        from app.models import MonitorState, MonitorRun
        service, source = self.service(), FakeSource()
        source.more, source.fail_page = True, 2
        service.run(source=source)
        with self.sessions() as session:
            state = session.get(MonitorState, 1)
            self.assertEqual(state.issue_page, 2)
            self.assertIsNone(state.checked_at)
            self.assertEqual(session.scalar(select(MonitorRun)).status, 'partial')
        self.assertIsNotNone(service.collector.cooldown())
        self.assertFalse(service.start())
        source.more, source.fail_page = False, None
        service.run(source=source)
        self.assertEqual(source.pages, [1, 2, 2])
        with self.sessions() as session:
            self.assertEqual(session.get(MonitorState, 1).issue_page, 1)
            self.assertIsNotNone(session.get(MonitorState, 1).checked_at)

    def test_hidden_and_unfollowed_do_not_request(self):
        from app.models import WatchProject
        service, source = self.service(), FakeSource()
        for field in ('hidden', 'followed'):
            with self.sessions.begin() as session:
                project = session.get(WatchProject, 1)
                project.hidden = field == 'hidden'
                project.followed = field != 'followed'
            service.run(source=source)
        self.assertEqual(source.pages, [])

    def test_api_filters_read_race_and_write_origin(self):
        from app.models import MonitorEvent
        from app.main import create_app
        from app.config import Settings
        service, source = self.service(), FakeSource()
        service.run(source=source)
        source.issue = issue('closed')
        service.run(source=source)
        app = create_app(Settings(schedule_enabled=False), self.engine)
        with TestClient(app) as client:
            result = client.get('/api/watch/events?unread=true').json()
            self.assertEqual(result['total'], 1)
            event = result['items'][0]
            path = f'/api/watch/events/{event["id"]}/read'
            body = {'changed_at': event['changed_at']}
            self.assertEqual(client.post(path, json=body, headers={'Origin': 'https://evil.test'}).status_code, 403)
            source.issue = issue('open')
            service.run(source=source)
            self.assertEqual(client.post(path, json=body).status_code, 409)
            current = client.get('/api/watch/events?unread=true').json()['items'][0]
            self.assertEqual(client.post(path, json={'changed_at': current['changed_at']}).status_code, 200)
            self.assertEqual(client.get('/api/watch/events?unread=true').json()['total'], 0)
            self.assertEqual(client.get('/api/watch/events?limit=9999').status_code, 422)
            self.assertEqual(client.get('/api/watch/monitor').json()['projects'][0]['full_name'], 'octo/alpha')

    def test_recovery_and_busy_lock(self):
        from app.models import MonitorRun
        service = self.service()
        with self.sessions.begin() as session:
            session.add(MonitorRun())
        service.recover()
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(MonitorRun)).status, 'interrupted')
        service.collector.busy.acquire()
        try:
            self.assertFalse(service.start())
        finally:
            service.collector.busy.release()

    def test_page_budget_resumes_without_restarting_and_completed_waits_six_hours(self):
        from app.models import MonitorState, MonitorRun
        service, source = self.service(), FakeSource()
        source.more = True
        service.run(source=source)
        self.assertEqual(source.pages, [1, 2, 3])
        with self.sessions() as session:
            self.assertEqual(session.get(MonitorState, 1).issue_page, 4)
        source.more = False
        service.run(source=source)
        self.assertEqual(source.pages, [1, 2, 3, 4])
        self.assertFalse(service.due())
        with self.sessions.begin() as session:
            for run in session.scalars(select(MonitorRun)):
                run.started_at -= timedelta(hours=7)
            session.get(MonitorState, 1).checked_at -= timedelta(hours=7)
        self.assertTrue(service.due())

    def test_comment_only_update_keeps_read_state_and_older_source_time(self):
        from app.models import MonitorEvent
        service, source = self.service(), FakeSource()
        service.run(source=source)
        source.issue = {**source.issue, 'comments': 99, 'updated_at': utcnow().isoformat()}
        service.run(source=source)
        with self.sessions() as session:
            event = session.scalar(select(MonitorEvent).where(MonitorEvent.kind == 'issue'))
            self.assertFalse(event.unread)
            self.assertEqual(len(event.history), 1)

    def test_existing_schema_upgrade_preserves_project_and_notes(self):
        from app.models import MonitorState, MonitorRun, MonitorEvent, WatchProject, EventAnalysis
        from app.database import initialize_database
        self.service()
        with self.engine.begin() as connection:
            for table in (EventAnalysis.__table__, MonitorEvent.__table__, MonitorState.__table__, MonitorRun.__table__):
                table.drop(connection)
        initialize_database(self.engine)
        initialize_database(self.engine)
        with self.sessions() as session:
            self.assertEqual(session.get(WatchProject, 1).notes, 'keep')
            self.assertEqual(session.scalar(select(func.count()).select_from(MonitorEvent)), 0)
