"""Host-only release validation worker; Python 3.9+ and Docker Compose required."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / '.local' / 'auto-validation'
IMAGE = 'github-source-smoke:1'
ARCHIVE_LIMIT = 30 * 1024 * 1024
REPO = re.compile(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}')


class ArchiveValidationError(ValueError):
    pass


def validate_job(job):
    if not isinstance(job, dict):
        raise ValueError('InvalidJob')
    for key in ('id', 'project_id'):
        if type(job.get(key)) is not int or job[key] <= 0:
            raise ValueError('InvalidIdentifier')
    if not isinstance(job.get('lease_token'), str) or not 1 <= len(job['lease_token']) <= 200:
        raise ValueError('InvalidLease')
    name, version = job.get('full_name'), job.get('version')
    if not isinstance(name, str) or not REPO.fullmatch(name) or name.split('/')[1] in ('.', '..'):
        raise ValueError('InvalidRepository')
    if not isinstance(version, str) or not 1 <= len(version) <= 100 or any(ord(c) < 32 or ord(c) == 127 for c in version):
        raise ValueError('InvalidVersion')
    url = urllib.parse.urlsplit(job.get('source_url', ''))
    if (url.scheme != 'https' or url.netloc != 'github.com' or url.query or url.fragment
            or urllib.parse.unquote(url.path) != '/' + name + '/releases/tag/' + version):
        raise ValueError('InvalidSourceURL')
    if job.get('suite') not in ('source-smoke-v1', 'scrapy-pagination-v1'):
        raise ValueError('InvalidSuite')
    if job['suite'] == 'scrapy-pagination-v1' and (name != 'scrapy/scrapy' or not re.fullmatch(r'v?\d+\.\d+\.\d+', version)):
        raise ValueError('InvalidScrapyRelease')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('RedirectRejected')


def open_url(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != 'https' or parts.netloc not in ('api.github.com', 'codeload.github.com'):
        raise ValueError('InvalidHost')
    request = urllib.request.Request(url, headers={'User-Agent': 'github-trending-validation', 'Accept': 'application/vnd.github+json'})
    return urllib.request.build_opener(NoRedirect()).open(request, timeout=20)


def fetch_json(url):
    deadline, chunks, total = time.monotonic() + 30, [], 0
    with open_url(url) as response:
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError('ResponseTimeout')
            chunk = response.read1(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > 1024 * 1024:
                raise ValueError('ResponseLimit')
            chunks.append(chunk)
    return json.loads(b''.join(chunks))


def resolve_commit(job):
    base = 'https://api.github.com/repos/' + job['full_name']
    repo = fetch_json(base)
    if (repo.get('private') is not False or repo.get('id') != job['project_id']
            or repo.get('full_name', '').lower() != job['full_name'].lower()):
        raise ValueError('RepositoryIdentityMismatch')
    commit = fetch_json(base + '/commits/' + urllib.parse.quote(job['version'], safe=''))
    sha = commit.get('sha', '')
    if not isinstance(sha, str) or not re.fullmatch('[a-f0-9]{40}', sha):
        raise ValueError('InvalidCommit')
    return sha


def download_archive(job, sha, destination):
    digest, total = hashlib.sha256(), 0
    deadline = time.monotonic() + 100
    url = 'https://codeload.github.com/' + job['full_name'] + '/tar.gz/' + sha
    with open_url(url) as response, destination.open('wb') as output:
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError('DownloadTimeout')
            chunk = response.read1(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > ARCHIVE_LIMIT:
                raise ValueError('ArchiveLimit')
            digest.update(chunk)
            output.write(chunk)
    destination.chmod(0o644)
    return digest.hexdigest()


def source_command(archive, name):
    return ['docker', 'run', '--name', name, '--rm', '--network', 'none', '--read-only',
            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--memory', '512m', '--cpus', '1',
            '--pids-limit', '64', '--user', '65534:65534', '--tmpfs', '/tmp:rw,noexec,nosuid,size=128m',
            '--mount', 'type=bind,src=' + str(archive.resolve()) + ',dst=/input/source.tar.gz,readonly', IMAGE]


def queue(action, payload=None):
    result = subprocess.run(['docker', 'compose', 'exec', '-T', 'api', 'python', '-m', 'app.validation_jobs', action],
                            cwd=ROOT, input=json.dumps(payload) if payload is not None else None,
                            capture_output=True, text=True, encoding='utf-8', check=True, timeout=30)
    return json.loads(result.stdout) if result.stdout.strip() else None


def execute(job, directory):
    validate_job(job)
    directory.mkdir(parents=True, exist_ok=True)
    if job['suite'] == 'scrapy-pagination-v1':
        version = job['version'].removeprefix('v')
        with (directory / 'worker.log').open('w', encoding='utf-8') as log:
            subprocess.run([sys.executable, str(ROOT / 'validation' / 'run.py'), '--versions', version,
                            '--output', str(directory)], stdout=log, stderr=subprocess.STDOUT, check=True, timeout=780)
        result = json.loads((directory / (version + '.json')).read_text(encoding='utf-8'))
        result.pop('version', None)
        result['evidence'].update(full_name=job['full_name'], version=job['version'])
        return result
    sha = resolve_commit(job)
    archive = directory / 'source.tar.gz'
    archive_sha = download_archive(job, sha, archive)
    with (directory / 'build.log').open('w', encoding='utf-8') as log:
        subprocess.run(['docker', 'build', '-f', str(ROOT / 'validation' / 'Source.Dockerfile'), '-t', IMAGE,
                        str(ROOT / 'validation')], stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
    name = 'source-validation-' + uuid.uuid4().hex
    try:
        process = subprocess.run(source_command(archive, name), capture_output=True, text=True,
                                 encoding='utf-8', timeout=120)
        (directory / 'run.log').write_text(process.stderr, encoding='utf-8')
        process.check_returncode()
        result = json.loads(process.stdout)
    finally:
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=30)
    result['evidence'].update(full_name=job['full_name'], version=job['version'], commit_sha=sha, archive_sha256=archive_sha)
    (directory / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


@contextmanager
def worker_lock():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with (OUTPUT / 'worker.lock').open('a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            lock.write(b'0')
            lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def once():
    job = queue('claim')
    if job is None:
        return False
    identity = {key: job.get(key) for key in ('id', 'lease_token')}
    try:
        validate_job(job)
        result = execute(job, OUTPUT / str(job['id']))
        if result.get('evidence', {}).get('archive_error'):
            raise ArchiveValidationError()
    except Exception as error:
        # Exception messages can contain URLs or subprocess environments; retain only the class.
        failure=dict(identity,error=type(error).__name__)
        if isinstance(error,urllib.error.HTTPError) and (error.code == 429 or error.headers.get('X-RateLimit-Remaining') == '0'):
            delay=3600
            try:
                delay=int(error.headers.get('X-RateLimit-Reset'))-int(time.time())+5
            except (TypeError,ValueError):
                pass
            failure.update(error='GitHubRateLimited',retry_after=max(60,min(7200,delay)))
        queue('error', failure)
        return True
    queue('complete', dict(identity, result=result))
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    with worker_lock():
        while True:
            try:
                claimed = once()
            except Exception as error:
                claimed = False
                print(type(error).__name__, file=sys.stderr, flush=True)
                if args.once:
                    return 1
            if args.once:
                return 0
            if not claimed:
                time.sleep(60)


if __name__ == '__main__':
    sys.exit(main())
