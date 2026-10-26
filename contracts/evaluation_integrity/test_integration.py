"""Additional negative paths, installed command routing and safe dashboard contracts."""
import json

from tests.support import OPERATOR, Rig
from contracts.evaluation_integrity.test_privacy import AUDITOR, configure, submit


def setup(tmp_path):
    r = Rig(tmp_path).setup()
    r.principals[AUDITOR] = {'id': 'auditor', 'role': 'auditor'}
    r.close()
    return r.open()


def test_role_remains_read_only_even_if_mistakenly_a_campaign_member(tmp_path):
    r = setup(tmp_path)
    try:
        with r.service.store.transaction():
            campaign = r.service.store.get(r.campaign, 'campaign')
            campaign['members'].append('auditor')
            r.service.store.save('campaign', campaign)
        configure(r)
        for op, payload in [('eval.submit', {'campaign_id': r.campaign}),
                            ('artifact.register', {}), ('note.add', {}),
                            ('campaign.submit', {}), ('job.submit', r.job_request())]:
            r.error(op, payload, 'FORBIDDEN', token=AUDITOR)
    finally:
        r.close()


def test_foreign_evidence_idempotency_conflict_and_receipt_forgery(tmp_path):
    r = setup(tmp_path)
    try:
        policy = configure(r)
        evaluation = r.evaluate()
        case = submit(r, policy, evaluation)
        other = r.evaluate()
        r.error('audit.submit', {'campaign_id': r.campaign, 'model_id': r.base,
            'eval_id': other['id'], 'policy_id': policy['id'], 'idempotency_key': 'case'}, 'IDEMPOTENCY_CONFLICT')
        r.error('audit.observe', {'id': case['id'], 'text': 'suspicion', 'evidence_ids': [r.dataset]},
                'FORBIDDEN', token=AUDITOR)
        r.error('audit.record', {'id': case['id'], 'state': 'checks_passed'}, 'FORBIDDEN', token=OPERATOR)
        r.service.reconcile_audits()
        r.close()
        r.open()
        assert r.ok('audit.show', {'id': case['id']})['state'] == 'checks_passed'
        assert len(r.ok('audit.feedback', {'campaign_id': r.campaign})['items']) == 1
        r.service.reconcile_audits()
        assert len(r.ok('audit.feedback', {'campaign_id': r.campaign})['items']) == 1
    finally:
        r.close()


def test_unconfigured_checks_never_certify_and_auditor_scope_is_revocable(tmp_path):
    r = setup(tmp_path)
    try:
        policy = configure(r, grader_mode='unconfigured')
        case = submit(r, policy)
        r.service.reconcile_audits()
        assert r.ok('audit.show', {'id': case['id']})['state'] == 'incomplete'
        # A distinct campaign and development protocol must not be visible through the grant.
        other = r.ok('campaign.create', {'name':'other', 'members':['alice'], 'gpu_hours_budget':1,
                    'protocol_id': r.protocol}, token=OPERATOR)
        r.error('audit.list', {'campaign_id': other['id']}, 'FORBIDDEN', token=AUDITOR)
    finally:
        r.close()


def test_cli_routes_all_audit_commands_and_safe_model_report(monkeypatch, tmp_path, capsys):
    from rsi_red.cli import main
    calls = []
    monkeypatch.setenv('RSI_TOKEN', 'test')
    monkeypatch.delenv('RSI_TOKEN_FILE', raising=False)
    def call(endpoint, token, operation, payload, timeout):
        calls.append((operation, payload))
        return {'data': {}, 'error': None}
    monkeypatch.setattr('rsi_red.cli.call', call)
    spec = tmp_path / 'case.json'
    spec.write_text(json.dumps({'campaign_id': 'campaign'}))
    for action in ('configure', 'submit', 'observe'):
        assert main(['audit', action, '--spec', str(spec)]) == 0
        assert calls[-1] == ('audit.' + action, {'campaign_id':'campaign'})
    for action in ('show', 'ack'):
        assert main(['audit', action, 'item']) == 0
        assert calls[-1] == ('audit.' + action, {'id':'item'})
    assert main(['audit', 'feedback', '--campaign', 'c', '--after', 'f', '--limit', '2']) == 0
    assert calls[-1] == ('audit.feedback', {'campaign_id':'c','after':'f','limit':2})
    assert main(['eval', 'model', 'm']) == 0
    assert calls[-1] == ('eval.model', {'id':'m'})
    capsys.readouterr()


