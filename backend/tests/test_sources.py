import base64
import unittest
import httpx

from app.sources import GitHubSource, SourceError, RateLimited


def search_item(number=1):
    return dict(id=number, full_name=f'o/repo{number}', stargazers_count=2000-number,
                created_at='2020-01-01T00:00:00Z', updated_at='2026-10-12T00:00:00Z',
                pushed_at='2026-10-11T00:00:00Z', default_branch='main', private=False)


class SourceTests(unittest.TestCase):
    def test_startup_scheduler_retries_source_blocked_by_other_job(self):
        import asyncio
        from unittest.mock import Mock, patch
        from app.main import schedule
        collector = Mock()
        collector.due.side_effect = lambda startup, kind: startup
        collector.start.side_effect = [True, False, True]
        class StopLoop(Exception):
            pass
        calls = 0
        async def sleep(seconds):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise StopLoop()
        with patch('app.main.asyncio.sleep', sleep), self.assertRaises(StopLoop):
            asyncio.run(schedule(collector))
        self.assertEqual([c.kwargs for c in collector.due.call_args_list], [
            dict(startup=True, kind='trending'), dict(startup=True, kind='search'),
            dict(startup=False, kind='trending'), dict(startup=True, kind='search')])

    def test_trending_page_parses_gains_and_rejects_malformed_rows(self):
        html = '<article class="Box-row"><h2><a href="/octo/alpha">octo / alpha</a></h2><span>1,234 stars today</span></article>'
        with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=html))) as client:
            rows = GitHubSource(client, 'secret').trending()
            self.assertEqual(rows, [dict(full_name='octo/alpha', daily_stars=1234, rank=1, source='trending')])
        for html in ('<html>blocked</html>', html.replace('1,234 stars today', 'invalid'), html * 2, html.replace('/octo/alpha', '//evil.test/a')):
            with self.subTest(html=html), httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=html))) as client:
                with self.assertRaises(SourceError):
                    GitHubSource(client).trending()

    def test_trending_request_does_not_send_api_token(self):
        def respond(request):
            self.assertNotIn('authorization', request.headers)
            self.assertEqual(str(request.url), 'https://github.com/trending?since=daily')
            return httpx.Response(200, text='<article class="Box-row"><h2><a href="/o/r">o/r</a></h2><span>12 stars today</span></article>')
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            GitHubSource(client, 'secret').trending()

    def test_search_uses_official_public_star_sort_and_returned_metadata(self):
        calls = []
        def respond(request):
            calls.append(request)
            self.assertEqual(request.url.host, 'api.github.com')
            self.assertEqual(request.url.path, '/search/repositories')
            self.assertEqual(dict(request.url.params), {'q': 'stars:>0 is:public fork:true', 'sort': 'stars', 'order': 'desc', 'per_page': '30', 'page': '1'})
            return httpx.Response(200, json={'total_count': 1, 'incomplete_results': False, 'items': [search_item()]})
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            rows = GitHubSource(client).search(30)
        self.assertEqual(len(calls), 1)
        self.assertEqual(rows[0]['metadata']['stars'], 1999)
        self.assertEqual(rows[0]['rank'], 1)
        self.assertIsNone(rows[0]['daily_stars'])
        self.assertEqual(rows[0]['source'], 'search')

    def test_search_pagination_keeps_page_size_and_stops_at_limit(self):
        pages = []
        def respond(request):
            page = int(request.url.params['page'])
            pages.append(page)
            self.assertEqual(request.url.params['per_page'], '100')
            return httpx.Response(200, json={'total_count': 10000, 'incomplete_results': False,
                'items': [search_item(n) for n in range((page-1)*100+1, page*100+1)]})
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            rows = GitHubSource(client).search(150)
        self.assertEqual(pages, [1, 2])
        self.assertEqual(len(rows), 150)
        self.assertEqual(rows[-1]['rank'], 150)

    def test_incomplete_empty_duplicate_and_private_search_rejected(self):
        invalid = [dict(total_count=1, incomplete_results=True, items=[search_item()]),
                   dict(total_count=1, incomplete_results=False, items=[]),
                   dict(total_count=2, incomplete_results=False, items=[search_item(), search_item()]),
                   dict(total_count=1, incomplete_results=False, items=[dict(search_item(), private=True)])]
        for payload in invalid:
            with self.subTest(payload=payload), httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))) as client:
                with self.assertRaises(SourceError):
                    GitHubSource(client).search(30)

    def test_search_limit_is_validated_without_network(self):
        with httpx.Client(transport=httpx.MockTransport(lambda r: self.fail('unexpected request'))) as client:
            for limit in (0, -1, 1001):
                with self.assertRaises(ValueError):
                    GitHubSource(client).search(limit)

    def test_incomplete_broad_query_retries_with_safe_star_floor(self):
        queries = []
        def respond(request):
            queries.append(request.url.params['q'])
            return httpx.Response(200, json={'total_count': 2, 'incomplete_results': len(queries) == 1,
                                           'items': [search_item(1), search_item(2)]})
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            self.assertEqual(len(GitHubSource(client).search(2)), 2)
        self.assertEqual(queries, ['stars:>0 is:public fork:true', 'stars:>=1000 is:public fork:true'])

    def test_star_floor_not_accepted_if_it_excludes_requested_ranks(self):
        def respond(request):
            return httpx.Response(200, json={'total_count': 1, 'incomplete_results': 'stars:>0 ' in request.url.params['q'],
                                           'items': [search_item()]})
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            with self.assertRaises(SourceError):
                GitHubSource(client).search(30)

    def test_readme_decoded_and_missing_readme_allowed(self):
        def response(request):
            if request.url.path.endswith('/readme'):
                return httpx.Response(200, json={'encoding': 'base64', 'content': base64.b64encode(b'# Hello').decode(), 'path': 'docs/README.md', 'sha': 'a'})
            return httpx.Response(404)
        with httpx.Client(transport=httpx.MockTransport(response)) as client:
            source = GitHubSource(client)
            self.assertEqual(source.readme('o/r'), ('# Hello', 'docs/README.md'))
        with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404))) as client:
            self.assertEqual(GitHubSource(client).readme('o/r'), (None, None))

    def test_rate_limit_has_wait_and_no_secret(self):
        with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429, headers={'Retry-After': '120'}, text='secret-key'))) as client:
            with self.assertRaises(RateLimited) as raised:
                GitHubSource(client).search(30)
            self.assertGreaterEqual(raised.exception.retry_at, 120)
            self.assertNotIn('secret-key', str(raised.exception))

    def test_invalid_repo_rejected_before_network(self):
        with httpx.Client(transport=httpx.MockTransport(lambda r: self.fail('network should not be called'))) as client:
            with self.assertRaises(SourceError):
                GitHubSource(client).readme('../secret')


if __name__ == '__main__':
    unittest.main()
