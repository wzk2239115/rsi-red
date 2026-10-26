import json

from rsi_red import cli
from rsi_red.errors import envelope


def test_paper_and_knowledge_cli_parser_exposes_planned_operations():
    parser = cli.parser()
    assert parser.parse_args(['paper', 'ingest', '--spec', 'paper.json']).verb == 'ingest'
    assert parser.parse_args(['paper', 'batch_show', 'batch-id']).id == 'batch-id'
    assert parser.parse_args(['knowledge', 'create', '--spec', 'mechanism.json']).verb == 'create'
    assert parser.parse_args(['knowledge', 'show', 'island-id']).id == 'island-id'


def test_knowledge_pack_cli_preserves_constraints(monkeypatch, tmp_path, capsys):
    calls = []
    request = {'signals': ['rollout'], 'capabilities': [], 'limit': 3, 'context_budget_chars': 1600}
    path = tmp_path / 'pack.json'
    path.write_text(json.dumps(request))
    def call(endpoint, token, operation, payload, timeout):
        calls.append((operation, payload))
        return envelope({'cards': [], 'context': '', 'context_chars': 0})
    monkeypatch.setattr(cli, 'call', call)
    assert cli.main(['knowledge', 'pack', '--spec', str(path), '--json']) == 0
    assert calls == [('knowledge.pack', request)]
    assert json.loads(capsys.readouterr().out)['data']['context_chars'] == 0
