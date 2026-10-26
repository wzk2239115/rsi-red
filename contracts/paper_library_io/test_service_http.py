"""CLI -> live controller -> live fixture source -> parser -> durable knowledge."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from contracts.paper_library.support import CURATOR, VENUE, mechanism
from rsi_red.cli import call
from tests.support import ALICE, OPERATOR


def test_live_http_controller_persists_public_evidence_without_training(official_http, tmp_path):
    base, _, _ = official_http
    config = {'root': str(tmp_path / 'state'), 'listen': '127.0.0.1:0', 'scheduler': {'backend': 'local', 'allow_cpu_only': True},
              'paper_source': {'api_base': base, 'allow_loopback_fixture': True},
              'principals': {OPERATOR: {'id': 'operator', 'role': 'operator'}, CURATOR: {'id': 'curator', 'role': 'curator'},
                             ALICE: {'id': 'reader', 'role': 'researcher'}}}
    config_file, ready_file = tmp_path / 'config.json', tmp_path / 'ready.json'
    config_file.write_text(json.dumps(config))
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / 'src'), NO_PROXY='127.0.0.1,localhost')
    process = subprocess.Popen([sys.executable, '-m', 'rsi_red.server', '--config', str(config_file), '--ready-file', str(ready_file)],
                               env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 20
        while not ready_file.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.05)
        assert ready_file.exists(), process.stderr.read().decode() if process.poll() is not None else 'not ready'
        endpoint = json.loads(ready_file.read_text())['endpoint']
        def request(op, payload, token=CURATOR):
            result = call(endpoint, token, op, payload, 10)
            assert result['error'] is None, result
            return result['data']
        policy = request('paper.policy_register', {'name': 'HTTP synthetic', 'venues': [{'provider': 'openreview_v2', 'venue_id': VENUE,
            'year': 2026, 'track': 'main'}], 'require_full_text': True, 'batch_size_limit': 1000, 'max_parallel': 4,
            'max_pdf_bytes': 1048576, 'source_timeout_seconds': 5, 'retry_limit': 2}, OPERATOR)
        queued = request('paper.ingest', {'policy_id': policy['id'], 'provider': 'openreview_v2', 'record_id': 'http-a', 'idempotency_key': 'http-one'})
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            paper = request('paper.show', {'id': queued['id']})
            if paper['state'] != 'queued':
                break
            time.sleep(.05)
        assert paper['state'] == 'ready', paper
        document = request('paper.document', {'id': paper['id']})
        item = mechanism()
        item['citations'] = [{'page': 1, 'kind': 'body', 'quote': document['pages'][0]['text'].strip()}]
        extraction = request('paper.extract', {'paper_id': paper['id'], 'mechanisms': [item]})
        island = request('knowledge.create', {'extraction_id': extraction['id'], 'mechanism_key': item['key']})
        assert request('knowledge.show', {'id': island['id']}, ALICE)['local_validation'] == 'not_tested'
        assert request('knowledge.bridges', {}, ALICE)['items'] == []
        assert call(endpoint, CURATOR, 'protocol.list', {}, 5)['error']['code'] == 'FORBIDDEN'
        assert call(endpoint, CURATOR, 'direction.authorize', {}, 5)['error']['code'] == 'FORBIDDEN'
    finally:
        process.terminate()
        process.communicate(timeout=15)
    # Normal SQLite reopening, without any private fixture source installed.
    import sqlite3
    with sqlite3.connect(tmp_path / 'state/research.sqlite') as db:
        assert db.execute("SELECT COUNT(*) FROM entities WHERE kind IN ('job','eval','direction_authorization')").fetchone()[0] == 0
