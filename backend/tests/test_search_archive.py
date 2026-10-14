import os
import unittest
from datetime import date, datetime, timezone
from unittest.mock import Mock
from fastapi.testclient import TestClient
from app.collector import Collector, save_repository
from app.config import Settings
from app.main import create_app
from tests import test_storage as storage


@unittest.skipUnless(os.getenv('TEST_DATABASE_URL'), 'Requires PostgreSQL')
class SearchArchiveTests(unittest.TestCase):
    setUp = storage.StorageTests.setUp
    tearDown = storage.StorageTests.tearDown

    def test_search_snapshot_is_immutable_and_detail_is_dated_without_translation(self):
        translator = Mock()
        row = dict(source='search', rank=1)
        for day, stars, content in [(date(2026,10,12),100,'first'), (date(2026,10,12),200,'ignored'), (date(2026,10,13),300,'second')]:
            save_repository(self.sessions, storage.metadata(stars=stars), content, 'README.md', row, day, translator)
        translator.translate.assert_not_called()
        with TestClient(create_app(Settings(schedule_enabled=False), self.engine)) as client:
            old = client.get('/api/repositories/1?source=search&date=2026-10-12').json()
            self.assertEqual((old['stars'], old['readme_original']), (100,'first'))
            self.assertEqual(client.get('/api/repositories/1?source=search&date=2026-10-13').json()['readme_original'], 'second')

    def test_search_defaults_and_one_am_boundary(self):
        settings = Settings(schedule_enabled=False)
        self.assertEqual((settings.search_limit, settings.collect_hour), (100,1))
        collector = Collector(self.engine,self.sessions,settings)
        self.assertFalse(collector.due(datetime(2026,10,11,16,59,tzinfo=timezone.utc),startup=True))
        self.assertTrue(collector.due(datetime(2026,10,11,17,0,tzinfo=timezone.utc),startup=True))

    def test_collects_100_and_retry_keeps_membership_without_translator(self):
        from unittest.mock import patch
        from sqlalchemy import select, func
        from app.models import SearchSnapshot
        from app.sources import SourceError
        from app.database import initialize_database
        source = Mock()
        source.search.return_value = [dict(full_name=f'o/r{i}', metadata=storage.metadata(i,f'o/r{i}'),rank=i) for i in range(1,101)]
        def readme(name):
            if name == 'o/r100':
                raise SourceError('temporary failure')
            return '# Original', 'README.md'
        source.readme.side_effect = readme
        settings = Settings(schedule_enabled=False, translation_base_url='https://test.example',translation_model='test',translation_api_key='test')
        collector = Collector(self.engine,self.sessions,settings)
        with patch('app.collector.Translator') as factory:
            collector.run(source=source)
            initialize_database(self.engine)
            source.readme.side_effect = None
            source.readme.return_value = ('# Retry', 'README.md')
            collector.run(source=source)
            self.assertFalse(collector.run(source=source))
            factory.assert_not_called()
        source.search.assert_called_once_with(100)
        self.assertEqual(source.readme.call_count,101)
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(SearchSnapshot)),100)
            self.assertEqual(session.scalar(select(SearchSnapshot).where(SearchSnapshot.repository_id==100)).details['readme_original'],'# Retry')
