"""Bounded public OpenReview API v2 I/O; acceptance policy lives in the service."""
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .errors import ResearchError, require


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


class OpenReviewSource:
    provider_version = 'openreview-v2/1'

    def __init__(self, api_base='https://api2.openreview.net', *, allow_loopback_fixture=False,
                 timeout=15, max_pdf_bytes=52428800):
        url = urlsplit(api_base)
        official = api_base.rstrip('/') == 'https://api2.openreview.net'
        fixture = allow_loopback_fixture and url.scheme == 'http' and url.hostname in {'127.0.0.1', 'localhost'}
        if not (official or fixture) or url.username or url.password or url.query or url.fragment:
            raise ValueError('Only official API v2 or explicit loopback fixture allowed')
        self.api_base = api_base.rstrip('/')
        self.timeout, self.max_pdf_bytes = timeout, max_pdf_bytes

    def configured(self, policy):
        return type(self)(self.api_base, allow_loopback_fixture=urlsplit(self.api_base).scheme == 'http',
                          timeout=policy['source_timeout_seconds'], max_pdf_bytes=policy['max_pdf_bytes'])

    def _get(self, path, query, *, pdf=False):
        bound = self.max_pdf_bytes if pdf else 4194304
        try:
            request = Request(self.api_base + path + '?' + urlencode(query), headers={'User-Agent': 'rsi-red-paper/1'})
            with build_opener(NoRedirect()).open(request, timeout=self.timeout) as stream:
                size = stream.headers.get('Content-Length')
                require(size is None or int(size) <= bound, 'DOCUMENT_TOO_LARGE', 'Source response exceeds bound')
                body = stream.read(bound + 1)
                require(len(body) <= bound, 'DOCUMENT_TOO_LARGE', 'Source response exceeds bound')
            return body if pdf else json.loads(body)
        except HTTPError as error:
            error.close()
            if error.code == 429:
                raise ResearchError('SOURCE_RATE_LIMITED', 'Source rate limited', retryable=True) from None
            raise ResearchError('SOURCE_UNAVAILABLE', 'Public source unavailable', retryable=error.code >= 500) from None
        except (TimeoutError, URLError):
            raise ResearchError('SOURCE_UNAVAILABLE', 'Public source unavailable', retryable=True) from None

    def _record(self, note):
        content = {k: v.get('value') if isinstance(v, dict) else v for k, v in note.get('content', {}).items()}
        venue = content.get('venueid', '')
        year = re.search(r'(?:^|/)(20\d{2})(?:/|$)', venue)
        track = 'main' if venue.endswith('/Conference') else 'unknown'
        withdrawn = bool(note.get('ddate')) or any(x in str(content.get('venue', '')).lower() for x in ('withdraw', 'reject'))
        return {'provider': 'openreview_v2', 'record_id': note['id'], 'forum_id': note.get('forum', note['id']),
                'title': content.get('title', ''), 'authors': content.get('authors', []), 'venue_id': venue,
                'year': int(year.group(1)) if year else None, 'track': track,
                'status': 'withdrawn' if withdrawn else ('accepted' if venue.endswith('/Conference') else 'unknown'),
                'is_public': 'everyone' in note.get('readers', []),
                'revision': str(note.get('mdate', note.get('pdate', 'unknown'))),
                'source_url': 'https://openreview.net/forum?' + urlencode({'id': note.get('forum', note['id'])}),
                'pdf_locator': content.get('pdf'), 'raw_response': note}

    def get_record(self, record_id):
        notes = self._get('/notes', {'id': record_id}).get('notes', [])
        require(len(notes) == 1 and notes[0]['id'] == record_id, 'SOURCE_UNAVAILABLE', 'Public note not found')
        record = self._record(notes[0])
        if record['venue_id']:
            groups = self._get('/groups', {'id': record['venue_id']}).get('groups', [])
            require(any(g.get('id') == record['venue_id'] and g.get('domain') == record['venue_id'] for g in groups),
                    'UNSUPPORTED_SOURCE', 'Venue API v2 domain not verified')
            record['venue_response'] = groups
        return record

    def get_pdf(self, record):
        # Never follow an arbitrary PDF URL supplied by a note.
        return self._get('/pdf', {'id': record['record_id']}, pdf=True)

    def discover(self, venue_id, cursor=None, limit=100):
        require(isinstance(limit, int) and 1 <= limit <= 1000, 'INVALID_REQUEST', 'Invalid page limit')
        offset = int(cursor or 0)
        require(offset >= 0, 'INVALID_REQUEST', 'Invalid source cursor')
        body = self._get('/notes', {'content.venueid': venue_id, 'limit': limit, 'offset': offset, 'sort': 'id:asc'})
        notes = body.get('notes', [])
        require(len(notes) <= limit, 'SOURCE_UNAVAILABLE', 'Invalid source page')
        return {'items': [self._record(n) for n in notes],
                'raw_response': body,
                'next_cursor': str(offset + len(notes)) if notes and offset + len(notes) < body.get('count', 0) else None}
