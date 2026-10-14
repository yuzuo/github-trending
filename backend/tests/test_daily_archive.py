import os
import unittest
from datetime import date, datetime, timezone
from sqlalchemy import select
from app.collector import Collector
from app.config import Settings
from app.models import CollectionRun, TrendingSnapshot
from app.sources import SourceError
from tests import test_storage as storage


@unittest.skipUnless(os.getenv('TEST_DATABASE_URL'), 'Requires test database')
class DailyArchiveTests(unittest.TestCase):
    setUp = storage.StorageTests.setUp
    tearDown = storage.StorageTests.tearDown

    def test_historical_api_uses_frozen_metadata_readme_and_filters(self):
        from fastapi.testclient import TestClient
        from app.main import create_app
        from app.collector import save_repository
        first, second = date(2026, 10, 12), date(2026, 10, 13)
        row = dict(source='trending', rank=1, daily_stars=10)
        save_repository(self.sessions, storage.metadata(), '# First', 'README.md', row, first, storage.IdentityTranslator())
        changed = {**storage.metadata(stars=200), 'description': 'New description', 'language': 'Rust'}
        save_repository(self.sessions, changed, '# Second', 'README.md', row, second, storage.IdentityTranslator())
        save_repository(self.sessions, {**changed, 'stars': 300}, '# Latest', 'README.md',
                        dict(source='search', rank=1), second, None)
        with TestClient(create_app(Settings(schedule_enabled=False), self.engine)) as client:
            old = client.get('/api/repositories/1?source=trending&date=2026-10-12').json()
            self.assertEqual((old['stars'], old['language'], old['readme_original']), (100, 'Python', '# First'))
            self.assertEqual(old['readme_zh'], '中文 # First')
            self.assertEqual(old['details_origin'], 'captured')
            result = client.get('/api/repositories?source=trending&date=2026-10-12&language=Python&q=Hello').json()
            self.assertEqual(result['languages'], ['Python'])
            self.assertEqual(len(result['items']), 1)
            self.assertEqual(client.get('/api/repositories?source=trending&date=2026-10-12&language=Rust').json()['items'], [])
            self.assertEqual(client.get('/api/repositories/1?source=trending&date=2026-10-11').status_code, 404)
            self.assertEqual(client.get('/api/repositories/1').json()['readme_original'], '# Latest')

    def test_one_am_shanghai_boundary_and_completed_day_never_repeats(self):
        collector = Collector(self.engine, self.sessions, Settings(schedule_enabled=False))
        before = datetime(2026, 10, 11, 16, 59, tzinfo=timezone.utc)
        after = datetime(2026, 10, 11, 17, 0, tzinfo=timezone.utc)
        self.assertFalse(collector.due(before, startup=True, kind='trending'))
        self.assertTrue(collector.due(after, startup=True, kind='trending'))
        with self.sessions.begin() as session:
            session.add(CollectionRun(date=date(2026, 10, 12), source='trending', status='success', started_at=before))
        self.assertFalse(collector.due(after, kind='trending'))

    def test_failed_retry_uses_first_daily_membership_and_skips_completed_items(self):
        class Source:
            attempts = 0
            def trending(self):
                self.attempts += 1
                if self.attempts != 1:
                    raise AssertionError('must retain initial membership')
                return [dict(full_name='o/one', rank=1, daily_stars=10), dict(full_name='o/two',rank=2,daily_stars=5)]
            def repository(self, name):
                if name == 'o/two' and not self.retry:
                    raise SourceError('temporary failure')
                if name == 'o/one' and self.retry:
                    raise AssertionError('completed item must not refetch')
                return storage.metadata(1 if name=='o/one' else 2, name)
            def readme(self, name):
                return '# Hello', 'README.md'
            retry = False
        source = Source()
        collector = Collector(self.engine, self.sessions, Settings(schedule_enabled=False))
        from app.models import utcnow
        from app.collector import TIMEZONE
        from app.database import initialize_database
        with self.sessions.begin() as session:
            session.add(CollectionRun(date=utcnow().astimezone(TIMEZONE).date(), source='trending', status='failed'))
        collector.run(source=source,kind='trending')
        initialize_database(self.engine)
        source.retry = True
        collector.run(source=source,kind='trending')
        self.assertFalse(collector.run(source=source,kind='trending'))
        with self.sessions() as session:
            self.assertEqual(len(session.scalars(select(TrendingSnapshot)).all()), 2)
            runs = session.scalars(select(CollectionRun).order_by(CollectionRun.id)).all()
            self.assertEqual([run.status for run in runs], ['failed', 'partial', 'success'])
            self.assertEqual(runs[1].items, runs[2].items)
