"""A lightweight peer layout is operational separation, not a security sandbox."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from rsi_red.dev import initialize


def test_ray_profile_has_four_distinct_identities_and_explicit_backend(tmp_path):
    result = initialize(
        tmp_path / "peers",
        profile="ray-peers",
        ray_address="http://127.0.0.1:8265",
        python_executable="/opt/train/bin/python",
        cluster_image="train@sha256:" + "1" * 64,
    )
    config = json.loads(result["config"].read_text())
    assert config["scheduler"]["backend"] == "ray"
    assert config["scheduler"]["python_executable"] == "/opt/train/bin/python"
    assert config["telemetry"]["backend"] == "nvidia-smi"
    assert config["evaluator"]["backend"] == "unconfigured"
    assert sum(p["role"] == "researcher" for p in config["principals"].values()) == 4
    identities = json.loads(result["peers_file"].read_text())
    assert identities["isolation"] == "workspace-only"
    assert identities["expected_gpus"] == 8
    assert identities["gpus_detected"] is False
    assert len(identities["peers"]) == 4
    tokens = set()
    for peer in identities["peers"]:
        token = Path(peer["token_file"]).read_text().strip()
        tokens.add(token)
        assert config["principals"][token]["id"] == peer["researcher_id"]
        assert Path(peer["workspace"]).is_dir()
        assert Path(peer["token_file"]).stat().st_mode & 0o077 == 0
    assert len(tokens) == 4
    assert result["token_file"].read_text().strip() not in tokens


def test_peer_environment_can_be_sourced_from_paths_with_spaces(tmp_path):
    result = initialize(tmp_path / "workspace with spaces", profile="ray-peers")
    peers = json.loads(result["peers_file"].read_text())["peers"]
    environments = []
    for peer in peers:
        completed = subprocess.run(
            [
                "bash",
                "--noprofile",
                "--norc",
                "-c",
                'source "$1"; printf "%s\\n" "$RSI_TOKEN_FILE" "$RSI_WORKSPACE" "$TMPDIR" "$HF_HOME"',
                "bash",
                peer["environment_file"],
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        lines = completed.stdout.splitlines()
        assert lines[0] == peer["token_file"]
        assert lines[1] == peer["workspace"]
        assert all(Path(path).exists() for path in lines)
        environments.append(tuple(lines))
    assert len(set(environments)) == 4


def test_profile_does_not_overwrite_existing_deployment(tmp_path):
    result = initialize(tmp_path / "existing", profile="ray-peers")
    original = result["config"].read_bytes()
    with pytest.raises(FileExistsError):
        initialize(tmp_path / "existing", profile="ray-peers")
    assert result["config"].read_bytes() == original


def test_offline_init_ignores_stale_service_token_file(tmp_path):
    env = dict(
        os.environ,
        RSI_TOKEN_FILE=str(tmp_path / "missing-token"),
        PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"),
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "rsi_red",
            "init",
            "--profile",
            "ray-peers",
            "--output",
            str(tmp_path / "new"),
            "--json",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["error"] is None


@pytest.mark.parametrize(
    "options",
    [
        {"ray_auth_mode": "token"},
        {"ray_auth_mode": "disabled", "ray_token_file": "/private/token"},
        {"ray_auth_mode": "unknown"},
        {"python_executable": "relative/python"},
    ],
)
def test_invalid_configuration_fails_before_creating_deployment(tmp_path, options):
    output = tmp_path / "invalid"
    with pytest.raises(ValueError):
        initialize(output, profile="ray-peers", **options)
    assert not output.exists()


def test_token_mode_keeps_ray_secret_as_operator_file_reference(tmp_path):
    token = tmp_path / "ray token"
    token.write_text("private-test-value")
    token.chmod(0o600)
    result = initialize(
        tmp_path / "new", profile="ray-peers", ray_auth_mode="token", ray_token_file=str(token)
    )
    config = json.loads(result["config"].read_text())
    assert config["scheduler"]["auth_mode"] == "token"
    assert config["scheduler"]["auth_token_file"] == str(token.resolve())
    for script in (tmp_path / "new" / "peers").glob("*/environment.sh"):
        assert "private-test-value" not in script.read_text()
        assert str(token) not in script.read_text()


def test_initialization_has_no_network_process_or_ray_side_effects(tmp_path, monkeypatch):
    import socket
    import rsi_red.schedulers

    def forbidden(*args, **kwargs):
        raise AssertionError("Initialization must not execute or contact services")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(rsi_red.schedulers, "create_scheduler", forbidden)
    result = initialize(tmp_path / "new", profile="ray-peers")
    config = json.loads(result["config"].read_text())
    assert not Path(config["root"]).exists()
    assert not list((tmp_path / "new").rglob("*.sqlite"))
    peers = json.loads(result["peers_file"].read_text())["peers"]
    for peer in peers:
        token = Path(peer["token_file"]).read_text().strip()
        assert token not in Path(peer["environment_file"]).read_text()
        for child in ("workspace", "tmp", "cache", "logs", "outputs"):
            folder = Path(peer["workspace"]).parent / child
            assert folder.stat().st_mode & 0o077 == 0


def test_cli_exposes_profile_options_and_roundtrips_explicit_values(tmp_path):
    from tests.test_cli import cli

    help_result = cli("init", "--help")
    assert help_result.returncode == 0
    for option in (
        "--profile",
        "--ray-address",
        "--python-executable",
        "--cluster-image",
        "--ray-auth-mode",
        "--ray-token-file",
    ):
        assert option in help_result.stdout
    destination = tmp_path / "configured"
    result = cli(
        "init",
        "--profile",
        "ray-peers",
        "--output",
        str(destination),
        "--ray-address",
        "http://127.0.0.1:28265",
        "--python-executable",
        "/opt/train/bin/python",
        "--cluster-image",
        "test@sha256:" + "a" * 64,
        "--ray-auth-mode",
        "disabled",
        "--json",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    config = json.loads(Path(json.loads(result.stdout)["data"]["config"]).read_text())
    assert config["scheduler"]["address"] == "http://127.0.0.1:28265"
    assert config["scheduler"]["python_executable"] == "/opt/train/bin/python"
    assert config["scheduler"]["cluster_image"] == "test@sha256:" + "a" * 64
    assert config["scheduler"]["auth_mode"] == "disabled"
