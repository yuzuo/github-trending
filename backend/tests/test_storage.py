from datetime import date, datetime, timezone
import os
import unittest
import uuid

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

from app.models import Base, Repository, SearchSnapshot, TrendingSnapshot, CollectionRun
from app.collector import Collector, save_repository
from app.config import Settings
from app.translation import TranslationError


def metadata(repo_id=1, name='octo/alpha', stars=100):
    now = datetime.now(timezone.utc)
    return dict(id=repo_id, full_name=name, html_url=f'https://github.com/{name}', description='Hello',
                language='Python', license='MIT', stars=stars, created_at=now, updated_at=now,
                pushed_at=now, default_branch='main')


class FailingTranslator:
    def translate(self, content):
        raise TranslationError('翻译服务失败')


class IdentityTranslator:
    def translate(self, content):
        return '中文 ' + content


@unittest.skipUnless(os.getenv('TEST_DATABASE_URL'), 'Set TEST_DATABASE_URL to a dedicated PostgreSQL test database')
class StorageTests(unittest.TestCase):
    def setUp(self):
        self.admin = create_engine(os.environ['TEST_DATABASE_URL'])
        if self.admin.url.get_backend_name() != 'postgresql' or not self.admin.url.database.endswith('_test'):
            raise RuntimeError('Tests require a PostgreSQL database ending in _test')
        self.schema = 'test_' + uuid.uuid4().hex
        with self.admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA {self.schema}'))
        self.engine = create_engine(os.environ['TEST_DATABASE_URL'], connect_args={'options': f'-csearch_path={self.schema}'})
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def tearDown(self):
        self.engine.dispose()
        with self.admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA {self.schema} CASCADE'))
        self.admin.dispose()

    def save(self, day=date(2026, 10, 12), stars=100, original='# Hello', translator=None):
        return save_repository(self.sessions, metadata(stars=stars), '# Hello' if original is None else original,
                               'README.md', dict(source='trending' if translator else 'search', daily_stars=20, trending_rank=1), day, translator)

    def test_same_day_immutable_and_historical_snapshot(self):
        self.save(stars=100)
        self.save(stars=120)
        self.save(day=date(2026, 10, 13), stars=150)
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Repository)), 1)
            snapshots = session.scalars(select(SearchSnapshot).order_by(SearchSnapshot.date)).all()
            self.assertEqual([item.stars for item in snapshots], [100, 150])

    def test_translation_failure_preserves_original_and_old_translation(self):
        self.save(translator=IdentityTranslator())
        self.save(day=date(2026, 10, 13), original='# Changed', translator=FailingTranslator())
        with self.sessions() as session:
            repo = session.get(Repository, 1)
            self.assertEqual(repo.readme_original, '# Changed')
            self.assertEqual(repo.readme_zh, '中文 # Hello')
            self.assertEqual(repo.translation_status, 'failed')
            self.assertNotEqual(repo.readme_hash, repo.translated_hash)

    def test_unchanged_readme_does_not_translate_again(self):
        self.save(translator=IdentityTranslator())
        self.save(translator=FailingTranslator())
        with self.sessions() as session:
            self.assertEqual(session.get(Repository, 1).translation_status, 'translated')

    def test_advisory_lock_prevents_overlap(self):
        first = Collector(self.engine, self.sessions, Settings(schedule_enabled=False))
        second = Collector(self.engine, self.sessions, Settings(schedule_enabled=False))
        with first.lock() as acquired:
            self.assertTrue(acquired)
            with second.lock() as other:
                self.assertFalse(other)
        with second.lock() as other:
            self.assertTrue(other)

    def test_partial_collection_keeps_successes(self):
        class Source:
            def search(self, limit):
                return [dict(full_name='octo/alpha', metadata=metadata(), daily_stars=None, rank=1),
                        dict(full_name='octo/beta', metadata=metadata(2, 'octo/beta'), daily_stars=None, rank=2)]
            def readme(self, name):
                from app.sources import SourceError
                if name.endswith('beta'):
                    raise SourceError('GitHub 请求失败')
                return '# Hello', 'README.md'
        collector = Collector(self.engine, self.sessions, Settings(schedule_enabled=False))
        collector.run(source=Source())
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Repository)), 1)
            run = session.scalar(select(CollectionRun))
            self.assertEqual((run.status, run.success_count, run.failure_count), ('partial', 1, 1))

    def test_api_sort_search_detail_and_origin(self):
        from fastapi.testclient import TestClient
        from app.main import create_app
        self.save()
        save_repository(self.sessions, metadata(2, 'octo/beta', 90), None, None,
                        dict(daily_stars=50, trending_rank=2), date(2026, 10, 12), None)
        with TestClient(create_app(Settings(schedule_enabled=False), self.engine)) as client:
            self.assertEqual(client.get('/api/health').status_code, 200)
            self.assertEqual(client.get('/api/dates').json(), ['2026-10-12'])
            rows = client.get('/api/repositories').json()['items']
            self.assertEqual([row['id'] for row in rows], [1, 2])
            self.assertEqual(rows[0]['rank'], 1)
            self.assertEqual(len(client.get('/api/repositories?q=alpha').json()['items']), 1)
            self.assertEqual(client.get('/api/repositories/1').json()['readme_original'], '# Hello')
            self.assertEqual(client.get('/api/repositories/99').status_code, 404)
            self.assertEqual(client.post('/api/collect', json={}, headers={'Origin': 'https://evil.test'}).status_code, 403)
            self.assertEqual(client.post('/api/collect', content='{}', headers={'Content-Type': 'text/plain'}).status_code, 415)
            self.assertEqual(client.get('/api/repositories?date=invalid').status_code, 422)

    def test_scheduler_startup_daily_and_no_hourly_success_repeat(self):
        collector = Collector(self.engine, self.sessions, Settings(schedule_enabled=False))
        now = datetime(2026, 10, 12, 2, tzinfo=timezone.utc)
        self.assertTrue(collector.due(now, startup=True))
        with self.sessions.begin() as session:
            session.add(CollectionRun(date=now.date(), status='success', started_at=now))
        self.assertFalse(collector.due(now, startup=True))
        self.assertFalse(collector.due(now))

    def test_failed_page_preserves_existing_snapshot(self):
        from app.sources import SourceError
        self.save()
        class Source:
            def search(self, limit):
                raise SourceError('页面结构异常')
        Collector(self.engine, self.sessions, Settings(schedule_enabled=False)).run(source=Source())
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(SearchSnapshot)), 1)
            self.assertEqual(session.scalar(select(CollectionRun.status)), 'failed')

    def test_configuring_translation_later_translates_description_without_readme(self):
        row = dict(source='trending', daily_stars=1, trending_rank=1)
        save_repository(self.sessions, metadata(), None, None, row, date(2026, 10, 12), None)
        save_repository(self.sessions, metadata(), None, None, row, date(2026, 10, 12), IdentityTranslator())
        with self.sessions() as session:
            self.assertEqual(session.get(Repository, 1).description_zh, '中文 Hello')

    def test_search_and_trending_same_day_are_isolated(self):
        from fastapi.testclient import TestClient
        from app.main import create_app
        day = date(2026, 10, 12)
        save_repository(self.sessions, metadata(), '# Legacy', 'README.md',
                        dict(source='trending', daily_stars=20, trending_rank=1), day, None)
        save_repository(self.sessions, metadata(stars=200), '# Current', 'README.md',
                        dict(source='search', daily_stars=None, rank=1), day, None)
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(SearchSnapshot)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(TrendingSnapshot)), 1)
        with TestClient(create_app(Settings(schedule_enabled=False), self.engine)) as client:
            current = client.get('/api/repositories').json()
            legacy = client.get('/api/repositories?source=trending').json()
            self.assertEqual(current['source'], 'search')
            self.assertEqual(current['items'][0]['stars'], 200)
            self.assertIsNone(current['items'][0]['daily_stars'])
            self.assertEqual(legacy['items'][0]['stars'], 100)
            self.assertEqual(legacy['items'][0]['daily_stars'], 20)

    def test_old_success_does_not_skip_new_source(self):
        now = datetime(2026, 10, 12, 2, tzinfo=timezone.utc)
        with self.sessions.begin() as session:
            session.add(CollectionRun(date=now.date(), source='trending', status='success', started_at=now))
        collector = Collector(self.engine, self.sessions, Settings(schedule_enabled=False))
        self.assertTrue(collector.due(now, startup=True))

    def test_legacy_schema_migration_preserves_rows_and_is_repeatable(self):
        from app.database import initialize_database
        self.save()
        with self.sessions.begin() as session:
            session.add(CollectionRun(date=date(2026, 10, 12), status='success'))
        with self.engine.begin() as connection:
            connection.execute(text('CREATE TABLE daily_snapshots (LIKE search_snapshots)'))
            connection.execute(text('INSERT INTO daily_snapshots SELECT * FROM search_snapshots'))
            connection.execute(text('DROP TABLE search_snapshots'))
            connection.execute(text('ALTER TABLE collection_runs DROP COLUMN source'))
        initialize_database(self.engine)
        initialize_database(self.engine)
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(TrendingSnapshot)).stars, 100)
            self.assertEqual(session.scalar(select(CollectionRun)).source, 'trending')
            self.assertEqual(session.get(Repository, 1).readme_original, '# Hello')
        self.save(stars=300)
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(SearchSnapshot)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(TrendingSnapshot)), 1)

    def test_refresh_preserves_existing_records_and_other_dates_and_sources(self):
        from app.models import utcnow
        from app.collector import TIMEZONE
        from datetime import timedelta
        day = utcnow().astimezone(TIMEZONE).date()
        self.save(day=day)
        self.save(day=day-timedelta(days=1))
        save_repository(self.sessions, metadata(), '# Old', 'README.md',
                        dict(source='trending', daily_stars=20, rank=1), day, None)
        class Source:
            def search(self, limit):
                return [dict(full_name='octo/beta', metadata=metadata(2, 'octo/beta'), daily_stars=None, rank=1)]
            def readme(self, name):
                return '# Beta', 'README.md'
        Collector(self.engine, self.sessions, Settings(schedule_enabled=False)).run(source=Source())
        with self.sessions() as session:
            current = session.scalars(select(SearchSnapshot).where(SearchSnapshot.date == day)).all()
            self.assertEqual(sorted(row.repository_id for row in current), [1, 2])
            self.assertEqual(session.scalar(select(func.count()).select_from(SearchSnapshot)), 3)
            self.assertEqual(session.scalar(select(func.count()).select_from(TrendingSnapshot)), 1)
            self.assertIsNotNone(session.get(Repository, 1))


if __name__ == '__main__':
    unittest.main()
