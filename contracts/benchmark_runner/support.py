from copy import deepcopy
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

from contracts.evaluation_direction.test_contract import authorize, metadata
from rsi_red.store import digest
from tests.support import OPERATOR


def prepare(r):
    source = r.root / 'harness-checkout'
    source.mkdir()
    script = Path(__file__).with_name('driver_fixture.py').read_bytes()
    (source / 'driver.py').write_bytes(script)
    for args in (['init', '-q'], ['remote', 'add', 'origin', 'https://example.org/cpu-fixture.git'],
                 ['add', 'driver.py'], ['-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.org',
                                        'commit', '-qm', 'CPU fixture harness']):
        subprocess.run(['git', '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null',
                        '-c', 'core.autocrlf=false', '-C', str(source), *args], check=True, capture_output=True)
    commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    code_digest = 'sha256:' + hashlib.sha256(script).hexdigest()
    spec = deepcopy(r.ok('protocol.show', {'id': r.protocol}, token=OPERATOR)['spec'])
    spec.pop('direction', None)
    spec.update(benchmark={'name': 'cpu-fixture', 'revision': 'v1', 'split': 'dev'},
                evaluator_digest=code_digest, direction_authorization_id=authorize(r)['id'])
    for item, meta in zip(spec['items'], metadata().values(), strict=True):
        item.update(meta)
    protocol = r.ok('protocol.register', spec, token=OPERATOR)
    r.protocol = protocol['id']
    r.campaign = r.ok('campaign.create', {'name': 'runner-fixture', 'members': ['alice', 'bob'],
        'gpu_hours_budget': 1, 'protocol_id': r.protocol, 'require_decontamination': False}, token=OPERATOR)['id']
    r.base = model(r, 'candidate-a', [.6, .6])
    r.other = model(r, 'candidate-b', [.2, .8])
    r.runner_spec = {
        'name': 'cpu-external-fixture', 'protocol_id': r.protocol,
        'source': {'repository': 'https://example.org/cpu-fixture.git', 'commit': commit, 'path': str(source),
                   'tree_digest': digest([{'path': 'driver.py', 'sha256': hashlib.sha256(script).hexdigest()}])},
        'judge': {'kind': 'code', 'revision': commit, 'code_digest': code_digest},
        'dataset': dict(spec['benchmark'], items_digest=digest(spec['items'])),
        'decoding': dict(spec['sampling'], eval_seed=spec['eval_seed']),
        'environment': {'python_executable': sys.executable, 'python_version': platform.python_version(),
                        'requirements': '', 'requirements_digest': hashlib.sha256(b'').hexdigest()},
        'execution': {'backend': 'local', 'resources': {'gpus': 0, 'cpus': 1, 'walltime_seconds': 30}},
        'command': ['{python}', 'driver.py', '--config', '{run_config}', '--mode', 'valid'],
        'output_schema': {'format': 'rsi-predictions-jsonl-v1', 'path': 'predictions.jsonl'},
    }
    return r


def model(r, name, scores):
    return r.model(name, files={'config.json': json.dumps({'fixture_scores': scores}),
                               'tokenizer.json': '{}', 'model.safetensors': 'fake weights, not inference'})


def register(r, **updates):
    spec = deepcopy(r.runner_spec)
    spec.update(updates)
    return r.ok('runner.register', spec, token=OPERATOR)


def submit(r, runner, *, model_id=None, **updates):
    return r.ok('eval.submit', dict(runner_id=runner['id'], model_id=model_id or r.base, **updates))


def finish(r, evaluation):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        r.reconcile()
        result = r.ok('eval.show', {'id': evaluation['id']})
        if result['state'] in {'succeeded', 'failed', 'cancelled', 'timed_out'}:
            return result
        time.sleep(.03)
    raise AssertionError('Runner eval did not reach a terminal state')
