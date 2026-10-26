"""Own only a disposable CLI head, with independent ports, auth, logs and process group."""

from contextlib import contextmanager
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time


def unused_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def head(*, auth_mode="disabled", dashboard_port=None):
    owned = Path(tempfile.mkdtemp(prefix="rsi-ray-", dir="/tmp"))
    owned.chmod(0o700)
    token = owned / "auth-token"
    if auth_mode == "token":
        token.write_text(secrets.token_hex(32))
        token.chmod(0o600)
    env = dict(os.environ)
    for key in (
        "RAY_ADDRESS",
        "RAY_API_SERVER_ADDRESS",
        "RAY_AUTH_TOKEN",
        "RAY_AUTH_TOKEN_PATH",
        "RAY_GCS_SERVER_PORT",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        env.pop(key, None)
    env.update(
        RAY_AUTH_MODE=auth_mode,
        RAY_USAGE_STATS_ENABLED="0",
        PATH=str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", ""),
        NO_PROXY="127.0.0.1,localhost",
        no_proxy="127.0.0.1,localhost",
    )
    if auth_mode == "token":
        env["RAY_AUTH_TOKEN_PATH"] = str(token)
    port = dashboard_port or unused_port()
    argv = [
        sys.executable,
        "-m",
        "ray.scripts.scripts",
        "start",
        "--head",
        "--block",
        "--port=0",
        "--node-ip-address=127.0.0.1",
        "--dashboard-host=127.0.0.1",
        f"--dashboard-port={port}",
        "--include-dashboard=true",
        "--num-cpus=2",
        "--num-gpus=0",
        "--object-store-memory=100000000",
        f"--temp-dir={owned}",
        "--disable-usage-stats",
    ]
    # Ray 2.59 defaults its dashboard agent HTTP port to 52365, even with an ephemeral GCS.
    for flag in (
        "dashboard-agent-listen-port",
        "dashboard-agent-grpc-port",
        "runtime-env-agent-port",
        "metrics-export-port",
        "ray-client-server-port",
    ):
        argv.append(f"--{flag}={unused_port()}")
    log = (owned / "launcher.log").open("w")
    process = subprocess.Popen(argv, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        from rsi_red.schedulers.ray import RayScheduler

        scheduler = RayScheduler(
            address=f"http://127.0.0.1:{port}",
            auth_mode=auth_mode,
            shared_filesystem=True,
            auth_token_file=str(token) if auth_mode == "token" else None,
            request_timeout=2,
            python_executable=sys.executable,
        )
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Owned Ray head exited; inspect reports/ray-logs")
            try:
                scheduler.reconnect()
                scheduler.client.list_jobs()
                break
            except Exception:
                time.sleep(0.2)
        else:
            raise RuntimeError("Owned Ray head not ready within 60 seconds")
        yield scheduler
    finally:
        # Never run `ray stop`: it would terminate unrelated heads on this host.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        log.close()
        destination = Path("reports/ray-logs") / owned.name
        destination.mkdir(parents=True, exist_ok=True)
        logs = owned / "session_latest" / "logs"
        if logs.exists():
            shutil.copytree(logs, destination, dirs_exist_ok=True, ignore=shutil.ignore_patterns("*.sock"))
        shutil.copy2(owned / "launcher.log", destination / "launcher.log")
        shutil.rmtree(owned, ignore_errors=True)
