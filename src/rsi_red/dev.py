"""Generate deployment files offline; initialization never launches sessions or jobs."""

import json
import os
from pathlib import Path
import secrets
import shlex
import sys


def private_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)


def private_file(path, content):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(content)


def initialize(
    output,
    *,
    profile="local",
    with_auditor=False,
    ray_address="http://127.0.0.1:8265",
    python_executable=None,
    cluster_image=None,
    ray_auth_mode="auto",
    ray_token_file=None,
):
    if profile not in {"local", "ray-peers"}:
        raise ValueError("Unknown initialization profile")
    if with_auditor and profile != "ray-peers":
        raise ValueError("Auditor profile requires ray-peers")
    if ray_auth_mode not in {"auto", "token", "disabled"}:
        raise ValueError("Invalid Ray authentication mode")
    if ray_auth_mode == "token" and not ray_token_file:
        raise ValueError("Token mode requires a Ray token file reference")
    if ray_auth_mode == "disabled" and ray_token_file:
        raise ValueError("Disabled auth cannot specify a Ray token file")
    if python_executable and not Path(python_executable).is_absolute():
        raise ValueError("Node Python must be an absolute path")
    output = Path(output).resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    token = secrets.token_urlsafe(32)
    token_file, config_file = output / "token", output / "service.json"
    config = {
        "root": str(output / "state"),
        "listen": "127.0.0.1:8787",
        "scheduler": {"backend": "local", "allow_cpu_only": True},
        "evaluator": {"backend": "simulation"},
        "principals": {token: {"id": "local-operator", "role": "operator"}},
    }
    result = {"config": config_file, "token_file": token_file, "ready_file": output / "ready.json"}
    if profile == "ray-peers":
        config["principals"][token]["id"] = "operator"
        config["scheduler"] = {
            "backend": "ray",
            "shared_filesystem": True,
            "address": ray_address,
            "python_executable": python_executable or sys.executable,
            "request_timeout": 5,
            "auth_mode": ray_auth_mode,
        }
        if ray_token_file:
            config["scheduler"]["auth_token_file"] = str(Path(ray_token_file).resolve())
        if cluster_image:
            config["scheduler"]["cluster_image"] = cluster_image
        config["evaluator"] = {"backend": "unconfigured"}
        config["telemetry"] = {"backend": "nvidia-smi"}
        private_directory(output / "peers")
        private_directory(output / "shared")
        for name in ("models", "datasets"):
            private_directory(output / "shared" / name)
        peers = []
        for name in ("agent-1", "agent-2", "agent-3", "agent-4"):
            folder = output / "peers" / name
            private_directory(folder)
            for sub in ("workspace", "tmp", "cache", "logs", "outputs"):
                private_directory(folder / sub)
            credential = secrets.token_urlsafe(32)
            credential_file = folder / "token"
            config["principals"][credential] = {"id": name, "role": "researcher"}
            private_file(credential_file, credential + "\n")
            environment_file = folder / "environment.sh"
            values = {
                "RSI_ENDPOINT": "http://127.0.0.1:8787",
                "RSI_TOKEN_FILE": str(credential_file),
                "RSI_WORKSPACE": str(folder / "workspace"),
                "TMPDIR": str(folder / "tmp"),
                "HF_HOME": str(folder / "cache"),
                "RSI_LOG_DIR": str(folder / "logs"),
                "RSI_OUTPUT_DIR": str(folder / "outputs"),
                "RSI_SHARED_MODELS": str(output / "shared" / "models"),
                "RSI_SHARED_DATASETS": str(output / "shared" / "datasets"),
            }
            script = "# Workspace separation only; same Unix user, no security sandbox.\n"
            script += "".join(
                "export " + key + "=" + shlex.quote(value) + "\n" for key, value in values.items()
            )
            private_file(environment_file, script)
            peers.append(
                {
                    "researcher_id": name,
                    "workspace": str(folder / "workspace"),
                    "token_file": str(credential_file),
                    "environment_file": str(environment_file),
                }
            )
        profile_data = {"isolation": "workspace-only", "expected_gpus": 8, "gpus_detected": False, "peers": peers}
        if with_auditor:
            folder = output / "auditor"
            private_directory(folder)
            private_directory(folder / "workspace")
            credential = secrets.token_urlsafe(32)
            credential_file = folder / "token"
            config["principals"][credential] = {"id": "auditor-1", "role": "auditor"}
            private_file(credential_file, credential + "\n")
            environment_file = folder / "environment.sh"
            private_file(environment_file, "# Workspace separation only; no OS security boundary.\n" +
                         "export RSI_ENDPOINT=http://127.0.0.1:8787\n" +
                         "export RSI_TOKEN_FILE=" + shlex.quote(str(credential_file)) + "\n" +
                         "export RSI_WORKSPACE=" + shlex.quote(str(folder / "workspace")) + "\n")
            profile_data["auditor"] = {"auditor_id": "auditor-1", "workspace": str(folder / "workspace"),
                                       "token_file": str(credential_file), "environment_file": str(environment_file)}
        peers_file = output / "peers.json"
        private_file(
            peers_file,
            json.dumps(
                profile_data,
                indent=2,
            )
            + "\n",
        )
        result["peers_file"] = peers_file
    private_file(token_file, token + "\n")
    private_file(config_file, json.dumps(config, indent=2) + "\n")
    return result
