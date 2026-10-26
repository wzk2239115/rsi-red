from copy import deepcopy

import pytest

from contracts.paper_library.support import CURATOR, mechanism
from tests.support import ALICE, OPERATOR


def test_one_paper_can_create_two_independent_islands_without_bridges(rig):
    paper = rig.paper()
    items = [mechanism(), mechanism('filtering', 'data_filtering')]
    extraction = rig.extract(paper, items)
    islands = [rig.ok('knowledge.create', {'extraction_id': extraction['id'], 'mechanism_key': m['key']}, token=CURATOR)
               for m in items]
    assert islands[0]['id'] != islands[1]['id']
    assert all(i['paper_ids'] == [paper['id']] for i in islands)
    assert rig.ok('knowledge.bridges', {})['items'] == []
    assert rig.cluster.submissions == []


@pytest.mark.parametrize('bad', ['missing_citation', 'invented_quote', 'wrong_page'])
def test_extraction_cannot_fabricate_body_evidence(rig, bad):
    paper = rig.paper()
    item = mechanism()
    if bad == 'missing_citation':
        item['citations'] = []
    elif bad == 'invented_quote':
        item['citations'][0]['quote'] = 'Never occurred in the frozen PDF'
    else:
        item['citations'][0]['page'] = 99
    rig.error('paper.extract', {'paper_id': paper['id'], 'mechanisms': [item]}, 'INVALID_CITATION', token=CURATOR)


def test_abstract_only_is_not_a_grounded_method(rig):
    rig.source.records['paper-a']['pdf_locator'] = None
    paper = rig.finish(rig.ingest())
    assert paper['state'] == 'needs_text'
    rig.error('paper.extract', {'paper_id': paper['id'], 'mechanisms': [mechanism()]}, 'FULL_TEXT_REQUIRED', token=CURATOR)


def test_paper_reported_does_not_become_local_validation(rig):
    island = rig.island()
    assert island['evidence_level'] == 'paper_reported'
    assert island['local_validation'] == 'not_tested'
    assert island['interpretation_status'] == 'curator_interpretation'
    assert island.get('campaign_id') is None
    paper = rig.paper('paper-b')
    item = mechanism()
    item['local_validation'] = 'validated_local'
    rig.error('paper.extract', {'paper_id': paper['id'], 'mechanisms': [item]}, 'UNVERIFIED_CLAIM', token=CURATOR)


def test_matching_mechanisms_merge_only_with_explicit_operator_review(rig):
    a = rig.island()
    b = rig.island(rig.paper('paper-b'))
    assert a['id'] != b['id']
    rig.error('knowledge.merge', {'ids': [a['id'], b['id']], 'rationale': 'same mechanism'}, 'FORBIDDEN', token=CURATOR)
    merged = rig.ok('knowledge.merge', {'ids': [a['id'], b['id']],
        'rationale': 'Targets, intervention, assumptions and invariant match in both cited methods'}, token=OPERATOR)
    assert set(merged['parent_ids']) == {a['id'], b['id']}
    assert set(merged['paper_ids']) == set(a['paper_ids'] + b['paper_ids'])
    assert merged['id'] not in {a['id'], b['id']}
    assert rig.ok('knowledge.bridges', {})['items'] == []


def test_same_topic_different_intervention_stays_separate(rig):
    a = rig.island()
    b = rig.island(rig.paper('paper-b'), mechanism('filtering', 'data_filtering'))
    rig.error('knowledge.merge', {'ids': [a['id'], b['id']], 'rationale': 'Both are RL papers'},
              'MECHANISM_MISMATCH', token=OPERATOR)


def test_same_intervention_different_critical_assumptions_stays_separate(rig):
    a = rig.island()
    item = mechanism()
    item['signature']['assumptions'] = ['teacher_required']
    b = rig.island(rig.paper('paper-b'), item)
    rig.error('knowledge.merge', {'ids': [a['id'], b['id']], 'rationale': 'Same title'},
              'MECHANISM_MISMATCH', token=OPERATOR)


