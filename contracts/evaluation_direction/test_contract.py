"""Human-authorized objective contracts. External scores are CPU fixtures, not inference."""
from copy import deepcopy
import json

import pytest

from rsi_red.evaluation import summarize
from rsi_red.kanban import snapshot
from tests.support import ALICE, OPERATOR, OUTSIDER


def mixed_spec(r):
    spec = deepcopy(r.ok('protocol.show', {'id': r.protocol}, token=OPERATOR)['spec'])
    spec.pop('direction', None)
    spec.pop('direction_authorization_id', None)
    spec.update(name='human-configured-mixed')
    for item, meta in zip(spec['items'], metadata().values(), strict=True):
        item.update(meta)
    return spec


def metadata():
    return {'math': {'direction': 'minimize', 'metric': 'asr', 'role': 'policy'},
            'logic': {'direction': 'maximize', 'metric': 'auroc', 'role': 'judge'}}


def authorize(r, *, tasks=None, source=None):
    return r.ok('direction.authorize', {'tasks': tasks or metadata(),
        'source_protocol_digest': source,
        'goal': '本人指定：math 的 ASR 降低，logic 的 AUROC 提高。'}, token=OPERATOR)


def register(r):
    spec = mixed_spec(r)
    grant = authorize(r)
    spec['direction_authorization_id'] = grant['id']
    return r.ok('protocol.register', spec, token=OPERATOR)


def predictions(asr, auroc):
    return [{'id': 'q1', 'task': 'math', 'answer': '2', 'score': asr, 'finish_reason': 'stop'},
            {'id': 'q2', 'task': 'logic', 'answer': 'true', 'score': auroc, 'finish_reason': 'stop'}]


def evaluate(r, protocol, asr, auroc, *, model=None):
    r.evaluator.evaluate = lambda *_: {'items': predictions(asr, auroc)}
    return r.evaluate(model=model, protocol=protocol)


def bind_campaign(r, protocol):
    r.campaign = r.ok('campaign.create', {'name': 'authorized-objective', 'members': ['alice', 'bob'],
        'gpu_hours_budget': 4, 'protocol_id': protocol, 'require_decontamination': False},
        token=OPERATOR)['id']
    r.base = r.model('direction-base')


def test_missing_direction_is_rejected_without_guessing(rig):
    spec = mixed_spec(rig)
    for item in spec['items']:
        item.pop('direction')
    rig.error('protocol.register', spec, 'INVALID_REQUEST', token=OPERATOR)


@pytest.mark.parametrize('bad', ['increase', '', None, True])
def test_invalid_direction_is_rejected(rig, bad):
    spec = mixed_spec(rig)
    spec['items'][0]['direction'] = bad
    rig.error('protocol.register', spec, 'INVALID_REQUEST', token=OPERATOR)


@pytest.mark.parametrize('field,value', [('role', 'attacker'), ('metric', ''), ('metric', 42)])
def test_invalid_annotation_is_rejected(rig, field, value):
    spec = mixed_spec(rig)
    spec['items'][0][field] = value
    rig.error('protocol.register', spec, 'INVALID_REQUEST', token=OPERATOR)


def test_same_task_cannot_contain_opposite_goals(rig):
    spec = mixed_spec(rig)
    spec['items'][1]['task'] = 'math'
    rig.error('protocol.register', spec, 'INVALID_REQUEST', token=OPERATOR)


def test_explicit_direction_still_requires_human_authorization(rig):
    rig.error('protocol.register', mixed_spec(rig), 'DIRECTION_AUTHORIZATION_REQUIRED', token=OPERATOR)


@pytest.mark.parametrize('role', ['researcher', 'auditor'])
def test_agent_cannot_authorize_by_asserting_human_approval(rig, role):
    token = ALICE
    if role == 'auditor':
        token = 'direction-auditor-fixture'
        rig.principals[token] = {'id': 'auditor', 'role': 'auditor'}
        rig.close()
        rig.open()
    rig.error('direction.authorize', {'tasks': metadata(), 'goal': 'human approved',
        'source_protocol_digest': None, 'human_authorized': True}, 'FORBIDDEN', token=token)
    assert rig.cluster.submissions == []


def test_human_authorization_is_durable_and_precisely_bound(rig):
    grant = authorize(rig)
    assert grant['tasks'] == metadata()
    assert grant['source_protocol_digest'] is None
    assert grant['authorized_by'] == 'operator'
    assert grant['authorized_at'] == rig.clock()
    assert grant['digest']
    rig.close()
    rig.open()
    spec = mixed_spec(rig)
    spec['direction_authorization_id'] = grant['id']
    result = rig.ok('protocol.register', spec, token=OPERATOR)
    assert result['spec']['direction_authorization_id'] == grant['id']


