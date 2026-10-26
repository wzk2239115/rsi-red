"""Implementation-phase contracts for scoped relations, long evidence and API views."""
from copy import deepcopy
import hashlib
import json
import threading
from urllib.request import urlopen

import pytest

from contracts.paper_library.support import CURATOR, mechanism, pdf
from contracts.paper_library.test_relations import relationship
from rsi_red.kanban import make_server
from tests.support import ALICE, OPERATOR


def test_table_caption_and_page_bounds_are_grounded(rig):
    paper = rig.paper()
    item = mechanism()
    item['citations'] = [{'page': 1, 'kind': 'table', 'label': 'Table 99',
                         'quote': 'Mechanism A changes rollout mixing.', 'bbox': [0, 0, 2000, 20]}]
    rig.error('paper.extract', {'paper_id': paper['id'], 'mechanisms': [item]}, 'INVALID_CITATION', token=CURATOR)
    item['citations'] = [{'page': 1, 'kind': 'table', 'label': 'Table 1',
                         'quote': 'Table 1: A=0.4 B=0.5 A+B=0.7 under matched compute and data.',
                         'caption': 'Table 1:', 'bbox': [0, 0, 600, 800]}]
    assert rig.extract(paper, [item])['mechanisms'][0]['citations'] == item['citations']


def test_long_interpretation_is_not_silently_truncated_to_fit_pack(rig):
    item = mechanism()
    item['ai_interpretation'] = 'Long scoped interpretation. ' * 1000
    island = rig.island(item=item)
    pack = rig.ok('knowledge.pack', {'capabilities': ['editable_sampler'], 'context_budget_chars': 3000})
    assert pack['cards'] == [] and len(pack['context']) <= 3000
    assert {'id': island['id'], 'reason': 'context_budget'} in pack['excluded']


def test_transfer_requires_identifiable_target_and_source(rig):
    payload = relationship(rig)
    payload['relation'] = 'transfer'
    payload['experiment'].pop('ablation')
    payload['experiment']['baselines'] = [{'id': 'target', 'score': .5}]
    payload['experiment']['treatment'] = {'id': 'target+source', 'score': .7}
    rig.error('paper.relationship_evidence', payload, 'INSUFFICIENT_BRIDGE_EVIDENCE', token=CURATOR)
    payload['experiment'].update(source_method='rollout mixing', target_setting='synthetic filtering')
    evidence = rig.ok('paper.relationship_evidence', payload, token=CURATOR)
    rig.ok('paper.review_relationship', {'id': evidence['id'], 'decision': 'supported', 'rationale': 'Only the cited fixture scope'}, token=OPERATOR)
    assert rig.ok('knowledge.bridge_register', {'evidence_id': evidence['id']}, token=CURATOR)['relation'] == 'transfer'


def test_contrary_review_suspends_but_does_not_destroy_old_receipt(rig):
    evidence = rig.ok('paper.relationship_evidence', relationship(rig), token=CURATOR)
    supported = rig.ok('paper.review_relationship', {'id': evidence['id'], 'decision': 'supported', 'rationale': 'Scoped'}, token=OPERATOR)
    bridge = rig.ok('knowledge.bridge_register', {'evidence_id': evidence['id']}, token=CURATOR)
    rig.ok('paper.review_relationship', {'id': evidence['id'], 'decision': 'contradicted', 'rationale': 'New contrary inspection'}, token=OPERATOR)
    rig.close()
    rig.open()
    assert rig.ok('knowledge.bridges', {})['items'] == []
    old = rig.ok('knowledge.bridges', {'include_suspended': True}, token=OPERATOR)['items'][0]
    assert old['id'] == bridge['id'] and old['review_id'] == supported['id'] and old['state'] == 'suspended'


def test_multisource_merge_keeps_valid_support_and_invalid_source_warning(rig):
    a, b = rig.island(), rig.island(rig.paper('paper-b'))
    merged = rig.ok('knowledge.merge', {'ids': [a['id'], b['id']], 'rationale': 'Explicit same mechanism'}, token=OPERATOR)
    rig.source.records['paper-a']['status'] = 'withdrawn'
    rig.ok('paper.recheck', {'id': a['paper_ids'][0]}, token=CURATOR)
    rig.close()
    rig.open()
    rig.reconcile()
    view = rig.ok('knowledge.show', {'id': merged['id']})
    assert view['eligible'] and view['warnings'] and view['digest'] == merged['digest']
    pack = rig.ok('knowledge.pack', {'capabilities': ['editable_sampler'], 'context_budget_chars': 20000})
    assert merged['id'] in {c['id'] for c in pack['cards']}


