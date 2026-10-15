"""Build versioned Scrapy images, execute restricted fixtures and retain machine output."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--versions', nargs='+', default=['2.18.0', '2.19.0'])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not all(re.fullmatch(r'\d+\.\d+\.\d+', version) for version in args.versions):
        parser.error('Only stable numeric Scrapy versions are supported')
    args.output.mkdir(parents=True, exist_ok=True)
    for version in args.versions:
        image = f'crawler-validation-scrapy:{version}'
        with (args.output / f'{version}-build.log').open('w', encoding='utf-8') as log:
            subprocess.run(['docker', 'build', '--build-arg', f'SCRAPY_VERSION={version}', '-t', image,
                str(Path(__file__).resolve().parent)], stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600)
        name = 'crawler-validation-' + uuid.uuid4().hex
        try:
            result = subprocess.run(['docker', 'run', '--name', name, '--rm', '--network', 'none', '--read-only',
                '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--memory', '512m', '--cpus', '1',
                '--pids-limit', '64', '--tmpfs', '/tmp:rw,noexec,nosuid,size=32m', image],
                capture_output=True, text=True, encoding='utf-8', timeout=90)
            (args.output / f'{version}-run.log').write_text(result.stderr, encoding='utf-8')
            result.check_returncode()
            data = json.loads(result.stdout)
            if data['version'] != version or data['evidence']['observed_version'] != version:
                raise ValueError('Installed version does not match requested version')
            (args.output / f'{version}.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(dict(version=version, status=data['status'], metrics=data['metrics']), ensure_ascii=False), flush=True)
        finally:
            subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=30)


if __name__ == '__main__':
    main()
