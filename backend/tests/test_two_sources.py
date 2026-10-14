from datetime import date, datetime, timezone
from unittest.mock import patch

from sqlalchemy import inspect, select, text
from fastapi.testclient import TestClient

from app.collector import Collector, save_repository
from app.config import Settings
from app.database import initialize_database
from app.main import create_app
from app.models import SearchSnapshot, TrendingSnapshot, CollectionRun
import unittest
import os
from tests import test_storage as storage
from tests.test_storage import metadata


@unittest.skipUnless(os.getenv('TEST_DATABASE_URL'), 'Requires test database')
class TwoSourcesTests(unittest.TestCase):
    setUp = storage.StorageTests.setUp
    tearDown = storage.StorageTests.tearDown
    save = storage.StorageTests.save

    def test_readme_added_by_search_is_translated_on_next_trending(self):
        from app.models import Repository
        from tests.test_storage import IdentityTranslator
        info = {**metadata(), 'description': None}
        day = date(2026, 10, 12)
        trend = dict(source='trending', rank=1, daily_stars=2)
        save_repository(self.sessions, info, None, None, trend, day, IdentityTranslator())
        save_repository(self.sessions, info, '# Added', 'README.md', dict(source='search', rank=1), day, None)
        save_repository(self.sessions, info, '# Added', 'README.md', trend, date(2026, 10, 13), IdentityTranslator())
        with self.sessions() as session:
            self.assertEqual(session.get(Repository, 1).readme_zh, '中文 # Added')

    def test_only_trending_calls_translator_and_search_preserves_translation(self):
        from app.models import Repository
        day = date(2026, 10, 12)
        with patch('app.collector.Translator') as factory:
            factory.return_value.translate.side_effect = lambda content: '中文 ' + content
            class Source:
                def search(self, limit):
                    return [dict(metadata=metadata(), full_name='octo/alpha', rank=1, daily_stars=None)]
                def trending(self):
                    return [dict(full_name='octo/alpha', rank=1, daily_stars=10)]
                def repository(self, name):
                    return metadata()
                def readme(self, name):
                    return '# Hello', 'README.md'
            settings = Settings(schedule_enabled=False, translation_base_url='https://translator.test',
                                translation_model='test', translation_api_key='test')
            collector = Collector(self.engine, self.sessions, settings)
            collector.run(source=Source(), kind='search')
            factory.assert_not_called()
            collector.run(source=Source(), kind='trending')
            self.assertEqual(factory.return_value.translate.call_count, 2)
            collector.run(source=Source(), kind='search')
            self.assertEqual(factory.call_count, 1)
        with self.sessions() as session:
            repo = session.get(Repository, 1)
            self.assertEqual(repo.readme_zh, '中文 # Hello')
            self.assertEqual(repo.translation_status, 'translated')
        with patch('app.collector.Translator') as factory:
            save_repository(self.sessions, {**metadata(), 'description':'Changed description'}, '# Hello',
                'README.md', dict(source='search', rank=1), date(2026, 10, 13), factory.return_value)
            factory.return_value.translate.assert_not_called()
        with self.sessions() as session:
            self.assertEqual(session.get(Repository, 1).translation_status, 'stale')

    def test_ip_and_localhost_access_preserve_origin_and_host_checks(self):
        app = create_app(Settings(schedule_enabled=False, app_origin='http://192.168.1.169:8080'), self.engine)
        with TestClient(app) as client, patch.object(app.state.collector, 'start', return_value=True):
            for host in ('192.168.1.169:8080', 'localhost:8080', '127.0.0.1:8080'):
                self.assertEqual(client.get('/api/health', headers={'Host':host}).status_code, 200)
                self.assertEqual(client.post('/api/collect?source=trending', json={},
                    headers={'Host':host, 'Origin':'http://' + host}).status_code, 202)
            self.assertEqual(client.get('/api/health', headers={'Host':'evil.test'}).status_code, 400)
            self.assertEqual(client.post('/api/collect', json={}, headers={
                'Host':'192.168.1.169:8080', 'Origin':'https://evil.test'}).status_code, 403)
    def test_independent_tables_and_scheduler(self):
        self.assertIn('search_snapshots', inspect(self.engine).get_table_names())
        self.assertIn('trending_snapshots', inspect(self.engine).get_table_names())
        now = datetime(2026, 10, 12, 2, tzinfo=timezone.utc)
        with self.sessions.begin() as session:
            session.add(CollectionRun(date=now.date(), source='search', status='success', started_at=now))
        collector = Collector(self.engine, self.sessions, Settings(schedule_enabled=False))
        self.assertFalse(collector.due(now, startup=True, kind='search'))
        self.assertTrue(collector.due(now, startup=True, kind='trending'))

    def test_trending_collection_and_manual_source_validation(self):
        class Source:
            def trending(self):
                return [dict(full_name='octo/alpha', rank=1, daily_stars=42, source='trending')]
            def repository(self, name):
                return metadata()
            def readme(self, name):
                return '# Test', 'README.md'
        collector = Collector(self.engine, self.sessions, Settings(schedule_enabled=False))
        collector.run(source=Source(), kind='trending')
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(TrendingSnapshot)).daily_stars, 42)
            self.assertIsNone(session.scalar(select(SearchSnapshot)))
            self.assertEqual(session.scalar(select(CollectionRun)).source, 'trending')
        app = create_app(Settings(schedule_enabled=False), self.engine)
        with TestClient(app) as client, patch.object(app.state.collector, 'start', return_value=True) as start:
            self.assertEqual(client.post('/api/collect?source=trending', json={}).status_code, 202)
            start.assert_called_once_with(kind='trending')
            self.assertEqual(client.post('/api/collect?source=other', json={}).status_code, 422)
            self.assertEqual(client.get('/api/repositories?source=other').status_code, 422)

    def test_mixed_legacy_migration_is_lossless(self):
        self.save()
        with self.engine.begin() as connection:
            connection.execute(text('CREATE TABLE daily_snapshots (LIKE search_snapshots INCLUDING DEFAULTS)'))
            connection.execute(text("ALTER TABLE daily_snapshots ADD COLUMN source VARCHAR(24) NOT NULL DEFAULT 'search'"))
            connection.execute(text("INSERT INTO daily_snapshots SELECT *, 'search' FROM search_snapshots"))
            connection.execute(text("INSERT INTO daily_snapshots (id, repository_id, date, trending_rank, daily_stars, stars, fetched_at, source) SELECT id+100, repository_id, date, trending_rank, 25, stars, fetched_at, 'trending' FROM search_snapshots"))
            connection.execute(text('DELETE FROM search_snapshots'))
        initialize_database(self.engine)
        initialize_database(self.engine)
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(SearchSnapshot)).stars, 100)
            self.assertEqual(session.scalar(select(TrendingSnapshot)).daily_stars, 25)
        self.assertNotIn('daily_snapshots', inspect(self.engine).get_table_names())

    def test_migration_mismatch_keeps_legacy_table(self):
        self.save()
        with self.engine.begin() as connection:
            connection.execute(text('CREATE TABLE daily_snapshots (LIKE search_snapshots INCLUDING DEFAULTS)'))
            connection.execute(text("ALTER TABLE daily_snapshots ADD COLUMN source VARCHAR(24) NOT NULL DEFAULT 'search'"))
            connection.execute(text("INSERT INTO daily_snapshots SELECT *, 'search' FROM search_snapshots"))
            connection.execute(text('UPDATE daily_snapshots SET stars=999'))
        with self.assertRaises(RuntimeError):
            initialize_database(self.engine)
        self.assertIn('daily_snapshots', inspect(self.engine).get_table_names())
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(text('SELECT stars FROM daily_snapshots')), 999)