@pytest.mark.parametrize('change', ['direction', 'metric', 'extra_task'])
def test_authorization_cannot_be_repurposed(rig, change):
    spec = mixed_spec(rig)
    spec['direction_authorization_id'] = authorize(rig)['id']
    if change == 'extra_task':
        spec['items'].append({'id': 'q3', 'task': 'extra', 'prompt': 'private', 'answer': 'private',
                              'direction': 'maximize'})
    else:
        spec['items'][0][change] = 'maximize' if change == 'direction' else 'accuracy'
    rig.error('protocol.register', spec, 'DIRECTION_AUTHORIZATION_MISMATCH', token=OPERATOR)


def test_explicit_protocol_default_and_item_override_resolve_consistently(rig):
    spec = mixed_spec(rig)
    spec['direction'] = 'maximize'
    spec['items'][1].pop('direction')
    spec['direction_authorization_id'] = authorize(rig)['id']
    protocol = rig.ok('protocol.register', spec, token=OPERATOR)
    shown = rig.ok('protocol.show', {'id': protocol['id']})
    assert shown['spec']['task_metrics'] == metadata()


def test_mixed_quality_preserves_raw_and_improves_for_both_human_goals():
    protocol = {'spec': {'items': [dict(id='q1', task='math', **metadata()['math']),
                                  dict(id='q2', task='logic', **metadata()['logic'])]}}
    before = summarize(predictions(.6, .6), protocol)
    after = summarize(predictions(.2, .8), protocol)
    assert before['score'] == pytest.approx(.5)
    assert after['score'] == pytest.approx(.8)
    assert after['raw_task_scores'] == {'math': .2, 'logic': .8}
    assert after['raw_score'] == pytest.approx(.5)
    assert after['normalized_score'] == after['score']
    assert after['normalized_task_scores'] == after['task_scores']
    assert after['normalization'] == 'bounded-complement-v1'


def test_asr_increase_is_regression_when_human_authorized_minimize():
    protocol = {'spec': {'items': [dict(id='q1', task='math', **metadata()['math']),
                                  dict(id='q2', task='logic', **metadata()['logic'])]}}
    good = summarize(predictions(.2, .8), protocol)
    bad = summarize(predictions(.6, .8), protocol)
    assert bad['score'] < good['score']


def test_human_can_reverse_benchmark_convention_without_changing_raw_grader():
    protocol = {'spec': {'items': [dict(id='q1', task='math', **metadata()['math']),
                                  dict(id='q2', task='logic', **metadata()['logic'])]}}
    raw = predictions(.2, .8)
    original = deepcopy(raw)
    lower = summarize(raw, protocol)
    protocol['spec']['items'][0]['direction'] = 'maximize'
    higher = summarize(raw, protocol)
    assert lower['score'] == pytest.approx(.8)
    assert higher['score'] == pytest.approx(.5)
    assert raw == original
    assert lower['raw_task_scores'] == higher['raw_task_scores']


def test_task_mean_is_equal_task_weight_not_equal_item_weight():
    rows = predictions(.2, .4)
    specs = [dict(id='q1', task='math', **metadata()['math']),
             dict(id='q2', task='logic', **metadata()['logic'])]
    for index in range(3, 7):
        specs.append(dict(id=f'q{index}', task='math', **metadata()['math']))
        rows.append(dict(rows[0], id=f'q{index}'))
    result = summarize(rows, {'spec': {'items': specs}})
    assert result['score'] == pytest.approx(.6)


def test_derive_needs_exact_new_human_grant_and_preserves_source(rig):
    source = register(rig)
    target = metadata()
    target['math']['direction'] = 'maximize'
    grant = authorize(rig, tasks=target, source=source['digest'])
    payload = {'id': source['id'], 'direction_authorization_id': grant['id'],
               'task_overrides': {'math': {'direction': 'maximize'}}}
    rig.error('protocol.derive', payload, 'FORBIDDEN')
    derived = rig.ok('protocol.derive', payload, token=OPERATOR)
    assert derived['id'] != source['id']
    assert derived['digest'] != source['digest']
    assert derived['source_protocol_id'] == source['id']
    assert derived['source_protocol_digest'] == source['digest']
    assert rig.ok('protocol.show', {'id': source['id']}, token=OPERATOR) == source
    assert derived['spec']['sampling'] == source['spec']['sampling']
    assert derived['spec']['evaluator_digest'] == source['spec']['evaluator_digest']


def test_source_bound_grant_cannot_authorize_unrelated_protocol(rig):
    source = register(rig)
    grant = authorize(rig, source='sha256:' + 'f' * 64)
    rig.error('protocol.derive', {'id': source['id'], 'direction_authorization_id': grant['id'],
        'task_overrides': {}}, 'DIRECTION_AUTHORIZATION_MISMATCH', token=OPERATOR)


