"""Additional RED→GREEN failure and privacy contracts, using real CPU workers."""
from copy import deepcopy
import json
from pathlib import Path
import threading
import time


from contracts.benchmark_runner.support import finish, register, submit
from tests.support import BOB, OPERATOR


def test_corrupt_source_blob_fails_with_durable_receipt(rig):
    runner = register(rig)
    blob = rig.service.store.root / 'blobs' / runner['files'][0]['sha256']
    blob.write_bytes(b'corrupted')
    result = finish(rig, submit(rig, runner))
    assert result['state'] == 'failed' and 'score' not in result
    receipt = rig.ok('eval.config', {'id': result['id']}, token=OPERATOR)['execution_receipt']
    assert receipt['error'] == 'CHECKSUM_MISMATCH'


def test_local_restart_recovers_in_flight_without_second_harness(rig):
    runner = register(rig)
    pending = submit(rig, runner)
    rig.service.reconcile_evaluations()
    rig.close()
    rig.open()
    assert finish(rig, pending)['state'] == 'succeeded'


def test_running_cancel_is_owner_only_and_ends_process(rig):
    command = deepcopy(rig.runner_spec['command'])
    command[-1] = 'sleep'
    runner = register(rig, command=command)
    pending = submit(rig, runner)
    rig.service.reconcile_evaluations()
    rig.error('eval.cancel', {'id': pending['id']}, 'FORBIDDEN', token=BOB)
    rig.ok('eval.cancel', {'id': pending['id']})
    result = finish(rig, pending)
    assert result['state'] == 'cancelled'
    assert 'score' not in result
    assert rig.ok('campaign.show', {'id': rig.campaign})['usage']['reserved_gpu_seconds'] == 0


def test_comparison_rejects_actual_environment_drift(rig):
    runner = register(rig)
    a = finish(rig, submit(rig, runner))
    b = finish(rig, submit(rig, runner, model_id=rig.other))
    # Simulate a persisted receipt from a second worker with different installed libraries.
    with rig.service.store.transaction():
        row = rig.service.store.get(b['id'], 'eval')
        row['comparison_digest'] = 'different-actual-runtime'
        rig.service.store.save('eval', row)
    rig.error('eval.compare', {'left': a['id'], 'right': b['id']}, 'EVALUATION_CONFIG_MISMATCH')
    rig.error('eval.aggregate', {'ids': [a['id'], b['id']]}, 'PROTOCOL_MISMATCH')
    chosen = rig.ok('campaign.select', {'id': rig.campaign, 'comparison_digest': a['comparison_digest']})
    assert chosen['model_id'] == rig.base
    rig.error('campaign.submit', {'id': rig.campaign, 'model_id': rig.other,
        'comparison_digest': a['comparison_digest']}, 'EVALUATION_NOT_READY')


def test_runner_logs_and_config_are_never_available_to_researcher(rig):
    runner = register(rig)
    e = finish(rig, submit(rig, runner))
    rig.error('eval.logs', {'id': e['id']}, 'EVALUATION_DETAILS_RESTRICTED')
    rig.error('eval.config', {'id': e['id']}, 'EVALUATION_DETAILS_RESTRICTED')
    assert isinstance(rig.ok('eval.logs', {'id': e['id']}, token=OPERATOR)['items'], list)


def test_submit_does_not_run_external_code_under_request_lock(rig, monkeypatch):
    runner = register(rig)
    def forbidden(*args, **kwargs):
        raise AssertionError('Request path launched external code')
    monkeypatch.setattr('subprocess.Popen', forbidden)
    pending = submit(rig, runner)
    assert pending['state'] == 'accepted'
    assert rig.ok('eval.config', {'id': pending['id']}, token=OPERATOR)['execution_receipt'] is None


def test_query_budget_is_shared_across_runner_versions(rig):
    rig.principals['audit-token'] = {'id': 'auditor', 'role': 'auditor'}
    rig.close()
    rig.open()
    first = register(rig)
    second = register(rig, name='second-version')
    rig.ok('audit.configure', {'campaign_id': rig.campaign, 'protocol_id': rig.protocol,
        'auditor_ids': ['auditor'], 'checks': ['grader_consistency'], 'max_evaluations': 1}, token=OPERATOR)
    submit(rig, first)
    rig.error('eval.submit', {'runner_id': second['id'], 'model_id': rig.other}, 'EVALUATION_BUDGET_EXCEEDED')