def test_revision_keeps_old_content_and_negative_evidence(rig):
    a = rig.island()
    revised = rig.ok('knowledge.revise', {'id': a['id'], 'limitations': ['Fails outside fixture setting'],
        'ai_interpretation': 'A narrower interpretation'}, token=CURATOR)
    assert a['id'] in revised['parent_ids'] and a['digest'] != revised['digest']
    assert 'Fails outside fixture setting' in revised['limitations']
    assert 'Synthetic setting only' in revised['limitations']
    rig.close()
    rig.open()
    assert rig.ok('knowledge.show', {'id': a['id']})['digest'] == a['digest']


def test_training_researcher_reads_but_cannot_publish_paper_islands(rig):
    island = rig.island()
    assert rig.ok('knowledge.show', {'id': island['id']}, token=ALICE)['id'] == island['id']
    rig.error('knowledge.create', {'extraction_id': 'fake', 'mechanism_key': 'x'}, 'FORBIDDEN', token=ALICE)


def test_pack_keeps_claim_scope_citations_and_no_training_side_effects(rig):
    island = rig.island()
    pack = rig.ok('knowledge.pack', {'signals': ['rollout'], 'capabilities': ['editable_sampler'],
                                  'limit': 5, 'context_budget_chars': 4000})
    assert island['id'] in {c['id'] for c in pack['cards']}
    assert all(c['citations'] and c['minimal_trial'] and c['falsifier'] and c['limitations'] and
               c['evidence_level'] == 'paper_reported' and c['local_validation'] == 'not_tested' for c in pack['cards'])
    assert len(pack['context']) == pack['context_chars'] <= 4000
    assert rig.cluster.submissions == [] and rig.evaluator.calls == []


def test_pack_explains_missing_capability_and_honors_small_budget(rig):
    island = rig.island()
    excluded = rig.ok('knowledge.pack', {'signals': ['rollout'], 'capabilities': [], 'limit': 5, 'context_budget_chars': 4000})
    assert island['id'] not in {c['id'] for c in excluded['cards']}
    assert any(x['id'] == island['id'] and x['reason'] == 'missing_capability' for x in excluded['excluded'])
    bounded = rig.ok('knowledge.pack', {'signals': ['rollout'], 'capabilities': ['editable_sampler'],
                                     'limit': 5, 'context_budget_chars': 120})
    assert len(bounded['context']) == bounded['context_chars'] <= 120


def test_withdrawal_excludes_default_pack_but_keeps_history(rig):
    island = rig.island()
    rig.source.records['paper-a']['status'] = 'withdrawn'
    rig.ok('paper.recheck', {'id': island['paper_ids'][0]}, token=CURATOR)
    rig.reconcile()
    pack = rig.ok('knowledge.pack', {'signals': ['rollout'], 'capabilities': ['editable_sampler'],
                                  'limit': 5, 'context_budget_chars': 4000})
    assert island['id'] not in {c['id'] for c in pack['cards']}
    old = rig.ok('knowledge.show', {'id': island['id']})
    assert old['digest'] == island['digest'] and old['warnings']


def test_even_operator_cannot_publish_held_out_as_paper_evidence(rig):
    paper = rig.paper()
    protocol = deepcopy(rig.ok('protocol.show', {'id': rig.protocol}, token=OPERATOR)['spec'])
    protocol['visibility'] = 'held_out'
    hidden = rig.ok('protocol.register', protocol, token=OPERATOR)
    item = mechanism()
    item['citations'] = [{'kind': 'protocol', 'id': hidden['id']}]
    rig.error('paper.extract', {'paper_id': paper['id'], 'mechanisms': [item]}, 'PROTECTED_EVIDENCE', token=OPERATOR)


@pytest.mark.parametrize('field', ['target', 'intervention', 'invariant'])
def test_atomic_mechanism_requires_specific_signature(rig, field):
    paper = rig.paper()
    item = mechanism()
    item['signature'].pop(field)
    rig.error('paper.extract', {'paper_id': paper['id'], 'mechanisms': [item]}, 'INVALID_REQUEST', token=CURATOR)
