"""Deterministic loopback-only Scrapy fixture and scorer."""
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import threading
import time

EXPECTED = {str(i): str(i * 10) for i in range(1, 7)}


def score(rows, retries, requests):
    counts = Counter(row.get('id') for row in rows)
    correct = sum(counts[key] == 1 and any(row == {'id': key, 'price': price} for row in rows) for key, price in EXPECTED.items())
    duplicates = sum(max(0, count-1) for count in counts.values())
    passed = (len(rows) == len(EXPECTED) == correct and duplicates == 0 and retries >= 1
              and all(requests.get(f'/page/{page}', 0) >= (2 if page == 2 else 1) for page in (1, 2, 3)))
    return passed, dict(expected_records=len(EXPECTED), actual_records=len(rows), correct_records=correct,
                        duplicates=duplicates, retry_requests=retries)


def main():
    import scrapy
    from scrapy.crawler import CrawlerProcess
    from scrapy import signals
    requests, rows = Counter(), []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            requests[self.path] += 1
            if self.path == '/page/2' and requests[self.path] == 1:
                self.send_response(503); self.end_headers(); return
            if self.path.startswith('/page/'):
                page = int(self.path.rsplit('/', 1)[-1])
                ids = [page*2-1, page*2, 1]
                html = ''.join(f'<a class="item" href="/item/{i}">item</a>' for i in ids)
                if page < 3:
                    html += f'<a class="next" href="/page/{page+1}">next</a>'
            elif self.path.startswith('/item/') and self.path.rsplit('/', 1)[-1] in EXPECTED:
                key = self.path.rsplit('/', 1)[-1]
                html = f'<span id="id">{key}</span><span id="price">{EXPECTED[key]}</span>'
            else:
                self.send_response(404); self.end_headers(); return
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(html.encode())

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    start = time.monotonic()

    class FixtureSpider(scrapy.Spider):
        name = 'fixed-pagination'
        async def start(self):
            yield scrapy.Request(f'http://127.0.0.1:{server.server_port}/page/1', callback=self.parse)

        def parse(self, response):
            for href in response.css('a.item::attr(href)').getall():
                yield response.follow(href, callback=self.parse_item)
            for href in response.css('a.next::attr(href)').getall():
                yield response.follow(href, callback=self.parse)

        def parse_item(self, response):
            yield dict(id=response.css('#id::text').get(), price=response.css('#price::text').get())

    process = CrawlerProcess(settings={'LOG_ENABLED': False, 'ROBOTSTXT_OBEY': False, 'RETRY_TIMES': 2,
        'DOWNLOAD_TIMEOUT': 10, 'CONCURRENT_REQUESTS': 2, 'TELNETCONSOLE_ENABLED': False})
    crawler = process.create_crawler(FixtureSpider)
    def on_item(item, **kwargs):
        rows.append(dict(item))
    crawler.signals.connect(on_item, signal=signals.item_scraped, weak=False)
    process.crawl(crawler)
    process.start()
    server.shutdown()
    stats = crawler.stats.get_stats()
    passed, metrics = score(rows, stats.get('retry/count', 0), requests)
    if stats.get('finish_reason') != 'finished':
        passed = False
    metrics['duration_seconds'] = round(time.monotonic()-start, 4)
    evidence = dict(observed_version=scrapy.__version__, finish_reason=stats.get('finish_reason'),
        fixture_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        records=sorted(rows, key=lambda row: row['id']), requests=dict(requests),
        duplicate_requests_filtered=stats.get('dupefilter/filtered', 0),
        python=platform.python_version(), architecture=platform.machine(),
        packages={distribution.metadata['Name']: distribution.version for distribution in importlib.metadata.distributions()})
    print(json.dumps(dict(version=scrapy.__version__, suite='scrapy-pagination-v1',
        status='passed' if passed else 'failed', metrics=metrics, evidence=evidence), sort_keys=True))


if __name__ == '__main__':
    main()
