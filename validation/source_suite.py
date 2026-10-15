"""Parse bounded release sources without extracting or executing their code."""
import ast
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import platform
import posixpath
import tarfile
import tempfile

COMPRESSED_LIMIT = 30 * 1024 * 1024
UNCOMPRESSED_LIMIT = 100 * 1024 * 1024
FILE_LIMIT = 5000
MEMBER_LIMIT = 2 * 1024 * 1024
SKIP_DIRS = {'test', 'tests', 'fixture', 'fixtures', '__fixtures__', 'vendor', 'vendored',
             'node_modules', '.venv', 'venv', '.git', '__pycache__'}


def safe_path(name):
    path = PurePosixPath(name)
    if not name or path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
        raise ValueError('UnsafeArchivePath')
    return path


def inspect_archive(path):
    checked, failed, errors = [], 0, []
    evidence = dict(fixture_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    python=platform.python_version(), scope='source', errors=errors,
                    checked_files=checked,
                    untested='Syntax and package.json JSON only; no execution, dependencies, build, security, '
                             'functional behavior or performance tested. Python syntax targets Python 3.12.')
    count = 0
    try:
        if path.stat().st_size > COMPRESSED_LIMIT:
            raise ValueError('CompressedLimit')
        # Bound gzip before tarfile parses extension headers or allocates member metadata.
        with tempfile.TemporaryFile() as uncompressed:
            total = 0
            with gzip.open(path, 'rb') as compressed:
                while True:
                    chunk = compressed.read(min(1024 * 1024, UNCOMPRESSED_LIMIT - total + 1))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > UNCOMPRESSED_LIMIT:
                        raise ValueError('UncompressedLimit')
                    uncompressed.write(chunk)
            uncompressed.seek(0)
            with tarfile.open(fileobj=uncompressed, mode='r|') as archive:
                for number, member in enumerate(archive, 1):
                    if number > FILE_LIMIT:
                        raise ValueError('FileCountLimit')
                    name = safe_path(member.name)
                    if member.size < 0:
                        raise ValueError('MemberSizeLimit')
                    if member.issym() or member.islnk():
                        target = member.linkname
                        if not target or target.startswith('/') or '\\' in target or ':' in target:
                            raise ValueError('UnsafeArchiveLink')
                        resolved = posixpath.normpath(posixpath.join(str(name.parent), target) if member.issym() else target)
                        safe_path(resolved)
                        continue
                    if member.isdir():
                        continue
                    if not member.isfile() or member.sparse is not None:
                        raise ValueError('UnsupportedArchiveEntry')
                    if any(part.lower() in SKIP_DIRS for part in name.parts[:-1]):
                        continue
                    if name.suffix != '.py' and name.name != 'package.json':
                        continue
                    if member.size > MEMBER_LIMIT:
                        raise ValueError('MemberSizeLimit')
                    count += 1
                    if len(checked) < 30:
                        checked.append(str(name)[:300])
                    try:
                        with archive.extractfile(member) as stream:
                            content = stream.read(MEMBER_LIMIT + 1)
                        if name.suffix == '.py':
                            ast.parse(content, filename=str(name))
                        else:
                            json.loads(content)
                    except (SyntaxError, ValueError, UnicodeError, RecursionError) as error:
                        failed += 1
                        if len(errors) < 30:
                            errors.append(dict(file=str(name)[:300], error=type(error).__name__))
        status = 'failed' if failed else ('passed' if count else 'unsupported')
    except (OSError, EOFError, tarfile.TarError, ValueError, RecursionError) as error:
        status = 'failed'
        evidence['archive_error'] = str(error) if type(error) is ValueError else type(error).__name__
        evidence['archive_error'] = evidence['archive_error'][:120]
    evidence['checked_files_truncated'] = count > len(checked)
    evidence['errors_truncated'] = failed > len(errors)
    return dict(suite='source-smoke-v1', status=status,
                metrics=dict(checked_files=count, failed_files=failed), evidence=evidence)


if __name__ == '__main__':
    print(json.dumps(inspect_archive(Path('/input/source.tar.gz')), sort_keys=True))
