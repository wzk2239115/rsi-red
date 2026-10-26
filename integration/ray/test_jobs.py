"""Real local Ray Jobs server tests; no fake client. Explicit invocation requires Ray extra."""
import hashlib
import socket
import tempfile
import shutil
from pathlib import Path
import sys
import time
import uuid

import pytest


def unused_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


@pytest.fixture(scope='module')
def ray_client():
    import ray
    from ray.job_submission import JobSubmissionClient
    owned = Path(tempfile.mkdtemp(prefix='rsi-ray-', dir='/tmp'))
    try:
        context = ray.init(address='local', num_cpus=2, num_gpus=0, include_dashboard=True,
            dashboard_host='127.0.0.1', dashboard_port=unused_port(),
            _node_ip_address='127.0.0.1', _temp_dir=str(owned))
        endpoint = context.address_info['webui_url']
        client = JobSubmissionClient('http://' + endpoint)
        deadline = time.monotonic() + 30
        while True:
            try:
                client.list_jobs()
                break
            except Exception:
                if time.monotonic() > deadline:
                    raise
                time.sleep(.2)
        yield client
    finally:
        # Ray 2.59.0 drops Popen references during shutdown without closing the reaper pipe.
        # Keep only this owned instance's handles alive, then explicitly reap and close them.
        node = ray._private.worker._global_node
        processes = [info.process for infos in node.all_processes.values() for info in infos] if node else []
        ray.shutdown()
        for process in processes:
            process.wait(timeout=10)
            for stream in [process.stdin, process.stdout, process.stderr]:
                if stream is not None:
                    stream.close()
        logs = owned / 'session_latest' / 'logs'
        if logs.exists():
            shutil.copytree(logs, Path('reports/ray-logs'), dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns('*.sock'))
        shutil.rmtree(owned, ignore_errors=True)


def scheduler(client):
    from rsi_red.schedulers.ray import RayScheduler
    return RayScheduler(client=client)


def wait(scheduler, key, terminal=None):
    terminal = terminal or {'succeeded', 'failed', 'cancelled', 'timed_out'}
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        state = scheduler.status(key)
        if state['state'] in terminal:
            return state
        time.sleep(.2)
    raise AssertionError('Ray job did not reach expected state: ' + str(scheduler.status(key)))


def submit(client, tmp_path, code, *, seconds=30):
    path = tmp_path / 'train.py'
    path.write_text(code)
    instance = scheduler(client)
    key = 'rsi-' + uuid.uuid4().hex
    instance.submit({'workdir': str(tmp_path), 'entrypoint': ['python', 'train.py'],
                     'resources': {'gpus': 0, 'cpus': 1, 'walltime_seconds': seconds}}, submission_key=key)
    return instance, key


def test_real_ray_tasks_execute_and_logs_return(ray_client, tmp_path):
    instance, key = submit(ray_client, tmp_path, '''import ray
ray.init(address="auto")
@ray.remote
def square(x): return x*x
print("ray-results", ray.get([square.remote(i) for i in range(4)]), flush=True)
''')
    try:
        assert wait(instance, key)['state'] == 'succeeded'
        assert 'ray-results [0, 1, 4, 9]' in '\n'.join(instance.logs(key))
        assert scheduler(ray_client).find(key) == key
    finally:
        instance.cancel(key)


def test_real_ray_cancel_running_job(ray_client, tmp_path):
    instance, key = submit(ray_client, tmp_path, 'import time\nprint("started",flush=True)\ntime.sleep(120)\n', seconds=150)
    try:
        wait(instance, key, {'running'})
        instance.cancel(key)
        assert wait(instance, key)['state'] == 'cancelled'
    finally:
        instance.cancel(key)


def test_real_ray_failure_is_not_success(ray_client, tmp_path):
    instance, key = submit(ray_client, tmp_path, 'raise SystemExit(7)\n')
    assert wait(instance, key)['state'] == 'failed'


def test_real_ray_walltime_is_enforced(ray_client, tmp_path):
    instance, key = submit(ray_client, tmp_path, 'import time\ntime.sleep(30)\n', seconds=1)
    try:
        assert wait(instance, key)['state'] == 'timed_out'
    finally:
        instance.cancel(key)


def test_control_service_reopens_and_finds_same_ray_job(ray_client, tmp_path):
    from rsi_red.service import ResearchService
    from rsi_red.evaluation import UnconfiguredEvaluator
    root = tmp_path / 'control'
    principals = {'token': {'id': 'operator', 'role': 'operator'}}
    def open_service():
        return ResearchService(root=root, scheduler=scheduler(ray_client),
                               evaluator=UnconfiguredEvaluator(), principals=principals)
    service = open_service()
    release = tmp_path / 'release'
    def call(operation, **payload):
        result = service.dispatch(token='token', operation=operation, payload=payload)
        assert result['error'] is None, result
        return result['data']
    try:
        protocol = call('protocol.register', name='ray-test', visibility='development',
            items=[{'id': 'q', 'task': 'fixture', 'prompt': 'x', 'answer': 'x'}],
            evaluator_digest='sha256:' + '1' * 64, sampling={'max_tokens': 1, 'temperature': 0},
            aggregation='task_mean', eval_seed=42)
        campaign = call('campaign.create', name='ray-real', members=['operator'], gpu_hours_budget=1,
                        protocol_id=protocol['id'], require_decontamination=False)
        output = tmp_path / 'completed'
        source = tmp_path / 'train.py'
        source.write_text('import pathlib,time\n'
            f'p=pathlib.Path({str(release)!r})\n'
            'deadline=time.monotonic()+40\n'
            'while not p.exists():\n'
            '    if time.monotonic()>deadline: raise SystemExit(9)\n'
            '    time.sleep(.1)\n'
            f'pathlib.Path({str(output)!r}).write_text("done")\n')
        job = call('job.submit', campaign_id=campaign['id'], idempotency_key='restart',
            entrypoint=[sys.executable, str(source)],
            code={'uri': source.as_uri(), 'digest': 'sha256:' + hashlib.sha256(source.read_bytes()).hexdigest()},
            datasets=[], parents=[], resources={'gpus': 0, 'cpus': 1, 'walltime_seconds': 50}, training_seed=42)
        service.reconcile()
        initial = call('job.show', id=job['id'])
        sid = initial['scheduler_id']
        assert sid
        service.close()
        release.touch()
        service = open_service()
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            service.reconcile()
            result = call('job.show', id=job['id'])
            if result['state'] in {'succeeded', 'failed'}:
                break
            time.sleep(.2)
        assert result['state'] == 'succeeded'
        assert result['scheduler_id'] == sid
        assert result['attempt_count'] == 1
        assert output.read_text() == 'done'
    finally:
        release.touch()
        service.close()
