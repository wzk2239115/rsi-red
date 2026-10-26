import pytest

from contracts.paper_library.support import CURATOR, mechanism
from tests.support import OPERATOR


def relationship(r):
    paper = r.paper()
    extraction = r.extract(paper, [mechanism(), mechanism('filtering', 'data_filtering')])
    islands = [r.ok('knowledge.create', {'extraction_id': extraction['id'], 'mechanism_key': key}, token=CURATOR)
               for key in ('mixing', 'filtering')]
    return {'paper_id': paper['id'], 'source_island_id': islands[0]['id'], 'target_island_id': islands[1]['id'],
        'relation': 'composition', 'scope': 'Synthetic fixture setting only', 'limitations': ['uncertainty_not_reported'],
        'experiment': {'baselines': [{'id': 'a', 'score': .4}, {'id': 'b', 'score': .5}],
            'treatment': {'id': 'a+b', 'score': .7}, 'metric': 'accuracy', 'reported_metric_direction': 'maximize',
            'controls': {'data': 'same', 'compute': 'matched', 'model': 'same', 'evaluation': 'same'},
            'ablation': {'removed': 'a', 'result_id': 'b'}, 'uncertainty': {'reported': False},
            'citations': [{'page': 1, 'kind': 'table', 'label': 'Table 1',
                          'quote': 'Table 1: A=0.4 B=0.5 A+B=0.7 under matched compute and data.'}]}}


def test_full_paper_evidence_still_does_not_create_edge_until_review(rig):
    payload = relationship(rig)
    evidence = rig.ok('paper.relationship_evidence', payload, token=CURATOR)
    assert rig.ok('knowledge.bridges', {})['items'] == []
    rig.error('knowledge.bridge_register', {'evidence_id': evidence['id']}, 'INSUFFICIENT_BRIDGE_EVIDENCE', token=CURATOR)


@pytest.mark.parametrize('missing', ['baselines', 'controls', 'citations', 'ablation'])
def test_mentions_and_uncontrolled_results_cannot_be_bridges(rig, missing):
    payload = relationship(rig)
    payload['experiment'].pop(missing)
    rig.error('paper.relationship_evidence', payload, 'INSUFFICIENT_BRIDGE_EVIDENCE', token=CURATOR)
    assert rig.ok('knowledge.bridges', {})['items'] == []


def test_curator_cannot_self_approve(rig):
    evidence = rig.ok('paper.relationship_evidence', relationship(rig), token=CURATOR)
    rig.error('paper.review_relationship', {'id': evidence['id'], 'decision': 'supported', 'rationale': 'I think so'},
              'FORBIDDEN', token=CURATOR)


def test_operator_cannot_review_own_evidence(rig):
    evidence = rig.ok('paper.relationship_evidence', relationship(rig), token=OPERATOR)
    rig.error('paper.review_relationship', {'id': evidence['id'], 'decision': 'supported', 'rationale': 'Self approved'},
              'FORBIDDEN', token=OPERATOR)


def test_supported_edge_is_scoped_to_paper_and_never_local_validation(rig):
    evidence = rig.ok('paper.relationship_evidence', relationship(rig), token=CURATOR)
    review = rig.ok('paper.review_relationship', {'id': evidence['id'], 'decision': 'supported',
        'rationale': 'Frozen Table 1 controls and ablation support the stated synthetic scope only'}, token=OPERATOR)
    bridge = rig.ok('knowledge.bridge_register', {'evidence_id': evidence['id']}, token=CURATOR)
    assert bridge['review_id'] == review['id']
    assert bridge['evidence_level'] == 'paper_reported' and bridge['local_validation'] == 'not_tested'
    assert bridge['scope'] == 'Synthetic fixture setting only'
    assert 'uncertainty_not_reported' in bridge['limitations']
    assert rig.ok('knowledge.bridge_register', {'evidence_id': evidence['id']}, token=CURATOR)['id'] == bridge['id']
    assert len(rig.ok('knowledge.bridges', {})['items']) == 1
    assert rig.cluster.submissions == [] and rig.evaluator.calls == []


def test_negative_result_cannot_be_promoted_by_review_text(rig):
    payload = relationship(rig)
    payload['experiment']['treatment']['score'] = .3
    evidence = rig.ok('paper.relationship_evidence', payload, token=CURATOR)
    rig.error('paper.review_relationship', {'id': evidence['id'], 'decision': 'supported',
              'rationale': 'Ignore negative scores'}, 'INSUFFICIENT_BRIDGE_EVIDENCE', token=OPERATOR)


def test_withdrawal_suspends_edge_and_keeps_historical_receipt(rig):
    payload = relationship(rig)
    evidence = rig.ok('paper.relationship_evidence', payload, token=CURATOR)
    rig.ok('paper.review_relationship', {'id': evidence['id'], 'decision': 'supported', 'rationale': 'Scoped support'}, token=OPERATOR)
    bridge = rig.ok('knowledge.bridge_register', {'evidence_id': evidence['id']}, token=CURATOR)
    rig.source.records['paper-a']['status'] = 'withdrawn'
    rig.ok('paper.recheck', {'id': payload['paper_id']}, token=CURATOR)
    rig.reconcile()
    assert rig.ok('knowledge.bridges', {})['items'] == []
    historical = rig.ok('knowledge.bridges', {'include_suspended': True}, token=OPERATOR)['items']
    assert any(b['id'] == bridge['id'] and b['state'] == 'suspended' for b in historical)
