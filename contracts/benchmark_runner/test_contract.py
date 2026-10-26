"""RED contracts for runner registry and actual external CPU execution; no product stubs."""
from copy import deepcopy
import json
from pathlib import Path
import shutil

import pytest

from contracts.benchmark_runner.support import finish, register, submit
from rsi_red.schedulers.local import LocalScheduler
from tests.support import ALICE, OPERATOR


def local(r):
    r.service.scheduler = LocalScheduler(root=r.root / 'worker', allow_cpu_only=True)


def test_registration_freezes_source_and_does_not_execute(rig):
    runner = register(rig)
    assert runner['digest']
    assert runner['protocol_digest'] == rig.ok('protocol.show', {'id': rig.protocol})['digest']
    assert rig.ok('runner.show', {'id': runner['id']}, token=OPERATOR) == runner
    assert rig.cluster.submissions == []
    assert rig.evaluator.calls == []


@pytest.mark.parametrize('role', ['researcher', 'auditor'])
def test_registration_is_operator_only(rig, role):
    token = ALICE
    if role == 'auditor':
        token = 'runner-auditor-fixture'
        rig.principals[token] = {'id': 'auditor', 'role': 'auditor'}
        rig.close()
        rig.open()
    rig.error('runner.register', rig.runner_spec, 'FORBIDDEN', token=token)


@pytest.mark.parametrize('path,value', [
    (('source', 'commit'), 'main'), (('source', 'commit'), 'latest'),
    (('command',), 'python driver.py'), (('command',), ['{unknown}']),
    (('output_schema', 'path'), '../outside.jsonl'),
    (('output_schema', 'format'), 'guess-from-stdout'),
    (('execution', 'resources', 'walltime_seconds'), 0),
    (('environment', 'requirements_digest'), '0' * 64),
])
def test_invalid_runner_config_is_rejected(rig, path, value):
    spec = deepcopy(rig.runner_spec)
    target = spec
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    rig.error('runner.register', spec, 'INVALID_REQUEST', token=OPERATOR)


@pytest.mark.parametrize('part,key,value', [
    ('judge', 'code_digest', 'sha256:' + 'f' * 64),
    ('dataset', 'split', 'other-split'), ('dataset', 'items_digest', 'f' * 64),
    ('decoding', 'max_tokens', 999), ('decoding', 'eval_seed', 100),
])
def test_runner_cannot_override_protocol_semantics(rig, part, key, value):
    spec = deepcopy(rig.runner_spec)
    spec[part][key] = value
    rig.error('runner.register', spec, 'RUNNER_PROTOCOL_MISMATCH', token=OPERATOR)


def test_dirty_source_is_rejected(rig):
    source = Path(rig.runner_spec['source']['path'])
    (source / 'driver.py').write_text('changed uncommitted code')
    rig.error('runner.register', rig.runner_spec, 'RUNNER_SOURCE_MISMATCH', token=OPERATOR)


def test_new_runner_is_a_new_version_and_old_record_survives_restart(rig):
    a = register(rig)
    command = list(rig.runner_spec['command'])
    command[-1] = 'missing'
    b = register(rig, command=command)
    assert b['id'] != a['id'] and b['digest'] != a['digest']
    rig.close()
    rig.open()
    assert rig.ok('runner.show', {'id': a['id']}, token=OPERATOR) == a


def test_public_runner_discovery_does_not_return_private_config(rig):
    runner = register(rig)
    shown = rig.ok('runner.show', {'id': runner['id']})
    listed = rig.ok('runner.list', {'protocol_id': rig.protocol})['items']
    assert runner['id'] in {item['id'] for item in listed}
    assert shown['digest'] == runner['digest']
    text = json.dumps([shown, listed])
    for forbidden in ('one plus one', 'choose true', '"command"', rig.runner_spec['source']['path']):
        assert forbidden not in text


def test_runner_submission_is_async_and_freezes_resolved_config(rig):
    runner = register(rig)
    local(rig)
    pending = submit(rig, runner)
    assert pending['state'] == 'accepted'
    assert pending['runner_id'] == runner['id']
    assert pending['runner_digest'] == runner['digest']
    config = rig.ok('eval.config', {'id': pending['id']}, token=OPERATOR)
    assert config['run_config']['model']['id'] == rig.base
    assert config['run_config']['protocol']['id'] == rig.protocol
    assert config['run_config_digest'] == pending['run_config_digest']
    assert all('{run_config}' not in arg for arg in config['run_config']['command'])
    assert config['execution_receipt'] is None
    assert rig.evaluator.calls == []


