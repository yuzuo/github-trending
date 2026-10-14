from datetime import date, timedelta
import os
import unittest
from unittest.mock import Mock

from sqlalchemy import select

from app.history import save_trending_repository
from app.models import Repository, TrendingSnapshot
from app.translation import TranslationError
from tests import test_storage as storage
from tests.test_storage import metadata


@unittest.skipUnless(os.getenv('TEST_DATABASE_URL'), 'Requires test database')
class HistoryTests(unittest.TestCase):
    setUp = storage.StorageTests.setUp
    tearDown = storage.StorageTests.tearDown

    def save(self, day=date(2026, 10, 12), original='# Original', translator=None, **changes):
        return save_trending_repository(self.sessions, {**metadata(), **changes}, original,
            'README.md', dict(rank=1, daily_stars=20), day, translator)

    def snapshot(self, day=date(2026, 10, 12)):
        with self.sessions() as session:
            return session.scalar(select(TrendingSnapshot).where(TrendingSnapshot.date == day))

    def test_next_day_and_latest_cache_changes_leave_old_day_untouched(self):
        translator = Mock()
        translator.translate.side_effect = lambda text: '中文 ' + text
        self.save(translator=translator)
        old = self.snapshot()
        self.save(day=old.date + timedelta(days=1), original='# Tomorrow', stars=200, translator=translator)
        with self.sessions.begin() as session:
            repo = session.get(Repository, 1)
            repo.readme_original, repo.description, repo.stars = '# Search', 'Search description', 300
        preserved = self.snapshot()
        self.assertEqual(preserved.details, old.details)
        self.assertEqual((preserved.stars, preserved.fetched_at, preserved.trending_rank),
                         (old.stars, old.fetched_at, old.trending_rank))
        self.assertEqual(preserved.details['readme_zh'], '中文 # Original')
        self.assertIsInstance(preserved.details['created_at'], str)
        self.assertEqual(preserved.details_origin, 'captured')

    def test_same_day_success_never_recaptures_or_retranslates(self):
        translator = Mock()
        translator.translate.side_effect = lambda text: '中文 ' + text
        self.save(translator=translator)
        before = self.snapshot()
        translator.reset_mock()
        self.save(original='# Replacement', description='Changed', stars=900, translator=translator)
        after = self.snapshot()
        translator.translate.assert_not_called()
        self.assertEqual(after.details, before.details)
        self.assertEqual(after.stars, 100)
        with self.sessions() as session:
            self.assertEqual(session.get(Repository, 1).readme_original, '# Original')

    def test_failed_retry_uses_frozen_original_and_preserves_newer_cache(self):
        failed = Mock()
        failed.translate.side_effect = TranslationError('翻译失败')
        self.assertFalse(self.save(translator=failed))
        before = self.snapshot()
        with self.sessions.begin() as session:
            repo = session.get(Repository, 1)
            repo.readme_original, repo.description, repo.readme_zh = '# Search', 'New description', '新译文'
        translator = Mock()
        translator.translate.side_effect = lambda text: '中文 ' + text
        self.assertTrue(self.save(original='# Changed', description='Changed', stars=999, translator=translator))
        self.assertEqual([call.args[0] for call in translator.translate.call_args_list], ['# Original', 'Hello'])
        after = self.snapshot()
        self.assertEqual(after.details['readme_original'], '# Original')
        self.assertEqual(after.details['readme_zh'], '中文 # Original')
        self.assertEqual(after.details['stars'], 100)
        self.assertEqual(after.fetched_at, before.fetched_at)
        with self.sessions() as session:
            repo = session.get(Repository, 1)
            self.assertEqual((repo.readme_original, repo.description, repo.readme_zh),
                             ('# Search', 'New description', '新译文'))

    def test_missing_readme_does_not_skip_description_and_preserves_legacy_origin(self):
        self.save(original=None)
        with self.sessions.begin() as session:
            snapshot = session.scalar(select(TrendingSnapshot))
            snapshot.details_origin = 'legacy_backfill'
        translator = Mock()
        translator.translate.side_effect = lambda text: '中文 ' + text
        self.save(original='# Ignore', translator=translator)
        translator.translate.assert_called_once_with('Hello')
        snapshot = self.snapshot()
        self.assertEqual(snapshot.details['description_zh'], '中文 Hello')
        self.assertEqual(snapshot.details['translation_status'], 'missing')
        self.assertEqual(snapshot.details_origin, 'legacy_backfill')

    def test_next_day_reuses_unchanged_complete_translation(self):
        translator = Mock()
        translator.translate.side_effect = lambda text: '中文 ' + text
        self.save(translator=translator)
        translator.reset_mock()
        self.save(day=date(2026, 10, 13), translator=translator)
        translator.translate.assert_not_called()
        self.assertEqual(self.snapshot(date(2026, 10, 13)).details['readme_zh'], '中文 # Original')

    def test_failure_preserves_previous_translation_in_frozen_record(self):
        translated = Mock()
        translated.translate.side_effect = lambda text: '中文 ' + text
        self.save(translator=translated)
        failed = Mock()
        failed.translate.side_effect = TranslationError('翻译失败')
        self.assertFalse(self.save(day=date(2026, 10, 13), original='# Changed', translator=failed))
        details = self.snapshot(date(2026, 10, 13)).details
        self.assertEqual(details['readme_original'], '# Changed')
        self.assertEqual(details['readme_zh'], '中文 # Original')
        self.assertEqual(details['translation_status'], 'failed')


if __name__ == '__main__':
    unittest.main()
