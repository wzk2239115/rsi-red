"""Installed-wheel PDF worker and literature loop; synthetic external I/O only."""
import hashlib
import io
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from rsi_red.evaluation import UnconfiguredEvaluator
from rsi_red.schedulers.local import LocalScheduler
from rsi_red.service import ResearchService

writer = PdfWriter()
page = writer.add_blank_page(width=600, height=800)
font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
                         NameObject('/BaseFont'): NameObject('/Helvetica')})
page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
stream = DecodedStreamObject()
stream.set_data(b'BT /F1 12 Tf 20 700 Td (Synthetic mechanism changes sampling.) Tj ET')
page[NameObject('/Contents')] = writer._add_object(stream)
out = io.BytesIO()
writer.write(out)
body = out.getvalue()


class Source:
    provider_version = 'installed-wheel-synthetic/1'
    def get_record(self, key):
        return {'provider': 'openreview_v2', 'record_id': key, 'forum_id': key, 'title': 'SYNTHETIC WHEEL FIXTURE',
                'authors': ['Fixture'], 'venue_id': 'Fixture/2026/Conference', 'year': 2026, 'track': 'main',
                'is_public': True, 'status': 'accepted', 'revision': 'v1', 'pdf_locator': key,
                'source_url': 'https://example.org/fixture', 'pdf_sha256': hashlib.sha256(body).hexdigest()}
    def get_pdf(self, record):
        return body


root = Path('wheel-papers').resolve()
service = ResearchService(root=root / 'state', scheduler=LocalScheduler(root=root / 'jobs', allow_cpu_only=True),
                          evaluator=UnconfiguredEvaluator(), principals={'operator': {'id': 'operator', 'role': 'operator'},
                                                                        'curator': {'id': 'curator', 'role': 'curator'}})
service.paper_sources = {'openreview_v2': Source()}


def request(op, p, token='curator'):
    response = service.dispatch(token=token, operation=op, payload=p)
    assert response['error'] is None, response
    return response['data']


try:
    policy = request('paper.policy_register', {'name': 'Wheel fixture', 'venues': [{'provider': 'openreview_v2',
          'venue_id': 'Fixture/2026/Conference', 'year': 2026, 'track': 'main'}], 'require_full_text': True,
          'batch_size_limit': 1000, 'max_parallel': 4, 'max_pdf_bytes': 1048576, 'source_timeout_seconds': 5, 'retry_limit': 1}, 'operator')
    queued = request('paper.ingest', {'policy_id': policy['id'], 'provider': 'openreview_v2', 'record_id': 'wheel', 'idempotency_key': 'wheel'})
    service.reconcile_papers()
    paper = request('paper.show', {'id': queued['id']})
    assert paper['state'] == 'ready', paper
    document = request('paper.document', {'id': paper['id']})
    assert 'Synthetic mechanism changes sampling.' in document['pages'][0]['text']
    mechanism = {'key': 'sampling', 'name': 'Synthetic sampling', 'signature': {'target': 'sampler', 'intervention': 'mix',
        'assumptions': ['editable_sampler'], 'invariant': 'reward'}, 'source_finding': 'Synthetic scoped finding',
        'ai_interpretation': 'Interpretation only', 'transfer_hypothesis': 'Requires experiment', 'minimal_trial': 'Change sampling only',
        'falsifier': 'No matched improvement', 'requirements': ['editable_sampler'], 'variants': {}, 'limitations': ['Synthetic only'],
        'citations': [{'page': 1, 'kind': 'body', 'quote': 'Synthetic mechanism changes sampling.'}]}
    extraction = request('paper.extract', {'paper_id': paper['id'], 'mechanisms': [mechanism]})
    island = request('knowledge.create', {'extraction_id': extraction['id'], 'mechanism_key': 'sampling'})
    pack = request('knowledge.pack', {'capabilities': ['editable_sampler'], 'context_budget_chars': 8000})
    assert [c['id'] for c in pack['cards']] == [island['id']]
    assert request('knowledge.bridges', {})['items'] == []
    assert service.store.list('job') == service.store.list('eval') == []
    print('Installed wheel: frozen PDF, isolated parser, grounded island and bounded pack passed (synthetic CPU).')
finally:
    service.close()
