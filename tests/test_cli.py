"""Executable public CLI tests: no fixture substitutes for missing product code."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


def cli(*args):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    env.pop("RSI_TOKEN", None)
    return subprocess.run([sys.executable, "-m", "rsi_red", *args], capture_output=True,
                          text=True, timeout=10, env=env)


def test_help_is_successful_without_backend_credentials():
    result = cli("--help")
    assert result.returncode == 0, result.stderr
    for command in ["job", "eval", "data", "artifact", "campaign", "events"]:
        assert command in result.stdout


def test_version_agrees_with_package_metadata():
    import tomllib
    metadata = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
    result = cli("--version")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == metadata["project"]["version"]


@pytest.mark.parametrize("args,code", [
    (["does-not-exist"], "INVALID_COMMAND"),
    (["job", "show"], "INVALID_ARGUMENT"),
    (["eval", "submit", "--unknown-option"], "INVALID_ARGUMENT"),
])
def test_invalid_invocation_emits_single_structured_json(args, code):
    result = cli(*args, "--json")
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "1"
    assert payload["data"] is None
    assert payload["error"]["code"] == code
    assert payload["error"]["retryable"] is False
    assert "Traceback" not in result.stderr


def test_unreachable_backend_is_retryable_not_hang():
    result = cli("--endpoint", "http://127.0.0.1:1", "--timeout", "0.1", "job", "show", "job-1", "--json")
    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert payload["error"]["retryable"] is True
