import tempfile
import unittest
import subprocess
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch
from unittest.mock import Mock

from validation import worker


def job(**changes):
    value = dict(id=1, lease_token='token', project_id=2, full_name='owner/repo', version='v1.2.3',
                 source_url='https://github.com/owner/repo/releases/tag/v1.2.3', suite='source-smoke-v1')
    value.update(changes)
    return value


class WorkerTests(unittest.TestCase):
    def test_rejects_malformed_jobs(self):
        for changes in ({'full_name': '../repo'}, {'version': 'a\nb'}, {'version': 'x' * 101},
                        {'source_url': 'https://evil.test/archive'}, {'source_url': 'https://codeload.github.com.evil.test/a'},
                        {'id': '../bad'}, {'suite': 'shell'}, {'suite': 'scrapy-pagination-v1'},
                        {'source_url': 'https://github.com/other/repo/releases/tag/v1.2.3'},
                        {'source_url': 'https://github.com/owner/repo/releases/tag/v9.9.9'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                worker.validate_job(job(**changes))

    def test_accepts_source_and_exact_scrapy(self):
        worker.validate_job(job())
        worker.validate_job(job(full_name='scrapy/scrapy', suite='scrapy-pagination-v1',
                                source_url='https://github.com/scrapy/scrapy/releases/tag/v1.2.3'))
        name='owner/'+'r'*100
        worker.validate_job(job(full_name=name,source_url=f'https://github.com/{name}/releases/tag/v1.2.3'))

    def test_container_has_security_limits_and_one_readonly_input(self):
        with tempfile.TemporaryDirectory() as directory:
            command = worker.source_command(Path(directory) / 'source.tar.gz', 'validation-123')
        for flag in ('--read-only', '--cap-drop', '--security-opt', '--memory', '--cpus', '--pids-limit', '--user'):
            self.assertIn(flag, command)
        self.assertEqual(command[command.index('--network') + 1], 'none')
        self.assertEqual(command.count('--mount'), 1)
        self.assertIn('readonly', command[command.index('--mount') + 1])
        self.assertNotIn('/var/run/docker.sock', ' '.join(command))

    def test_public_identity_and_tag_sha(self):
        with patch.object(worker, 'fetch_json', side_effect=[{'id': 2, 'full_name': 'owner/repo', 'private': False}, {'sha': 'a' * 40}]) as fetch:
            self.assertEqual(worker.resolve_commit(job(version='release/1')), 'a' * 40)
            self.assertIn('release%2F1', fetch.call_args.args[0])
        with patch.object(worker, 'fetch_json', return_value={'full_name': 'other/repo', 'private': False}):
            with self.assertRaises(ValueError):
                worker.resolve_commit(job())
        with patch.object(worker, 'fetch_json', return_value={'id': 3, 'full_name': 'owner/repo', 'private': False}) as fetch:
            with self.assertRaises(ValueError):
                worker.resolve_commit(job())
            self.assertEqual(fetch.call_count, 1)

    def test_error_reporting_contains_no_exception_message(self):
        with patch.object(worker, 'queue', side_effect=[job(), None]) as queue, \
                patch.object(worker, 'execute', side_effect=ValueError('secret-token=https://secret')):
            worker.once()
        self.assertEqual(queue.call_args.args, ('error', {'id': 1, 'lease_token': 'token', 'error': 'ValueError'}))

    def test_rate_limit_uses_reset_header_without_exposing_response(self):
        import urllib.error
        error=urllib.error.HTTPError('https://api.github.com/repos/owner/repo',403,'secret',
            {'X-RateLimit-Remaining':'0','X-RateLimit-Reset':'1500'},None)
        with patch.object(worker,'queue',side_effect=[job(),None]) as queue, \
                patch.object(worker,'execute',side_effect=error),patch.object(worker.time,'time',return_value=1000):
            worker.once()
        self.assertEqual(queue.call_args.args[1]['error'],'GitHubRateLimited')
        self.assertEqual(queue.call_args.args[1]['retry_after'],505)

    def test_completion_and_no_job(self):
        result = {'suite': 'source-smoke-v1', 'status': 'unsupported', 'metrics': {}, 'evidence': {}}
        with patch.object(worker, 'queue', side_effect=[job(), None]) as queue, \
                patch.object(worker, 'execute', return_value=result):
            worker.once()
        self.assertEqual(queue.call_args.args[1]['result'], result)
        with patch.object(worker, 'queue', return_value=None) as queue:
            worker.once()
        queue.assert_called_once_with('claim')

    def test_oversized_download_is_rejected(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read1.side_effect = [b'1234', b'']
        with tempfile.TemporaryDirectory() as directory, patch.object(worker, 'open_url', return_value=response), \
                patch.object(worker, 'ARCHIVE_LIMIT', 3):
            with self.assertRaises(ValueError):
                worker.download_archive(job(), 'a' * 40, Path(directory) / 'source.tar.gz')

    def test_redirects_are_rejected(self):
        with self.assertRaises(ValueError):
            worker.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.test')

    def test_uncheckable_archive_reports_execution_error(self):
        result = {'suite': 'source-smoke-v1', 'status': 'failed', 'metrics': {}, 'evidence': {'archive_error': 'MemberSizeLimit'}}
        with patch.object(worker, 'queue', side_effect=[job(), None]) as queue, \
                patch.object(worker, 'execute', return_value=result):
            worker.once()
        self.assertEqual(queue.call_args.args[0], 'error')
        self.assertEqual(queue.call_args.args[1]['error'], 'ArchiveValidationError')

    def test_drains_queue_before_sleep(self):
        with patch.object(worker.sys, 'argv', ['worker.py']), \
                patch.object(worker, 'worker_lock', return_value=nullcontext()), \
                patch.object(worker, 'once', side_effect=[True, False]) as once, \
                patch.object(worker.time, 'sleep', side_effect=KeyboardInterrupt) as sleep:
            with self.assertRaises(KeyboardInterrupt):
                worker.main()
        self.assertEqual(once.call_count, 2)
        sleep.assert_called_once_with(60)

    def test_timeout_removes_its_named_container(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(worker, 'resolve_commit', return_value='a' * 40), \
                patch.object(worker, 'download_archive', return_value='b' * 64), \
                patch.object(worker.subprocess, 'run', side_effect=[None, subprocess.TimeoutExpired('docker', 120), None]) as run:
            with self.assertRaises(subprocess.TimeoutExpired):
                worker.execute(job(), Path(directory))
        command = run.call_args_list[1].args[0]
        name = command[command.index('--name') + 1]
        self.assertTrue(name.startswith('source-validation-'))
        self.assertEqual(run.call_args.args[0], ['docker', 'rm', '-f', name])


if __name__ == '__main__':
    unittest.main()
