"""Actual loopback HTTP fixture; never a claim of real conference verification."""
import importlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from urllib.parse import parse_qs, urlsplit

import pytest

from contracts.paper_library.support import VENUE, pdf
from rsi_red.errors import ResearchError


@pytest.fixture
def official_http(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    requested = []
    document = pdf('Synthetic public source fixture, no actual accepted paper.')
    def note(key):
        return {'id': key, 'forum': key, 'readers': ['everyone'], 'mdate': 1000, 'pdate': 500,
                'content': {'title': {'value': 'Synthetic ' + key}, 'venueid': {'value': VENUE},
                            'authors': {'value': ['Fixture Author']}, 'pdf': {'value': '/pdf?id=' + key}}}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_GET(self):
            url = urlsplit(self.path)
            query = parse_qs(url.query)
            requested.append((url.path, query))
            if query.get('id') == ['rate-limited']:
                self.send_response(429)
                self.send_header('Retry-After', '2')
                self.end_headers()
                return
            if url.path == '/notes':
                offset = int(query.get('offset', ['0'])[0])
                data = {'notes': [note(query['id'][0])] if 'id' in query else [note(('http-a', 'http-b')[offset])], 'count': 2}
            elif url.path == '/groups':
                data = {'groups': [{'id': VENUE, 'domain': VENUE, 'content': {}}]}
            elif url.path == '/pdf':
                self.send_response(200)
                self.send_header('Content-Type', 'application/pdf')
                self.send_header('Content-Length', str(len(document)))
                self.end_headers()
                self.wfile.write(document)
                return
            else:
                self.send_error(404)
                return
            body = json.dumps(data).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', requested, document
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


def test_actual_http_openreview_v2_record_and_pdf(official_http):
    base, requested, document = official_http
    module = importlib.import_module('rsi_red.paper_sources')
    source = module.OpenReviewSource(api_base=base, allow_loopback_fixture=True)
    record = source.get_record('http-a')
    assert record['record_id'] == 'http-a' and record['venue_id'] == VENUE
    assert record['title'] == 'Synthetic http-a'
    assert source.get_pdf(record) == document
    assert {r[0] for r in requested} >= {'/notes', '/pdf'}


def test_http_catalog_pagination_is_bounded(official_http):
    base, requested, _ = official_http
    module = importlib.import_module('rsi_red.paper_sources')
    source = module.OpenReviewSource(api_base=base, allow_loopback_fixture=True)
    a = source.discover(VENUE, cursor=None, limit=1)
    b = source.discover(VENUE, cursor=a['next_cursor'], limit=1)
    assert len(a['items']) == len(b['items']) == 1
    assert a['items'][0]['record_id'] != b['items'][0]['record_id']
    assert b['next_cursor'] is None and len(requested) <= 6


def test_http_rate_limit_is_structured_and_does_not_busy_retry(official_http):
    base, requested, _ = official_http
    module = importlib.import_module('rsi_red.paper_sources')
    source = module.OpenReviewSource(api_base=base, allow_loopback_fixture=True)
    with pytest.raises(ResearchError) as caught:
        source.get_record('rate-limited')
    assert caught.value.code == 'SOURCE_RATE_LIMITED'
    assert caught.value.retryable is True
    assert len(requested) == 1


def test_non_fixture_source_cannot_silently_use_loopback(official_http):
    base, _, _ = official_http
    module = importlib.import_module('rsi_red.paper_sources')
    with pytest.raises(ValueError):
        module.OpenReviewSource(api_base=base)