def test_unknown_fields_and_inline_credentials_rejected(rig):
    rig.error('runner.register', dict(rig.runner_spec, password='do-not-store'), 'INVALID_REQUEST', token=OPERATOR)
    rig.error('runner.register', dict(rig.runner_spec, command=['python', '--api-key=do-not-store']),
              'INVALID_REQUEST', token=OPERATOR)
    rig.error('runner.register', dict(rig.runner_spec, secret_refs={'KEY': 'plaintext'}), 'INVALID_REQUEST', token=OPERATOR)


def test_pinned_environment_mismatch_fails_with_environment_receipt(rig):
    env = deepcopy(rig.runner_spec['environment'])
    env['python_version'] = '0.0.0'
    runner = register(rig, environment=env)
    e = finish(rig, submit(rig, runner))
    assert e['state'] == 'failed' and 'score' not in e
    assert rig.ok('eval.config', {'id': e['id']}, token=OPERATOR)['execution_receipt']['environment']['python_version'] != '0.0.0'


def test_output_snapshot_corruption_cannot_publish_partial_scores(rig, monkeypatch):
    runner = register(rig)
    original = rig.service._runner_finish
    def broken(e, status):
        root = Path(e['run_config']['bindings']['config_path']).parent
        (root / 'validated-output.json').write_text('[]')
        return original(e, status)
    monkeypatch.setattr(rig.service, '_runner_finish', broken)
    e = finish(rig, submit(rig, runner))
    assert e['state'] == 'failed' and 'score' not in e


def test_concurrent_cancel_during_submission_is_not_overwritten(rig, monkeypatch):
    runner = register(rig)
    pending = submit(rig, runner)
    scheduler = rig.service._runner_scheduler(rig.service.store.get(pending['id'], 'eval'))
    original = scheduler.submit
    entered, proceed = threading.Event(), threading.Event()
    def delayed(*args, **kwargs):
        entered.set()
        assert proceed.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(scheduler, 'submit', delayed)
    monkeypatch.setattr(rig.service, '_runner_scheduler', lambda e: scheduler)
    thread = threading.Thread(target=rig.service.reconcile_evaluations)
    thread.start()
    assert entered.wait(5)
    rig.ok('eval.cancel', {'id': pending['id']})
    proceed.set()
    thread.join(5)
    assert not thread.is_alive()
    assert finish(rig, pending)['state'] == 'cancelled'


def test_empty_argv_and_non_python_commands_use_pinned_interpreter_supervisor(rig):
    spec = deepcopy(rig.runner_spec)
    spec['command'] = ['{python}', 'driver.py', '--config', '{run_config}', '--mode', 'valid']
    e = finish(rig, submit(rig, register(rig, **spec)))
    assert e['state'] == 'succeeded'


def test_non_model_artifact_rejected_by_protocol(rig):
    runner = register(rig)
    with rig.service.store.transaction():
        artifact = rig.service.store.get(rig.base, 'artifact')
        artifact['kind'] = 'dataset'
        rig.service.store.save('artifact', artifact)
    rig.error('eval.submit', {'runner_id': runner['id'], 'model_id': rig.base}, 'EVALUATION_UNSUPPORTED_ARTIFACT')


def test_auditor_runner_discovery_obeys_active_protocol_scope(rig):
    runner = register(rig)
    rig.principals['audit-token'] = {'id': 'auditor', 'role': 'auditor'}
    rig.close()
    rig.open()
    rig.error('runner.show', {'id': runner['id']}, 'FORBIDDEN', token='audit-token')
    rig.ok('audit.configure', {'campaign_id': rig.campaign, 'protocol_id': rig.protocol,
        'auditor_ids': ['auditor'], 'checks': ['grader_consistency'], 'runner_id': runner['id']}, token=OPERATOR)
    assert rig.ok('runner.show', {'id': runner['id']}, token='audit-token')['id'] == runner['id']
    rig.error('eval.submit', {'runner_id': runner['id'], 'model_id': rig.base}, 'FORBIDDEN', token='audit-token')


