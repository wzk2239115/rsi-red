"""A lightweight peer layout is operational separation, not a security sandbox."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from rsi_red.dev import initialize


def test_ray_profile_has_four_distinct_identities_and_explicit_backend(tmp_path):
    result = initialize(tmp_path / 'peers', profile='ray-peers', ray_address='http://127.0.0.1:8265',
                        python_executable='/opt/train/bin/python', cluster_image='train@sha256:'+'1'*64)
    config = json.loads(result['config'].read_text())
    assert config['scheduler']['backend'] == 'ray'
    assert config['scheduler']['python_executable'] == '/opt/train/bin/python'
    assert config['telemetry']['backend'] == 'nvidia-smi'
    assert config['evaluator']['backend'] == 'unconfigured'
    assert sum(p['role'] == 'researcher' for p in config['principals'].values()) == 4
    identities = json.loads(result['peers_file'].read_text())
    assert identities['isolation'] == 'workspace-only'
    assert identities['expected_gpus'] == 8
    assert identities['gpus_detected'] is False
    assert len(identities['peers']) == 4
    tokens = set()
    for peer in identities['peers']:
        token = Path(peer['token_file']).read_text().strip()
        tokens.add(token)
        assert config['principals'][token]['id'] == peer['researcher_id']
        assert Path(peer['workspace']).is_dir()
        assert Path(peer['token_file']).stat().st_mode & 0o077 == 0
    assert len(tokens) == 4
    assert result['token_file'].read_text().strip() not in tokens


def test_peer_environment_can_be_sourced_from_paths_with_spaces(tmp_path):
    result = initialize(tmp_path / 'workspace with spaces', profile='ray-peers')
    peers = json.loads(result['peers_file'].read_text())['peers']
    environments = []
    for peer in peers:
        completed = subprocess.run(['bash','--noprofile','--norc','-c',
            'source "$1"; printf "%s\\n" "$RSI_TOKEN_FILE" "$RSI_WORKSPACE" "$TMPDIR" "$HF_HOME"',
            'bash',peer['environment_file']], capture_output=True,text=True,check=True)
        lines = completed.stdout.splitlines()
        assert lines[0] == peer['token_file']
        assert lines[1] == peer['workspace']
        assert all(Path(path).exists() for path in lines)
        environments.append(tuple(lines))
    assert len(set(environments)) == 4


def test_profile_does_not_overwrite_existing_deployment(tmp_path):
    result = initialize(tmp_path / 'existing', profile='ray-peers')
    original = result['config'].read_bytes()
    with pytest.raises(FileExistsError):
        initialize(tmp_path / 'existing', profile='ray-peers')
    assert result['config'].read_bytes() == original


def test_offline_init_ignores_stale_service_token_file(tmp_path):
    env = dict(os.environ, RSI_TOKEN_FILE=str(tmp_path / 'missing-token'),
               PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'))
    result = subprocess.run([sys.executable,'-m','rsi_red','init','--profile','ray-peers',
                             '--output',str(tmp_path / 'new'),'--json'],env=env,
                            capture_output=True,text=True,timeout=10)
    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout)['error'] is None