def test_dashboard_only_projects_safe_audit_fields(tmp_path):
    from rsi_red.kanban import snapshot
    r = setup(tmp_path)
    try:
        policy = configure(r)
        case = submit(r, policy)
        r.ok('audit.observe', {'id':case['id'], 'text':'PRIVATE QUESTION AND ANSWER',
                              'evidence_ids':[case['eval_id']]}, token=AUDITOR)
        result = snapshot(lambda op, payload: r.ok(op, payload, token=OPERATOR))
        assert result['audits'][0]['id'] == case['id']
        assert result['audit_feedback'][0]['status'] == 'suspected'
        assert result['audit_feedback'][0]['acknowledged_by'] == []
        assert 'PRIVATE' not in json.dumps(result)
    finally:
        r.close()


def test_optional_auditor_profile_has_a_distinct_restricted_credential(tmp_path):
    from rsi_red.dev import initialize
    import stat
    result = initialize(tmp_path / 'deployment', profile='ray-peers', with_auditor=True)
    config = json.loads(result['config'].read_text())
    peers = json.loads(result['peers_file'].read_text())
    assert len(peers['peers']) == 4
    auditor = peers['auditor']
    assert auditor['auditor_id'] == 'auditor-1'
    from pathlib import Path
    token = Path(auditor['token_file']).read_text().strip()
    assert config['principals'][token] == {'id':'auditor-1', 'role':'auditor'}
    assert stat.S_IMODE(Path(auditor['token_file']).stat().st_mode) == 0o600
    assert 'RSI_TOKEN_FILE' in Path(auditor['environment_file']).read_text()
    assert Path(auditor['workspace']).is_dir()
    assert not (result['config'].parent / 'state').exists()  # no service/cluster side effect


def test_background_http_reconciler_and_real_cli_enforce_projection(tmp_path):
    import os
    from pathlib import Path
    import subprocess
    import sys
    import time
    from rsi_red.cli import call
    r = setup(tmp_path / 'state')
    policy = configure(r)
    case = submit(r, policy)
    campaign_id, model_id = r.campaign, r.base
    principals = r.principals
    r.close()
    config = tmp_path / 'service.json'
    config.write_text(json.dumps({'root':str(tmp_path / 'state'), 'listen':'127.0.0.1:0',
        'scheduler': {'backend':'local', 'allow_cpu_only':True}, 'principals':principals}))
    ready = tmp_path / 'ready.json'
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / 'src'), RSI_TOKEN=next(
        token for token, actor in principals.items() if actor['id'] == 'alice'))
    env.pop('RSI_TOKEN_FILE', None)
    process = subprocess.Popen([sys.executable, '-m', 'rsi_red.server', '--config', str(config),
                                '--ready-file', str(ready)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline and process.poll() is None:
            time.sleep(.02)
        assert ready.exists(), process.poll()
        endpoint = json.loads(ready.read_text())['endpoint']
        while time.monotonic() < deadline:
            result = call(endpoint, env['RSI_TOKEN'], 'audit.show', {'id':case['id']}, 2)
            assert result['error'] is None
            if result['data']['state'] == 'checks_passed':
                break
            time.sleep(.02)
        assert result['data']['state'] == 'checks_passed'
        result = subprocess.run([sys.executable, '-m', 'rsi_red', '--endpoint', endpoint,
                                 'eval', 'model', model_id, '--json'], env=env,
                                capture_output=True, text=True, timeout=5)
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)['data']
        assert len(report['audits']) == 1 and 'one plus one' not in result.stdout
        feedback = call(endpoint, env['RSI_TOKEN'], 'audit.feedback', {'campaign_id':campaign_id}, 2)['data']
        assert feedback['items'][0]['status'] == 'checks_passed'
    finally:
        process.terminate()
        process.communicate(timeout=5)


def test_auditor_protocol_listing_obeys_grants_and_revocation(tmp_path):
    from copy import deepcopy
    r = setup(tmp_path)
    try:
        configure(r)
        spec = deepcopy(r.ok('protocol.show', {'id': r.protocol}, token=OPERATOR)['spec'])
        spec['name'] = 'another-private-development-suite'
        other = r.ok('protocol.register', spec, token=OPERATOR)
        listed = r.ok('protocol.list', {'campaign_id': r.campaign}, token=AUDITOR)['items']
        assert {p['id'] for p in listed} == {r.protocol}
        assert other['id'] not in json.dumps(r.ok('protocol.list', {}, token=AUDITOR))
        r.service.principals['replacement'] = {'id':'another-auditor','role':'auditor'}
        r.ok('audit.configure', {'campaign_id':r.campaign,'protocol_id':r.protocol,
                               'auditor_ids':['another-auditor'],'checks':['grader_consistency']}, token=OPERATOR)
        r.error('protocol.show', {'id': r.protocol}, 'FORBIDDEN', token=AUDITOR)
        assert r.ok('protocol.list', {}, token=AUDITOR)['items'] == []
    finally:
        r.close()
