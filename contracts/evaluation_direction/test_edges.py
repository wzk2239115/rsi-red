"""Direction boundary cases, added before implementation."""
from copy import deepcopy

import pytest

from contracts.evaluation_direction.test_contract import (
    authorize, bind_campaign, evaluate, metadata, predictions, register,
)
from rsi_red.errors import ResearchError
from rsi_red.evaluation import summarize
from tests.support import OPERATOR


@pytest.mark.parametrize('value', [-.1, 1.1, float('nan'), float('inf'), True])
def test_raw_score_is_never_clamped_or_reinterpreted(value):
    protocol = {'spec': {'items': [dict(id='q1', task='math', **metadata()['math']),
                                  dict(id='q2', task='logic', **metadata()['logic'])]}}
    with pytest.raises(ResearchError, match='Score'):
        summarize(predictions(value, .5), protocol)


def test_evaluator_cannot_supply_its_own_quality():
    protocol = {'spec': {'items': [dict(id='q1', task='math', **metadata()['math']),
                                  dict(id='q2', task='logic', **metadata()['logic'])]}}
    rows = predictions(.8, .2)
    for row in rows:
        row['normalized_score'] = 1
    result = summarize(rows, protocol)
    assert result['normalized_score'] == pytest.approx(.2)
    assert rows[0]['score'] == .8


@pytest.mark.parametrize('field,value', [('metric', 'other'), ('role', 'judge')])
def test_same_task_annotation_conflict_rejected(rig, field, value):
    from contracts.evaluation_direction.test_contract import mixed_spec
    spec = mixed_spec(rig)
    extra = dict(spec['items'][0], id='q3')
    extra[field] = value
    spec['items'].append(extra)
    rig.error('protocol.register', spec, 'INVALID_REQUEST', token=OPERATOR)


@pytest.mark.parametrize('extra', [{'human_authorized': True}, {'grant_all': True}])
def test_authorization_rejects_unknown_fields(rig, extra):
    rig.error('direction.authorize', dict(tasks=metadata(), source_protocol_digest=None,
        goal='明确授权测试方向', **extra), 'INVALID_REQUEST', token=OPERATOR)


@pytest.mark.parametrize('patch', [{'sampling': {'max_tokens': 999}}, {'items': []},
                                 {'task_overrides': {'unknown': {'direction': 'maximize'}}}])
def test_derive_cannot_change_grader_or_invent_tasks(rig, patch):
    source = register(rig)
    grant = authorize(rig, source=source['digest'])
    payload = dict(id=source['id'], direction_authorization_id=grant['id'], task_overrides={})
    payload.update(patch)
    rig.error('protocol.derive', payload, 'INVALID_REQUEST', token=OPERATOR)


def test_derived_protocol_is_durable_and_cannot_be_compared_as_same_goal(rig):
    source = register(rig)
    a = evaluate(rig, source['id'], .2, .8)
    target = metadata()
    target['math']['direction'] = 'maximize'
    grant = authorize(rig, tasks=target, source=source['digest'])
    new = rig.ok('protocol.derive', {'id': source['id'], 'direction_authorization_id': grant['id'],
        'task_overrides': {'math': {'direction': 'maximize'}}}, token=OPERATOR)
    rig.close()
    rig.open()
    assert rig.ok('protocol.show', {'id': new['id']}, token=OPERATOR) == new
    b = evaluate(rig, new['id'], .2, .8)
    rig.error('eval.compare', {'left': a['id'], 'right': b['id']}, 'PROTOCOL_MISMATCH')


def test_legacy_history_readable_but_new_eval_and_selection_require_direction(rig):
    old = rig.evaluate()
    with rig.service.store.transaction():
        protocol = rig.service.store.get(rig.protocol, 'protocol')
        protocol['spec'].pop('direction', None)
        protocol['spec'].pop('direction_authorization_id', None)
        for item in protocol['spec']['items']:
            item.pop('direction', None)
        rig.service.store.save('protocol', protocol)
        record = rig.service.store.get(old['id'], 'eval')
        for key in ('task_metrics', 'normalization', 'normalized_score', 'normalized_task_scores'):
            record.pop(key, None)
        rig.service.store.save('eval', record)
    rig.close()
    rig.open()
    shown = rig.ok('protocol.show', {'id': rig.protocol})
    assert shown['direction_status'] == 'legacy_unconfigured'
    assert rig.ok('eval.show', {'id': old['id']})['score'] == old['score']
    rig.error('eval.submit', {'campaign_id': rig.campaign, 'model_id': rig.base,
        'protocol_id': rig.protocol}, 'DIRECTION_UNCONFIGURED')
    rig.error('campaign.select', {'id': rig.campaign}, 'DIRECTION_UNCONFIGURED')


def test_repeat_mean_can_lose_to_stable_candidate_and_ties_are_deterministic(rig):
    protocol = register(rig)['id']
    bind_campaign(rig, protocol)
    a = rig.base
    b = rig.model('stable')
    evaluate(rig, protocol, 0, 1, model=a)
    evaluate(rig, protocol, 1, 0, model=a)
    evaluate(rig, protocol, .3, .7, model=b)
    assert rig.ok('campaign.select', {'id': rig.campaign})['model_id'] == b
    evaluate(rig, protocol, .7, .3, model=b)
    assert rig.ok('campaign.select', {'id': rig.campaign})['model_id'] == min(a, b)


def test_selection_requires_evidence_from_campaign_protocol(rig):
    protocol = register(rig)['id']
    bind_campaign(rig, protocol)
    evaluate(rig, rig.protocol, 0, 1)
    rig.error('campaign.select', {'id': rig.campaign}, 'NO_ELIGIBLE_CANDIDATE')


def test_minimize_does_not_break_raw_grader_audit_and_select_passed_candidate(rig):
    protocol = register(rig)['id']
    bind_campaign(rig, protocol)
    rig.principals['auditor-test'] = {'id': 'auditor', 'role': 'auditor'}
    rig.close()
    rig.open()
    policy = rig.ok('audit.configure', {'campaign_id': rig.campaign, 'protocol_id': protocol,
        'auditor_ids': ['auditor'], 'checks': ['grader_consistency'], 'grader_mode': 'exact_match'},
        token=OPERATOR)
    result = evaluate(rig, protocol, 1, 1)
    assert result['task_scores']['math'] == 0
    case = rig.ok('audit.submit', {'campaign_id': rig.campaign, 'model_id': rig.base,
        'eval_id': result['id'], 'policy_id': policy['id'], 'idempotency_key': 'raw-grading'})
    rig.reconcile()
    assert rig.ok('audit.show', {'id': case['id']})['state'] == 'checks_passed'
    assert rig.ok('campaign.select', {'id': rig.campaign})['model_id'] == rig.base
    assert rig.ok('campaign.submit', {'id': rig.campaign, 'model_id': rig.base})['model_id'] == rig.base


def test_hidden_eval_list_and_dashboard_never_disclose_hidden_score(rig):
    source = register(rig)
    spec = deepcopy(source['spec'])
    spec['visibility'] = 'held_out'
    hidden = rig.ok('protocol.register', spec, token=OPERATOR)
    pending = rig.ok('eval.submit', {'campaign_id': rig.campaign, 'model_id': rig.base,
        'protocol_id': hidden['id']}, token=OPERATOR)
    rig.reconcile()
    assert pending['id'] not in {e['id'] for e in rig.ok('eval.list', {'campaign_id': rig.campaign})['items']}
