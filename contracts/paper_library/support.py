"""Synthetic papers and external source I/O double; no product logic substituted."""
from copy import deepcopy
import hashlib
import time
import textwrap
import threading

from tests.support import OPERATOR, Rig

CURATOR = 'test-paper-curator-token'
CURATOR_TWO = 'test-paper-curator-two-token'
VENUE = 'Fixture.cc/2026/Conference'
BODY = ('Mechanism A changes rollout mixing. Mechanism B changes data filtering. '
        'Table 1: A=0.4 B=0.5 A+B=0.7 under matched compute and data. '
        'The result holds only for the synthetic fixture setting.')


def pdf(text):
    """Small valid text PDF made without adding a dependency to RED collection."""
    lines = textwrap.wrap(text, width=80)
    operations = []
    for line in lines:
        escaped = line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        operations.append('(' + escaped + ') Tj T*')
    stream = ('BT /F1 9 Tf 12 TL 30 700 Td ' + ' '.join(operations) + ' ET').encode()
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream']
    output = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(str(i).encode() + b' 0 obj\n' + obj + b'\nendobj\n')
    start = len(output)
    output.extend(b'xref\n0 6\n0000000000 65535 f \n')
    for offset in offsets[1:]:
        output.extend(f'{offset:010d} 00000 n \n'.encode())
    output.extend(f'trailer << /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode())
    return bytes(output)


class Source:
    provider_version = 'synthetic-openreview-v2-fixture/1'
    def __init__(self):
        self.records, self.documents, self.calls, self.failures = {}, {}, [], {}
        self.active, self.peak = 0, 0
        self.lock = threading.Lock()
        for key in ('paper-a', 'paper-b'):
            self.add(key)

    def add(self, key, **changes):
        document = pdf(BODY + ' Record ' + key)
        self.documents[key] = document
        self.records[key] = dict(provider='openreview_v2', record_id=key, forum_id=key,
            title='Synthetic ' + key, authors=['Fixture Author'], venue_id=VENUE, year=2026, track='main',
            status='accepted', is_public=True, revision='v1', source_url='https://openreview.net/forum?id=' + key,
            pdf_locator=key, pdf_sha256=hashlib.sha256(document).hexdigest())
        self.records[key].update(changes)

    def get_record(self, record_id):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            self.calls.append(('record', record_id))
            time.sleep(.001)
            if self.failures.get(record_id, 0):
                self.failures[record_id] -= 1
                raise TimeoutError('fixture source temporarily unavailable')
            return deepcopy(self.records[record_id])
        finally:
            with self.lock:
                self.active -= 1

    def get_pdf(self, record):
        key = record['record_id']
        self.calls.append(('pdf', key))
        return self.documents[key]

    def discover(self, venue_id, cursor=None, limit=100):
        self.calls.append(('discover', cursor))
        keys = sorted(k for k, v in self.records.items() if v['venue_id'] == venue_id and v['status'] == 'accepted')
        start = int(cursor or 0)
        chosen = keys[start:start + limit]
        return {'items': [deepcopy(self.records[k]) for k in chosen],
                'next_cursor': str(start + limit) if start + limit < len(keys) else None}


class PaperRig(Rig):
    def __init__(self, root):
        self.source = Source()
        super().__init__(root)
        self.setup()
        self.principals.update({CURATOR: {'id': 'curator-a', 'role': 'curator'},
                                CURATOR_TWO: {'id': 'curator-b', 'role': 'curator'}})
        self.close()
        self.open()

    def open(self):
        super().open()
        self.service.paper_sources = {'openreview_v2': self.source}
        return self

    def policy(self, **updates):
        spec = dict(name='synthetic-accepted-main',
            venues=[dict(provider='openreview_v2', venue_id=VENUE, year=2026, track='main')],
            require_full_text=True, batch_size_limit=1000, max_parallel=4, max_pdf_bytes=1024*1024,
            source_timeout_seconds=5, retry_limit=3)
        spec.update(updates)
        return self.ok('paper.policy_register', spec, token=OPERATOR)

    def ingest(self, key='paper-a', policy=None, **updates):
        request = dict(policy_id=(policy or self.policy())['id'], provider='openreview_v2',
                       record_id=key, idempotency_key='ingest-' + key)
        request.update(updates)
        return self.ok('paper.ingest', request, token=CURATOR)

    def finish(self, paper):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            self.reconcile()
            self.clock.advance(5)
            result = self.ok('paper.show', {'id': paper['id']}, token=CURATOR)
            if result['state'] in {'ready', 'ineligible', 'failed', 'quarantine', 'needs_text', 'duplicate'}:
                return result
            time.sleep(.01)
        raise AssertionError('Paper ingestion did not finish')

    def paper(self, key='paper-a', **updates):
        result = self.finish(self.ingest(key, **updates))
        assert result['state'] == 'ready', result
        return result

    def extract(self, paper, mechanisms=None, token=CURATOR):
        return self.ok('paper.extract', {'paper_id': paper['id'], 'mechanisms': mechanisms or [mechanism()]}, token=token)

    def island(self, paper=None, item=None):
        extraction = self.extract(paper or self.paper(), [item or mechanism()])
        return self.ok('knowledge.create', {'extraction_id': extraction['id'], 'mechanism_key': (item or mechanism())['key']}, token=CURATOR)


def mechanism(key='mixing', intervention='sampling_mixture'):
    return dict(key=key, name='Synthetic mechanism ' + key,
        signature={'target': 'rollout_sampler', 'intervention': intervention,
                   'assumptions': ['editable_sampler'], 'invariant': 'unchanged_reward'},
        source_finding='Paper reports a scoped synthetic result', ai_interpretation='AI interpretation, not proof',
        transfer_hypothesis='Hypothesis to test locally', minimal_trial='Change only the intervention',
        falsifier='No improvement under matched controls', requirements=['editable_sampler'],
        variants={'greedy_fraction': .25}, limitations=['Synthetic setting only'],
        citations=[{'page': 1, 'quote': 'Mechanism A changes rollout mixing.', 'kind': 'body'}])