def test_two_checkpoints_execute_same_external_harness_and_compare(rig):
    runner = register(rig)
    local(rig)
    a = finish(rig, submit(rig, runner))
    b = finish(rig, submit(rig, runner, model_id=rig.other))
    assert a['state'] == b['state'] == 'succeeded'
    assert a['score'] == pytest.approx(.5) and b['score'] == pytest.approx(.8)
    compared = rig.ok('eval.compare', {'left': a['id'], 'right': b['id']})
    assert compared['delta'] == pytest.approx(.3)
    assert compared['runner_digest'] == runner['digest']
    assert compared['right']['raw_score'] == pytest.approx(.5)
    assert rig.evaluator.calls == []  # Must not use the in-memory fixture evaluator.
    configs = [rig.ok('eval.config', {'id': item['id']}, token=OPERATOR) for item in (a, b)]
    assert configs[0]['run_config_digest'] != configs[1]['run_config_digest']
    assert a['comparison_digest'] == b['comparison_digest']
    for config in configs:
        assert config['execution_receipt']['exit_code'] == 0
        assert config['execution_receipt']['python_version'] == rig.runner_spec['environment']['python_version']
    rig.close()
    rig.open()
    for item, config in zip((a, b), configs, strict=True):
        assert rig.ok('eval.config', {'id': item['id']}, token=OPERATOR) == config
        rows = rig.ok('eval.samples', {'id': item['id']}, token=OPERATOR)['items']
        assert len(rows) == 2 and all('score' in row and ('prediction' in row or 'answer' in row) for row in rows)


def test_original_checkout_can_disappear_after_registration(rig):
    runner = register(rig)
    shutil.rmtree(rig.runner_spec['source']['path'])
    local(rig)
    assert finish(rig, submit(rig, runner))['state'] == 'succeeded'


@pytest.mark.parametrize('mode', ['missing', 'duplicate', 'unknown', 'nan', 'badjson', 'exit'])
def test_bad_external_output_fails_without_partial_suite(rig, mode):
    command = list(rig.runner_spec['command'])
    command[-1] = mode
    runner = register(rig, command=command)
    local(rig)
    result = finish(rig, submit(rig, runner))
    assert result['state'] == 'failed'
    assert 'score' not in result
    saved = rig.ok('eval.config', {'id': result['id']}, token=OPERATOR)
    assert saved['run_config_digest'] and saved['execution_receipt'] is not None


def test_unknown_runner_cannot_silently_fall_back_to_legacy_evaluator(rig):
    rig.error('eval.submit', {'campaign_id': rig.campaign, 'model_id': rig.base,
        'protocol_id': rig.protocol, 'runner_id': 'runner-not-found'}, 'NOT_FOUND')
    assert rig.evaluator.calls == []


def test_explicit_protocol_conflict_is_rejected(rig):
    runner = register(rig)
    rig.error('eval.submit', {'runner_id': runner['id'], 'model_id': rig.base,
        'protocol_id': 'different-protocol'}, 'RUNNER_PROTOCOL_MISMATCH')


def test_same_protocol_different_runner_versions_cannot_compare(rig):
    a_runner = register(rig)
    execution = deepcopy(rig.runner_spec['execution'])
    execution['resources']['cpus'] = 2
    b_runner = register(rig, execution=execution)
    local(rig)
    a = finish(rig, submit(rig, a_runner))
    b = finish(rig, submit(rig, b_runner))
    rig.error('eval.compare', {'left': a['id'], 'right': b['id']}, 'RUNNER_MISMATCH')
    rig.error('eval.aggregate', {'ids': [a['id'], b['id']]}, 'RUNNER_MISMATCH')
    rig.error('campaign.select', {'id': rig.campaign}, 'EVALUATION_GROUP_REQUIRED')


def test_run_config_is_operator_only_and_public_evidence_has_no_questions(rig):
    runner = register(rig)
    local(rig)
    result = finish(rig, submit(rig, runner))
    rig.error('eval.config', {'id': result['id']}, 'EVALUATION_DETAILS_RESTRICTED')
    shown = rig.ok('eval.show', {'id': result['id']})
    listed = rig.ok('eval.list', {'campaign_id': rig.campaign})
    jobs = rig.ok('job.list', {'campaign_id': rig.campaign})['items']
    assert jobs == []
    body = json.dumps([shown, listed, rig.events()])
    for forbidden in ('one plus one', 'choose true', 'fixture prediction', '"command"', '"bindings"'):
        assert forbidden not in body


def test_gpu_eval_cannot_bypass_campaign_budget(rig):
    execution = {'backend': 'ray', 'resources': {'gpus': 100, 'cpus': 1, 'walltime_seconds': 3600}}
    runner = register(rig, execution=execution)
    rig.error('eval.submit', {'runner_id': runner['id'], 'model_id': rig.base}, 'BUDGET_EXCEEDED')
    assert rig.cluster.submissions == []


def test_cancel_pending_runner_eval_keeps_config_and_releases_reservation(rig):
    runner = register(rig)
    pending = submit(rig, runner)
    result = rig.ok('eval.cancel', {'id': pending['id']})
    assert result['state'] == 'cancelled'
    assert rig.ok('eval.config', {'id': result['id']}, token=OPERATOR)['run_config_digest']
    assert rig.ok('campaign.show', {'id': rig.campaign})['usage']['reserved_gpu_seconds'] == 0


