"""Authenticated HTTP/CLI and browser snapshot boundary, without transport mocks."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.request

from contracts.benchmark_runner.support import register
from rsi_red import cli
from rsi_red.kanban import make_server
from tests.support import ALICE, OPERATOR


def test_real_cli_http_runner_and_safe_kanban(rig, capsys):
    runner = register(rig)
    ready = rig.root / 'http-ready.json'
    config = rig.root / 'http-service.json'
    config.write_text(json.dumps({'root': str(rig.root), 'listen': '127.0.0.1:0', 'principals': rig.principals,
                                 'scheduler': {'backend': 'local', 'allow_cpu_only': True}}))
    rig.close()
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
    with (rig.root / 'http-server.log').open('w') as log:
        process = subprocess.Popen([sys.executable, '-m', 'rsi_red.server', '--config', str(config),
                                    '--ready-file', str(ready)], stdout=log, stderr=log, env=env)
    try:
        deadline = time.monotonic() + 15
        while not ready.exists():
            assert process.poll() is None
            assert time.monotonic() < deadline
            time.sleep(.03)
        endpoint = json.loads(ready.read_text())['endpoint']
        token = rig.root / 'http-token'
        token.write_text(ALICE)
        prefix = ['--endpoint', endpoint, '--token-file', str(token)]
        assert cli.main(prefix + ['eval', 'submit', '--runner', runner['id'], '--model', rig.base, '--json']) == 0
        pending = json.loads(capsys.readouterr().out)['data']
        deadline = time.monotonic() + 15
        while True:
            result = cli.call(endpoint, ALICE, 'eval.show', {'id': pending['id']}, 5)['data']
            if result['state'] in {'failed', 'succeeded'}:
                break
            assert time.monotonic() < deadline
            time.sleep(.05)
        assert result['state'] == 'succeeded'
        denied = cli.call(endpoint, ALICE, 'eval.config', {'id': result['id']}, 5)
        assert denied['error']['code'] == 'EVALUATION_DETAILS_RESTRICTED'
        assert cli.call(endpoint, OPERATOR, 'eval.config', {'id': result['id']}, 5)['data']['execution_receipt']['exit_code'] == 0
        server = make_server(port=0, demo=False, endpoint=endpoint, token=ALICE)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/api/snapshot', timeout=5) as response:
                snapshot = json.load(response)
            row = next(e for e in snapshot['evaluations'] if e['id'] == result['id'])
            assert row['runner_digest'] == runner['digest']
            assert row['comparison_digest']
            assert row['task_metrics']['math']['direction'] == 'minimize'
            assert row['task_metrics']['logic']['direction'] == 'maximize'
            for private in ('one plus one', 'choose true', 'fixture prediction', '"bindings"', '"command"', str(rig.root), ALICE):
                assert private not in json.dumps(snapshot)
            with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/app.js') as response:
                assert 'row.comparison_digest' in response.read().decode()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(3)
    finally:
        process.terminate()
        process.wait(timeout=15)
        rig.open()


def test_cli_rejects_mixed_spec_and_flags(tmp_path, capsys):
    spec = Path(tmp_path) / 'eval.json'
    spec.write_text('{}')
    assert cli.main(['eval', 'submit', '--spec', str(spec), '--runner', 'runner-id', '--model', 'model-id']) == 2
    assert json.loads(capsys.readouterr().out)['error']['code'] == 'INVALID_ARGUMENT'
