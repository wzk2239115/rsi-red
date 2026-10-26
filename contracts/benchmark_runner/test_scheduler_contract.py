"""External scheduler faults; product registry/reconciler/budgets remain real."""
from copy import deepcopy
import threading

from contracts.benchmark_runner.support import register, submit
from tests.support import ALICE, BOB


def ray(r):
    r.cluster.shared_filesystem = True
    execution = deepcopy(r.runner_spec['execution'])
    execution.update(backend='ray', resources={'gpus': 1, 'cpus': 1, 'walltime_seconds': 2000})
    return register(r, execution=execution)


def test_ambiguous_submit_is_found_after_restart_and_not_replayed(rig):
    runner = ray(rig)
    rig.cluster.lose_response = True
    e = submit(rig, runner)
    rig.service.reconcile_evaluations()
    assert len(rig.cluster.submissions) == 1
    rig.close()
    rig.open()
    rig.service.reconcile_evaluations()
    assert len(rig.cluster.submissions) == 1
    stored = rig.service.store.get(e['id'], 'eval')
    assert stored['scheduler_id'] in rig.cluster.jobs
    assert stored['state'] == 'running'


def test_unavailable_remote_status_keeps_reservation_and_does_not_replay(rig, monkeypatch):
    runner = ray(rig)
    e = submit(rig, runner)
    rig.service.reconcile_evaluations()
    def unavailable(*args):
        raise TimeoutError('private endpoint details')
    monkeypatch.setattr(rig.cluster, 'status', unavailable)
    rig.service.reconcile_evaluations()
    assert len(rig.cluster.submissions) == 1
    assert rig.ok('campaign.show', {'id': rig.campaign})['usage']['reserved_gpu_seconds'] == 2000
    assert 'private endpoint' not in str(rig.ok('eval.show', {'id': e['id']}))


def test_concurrent_evaluation_reservations_share_campaign_budget(rig):
    runner = ray(rig)
    outcomes = []
    def send(token):
        outcomes.append(rig.call('eval.submit', {'runner_id': runner['id'], 'model_id': rig.base}, token=token))
    threads = [threading.Thread(target=send, args=(token,)) for token in (ALICE, BOB)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(o['error'] is None for o in outcomes) == 1
    assert [o['error']['code'] for o in outcomes if o['error']] == ['BUDGET_EXCEEDED']


def test_eval_reservation_also_blocks_training_job(rig):
    runner = ray(rig)
    submit(rig, runner)
    request = rig.job_request(key='blocked-job', datasets=[])
    request['resources'].update(gpus=1, walltime_seconds=2000)
    rig.error('job.submit', request, 'BUDGET_EXCEEDED')


def test_cancelled_remote_eval_accounting_is_charged_once(rig):
    runner = ray(rig)
    e = submit(rig, runner)
    rig.service.reconcile_evaluations()
    stored = rig.service.store.get(e['id'], 'eval')
    rig.cluster.set_state(stored['scheduler_id'], 'cancelled', gpu_seconds=17)
    rig.service.reconcile_evaluations()
    rig.service.reconcile_evaluations()
    usage = rig.ok('campaign.show', {'id': rig.campaign})['usage']
    assert usage == {'gpu_seconds': 17, 'reserved_gpu_seconds': 0}
    assert rig.ok('eval.config', {'id': e['id']}, token='test-operator-token')['execution_receipt']['backend'] == 'ray'


def test_lost_remote_job_ends_without_relaunch(rig, monkeypatch):
    from rsi_red.schedulers.ray import RayUnavailable
    runner = ray(rig)
    e = submit(rig, runner)
    rig.service.reconcile_evaluations()
    def missing(*args):
        raise RayUnavailable('RAY_JOB_LOST')
    monkeypatch.setattr(rig.cluster, 'status', missing)
    rig.service.reconcile_evaluations()
    assert rig.ok('eval.show', {'id': e['id']})['state'] == 'failed'
    assert len(rig.cluster.submissions) == 1