def test_recheck_new_official_revision_does_not_revalidate_old_content(rig):
    paper = rig.paper()
    rig.source.records['paper-a']['revision'] = 'new-version'
    body = pdf('Completely revised findings, not the frozen mechanism.')
    rig.source.documents['paper-a'] = body
    rig.source.records['paper-a']['pdf_sha256'] = hashlib.sha256(body).hexdigest()
    rig.ok('paper.recheck', {'id': paper['id']}, token=CURATOR)
    rig.reconcile()
    view = rig.ok('paper.show', {'id': paper['id']}, token=CURATOR)
    assert view['revision'] == paper['revision']
    assert view['acceptance']['status'] != 'verified'


@pytest.mark.parametrize('token', [ALICE, CURATOR, OPERATOR])
def test_readonly_kanban_library_http_preserves_roles_and_has_no_training_effect(rig, token):
    island = rig.island()
    server = make_server(port=0, demo=False, endpoint='unused', token=token)
    # Only replace network transport; real dispatch/permissions/storage/projection run.
    import rsi_red.kanban as module
    original = module.call
    module.call = lambda endpoint, credential, operation, payload, timeout: rig.call(operation, payload, token=credential)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    before = deepcopy(rig.ok('protocol.show', {'id': rig.protocol}, token=OPERATOR))
    try:
        with urlopen(f'http://127.0.0.1:{server.server_port}/api/library') as response:
            report = json.load(response)
        assert report['kind'] == 'paper_mechanism' and report['bridges'] == []
        assert island['id'] in {x['id'] for x in report['islands']}
        assert all(x['local_validation'] == 'not_tested' for x in report['islands'])
        assert 'owner' not in json.dumps(report)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)
        module.call = original
    assert rig.cluster.submissions == [] and rig.evaluator.calls == []
    assert rig.ok('protocol.show', {'id': rig.protocol}, token=OPERATOR) == before


def test_repeated_recheck_requests_do_not_reset_inflight_retry_budget(rig):
    paper = rig.paper()
    rig.source.failures['paper-a'] = 100
    rig.ok('paper.recheck', {'id': paper['id']}, token=CURATOR)
    rig.reconcile()
    attempts = rig.ok('paper.show', {'id': paper['id']}, token=CURATOR)['recheck_attempts']
    rig.ok('paper.recheck', {'id': paper['id']}, token=CURATOR)
    assert rig.ok('paper.show', {'id': paper['id']}, token=CURATOR)['recheck_attempts'] == attempts


def test_restart_after_attempt_reserved_cannot_exceed_total_budget(rig):
    queued = rig.ingest()
    with rig.service.store.transaction():
        paper = rig.service.store.get(queued['id'], 'paper')
        paper['attempts'] = 4  # crash after final attempt was durably reserved, before response committed
        rig.service.store.save('paper', paper)
    rig.close()
    rig.open()
    rig.reconcile()
    result = rig.ok('paper.show', {'id': queued['id']}, token=CURATOR)
    assert result['state'] == 'failed' and result['attempts'] == 4
    assert rig.source.calls == []


def test_concurrent_recheck_yields_database_and_runs_one_fetch(rig):
    paper = rig.paper()
    rig.ok('paper.recheck', {'id': paper['id']}, token=CURATOR)
    entered, release = threading.Event(), threading.Event()
    original = rig.source.get_record
    def slow_record(record_id):
        entered.set()
        assert release.wait(5)
        return original(record_id)
    rig.source.get_record = slow_record
    worker = threading.Thread(target=rig.service.reconcile_papers)
    worker.start()
    try:
        assert entered.wait(5)
        # These requests would deadlock if I/O held the metadata lock.
        assert rig.ok('knowledge.bridges', {})['items'] == []
        rig.ok('paper.recheck', {'id': paper['id']}, token=CURATOR)
        rig.service.reconcile_papers()  # overlapping tick must yield, not duplicate work
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    view = rig.ok('paper.show', {'id': paper['id']}, token=CURATOR)
    assert view['acceptance']['status'] == 'verified' and view['recheck_attempts'] == 1


@pytest.mark.parametrize('operation,payload,token', [
    ('knowledge.list', {'query': 123}, ALICE),
    ('paper.batch_submit', {'policy_id': None, 'idempotency_key': 'malformed', 'catalog': []}, CURATOR),
    ('paper.policy_register', {'name': 'bad', 'venues': [123]}, OPERATOR),
])
def test_malformed_library_shapes_return_structured_error(rig, operation, payload, token):
    if operation == 'paper.batch_submit':
        payload = dict(payload, policy_id=rig.policy()['id'])
    rig.error(operation, payload, 'INVALID_REQUEST', token=token)
