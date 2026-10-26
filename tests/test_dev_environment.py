import importlib
import json
import os
import stat
import subprocess
import sys


def test_init_creates_private_credentials_and_simulation_config(tmp_path):
    init = importlib.import_module("rsi_red.dev").initialize
    result = init(tmp_path / "dev")
    config = json.loads(result["config"].read_text())
    token = result["token_file"].read_text().strip()
    assert len(token) >= 32
    assert config["principals"][token]["role"] == "operator"
    assert config["scheduler"]["backend"] == "local"
    assert config["evaluator"]["backend"] == "simulation"
    assert stat.S_IMODE(result["token_file"].stat().st_mode) == 0o600
    assert stat.S_IMODE(result["config"].stat().st_mode) == 0o600
    assert config["listen"].startswith("127.0.0.1:")


def test_init_does_not_replace_existing_secrets(tmp_path):
    init = importlib.import_module("rsi_red.dev").initialize
    result = init(tmp_path / "dev")
    token = result["token_file"].read_text()
    import pytest
    with pytest.raises(FileExistsError):
        init(tmp_path / "dev")
    assert result["token_file"].read_text() == token


def test_cli_simulation_is_explicit_and_usable(tmp_path):
    from pathlib import Path
    environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    completed = subprocess.run([sys.executable, "-m", "rsi_red", "demo", "--output", str(tmp_path / "demo"),
                                "--json"], capture_output=True, text=True, env=environment, timeout=20)
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["data"]["simulation"] is True
    assert report["data"]["final_score"] > report["data"]["base_score"]
