import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from validation import source_suite


class SourceSuiteTests(unittest.TestCase):
    def run_archive(self, files, link=None):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.tar.gz'
            with tarfile.open(path, 'w:gz') as archive:
                for name, data in files.items():
                    entry = tarfile.TarInfo(name)
                    entry.size = len(data)
                    archive.addfile(entry, io.BytesIO(data))
                if link:
                    entry = tarfile.TarInfo('repo/link')
                    entry.type = tarfile.SYMTYPE
                    entry.linkname = link
                    archive.addfile(entry)
            return source_suite.inspect_archive(path)

    def test_valid_python_and_package(self):
        result = self.run_archive({'repo/a.py': b'x = 1', 'repo/package.json': b'{"name":"demo"}'})
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['metrics']['checked_files'], 2)
        self.assertEqual(len(result['evidence']['fixture_sha256']), 64)
        self.assertIn('untested', result['evidence'])

    def test_invalid_source_and_truncated_errors(self):
        result = self.run_archive({'repo/f%d.py' % n: b'def invalid(' for n in range(40)})
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['metrics']['failed_files'], 40)
        self.assertEqual(len(result['evidence']['errors']), 30)

    def test_unsupported_and_skipped_fixtures(self):
        result = self.run_archive({'repo/readme.md': b'hello', 'repo/tests/bad.py': b'(', 'repo/node_modules/package.json': b'{'})
        self.assertEqual(result['status'], 'unsupported')

    def test_unsafe_paths_and_links_fail(self):
        for name in ('../escape.py', '/absolute.py', 'repo/../../escape.py', 'C:/escape.py', 'repo\\escape.py'):
            with self.subTest(name=name):
                self.assertEqual(self.run_archive({name: b'x=1'})['status'], 'failed')
        self.assertEqual(self.run_archive({}, link='../../escape')['status'], 'failed')

    def test_safe_symlink_is_not_read(self):
        self.assertEqual(self.run_archive({'repo/a.py': b'x=1'}, link='a.py')['metrics']['checked_files'], 1)

    def test_large_non_source_is_skipped_but_large_source_is_incomplete(self):
        blob=b'x' * (2 * 1024 * 1024 + 1)
        self.assertEqual(self.run_archive({'repo/screenshots/demo.gif': blob, 'repo/a.py':b'x=1'})['status'], 'passed')
        self.assertIn('archive_error',self.run_archive({'repo/large.py':blob})['evidence'])

    def test_compressed_uncompressed_and_file_count_limits(self):
        for name, limit in (('COMPRESSED_LIMIT', 10), ('UNCOMPRESSED_LIMIT', 100), ('FILE_LIMIT', 1)):
            with self.subTest(limit=name), patch.object(source_suite, name, limit):
                result = self.run_archive({'repo/a.py': b'x=1', 'repo/b.py': b'x=2'})
                self.assertEqual(result['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