def test_legacy_and_runner_results_cannot_be_mixed(rig):
    runner = register(rig)
    legacy = rig.evaluate()
    local(rig)
    result = finish(rig, submit(rig, runner))
    rig.error('eval.compare', {'left': legacy['id'], 'right': result['id']}, 'RUNNER_MISMATCH')


def test_runner_eval_idempotency_does_not_duplicate_or_change_model(rig):
    runner = register(rig)
    a = submit(rig, runner, idempotency_key='same-evaluation')
    assert submit(rig, runner, idempotency_key='same-evaluation')['id'] == a['id']
    rig.error('eval.submit', {'runner_id': runner['id'], 'model_id': rig.other,
        'idempotency_key': 'same-evaluation'}, 'IDEMPOTENCY_CONFLICT')


def test_local_gpu_request_is_explicitly_unsupported(rig):
    spec = deepcopy(rig.runner_spec)
    spec['execution']['resources']['gpus'] = 1
    rig.error('runner.register', spec, 'UNSUPPORTED_RESOURCES', token=OPERATOR)


def test_runner_timeout_retains_configuration_without_success_score(rig):
    spec = deepcopy(rig.runner_spec)
    spec['command'][-1] = 'sleep'
    spec['execution']['resources']['walltime_seconds'] = 1
    runner = rig.ok('runner.register', spec, token=OPERATOR)
    local(rig)
    result = finish(rig, submit(rig, runner))
    assert result['state'] == 'timed_out'
    assert 'score' not in result
    assert rig.ok('eval.config', {'id': result['id']}, token=OPERATOR)['execution_receipt'] is not None


def test_hidden_runner_cannot_be_discovered_by_researcher(rig):
    spec = deepcopy(rig.ok('protocol.show', {'id': rig.protocol}, token=OPERATOR)['spec'])
    spec['visibility'] = 'held_out'
    hidden = rig.ok('protocol.register', spec, token=OPERATOR)
    runner = register(rig, protocol_id=hidden['id'])
    rig.error('runner.show', {'id': runner['id']}, 'FORBIDDEN')
    assert runner['id'] not in {row['id'] for row in rig.ok('runner.list', {})['items']}


@pytest.mark.parametrize('field,value', [('commit', '0' * 40), ('tree_digest', '0' * 64)])
def test_source_identity_mismatch_is_not_just_a_label(rig, field, value):
    spec = deepcopy(rig.runner_spec)
    spec['source'][field] = value
    rig.error('runner.register', spec, 'RUNNER_SOURCE_MISMATCH', token=OPERATOR)


@pytest.mark.parametrize('corrupt', [False, True])
def test_local_model_judge_identity_is_frozen_and_verified(rig, corrupt):
    import hashlib
    judge_id = rig.model('judge-fixture')
    artifact = rig.ok('artifact.show', {'id': judge_id})
    template = 'Fixture judge template, not an LLM inference implementation'
    judge = {'kind': 'model', 'artifact_id': judge_id, 'artifact_digest': artifact['digest'],
        'revision': 'fixture-v1', 'template': template,
        'template_digest': hashlib.sha256(template.encode()).hexdigest(),
        'code_digest': rig.runner_spec['judge']['code_digest']}
    if corrupt:
        judge['artifact_digest'] = '0' * 64
    protocol = deepcopy(rig.ok('protocol.show', {'id': rig.protocol}, token=OPERATOR)['spec'])
    protocol['judge'] = judge
    bound = rig.ok('protocol.register', protocol, token=OPERATOR)
    spec = deepcopy(rig.runner_spec)
    spec.update(protocol_id=bound['id'], judge=judge)
    if corrupt:
        rig.error('runner.register', spec, 'CHECKSUM_MISMATCH', token=OPERATOR)
    else:
        runner = rig.ok('runner.register', spec, token=OPERATOR)
        assert runner['spec']['judge']['artifact_digest'] == artifact['digest']
        assert runner['spec']['judge']['template_digest'] == judge['template_digest']


def test_legacy_audit_pass_cannot_authorize_runner_submission(rig):
    runner = register(rig)
    rig.principals['runner-auditor'] = {'id': 'auditor', 'role': 'auditor'}
    rig.close()
    rig.open()
    policy = rig.ok('audit.configure', {'campaign_id': rig.campaign, 'protocol_id': rig.protocol,
        'auditor_ids': ['auditor'], 'checks': ['grader_consistency'], 'grader_mode': 'exact_match'}, token=OPERATOR)
    legacy = rig.evaluate()
    case = rig.ok('audit.submit', {'campaign_id': rig.campaign, 'model_id': rig.base,
        'eval_id': legacy['id'], 'policy_id': policy['id'], 'idempotency_key': 'legacy-check'})
    rig.reconcile()
    assert rig.ok('audit.show', {'id': case['id']})['state'] == 'checks_passed'
    local(rig)
    result = finish(rig, submit(rig, runner))
    assert result['state'] == 'succeeded'
    rig.error('campaign.submit', {'id': rig.campaign, 'model_id': rig.base,
        'runner_id': runner['id'], 'comparison_digest': result['comparison_digest']}, 'AUDIT_REQUIRED')
