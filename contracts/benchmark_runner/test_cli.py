import json

from rsi_red import cli
from rsi_red.errors import envelope


def test_eval_runner_model_flags_delegate_unmodified(monkeypatch, capsys):
    calls = []
    def request(endpoint, token, operation, payload, timeout):
        calls.append((operation, payload))
        return envelope({'id': 'eval-cli', 'state': 'accepted'})
    monkeypatch.setattr(cli, 'call', request)
    assert cli.main(['eval', 'submit', '--runner', 'runner-v1', '--model', 'artifact-v2', '--json']) == 0
    assert calls == [('eval.submit', {'runner_id': 'runner-v1', 'model_id': 'artifact-v2'})]
    assert json.loads(capsys.readouterr().out)['data']['id'] == 'eval-cli'


def test_runner_cli_register_show_and_config_help_are_available():
    parser = cli.parser()
    assert parser.parse_args(['runner', 'register', '--spec', 'runner.json']).verb == 'register'
    assert parser.parse_args(['runner', 'show', 'runner-id']).id == 'runner-id'
    assert parser.parse_args(['eval', 'config', 'eval-id']).id == 'eval-id'
