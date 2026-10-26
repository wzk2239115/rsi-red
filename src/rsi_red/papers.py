"""Persistent literature queue and conservative, source-grounded mechanism library."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
import math
import subprocess
import sys
import threading

from .errors import ResearchError, require
from .paper_sources import OpenReviewSource
from .store import digest, encoded

CURATOR_OPERATIONS = frozenset('paper.' + v for v in (
    'policy_show', 'ingest', 'show', 'list', 'document', 'batch_submit', 'batch_show', 'batch_retry',
    'batch_list', 'extract', 'recheck', 'relationship_evidence')) | frozenset('knowledge.' + v for v in (
    'create', 'show', 'list', 'revise', 'pack', 'bridges', 'bridge_register'))
TERMINAL = {'ready', 'duplicate', 'failed', 'ineligible', 'quarantine', 'needs_text'}


def text(value):
    return isinstance(value, str) and bool(value.strip())


def strings(value):
    return isinstance(value, list) and all(text(v) for v in value)


def normalized(value):
    return ' '.join(value.split())


class PaperMixin:
    def _init_papers(self):
        self.paper_sources = {'openreview_v2': OpenReviewSource()}
        self.paper_lock = threading.Lock()

    def _curator(self, actor):
        require(actor['role'] in {'curator', 'operator'}, 'FORBIDDEN', 'Curator identity required')

    def _paper_owner(self, item, actor):
        require(actor['role'] == 'operator' or actor['id'] == item['owner'], 'FORBIDDEN', 'Owner required')

    def _paper_new(self, kind, value, actor):
        result = self.store.create(kind, dict(value, owner=actor['id'], created_at=self.clock()))
        self._event(kind + '.created', result, actor)
        return result

    def _paper_idem(self, kind, p, actor):
        require(text(p.get('idempotency_key')), 'INVALID_REQUEST', 'Idempotency key required')
        for item in self.store.list(kind):
            if item['owner'] == actor['id'] and item.get('idempotency_key') == p['idempotency_key']:
                require(item['request_digest'] == digest(p), 'IDEMPOTENCY_CONFLICT', 'Idempotency request changed')
                return item
        return None

    def op_paper_policy_register(self, p, actor):
        self._operator(actor)
        require(text(p.get('name')) and isinstance(p.get('venues'), list) and p['venues'], 'INVALID_REQUEST', 'Policy needs venues')
        for v in p['venues']:
            require(isinstance(v, dict), 'INVALID_REQUEST', 'Venue must be an object')
            require(v.get('provider') == 'openreview_v2', 'UNSUPPORTED_SOURCE', 'Unsupported provider')
            require(text(v.get('venue_id')) and type(v.get('year')) is int and strings([v.get('track')]),
                    'INVALID_REQUEST', 'Venue, year and track required')
        for key, low, high in [('batch_size_limit', 1, 1000), ('max_parallel', 1, 4),
                              ('max_pdf_bytes', 1024, 52428800), ('source_timeout_seconds', 1, 60), ('retry_limit', 0, 5)]:
            require(type(p.get(key)) is int and low <= p[key] <= high, 'INVALID_REQUEST', 'Policy bound invalid')
        require(type(p.get('require_full_text')) is bool, 'INVALID_REQUEST', 'Full text policy required')
        return self._paper_new('paper_policy', {'spec': p, 'digest': digest(p)}, actor)

    def op_paper_policy_show(self, p, actor):
        self._curator(actor)
        return self.store.get(p['id'], 'paper_policy')

    def _paper_request(self, p):
        policy = self.store.get(p['policy_id'], 'paper_policy')['spec']
        require(p.get('provider') in self.paper_sources, 'UNSUPPORTED_SOURCE', 'Unsupported provider')
        require(any(v['provider'] == p['provider'] for v in policy['venues']), 'UNSUPPORTED_SOURCE', 'Provider not allowed')
        require(text(p.get('record_id')), 'INVALID_REQUEST', 'Record identity required')
        return policy

    def op_paper_ingest(self, p, actor):
        self._curator(actor)
        require(set(p) <= {'policy_id', 'provider', 'record_id', 'idempotency_key'}, 'INVALID_REQUEST', 'Unsupported ingest field')
        self._paper_request(p)
        existing = self._paper_idem('paper', p, actor)
        if existing:
            return existing
        return self._paper_new('paper', dict(p, request_digest=digest(p), state='queued', attempts=0,
                                              next_attempt_at=0, acceptance={'status': 'pending'}, checks=[]), actor)

    def _paper_visible(self, paper, actor):
        if actor['role'] != 'operator' and actor['id'] != paper['owner']:
            require(paper['state'] == 'ready', 'FORBIDDEN', 'Private pending record')
        return paper

    def _paper_public(self, paper):
        fields = ('id', 'state', 'canonical_key', 'metadata', 'acceptance', 'revision', 'duplicate_of', 'error', 'created_at')
        return {k: paper[k] for k in fields if k in paper}

    def op_paper_show(self, p, actor):
        paper = self._paper_visible(self.store.get(p['id'], 'paper'), actor)
        return paper if actor['role'] in {'operator', 'curator'} else self._paper_public(paper)

    def op_paper_list(self, p, actor):
        items = [x for x in self.store.list('paper') if x['state'] == 'ready' and
                 (not p.get('eligible_only', True) or self._paper_eligible(x))]
        return self._paper_page([self._paper_public(x) for x in items], p)

    def op_paper_document(self, p, actor):
        self._curator(actor)
        paper = self._paper_visible(self.store.get(p['id'], 'paper'), actor)
        require('revision' in paper and paper['revision'].get('text_digest'), 'FULL_TEXT_REQUIRED', 'Frozen full text required')
        self.store.read_blob(paper['revision']['pdf_digest'])
        return json.loads(self.store.read_blob(paper['revision']['text_digest']))

    def _paper_eligible(self, paper):
        return paper['state'] == 'ready' and paper['acceptance']['status'] == 'verified'

    def _paper_ready(self, key):
        paper = self.store.get(key, 'paper')
        require(paper['state'] != 'needs_text', 'FULL_TEXT_REQUIRED', 'Frozen full text required')
        require(self._paper_eligible(paper), 'PAPER_NOT_ELIGIBLE', 'Paper not eligible')
        return paper

    def _acceptance(self, record, policy):
        allowed = record.get('status') == 'accepted' and record.get('is_public') is True and any(
            all(record.get(k) == v[k] for k in ('provider', 'venue_id', 'year', 'track')) for v in policy['venues'])
        return {'status': 'verified' if allowed else 'ineligible', 'source_status': record.get('status', 'unknown'),
                'venue_id': record.get('venue_id'), 'year': record.get('year'), 'track': record.get('track'),
                'source_digest': self.store.blob(encoded(record).encode()), 'observed_at': self.clock()}

    def op_paper_recheck(self, p, actor):
        self._curator(actor)
        paper = self.store.get(p['id'], 'paper')
        self._paper_owner(paper, actor)
        require(paper['state'] == 'ready', 'PAPER_NOT_ELIGIBLE', 'Only frozen papers can be rechecked')
        if paper.get('recheck_pending'):
            return {'id': paper['id'], 'state': 'queued'}
        paper['recheck_pending'] = True
        paper['recheck_attempts'] = 0
        paper['recheck_next_at'] = 0
        self.store.save('paper', paper)
        return {'id': paper['id'], 'state': 'queued'}

    def op_paper_batch_submit(self, p, actor):
        self._curator(actor)
        require(set(p) <= {'policy_id', 'idempotency_key', 'records', 'catalog'} and
                ('records' in p) != ('catalog' in p), 'INVALID_REQUEST', 'Choose records or catalog')
        policy = self.store.get(p['policy_id'], 'paper_policy')['spec']
        existing = self._paper_idem('paper_batch', p, actor)
        if existing:
            return self._batch_view(existing)
        records = p.get('records')
        if records is not None:
            require(isinstance(records, list) and 0 < len(records) <= policy['batch_size_limit'], 'INVALID_REQUEST', 'Invalid batch size')
            for record in records:
                require(set(record) == {'provider', 'record_id'}, 'INVALID_REQUEST', 'Invalid record manifest')
                self._paper_request(dict(record, policy_id=p['policy_id']))
        else:
            c = p['catalog']
            require(isinstance(c, dict), 'INVALID_REQUEST', 'Catalog must be an object')
            require(c.get('provider') in self.paper_sources, 'UNSUPPORTED_SOURCE', 'Unsupported provider')
            require(any(v['provider'] == c['provider'] and v['venue_id'] == c.get('venue_id') for v in policy['venues']) and
                    type(c.get('limit')) is int and 1 <= c['limit'] <= policy['batch_size_limit'],
                    'INVALID_REQUEST', 'Catalog outside policy')
        batch = self._paper_new('paper_batch', dict(p, request_digest=digest(p), state='queued', items=[],
                   catalog_loaded=records is not None, catalog_attempts=0, catalog_next_at=0, next_cursor=None), actor)
        if records:
            batch['items'] = [self._batch_item(batch, record, i, actor) for i, record in enumerate(records)]
            self.store.save('paper_batch', batch)
        return self._batch_view(batch)

    def _batch_item(self, batch, record, index, actor):
        paper = self.op_paper_ingest(dict(record, policy_id=batch['policy_id'],
                                         idempotency_key=batch['id'] + '-' + str(index)), actor)
        return dict(record, paper_id=paper['id'])

    def _batch_view(self, batch):
        result = deepcopy(batch)
        items = []
        for item in batch['items']:
            paper = self.store.get(item['paper_id'], 'paper')
            items.append(dict(item, state=paper['state'], attempts=paper['attempts'], **({'error': paper['error']} if 'error' in paper else {})))
        counts = Counter(i['state'] for i in items)
        result['items'], result['counts'] = items, dict(total=len(items), ready=counts['ready'], failed=counts['failed'],
                                                          duplicate=counts['duplicate'], **{k: v for k, v in counts.items() if k not in {'ready', 'failed', 'duplicate'}})
        if batch['catalog_loaded'] and all(i['state'] in TERMINAL for i in items):
            result['state'] = 'completed_with_errors' if any(i['state'] not in {'ready', 'duplicate'} for i in items) else 'completed'
        return result

    def op_paper_batch_show(self, p, actor):
        self._curator(actor)
        batch = self.store.get(p['id'], 'paper_batch')
        self._paper_owner(batch, actor)
        return self._batch_view(batch)

    def op_paper_batch_list(self, p, actor):
        self._curator(actor)
        return self._paper_page([self._batch_view(x) for x in self.store.list('paper_batch')
                                if actor['role'] == 'operator' or x['owner'] == actor['id']], p)

    def op_paper_batch_retry(self, p, actor):
        batch = self.store.get(p['id'], 'paper_batch')
        self._curator(actor)
        self._paper_owner(batch, actor)
        policy = self.store.get(batch['policy_id'], 'paper_policy')['spec']
        for item in batch['items']:
            paper = self.store.get(item['paper_id'], 'paper')
            if paper['state'] == 'failed' and paper.get('error', {}).get('retryable') and paper['attempts'] <= policy['retry_limit']:
                paper.update(state='queued', next_attempt_at=self.clock())
                self.store.save('paper', paper)
        return self._batch_view(batch)

    def _source(self, provider, policy):
        source = self.paper_sources[provider]
        return source.configured(policy) if isinstance(source, OpenReviewSource) else source

    def _paper_fetch(self, paper, policy):
        source = self._source(paper['provider'], policy)
        record = source.get_record(paper['record_id'])
        require(record.get('record_id') == paper['record_id'] and record.get('provider') == paper['provider'],
                'SOURCE_IDENTITY_MISMATCH', 'Official identity changed')
        result = {'record': record, 'provider_version': source.provider_version}
        if paper.get('recheck_pending'):
            return result
        # Eligibility is checked before downloading an unsupported/private source.
        allowed = record.get('status') == 'accepted' and record.get('is_public') is True and any(
            all(record.get(k) == v[k] for k in ('provider', 'venue_id', 'year', 'track')) for v in policy['venues'])
        if not allowed or not record.get('pdf_locator'):
            return result
        body = source.get_pdf(record)
        require(len(body) <= policy['max_pdf_bytes'], 'DOCUMENT_TOO_LARGE', 'PDF exceeds policy bound')
        require(not record.get('pdf_sha256') or hashlib.sha256(body).hexdigest() == record['pdf_sha256'],
                'CHECKSUM_MISMATCH', 'Source PDF checksum mismatch')
        try:
            process = subprocess.run([sys.executable, '-m', 'rsi_red.paper_parse'], input=body, capture_output=True,
                                     timeout=policy['source_timeout_seconds'])
        except subprocess.TimeoutExpired:
            raise ResearchError('PDF_PARSE_TIMEOUT', 'PDF parsing exceeded bound') from None
        require(process.returncode == 0 and len(process.stdout) <= 24000000, 'INVALID_PDF', 'PDF parser rejected document')
        result.update(pdf=body, document=json.loads(process.stdout))
        return result

    def _paper_failure(self, paper, error, policy, *, recheck=False):
        failure = error if isinstance(error, ResearchError) else ResearchError('SOURCE_UNAVAILABLE', 'Source request failed', retryable=True)
        field = 'recheck_attempts' if recheck else 'attempts'
        attempts = paper[field]
        retry = failure.retryable and attempts <= policy['retry_limit']
        safe = {'code': failure.code, 'retryable': failure.retryable}
        if recheck:
            paper.update(recheck_pending=retry, recheck_error=safe, recheck_next_at=self.clock() + min(2**attempts, 30))
            # Unverifiable current eligibility is conservative; frozen content remains readable.
            paper['acceptance'] = dict(paper['acceptance'], status='unverified')
        else:
            paper.update(state='queued' if retry else 'failed', error=safe, next_attempt_at=self.clock() + min(2**attempts, 30))
        self.store.save('paper', paper)

    def _paper_publish(self, paper, result):
        policy = self.store.get(paper['policy_id'], 'paper_policy')['spec']
        record = result['record']
        acceptance = self._acceptance(record, policy)
        if paper.get('recheck_pending'):
            if record.get('revision') != paper.get('official_revision'):
                acceptance.update(status='revision_changed', reason='ingest_new_revision')
            paper['checks'].append(dict(acceptance, provider_version=result['provider_version']))
            paper.update(acceptance=acceptance, recheck_pending=False)
            self.store.save('paper', paper)
            return
        paper.update(acceptance=acceptance, canonical_key=paper['provider'] + ':' + record.get('forum_id', record['record_id']),
                     metadata={k: record.get(k) for k in ('title', 'authors', 'venue_id', 'year', 'track', 'source_url')},
                     official_revision=record.get('revision'), provider_version=result['provider_version'])
        paper['checks'].append(dict(acceptance, provider_version=result['provider_version']))
        paper['state'] = 'ineligible' if acceptance['status'] != 'verified' else 'needs_text'
        if 'document' in result:
            body, document = result['pdf'], result['document']
            revision = {'pdf_digest': self.store.blob(body), 'text_digest': self.store.blob(encoded(document).encode()),
                        'official_revision': record.get('revision'), 'parser': document['parser'], 'source_digest': acceptance['source_digest']}
            paper.update(revision=revision, state='ready' if any(text(p['text']) for p in document['pages']) else 'needs_text')
            for old in self.store.list('paper'):
                if old['id'] == paper['id'] or old.get('canonical_key') != paper['canonical_key'] or old['state'] != 'ready':
                    continue
                if old['revision']['pdf_digest'] == revision['pdf_digest']:
                    paper.update(state='duplicate', duplicate_of=old['id'])
                    break
                if old.get('official_revision') == record.get('revision'):
                    paper.update(state='quarantine', error={'code': 'REVISION_CONFLICT', 'retryable': False})
                    break
        paper.pop('error', None) if paper['state'] != 'quarantine' else None
        self.store.save('paper', paper)
        self._event('paper.' + paper['state'], paper, 'service')

    def reconcile_papers(self):
        if not self.paper_lock.acquire(blocking=False):
            return
        try:
            # One bounded discovery page per tick; network never holds the SQLite transaction.
            with self.store.transaction():
                batches = self.store.list('paper_batch')
            for batch in batches:
                if batch['catalog_loaded'] or batch.get('catalog_error') or batch['catalog_next_at'] > self.clock():
                    continue
                with self.store.transaction():
                    policy = self.store.get(batch['policy_id'], 'paper_policy')['spec']
                    if batch['catalog_attempts'] >= policy['retry_limit'] + 1:
                        batch.update(catalog_error={'code': 'RETRY_EXHAUSTED'}, state='completed_with_errors')
                        self.store.save('paper_batch', batch)
                        continue
                    batch['catalog_attempts'] += 1
                    self.store.save('paper_batch', batch)
                try:
                    c = batch['catalog']
                    page = self._source(c['provider'], policy).discover(c['venue_id'], c.get('cursor'), c['limit'])
                    require(len(page['items']) <= c['limit'], 'INVALID_REQUEST', 'Catalog page too large')
                    with self.store.transaction():
                        batch['items'] = [self._batch_item(batch, {'provider': c['provider'], 'record_id': r['record_id']}, i,
                                                         {'id': batch['owner'], 'role': 'curator'}) for i, r in enumerate(page['items'])]
                        batch.update(catalog_loaded=True, next_cursor=page['next_cursor'],
                                     catalog_snapshot_digest=self.store.blob(encoded(page).encode()))
                        self.store.save('paper_batch', batch)
                except Exception as error:
                    with self.store.transaction():
                        retryable = not isinstance(error, ResearchError) or error.retryable
                        if not retryable or batch['catalog_attempts'] > policy['retry_limit']:
                            batch.update(catalog_error={'code': getattr(error, 'code', 'SOURCE_UNAVAILABLE')}, state='completed_with_errors')
                        batch['catalog_next_at'] = self.clock() + min(2**batch['catalog_attempts'], 30)
                        self.store.save('paper_batch', batch)
                break
            with self.store.transaction():
                candidates = []
                for paper in self.store.list('paper'):
                    recheck = paper.get('recheck_pending', False)
                    if not (recheck or paper['state'] == 'queued') or paper.get('recheck_next_at' if recheck else 'next_attempt_at', 0) > self.clock():
                        continue
                    policy = self.store.get(paper['policy_id'], 'paper_policy')['spec']
                    field = 'recheck_attempts' if recheck else 'attempts'
                    if paper.get(field, 0) >= policy['retry_limit'] + 1:
                        self._paper_failure(paper, ResearchError('RETRY_EXHAUSTED', 'Reserved attempt budget exhausted'), policy, recheck=recheck)
                        continue
                    candidates.append((paper, policy))
                bound = min([policy['max_parallel'] for _, policy in candidates] or [4])
                candidates = candidates[:bound]
                for paper, _ in candidates:
                    field = 'recheck_attempts' if paper.get('recheck_pending') else 'attempts'
                    paper[field] += 1
                    self.store.save('paper', paper)
            with ThreadPoolExecutor(max_workers=bound) as workers:
                futures = [(paper, policy, workers.submit(self._paper_fetch, paper, policy)) for paper, policy in candidates]
                for paper, policy, future in futures:
                    try:
                        result = future.result()
                    except Exception as error:
                        with self.store.transaction():
                            self._paper_failure(paper, error, policy, recheck=paper.get('recheck_pending', False))
                    else:
                        with self.store.transaction():
                            self._paper_publish(paper, result)
        finally:
            self.paper_lock.release()

    def _paper_citations(self, paper, citations):
        require(isinstance(citations, list) and citations, 'INVALID_CITATION', 'Frozen body citations required')
        require(all(isinstance(c, dict) for c in citations), 'INVALID_CITATION', 'Invalid citation')
        require(all(c.get('kind') in {'body', 'figure', 'table'} and not any(k in c for k in ('protocol_id', 'eval_id', 'campaign_id'))
                    for c in citations), 'PROTECTED_EVIDENCE', 'Only public paper evidence allowed')
        self.store.read_blob(paper['revision']['pdf_digest'])
        document = json.loads(self.store.read_blob(paper['revision']['text_digest']))
        for cite in citations:
            page = cite.get('page')
            require(type(page) is int and 1 <= page <= len(document['pages']) and text(cite.get('quote')),
                    'INVALID_CITATION', 'Invalid frozen page locator')
            body = normalized(document['pages'][page - 1]['text'])
            require(normalized(cite['quote']) in body, 'INVALID_CITATION', 'Quote absent from frozen page')
            if cite['kind'] in {'figure', 'table'}:
                require(text(cite.get('label')) and normalized(cite['label']) in normalized(cite['quote']),
                        'INVALID_CITATION', 'Figure/table label must be grounded in cited text')
                if 'caption' in cite:
                    require(text(cite['caption']) and normalized(cite['caption']) in body, 'INVALID_CITATION', 'Caption absent')
                if 'bbox' in cite:
                    b, p = cite['bbox'], document['pages'][page - 1]
                    require(isinstance(b, list) and len(b) == 4 and all(type(n) in (int, float) and math.isfinite(n) for n in b)
                            and 0 <= b[0] < b[2] <= p['width'] and 0 <= b[1] < b[3] <= p['height'],
                            'INVALID_CITATION', 'Invalid page bounds')

    def op_paper_extract(self, p, actor):
        self._curator(actor)
        paper = self._paper_ready(p['paper_id'])
        mechanisms = p.get('mechanisms')
        require(isinstance(mechanisms, list) and 0 < len(mechanisms) <= 100, 'INVALID_REQUEST', 'Mechanisms required')
        keys = set()
        for m in mechanisms:
            require(isinstance(m, dict), 'INVALID_REQUEST', 'Invalid mechanism')
            require(m.get('local_validation', 'not_tested') == 'not_tested' and m.get('evidence_level', 'paper_reported') == 'paper_reported',
                    'UNVERIFIED_CLAIM', 'Literature is not local validation')
            sig = m.get('signature', {})
            require(isinstance(sig, dict) and set(sig) == {'target', 'intervention', 'assumptions', 'invariant'} and
                    all(text(sig.get(k)) for k in ('target', 'intervention', 'invariant')) and strings(sig.get('assumptions')),
                    'INVALID_REQUEST', 'Specific mechanism signature required')
            require(all(text(m.get(k)) for k in ('key', 'name', 'source_finding', 'ai_interpretation', 'transfer_hypothesis', 'minimal_trial', 'falsifier'))
                    and strings(m.get('requirements')) and strings(m.get('limitations')) and m['limitations']
                    and isinstance(m.get('variants'), dict) and m['key'] not in keys, 'INVALID_REQUEST', 'Incomplete mechanism')
            self._paper_citations(paper, m.get('citations'))
            keys.add(m['key'])
        value = dict(p, paper_revision=paper['revision'], interpretation_status='curator_interpretation')
        return self._paper_new('paper_extraction', dict(value, digest=digest(value)), actor)

    def _knowledge_new(self, value, actor):
        value = {k: v for k, v in value.items() if k not in {'id', 'digest', 'owner', 'created_at', 'warnings', 'eligible'}}
        value.update(kind='paper_mechanism', evidence_level='paper_reported', local_validation='not_tested',
                     interpretation_status='curator_interpretation')
        return self._paper_new('knowledge_island', dict(value, digest=digest(value)), actor)

    def op_knowledge_create(self, p, actor):
        self._curator(actor)
        extraction = self.store.get(p['extraction_id'], 'paper_extraction')
        self._paper_ready(extraction['paper_id'])
        matches = [m for m in extraction['mechanisms'] if m['key'] == p['mechanism_key']]
        require(len(matches) == 1, 'NOT_FOUND', 'Mechanism not found')
        m = matches[0]
        return self._knowledge_new(dict(m, extraction_id=extraction['id'], paper_ids=[extraction['paper_id']], parent_ids=[],
                                        source_variants=[{'paper_id': extraction['paper_id'], 'variants': m['variants'],
                                                          'citations': m['citations'], 'limitations': m['limitations']}]), actor)

    def _knowledge_view(self, item):
        warnings, valid = [], []
        for key in item['paper_ids']:
            paper = self.store.get(key, 'paper')
            if self._paper_eligible(paper):
                valid.append(key)
            else:
                warnings.append({'paper_id': key, 'reason': 'source_ineligible'})
        return dict(item, eligible=bool(valid), eligible_paper_ids=valid, warnings=warnings)

    def op_knowledge_show(self, p, actor):
        return self._knowledge_view(self.store.get(p['id'], 'knowledge_island'))

    def _paper_page(self, items, p):
        limit, offset = p.get('limit', 100), int(p.get('cursor') or 0)
        require(type(limit) is int and 1 <= limit <= 1000 and offset >= 0, 'INVALID_REQUEST', 'Invalid page bounds')
        return {'items': items[offset:offset + limit], 'next_cursor': str(offset + limit) if offset + limit < len(items) else None}

    def op_knowledge_list(self, p, actor):
        require('query' not in p or isinstance(p['query'], str), 'INVALID_REQUEST', 'Query must be text')
        items = [self._knowledge_view(x) for x in self.store.list('knowledge_island')]
        if p.get('eligible_only', True):
            items = [x for x in items if x['eligible']]
        if p.get('query'):
            items = [x for x in items if p['query'].casefold() in encoded(x).casefold()]
        return self._paper_page(items, p)

    def op_knowledge_merge(self, p, actor):
        self._operator(actor)
        require(isinstance(p.get('ids'), list) and 2 <= len(p['ids']) <= 100 and len(set(p['ids'])) == len(p['ids'])
                and text(p.get('rationale')), 'INVALID_REQUEST', 'Distinct islands and rationale required')
        items = [self.store.get(k, 'knowledge_island') for k in p['ids']]
        signatures = [dict(x['signature'], assumptions=sorted(set(x['signature']['assumptions']))) for x in items]
        require(all(s == signatures[0] for s in signatures), 'MECHANISM_MISMATCH', 'Independent mechanisms must remain separate')
        for x in items:
            for key in x['paper_ids']:
                self._paper_ready(key)
        merged = deepcopy(items[0])
        merged.update(parent_ids=p['ids'], rationale=p['rationale'], signature=signatures[0],
                      paper_ids=list(dict.fromkeys(k for x in items for k in x['paper_ids'])),
                      limitations=list(dict.fromkeys(k for x in items for k in x['limitations'])),
                      requirements=list(dict.fromkeys(k for x in items for k in x['requirements'])),
                      citations=[c for x in items for c in x['citations']],
                      source_variants=[v for x in items for v in x['source_variants']],
                      source_findings=[{'id': x['id'], 'source_finding': x['source_finding'], 'ai_interpretation': x['ai_interpretation'],
                                        'transfer_hypothesis': x['transfer_hypothesis']} for x in items] +
                                      [finding for x in items for finding in x.get('source_findings', [])])
        return self._knowledge_new(merged, actor)

    def op_knowledge_revise(self, p, actor):
        self._curator(actor)
        item = self.store.get(p['id'], 'knowledge_island')
        self._paper_owner(item, actor)
        require(set(p) <= {'id', 'limitations', 'ai_interpretation', 'transfer_hypothesis', 'unknowns'}, 'INVALID_REQUEST', 'Unsupported revision')
        if 'limitations' in p:
            require(strings(p['limitations']), 'INVALID_REQUEST', 'Limitations must be text')
        value = dict(item, parent_ids=[item['id']], limitations=list(dict.fromkeys(item['limitations'] + p.get('limitations', []))))
        for key in ('ai_interpretation', 'transfer_hypothesis', 'unknowns'):
            if key in p:
                require(text(p[key]), 'INVALID_REQUEST', 'Revision text required')
                value[key] = p[key]
        return self._knowledge_new(value, actor)

    def op_knowledge_pack(self, p, actor):
        require(strings(p.get('signals', [])) and strings(p.get('capabilities', [])), 'INVALID_REQUEST', 'Signals/capabilities must be text lists')
        budget, limit = p.get('context_budget_chars', 8000), p.get('limit', 5)
        require(type(budget) is int and 0 <= budget <= 200000 and type(limit) is int and 1 <= limit <= 100,
                'INVALID_REQUEST', 'Pack bounds invalid')
        cards, excluded, context = [], [], ''
        signals = [s.casefold() for s in p.get('signals', [])]
        items = [self._knowledge_view(x) for x in self.store.list('knowledge_island')]
        items.sort(key=lambda x: (-sum(s in encoded(x).casefold() for s in signals), x['id']))
        for item in items:
            reason = None
            if not item['eligible']:
                reason = 'source_ineligible'
            elif not set(item['requirements']) <= set(p.get('capabilities', [])):
                reason = 'missing_capability'
            elif len(cards) >= limit:
                reason = 'limit'
            rendered = encoded(item) + '\n'
            if reason is None and len(context) + len(rendered) > budget:
                reason = 'context_budget'
            if reason:
                excluded.append({'id': item['id'], 'reason': reason})
            else:
                cards.append(dict(item, recommendation_reason='signal_match' if any(s in encoded(item).casefold() for s in signals) else 'capability_compatible'))
                # Render precisely the returned card, including recommendation and all limitations.
                rendered = encoded(cards[-1]) + '\n'
                if len(context) + len(rendered) > budget:
                    cards.pop()
                    excluded.append({'id': item['id'], 'reason': 'context_budget'})
                else:
                    context += rendered
        return {'cards': cards, 'context': context, 'context_chars': len(context), 'excluded': excluded,
                'bridges': self.op_knowledge_bridges({}, actor)['items']}

    def _relation_check(self, value, *, positive=False):
        code = 'INSUFFICIENT_BRIDGE_EVIDENCE'
        require(value.get('relation') in {'composition', 'transfer'} and text(value.get('scope')) and
                strings(value.get('limitations')), code, 'Scoped relation required')
        e = value.get('experiment', {})
        require(isinstance(e, dict) and all(k in e for k in ('baselines', 'treatment', 'metric', 'reported_metric_direction', 'controls', 'uncertainty', 'citations')),
                code, 'Direct experiment required')
        require(e['reported_metric_direction'] in {'maximize', 'minimize'} and text(e['metric']), code, 'Paper metric required')
        require(isinstance(e['controls'], dict) and set(e['controls']) >= {'data', 'compute', 'model', 'evaluation'} and
                all(e['controls'][k] in {'same', 'matched'} for k in ('data', 'compute', 'model', 'evaluation')),
                code, 'Matched controls required')
        baselines = e['baselines']
        require(isinstance(baselines, list) and len(baselines) >= (2 if value['relation'] == 'composition' else 1), code, 'Identifiable baselines required')
        results = baselines + [e['treatment']]
        require(all(isinstance(r, dict) and text(r.get('id')) and type(r.get('score')) in {float, int} and math.isfinite(r['score']) for r in results)
                and len({r['id'] for r in results}) == len(results), code, 'Finite distinct results required')
        if value['relation'] == 'composition':
            require(isinstance(e.get('ablation'), dict) and text(e['ablation'].get('removed')) and
                    e['ablation'].get('result_id') in {b['id'] for b in baselines}, code, 'Identifiable ablation required')
        else:
            require(text(e.get('source_method')) and text(e.get('target_setting')), code, 'Transfer source and target setting required')
        require(isinstance(e['uncertainty'], dict) and type(e['uncertainty'].get('reported')) is bool, code, 'Uncertainty status required')
        require(e['uncertainty']['reported'] or 'uncertainty_not_reported' in value['limitations'], code, 'Missing uncertainty must be explicit')
        paper = self._paper_ready(value['paper_id'])
        require(bool(e.get('citations')), code, 'Experimental citations required')
        self._paper_citations(paper, e['citations'])
        source, target = [self.store.get(value[k], 'knowledge_island') for k in ('source_island_id', 'target_island_id')]
        require(source['id'] != target['id'] and all(self._knowledge_view(x)['eligible'] for x in (source, target)), code, 'Valid distinct endpoints required')
        require(value['paper_id'] in source['paper_ids'] and value['paper_id'] in target['paper_ids'], code, 'Paper must ground both mechanisms')
        if positive:
            score = e['treatment']['score']
            require(all(score > b['score'] if e['reported_metric_direction'] == 'maximize' else score < b['score'] for b in baselines),
                    code, 'Reported result does not support improvement')

    def op_paper_relationship_evidence(self, p, actor):
        self._curator(actor)
        require(set(p) == {'paper_id', 'source_island_id', 'target_island_id', 'relation', 'scope', 'limitations', 'experiment'},
                'INVALID_REQUEST', 'Only experimental evidence accepted')
        self._relation_check(p)
        return self._paper_new('paper_relation_evidence', dict(p, digest=digest(p)), actor)

    def op_paper_review_relationship(self, p, actor):
        self._operator(actor)
        evidence = self.store.get(p['id'], 'paper_relation_evidence')
        require(actor['id'] != evidence['owner'], 'FORBIDDEN', 'Independent reviewer required')
        require(p.get('decision') in {'supported', 'insufficient', 'contradicted'} and text(p.get('rationale')),
                'INVALID_REQUEST', 'Decision and rationale required')
        if p['decision'] == 'supported':
            self._relation_check(evidence, positive=True)
        return self._paper_new('paper_relation_review', {'evidence_id': evidence['id'], 'evidence_digest': evidence['digest'],
                                                       'decision': p['decision'], 'rationale': p['rationale']}, actor)

    def _relation_review(self, evidence_id):
        reviews = [x for x in self.store.list('paper_relation_review') if x['evidence_id'] == evidence_id]
        return reviews[-1] if reviews else None

    def op_knowledge_bridge_register(self, p, actor):
        self._curator(actor)
        require(set(p) == {'evidence_id'}, 'INVALID_REQUEST', 'Server-owned review required')
        evidence = self.store.get(p['evidence_id'], 'paper_relation_evidence')
        review = self._relation_review(evidence['id'])
        require(review and review['decision'] == 'supported' and review['evidence_digest'] == evidence['digest'],
                'INSUFFICIENT_BRIDGE_EVIDENCE', 'Independent supported review required')
        self._relation_check(evidence, positive=True)
        for bridge in self.store.list('paper_bridge'):
            if bridge['evidence_id'] == evidence['id']:
                return self._bridge_view(bridge)
        return self._bridge_view(self._paper_new('paper_bridge', {k: evidence[k] for k in
            ('paper_id', 'source_island_id', 'target_island_id', 'scope', 'limitations', 'relation', 'experiment')} |
            {'evidence_id': evidence['id'], 'review_id': review['id'], 'evidence_level': 'paper_reported', 'local_validation': 'not_tested'}, actor))

    def _bridge_view(self, bridge):
        review = self._relation_review(bridge['evidence_id'])
        valid = self._paper_eligible(self.store.get(bridge['paper_id'], 'paper')) and review and review['decision'] == 'supported'
        for key in ('source_island_id', 'target_island_id'):
            valid = valid and self._knowledge_view(self.store.get(bridge[key], 'knowledge_island'))['eligible']
        return dict(bridge, state='active' if valid else 'suspended', current_review_id=review['id'] if review else None)

    def op_knowledge_bridges(self, p, actor):
        if p.get('include_suspended'):
            self._operator(actor)
        items = [self._bridge_view(b) for b in self.store.list('paper_bridge')]
        return self._paper_page([b for b in items if b['state'] == 'active' or p.get('include_suspended')], p)
