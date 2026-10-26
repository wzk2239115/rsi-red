"""Execute two fake checkpoints through an installed-wheel external CPU Runner.

Run outside the repository. No tests imports and no rsi-red source-path injection.
"""
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

from rsi_red.evaluation import UnconfiguredEvaluator
from rsi_red.schedulers.local import LocalScheduler
from rsi_red.service import ResearchService
from rsi_red.store import digest

root = Path('wheel-runner').resolve()
root.mkdir()
source = root / 'harness'
source.mkdir()
fixture = Path(__file__).resolve().parents[1] / 'contracts/benchmark_runner/driver_fixture.py'
script = fixture.read_bytes()
(source / 'driver.py').write_bytes(script)
for args in (['init', '-q'], ['remote', 'add', 'origin', 'https://example.org/wheel-harness.git'], ['add', '.'],
             ['-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.org', 'commit', '-qm', 'fixed fixture']):
    subprocess.run(['git', '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null', '-C', str(source), *args],
                   check=True, capture_output=True)
commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
s = ResearchService(root=root / 'state', scheduler=LocalScheduler(root=root / 'workers', allow_cpu_only=True),
                    evaluator=UnconfiguredEvaluator(), principals={'fixture': {'id': 'operator', 'role': 'operator'}})


def call(op, **payload):
    response = s.dispatch(token='fixture', operation=op, payload=payload)
    assert response['error'] is None, response
    return response['data']


try:
    auth = call('direction.authorize', tasks={'math': {'direction': 'minimize'}, 'logic': {'direction': 'maximize'}},
                source_protocol_digest=None, goal='Installed-wheel fixture explicitly authorizes mixed directions')
    items = [{'id': 'q1', 'task': 'math', 'prompt': 'private fixture one', 'answer': 'a', 'direction': 'minimize'},
             {'id': 'q2', 'task': 'logic', 'prompt': 'private fixture two', 'answer': 'b', 'direction': 'maximize'}]
    protocol = call('protocol.register', name='wheel-mixed-fixture', visibility='development', items=items,
                    direction_authorization_id=auth['id'], aggregation='task_mean', eval_seed=1,
                    sampling={'max_tokens': 16}, evaluator_digest='sha256:' + hashlib.sha256(script).hexdigest(),
                    benchmark={'name': 'wheel-fixture', 'revision': 'v1', 'split': 'dev'})
    campaign = call('campaign.create', name='wheel fixture', members=['operator'], protocol_id=protocol['id'],
                    gpu_hours_budget=1, require_decontamination=False)
    models = []
    for index, scores in enumerate(([.6, .6], [.2, .8])):
        folder = root / f'model-{index}'
        folder.mkdir()
        for name, content in {'config.json': json.dumps({'fixture_scores': scores}), 'tokenizer.json': '{}',
                              'model.safetensors': 'FAKE WEIGHTS; NO MODEL INFERENCE'}.items():
            (folder / name).write_text(content)
        models.append(call('artifact.register', campaign_id=campaign['id'], path=str(folder), kind='model',
                           files=[{'path': f.name, 'sha256': hashlib.sha256(f.read_bytes()).hexdigest()}
                                  for f in sorted(folder.iterdir())])['id'])
    runner = call('runner.register', name='wheel external CPU fixture', protocol_id=protocol['id'],
                  source={'repository': 'https://example.org/wheel-harness.git', 'commit': commit, 'path': str(source),
                          'tree_digest': digest([{'path': 'driver.py', 'sha256': hashlib.sha256(script).hexdigest()}])},
                  judge={'kind': 'code', 'revision': commit, 'code_digest': protocol['spec']['evaluator_digest']},
                  dataset=dict(protocol['spec']['benchmark'], items_digest=digest(items)),
                  decoding=dict(protocol['spec']['sampling'], eval_seed=1),
                  environment={'python_executable': sys.executable, 'python_version': platform.python_version(),
                               'requirements': '', 'requirements_digest': hashlib.sha256(b'').hexdigest()},
                  execution={'backend': 'local', 'resources': {'gpus': 0, 'cpus': 1, 'walltime_seconds': 20}},
                  command=['{python}', 'driver.py', '--config', '{run_config}'],
                  output_schema={'format': 'rsi-predictions-jsonl-v1', 'path': 'predictions.jsonl'})
    shutil.rmtree(source)
    evaluations, configs = [], []
    for model in models:
        e = call('eval.submit', runner_id=runner['id'], model_id=model)
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            s.reconcile_evaluations()
            result = call('eval.show', id=e['id'])
            if result['state'] in {'succeeded', 'failed', 'timed_out'}:
                break
            time.sleep(.05)
        assert result['state'] == 'succeeded', result
        evaluations.append(result)
        configs.append(call('eval.config', id=e['id']))
    compared = call('eval.compare', left=evaluations[0]['id'], right=evaluations[1]['id'])
    assert abs(compared['delta'] - .3) < 1e-9
    assert configs[0]['run_config_digest'] != configs[1]['run_config_digest']
    assert evaluations[0]['comparison_digest'] == evaluations[1]['comparison_digest']
    assert call('campaign.select', id=campaign['id'])['model_id'] == models[1]
    report = {'fixture_only': True, 'model_inference': False, 'runner_digest': runner['digest'],
              'evaluations': evaluations, 'delta': compared['delta'], 'config_restored': True,
              'original_checkout_deleted': True, 'python_version': platform.python_version()}
    (root / 'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))
finally:
    s.close()
