"""RED before registry exists; once GREEN these must execute an actual Ray CPU head."""
from copy import deepcopy
import os

import pytest

from contracts.benchmark_runner.support import finish, prepare, register, submit
from integration.ray.cluster import head
from tests.support import OPERATOR, Rig


@pytest.fixture
def rig(tmp_path):
    r = Rig(tmp_path).setup()
    try:
        yield prepare(r)
    finally:
        r.close()


def ray_config(r):
    execution = deepcopy(r.runner_spec['execution'])
    execution['backend'] = 'ray'
    execution['resources']['walltime_seconds'] = 60
    return execution


def test_actual_ray_runner_retains_config_predictions_and_recovers_control_restart(rig, monkeypatch):
    runner = register(rig, execution=ray_config(rig))
    local = os.environ.get('NO_PROXY', '') + ',127.0.0.1,localhost'
    monkeypatch.setenv('NO_PROXY', local)
    monkeypatch.setenv('no_proxy', local)
    with head() as scheduler:
        rig.service.scheduler = scheduler
        pending = submit(rig, runner)
        rig.service.reconcile_evaluations()
        rig.close()
        rig.open()
        rig.service.scheduler = scheduler
        result = finish(rig, pending)
        assert result['state'] == 'succeeded'
        assert result['score'] == pytest.approx(.5)
        saved = rig.ok('eval.config', {'id': result['id']}, token=OPERATOR)
        assert saved['execution_receipt']['backend'] == 'ray'
        assert saved['execution_receipt']['exit_code'] == 0
        assert saved['run_config']['runner']['digest'] == runner['digest']
        assert len(rig.ok('eval.samples', {'id': result['id']}, token=OPERATOR)['items']) == 2
        assert rig.evaluator.calls == []


def test_ray_runner_checks_shared_filesystem_instead_of_falling_back(rig, monkeypatch):
    runner = register(rig, execution=ray_config(rig))
    local = os.environ.get('NO_PROXY', '') + ',127.0.0.1,localhost'
    monkeypatch.setenv('NO_PROXY', local)
    monkeypatch.setenv('no_proxy', local)
    with head() as scheduler:
        scheduler.shared_filesystem = False
        rig.service.scheduler = scheduler
        rig.error('eval.submit', {'runner_id': runner['id'], 'model_id': rig.base}, 'UNSUPPORTED_RUNNER_BACKEND')


def test_ray_runner_prepares_private_requirements_runtime(rig, monkeypatch):
    import hashlib
    environment = deepcopy(rig.runner_spec['environment'])
    environment['requirements'] = '# real venv with stdlib only\n'
    environment['requirements_digest'] = hashlib.sha256(environment['requirements'].encode()).hexdigest()
    runner = register(rig, execution=ray_config(rig), environment=environment)
    local = os.environ.get('NO_PROXY', '') + ',127.0.0.1,localhost'
    monkeypatch.setenv('NO_PROXY', local)
    monkeypatch.setenv('no_proxy', local)
    with head() as scheduler:
        rig.service.scheduler = scheduler
        result = finish(rig, submit(rig, runner))
        assert result['state'] == 'succeeded'
        receipt = rig.ok('eval.config', {'id': result['id']}, token=OPERATOR)['execution_receipt']
        assert receipt['execution']['runtime']['isolation'] == 'job-venv'
        assert receipt['environment']['requirements_digest'] == environment['requirements_digest']
        assert receipt['actual_python'] != environment['python_executable']
