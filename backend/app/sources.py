import base64
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx
from bs4 import BeautifulSoup


class SourceError(Exception):
    pass


class IncompleteSearch(SourceError):
    pass


class RateLimited(SourceError):
    def __init__(self, retry_at):
        self.retry_at = retry_at
        super().__init__('GitHub 请求限流，请在冷却时间结束后重试')


REPO_NAME = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+')


def validate_repo(name):
    if not REPO_NAME.fullmatch(name) or any(part in {'.', '..'} for part in name.split('/')):
        raise SourceError('无效的 GitHub 仓库名称')


class GitHubSource:
    def __init__(self, client, token=''):
        self.client = client
        self.headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'local-github-trending'}
        if token:
            self.headers['Authorization'] = f'Bearer {token}'

    def _get(self, url, *, params=None, missing_ok=False, authenticated=True):
        try:
            headers = self.headers if authenticated else {'User-Agent': self.headers['User-Agent']}
            response = self.client.get(url, params=params, headers=headers)
        except httpx.RequestError as exc:
            raise SourceError('GitHub 网络请求失败') from exc
        if response.status_code in (403, 429):
            now = time.time()
            retry = response.headers.get('Retry-After', '')
            try:
                retry_at = now + float(retry)
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(retry).timestamp()
                except (ValueError, TypeError):
                    retry_at = now + 60
            try:
                retry_at = max(retry_at, float(response.headers.get('X-RateLimit-Reset', '0')))
            except ValueError:
                pass
            raise RateLimited(max(now + 60, retry_at))
        if missing_ok and response.status_code == 404:
            return None
        if response.status_code != 200:
            raise SourceError(f'GitHub 请求失败（HTTP {response.status_code}）')
        return response

    def trending(self):
        response = self._get('https://github.com/trending', params={'since': 'daily'}, authenticated=False)
        soup = BeautifulSoup(response.text, 'html.parser')
        rows, seen = [], set()
        for article in soup.select('article.Box-row'):
            link = article.select_one('h2 a[href]')
            href = link.get('href', '') if link else ''
            if not href.startswith('/'):
                raise SourceError('Trending 项目地址异常，未覆盖已有榜单')
            name = href[1:]
            validate_repo(name)
            gains = re.search(r'\b([0-9][0-9,]*)\s+stars? today\b', article.get_text(' ', strip=True))
            if not gains or name in seen:
                raise SourceError('Trending 页面格式异常，未覆盖已有榜单')
            seen.add(name)
            rows.append(dict(full_name=name, daily_stars=int(gains[1].replace(',', '')),
                             rank=len(rows)+1, source='trending'))
        if not rows:
            raise SourceError('Trending 未返回项目，未覆盖已有榜单')
        return rows

    def repository(self, name, public_only=False):
        validate_repo(name)
        response = self._get(f'https://api.github.com/repos/{name}')
        try:
            data = response.json()
            if public_only and data.get('private') is not False:
                raise SourceError('观察模块只接受公开 GitHub 仓库')
            return self.repository_metadata(data)
        except ValueError as exc:
            raise SourceError('GitHub 仓库资料格式异常') from exc

    def search(self, limit=30):
        if not 1 <= limit <= 1000:
            raise ValueError('SEARCH_LIMIT must be between 1 and 1000')
        try:
            return self._search(limit, 'stars:>0')
        except IncompleteSearch:
            # A complete result with >= limit matches proves excluded low-star repos cannot enter Top N.
            return self._search(limit, 'stars:>=1000', require_full_limit=True)

    def _search(self, limit, star_query, require_full_limit=False):
        rows, seen = [], set()
        page_size = min(limit, 100)
        for page in range(1, (limit + page_size - 1) // page_size + 1):
            response = self._get('https://api.github.com/search/repositories', params={
                'q': f'{star_query} is:public fork:true', 'sort': 'stars', 'order': 'desc',
                'per_page': page_size, 'page': page})
            try:
                data = response.json()
                if data['incomplete_results'] is not False:
                    raise IncompleteSearch('GitHub Search 返回不完整结果，本次未覆盖已有榜单')
                total = int(data['total_count'])
                if total < 1 or (require_full_limit and total < limit):
                    raise SourceError('GitHub Search 无法确认完整 Top N，本次未覆盖已有榜单')
                items = data['items']
                if not isinstance(items, list) or not items:
                    raise ValueError('empty search')
                for item in items[:limit-len(rows)]:
                    if not isinstance(item, dict) or item.get('private') is not False:
                        raise SourceError('GitHub Search 返回非公开仓库，本次不保存')
                    metadata = self.repository_metadata(item)
                    if metadata['id'] in seen:
                        raise SourceError('GitHub Search 分页出现重复项目，请稍后重试')
                    seen.add(metadata['id'])
                    rows.append(dict(full_name=metadata['full_name'], metadata=metadata,
                                     rank=len(rows)+1, daily_stars=None, source='search'))
                if len(rows) >= min(limit, total):
                    return rows
                if len(items) != page_size:
                    raise SourceError('GitHub Search 分页数据不完整，请稍后重试')
            except (KeyError, TypeError, ValueError) as exc:
                raise SourceError('GitHub Search 返回数据异常，未覆盖已有榜单') from exc
        return rows

    @staticmethod
    def repository_metadata(data):
        try:
            full_name = data['full_name']
            validate_repo(full_name)
            stars = int(data['stargazers_count'])
            if stars < 0 or int(data['id']) <= 0:
                raise ValueError('invalid metadata')
            def date(key):
                return datetime.fromisoformat(data[key].replace('Z', '+00:00')).astimezone(timezone.utc) if data.get(key) else None
            created, updated = date('created_at'), date('updated_at')
            if not created or not updated:
                raise ValueError('missing dates')
            return dict(id=int(data['id']), full_name=full_name, html_url=f'https://github.com/{full_name}',
                        description=data.get('description'), language=data.get('language'),
                        license=(data.get('license') or {}).get('spdx_id'), stars=stars,
                        created_at=created, updated_at=updated, pushed_at=date('pushed_at'),
                        default_branch=data['default_branch'])
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceError('GitHub 仓库资料格式异常') from exc

    def readme(self, name):
        validate_repo(name)
        response = self._get(f'https://api.github.com/repos/{name}/readme', missing_ok=True)
        if response is None:
            return None, None
        try:
            data = response.json()
            if data['encoding'] != 'base64':
                raise ValueError('unsupported encoding')
            content = base64.b64decode(''.join(data['content'].split()), validate=True).decode('utf-8')
            return content, data['path']
        except (KeyError, TypeError, ValueError, UnicodeError) as exc:
            raise SourceError('README 内容无法解码，未覆盖已有原文') from exc
