"""Actual subprocess CLI and authenticated HTTP, with stored CPU fixture scores."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

from contracts.evaluation_direction.test_contract import bind_campaign, evaluate, metadata, register
from rsi_red.kanban import make_server
from tests.support import ALICE, OPERATOR


def test_cli_direction_to_comparison_selection_and_http_dashboard(rig, tmp_path):
    source = register(rig)
    bind_campaign(rig, source['id'])
    a = evaluate(rig, source['id'], .6, .6)
    b = evaluate(rig, source['id'], .2, .8)
    config = tmp_path / 'service.json'
    config.write_text(json.dumps({'root': str(rig.root), 'listen': '127.0.0.1:0',
        'scheduler': {'backend': 'local', 'allow_cpu_only': True},
        'evaluator': {'backend': 'unconfigured'}, 'principals': rig.principals}))
    ready = tmp_path / 'ready.json'
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / 'src'))
    process = subprocess.Popen([sys.executable, '-m', 'rsi_red.server', '--config', str(config),
        '--ready-file', str(ready)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    dashboard = None
    token_path = tmp_path / 'token'
    token_path.write_text(OPERATOR)
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.03)
        assert ready.exists(), 'HTTP control service did not become ready'
        endpoint = json.loads(ready.read_text())['endpoint']

        def cli(*args):
            completed = subprocess.run([sys.executable, '-m', 'rsi_red', '--endpoint', endpoint,
                '--token-file', str(token_path), *args, '--json'], env=env, capture_output=True,
                text=True, timeout=10)
            assert completed.returncode == 0, completed.stdout + completed.stderr
            return json.loads(completed.stdout)['data']

        target = metadata()
        target['math']['direction'] = 'maximize'
        auth = tmp_path / 'authorization.json'
        auth.write_text(json.dumps({'tasks': target, 'source_protocol_digest': source['digest'],
            'goal': 'CLI fixture operator explicitly authorizes math ASR maximize'}))
        grant = cli('direction', 'authorize', '--spec', str(auth))
        patch = tmp_path / 'derive.json'
        patch.write_text(json.dumps({'id': source['id'], 'direction_authorization_id': grant['id'],
            'task_overrides': {'math': {'direction': 'maximize'}}}))
        derived = cli('protocol', 'derive', '--spec', str(patch))
        assert derived['digest'] != source['digest']
        token_path.write_text(ALICE)
        assert cli('protocol', 'show', derived['id'])['spec']['task_metrics'] == target
        assert cli('eval', 'compare', a['id'], b['id'])['delta'] == pytest.approx(.3)
        assert len(cli('eval', 'list', '--campaign', rig.campaign)['items']) == 2
        selected = cli('campaign', 'select', rig.campaign)
        assert selected['normalized_mean_score'] == pytest.approx(.65)
        assert cli('campaign', 'submit', rig.campaign, '--model', selected['model_id'])['model_id'] == rig.base
        dashboard = make_server(port=0, demo=False, endpoint=endpoint, token=ALICE)
        thread = threading.Thread(target=dashboard.serve_forever, daemon=True)
        thread.start()
        url = f'http://127.0.0.1:{dashboard.server_port}/api/snapshot'
        with urllib.request.urlopen(url, timeout=5) as response:
            body = response.read().decode()
        snapshot = json.loads(body)
        assert snapshot['evaluations'][-1]['task_metrics'] == metadata()
        assert snapshot['evaluations'][-1]['normalized_score'] == pytest.approx(.8)
        for secret in ('one plus one', 'choose true', OPERATOR, ALICE, '"answer"'):
            assert secret not in body
        with pytest.raises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(urllib.request.Request(url, data=b'{}'), timeout=5)
        assert denied.value.code == 405
        denied.value.close()
    finally:
        if dashboard:
            dashboard.shutdown()
            dashboard.server_close()
            thread.join(timeout=5)
        process.terminate()
        process.communicate(timeout=5)