def test_public_eval_compare_has_raw_and_quality_without_questions(rig):
    protocol = register(rig)
    a = evaluate(rig, protocol['id'], .6, .6)
    b = evaluate(rig, protocol['id'], .2, .8)
    comparison = rig.ok('eval.compare', {'left': a['id'], 'right': b['id']})
    assert comparison['delta'] == pytest.approx(.3)
    assert comparison['task_deltas'] == pytest.approx({'math': .4, 'logic': .2})
    assert comparison['regressions'] == []
    assert comparison['confidence_interval'] == pytest.approx([.3, .3])
    assert comparison['left']['raw_score'] == pytest.approx(.6)
    assert comparison['right']['normalized_score'] == pytest.approx(.8)
    assert comparison['task_metrics'] == metadata()
    shown = rig.ok('protocol.show', {'id': protocol['id']})
    assert shown['spec']['task_metrics'] == comparison['task_metrics'] == b['task_metrics']
    body = json.dumps([shown, comparison, a, b])
    for forbidden in ('one plus one', 'choose true', '"answer"', '"items"', '"q1"', '"q2"'):
        assert forbidden not in body


def test_compare_reports_minimize_regression(rig):
    protocol = register(rig)['id']
    a = evaluate(rig, protocol, .2, .8)
    b = evaluate(rig, protocol, .6, .8)
    result = rig.ok('eval.compare', {'left': a['id'], 'right': b['id']})
    assert result['delta'] == pytest.approx(-.2)
    assert result['regressions'] == ['math']


def test_repeated_eval_aggregation_uses_quality(rig):
    protocol = register(rig)['id']
    a = evaluate(rig, protocol, .2, .8)
    b = evaluate(rig, protocol, .4, .6)
    result = rig.ok('eval.aggregate', {'ids': [a['id'], b['id']]})
    assert result['mean_score'] == pytest.approx(.7)
    assert result['mean'] == result['mean_score']
    assert result['raw_mean_score'] == pytest.approx(.5)


def test_campaign_select_recommends_quality_not_raw_and_does_not_submit(rig):
    protocol = register(rig)['id']
    bind_campaign(rig, protocol)
    lower = rig.base
    higher = rig.model('high-raw', files={'config.json': '{}', 'tokenizer.json': '{}',
                                        'model.safetensors': 'another-fixture'})
    evaluate(rig, protocol, .1, .8, model=lower)
    evaluate(rig, protocol, .9, .8, model=higher)
    result = rig.ok('campaign.select', {'id': rig.campaign})
    assert result['model_id'] == lower
    assert result['normalized_mean_score'] == pytest.approx(.85)
    assert result['raw_mean_score'] == pytest.approx(.45)
    assert 'submission' not in rig.ok('campaign.show', {'id': rig.campaign})


def test_selection_cannot_bypass_pending_audit(rig):
    protocol = register(rig)['id']
    bind_campaign(rig, protocol)
    rig.principals['auditor-fixture'] = {'id': 'auditor', 'role': 'auditor'}
    rig.close()
    rig.open()
    rig.ok('audit.configure', {'campaign_id': rig.campaign, 'protocol_id': protocol,
        'auditor_ids': ['auditor'], 'checks': ['grader_consistency'], 'grader_mode': 'exact_match'},
        token=OPERATOR)
    evaluate(rig, protocol, .1, .8)
    rig.error('campaign.select', {'id': rig.campaign}, 'NO_ELIGIBLE_CANDIDATE')
    assert 'submission' not in rig.ok('campaign.show', {'id': rig.campaign})


def test_dashboard_uses_safe_direction_metadata_and_quality(rig):
    protocol = register(rig)['id']
    bind_campaign(rig, protocol)
    evaluated = evaluate(rig, protocol, .2, .8)
    def request(operation, payload):
        response = rig.call(operation, payload)
        if response['error']:
            raise RuntimeError(response['error']['code'])
        return response['data']
    result = snapshot(request)
    row = next(row for row in result['evaluations'] if row['id'] == evaluated['id'])
    assert row['task_metrics'] == metadata()
    assert row['normalized_score'] == pytest.approx(.8)
    body = json.dumps(result)
    assert 'one plus one' not in body
    assert 'choose true' not in body
    assert '"answer"' not in body
    assert rig.cluster.submissions == []


def test_eval_list_is_scoped_and_summary_only(rig):
    protocol = register(rig)['id']
    result = evaluate(rig, protocol, .2, .8)
    rows = rig.ok('eval.list', {'campaign_id': rig.campaign})['items']
    assert result['id'] in {row['id'] for row in rows}
    assert all('items' not in row and 'answer' not in row for row in rows)
    rig.error('eval.list', {'campaign_id': rig.campaign}, 'FORBIDDEN', token=OUTSIDER)