def test_runner_audit_case_pins_exact_execution_evidence(rig):
    runner = register(rig)
    rig.principals['audit-token'] = {'id': 'auditor', 'role': 'auditor'}
    rig.close()
    rig.open()
    policy = rig.ok('audit.configure', {'campaign_id': rig.campaign, 'protocol_id': rig.protocol,
        'auditor_ids': ['auditor'], 'checks': ['grader_consistency'], 'grader_mode': 'exact_match',
        'runner_id': runner['id']}, token=OPERATOR)
    e = finish(rig, submit(rig, runner))
    case = rig.ok('audit.submit', {'campaign_id': rig.campaign, 'model_id': rig.base, 'eval_id': e['id'],
        'policy_id': policy['id'], 'idempotency_key': 'bound'})
    assert case['runner_digest'] == runner['digest']
    assert case['comparison_digest'] == e['comparison_digest']
    assert case['run_config_digest'] == e['run_config_digest']


def test_local_lost_worker_is_not_replayed_and_reaches_terminal_state(rig):
    runner = register(rig)
    pending = submit(rig, runner)
    row = rig.service.store.get(pending['id'], 'eval')
    scheduler = rig.service._runner_scheduler(row)
    request = rig.service._prepare_runner(row, runner)
    folder = scheduler.root / row['id']
    folder.mkdir()
    (folder / 'request.json').write_text(json.dumps(request))
    (folder / 'state.json').write_text(json.dumps({'state': 'running', 'started_at': time.time()-5, 'worker_pid': 999999}))
    with rig.service.store.transaction():
        row.update(state='running', submission_attempted=True, scheduler_id=row['id'])
        rig.service.store.save('eval', row)
    assert finish(rig, pending)['state'] == 'failed'


def test_private_secret_refs_do_not_return_secret_stdout(rig, monkeypatch):
    monkeypatch.setenv('RUNNER_TEST_SECRET', 'fixture-credential-value')
    runner = register(rig, command=['{python}', '-c', 'import os;print(os.environ["PRIVATE_KEY"])'],
                      secret_refs={'PRIVATE_KEY': 'env:RUNNER_TEST_SECRET'})
    e = finish(rig, submit(rig, runner))
    body = json.dumps(rig.ok('eval.logs', {'id': e['id']}, token=OPERATOR))
    assert 'fixture-credential-value' not in body
    assert 'fixture-credential-value' not in json.dumps(rig.ok('eval.config', {'id': e['id']}, token=OPERATOR))


def test_legacy_protocol_records_have_no_fabricated_config(rig):
    e = rig.evaluate()
    rig.error('eval.config', {'id': e['id']}, 'RUN_CONFIG_UNAVAILABLE', token=OPERATOR)


def test_requirements_snapshot_creates_real_private_runtime(rig):
    import hashlib
    env = deepcopy(rig.runner_spec['environment'])
    env['requirements'] = '# stdlib fixture; no network dependency\n'
    env['requirements_digest'] = hashlib.sha256(env['requirements'].encode()).hexdigest()
    e = finish(rig, submit(rig, register(rig, environment=env)))
    assert e['state'] == 'succeeded'
    receipt = rig.ok('eval.config', {'id': e['id']}, token=OPERATOR)['execution_receipt']
    assert receipt['execution']['runtime']['isolation'] == 'job-venv'
    assert receipt['actual_python'] != env['python_executable']
    assert receipt['environment']['requirements_digest'] == env['requirements_digest']
    assert receipt['log_blob']


def test_log_snapshot_survives_scheduler_deletion(rig):
    import shutil
    runner = register(rig)
    e = finish(rig, submit(rig, runner))
    before = rig.ok('eval.logs', {'id': e['id']}, token=OPERATOR)
    shutil.rmtree(rig.service.store.root / 'evaluation-workers')
    rig.close()
    rig.open()
    assert rig.ok('eval.logs', {'id': e['id']}, token=OPERATOR) == before


def test_completed_execution_is_not_timed_out_by_late_controller_poll(rig):
    execution = deepcopy(rig.runner_spec['execution'])
    execution['resources']['walltime_seconds'] = 2
    runner = register(rig, execution=execution)
    e = submit(rig, runner)
    rig.service.reconcile_evaluations()
    # Harness finishes within its deadline while the controller is temporarily absent.
    time.sleep(2.1)
    assert finish(rig, e)['state'] == 'succeeded'


def test_zero_cpu_reservation_and_empty_argument_are_valid_argv(rig):
    execution = deepcopy(rig.runner_spec['execution'])
    execution['resources']['cpus'] = 0
    runner = register(rig, execution=execution, command=['{python}', '-c', ''])
    assert runner['spec']['command'][-1] == ''
    assert runner['spec']['execution']['resources']['cpus'] == 0
