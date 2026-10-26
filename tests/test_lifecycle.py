"""Real process acceptance; the trainer is a CPU fixture, not a real model trainer."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def test_job_survives_cli_exit_and_service_restart(tmp_path):
    """Service must own a detached worker. This cannot pass with scheduler doubles."""
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    config = tmp_path / "service.json"
    config.write_text(json.dumps({"root": str(tmp_path / "state"), "listen": "127.0.0.1:0",
        "scheduler": {"backend": "local", "allow_cpu_only": True},
        "principals": {"process-test-token": {"id": "operator", "role": "operator"}}}))
    ready = tmp_path / "ready.json"
    processes = []
    log = (tmp_path / "service.log").open("w+")

    def start():
        ready.unlink(missing_ok=True)
        process = subprocess.Popen([sys.executable, "-m", "rsi_red.server", "--config", str(config),
                                    "--ready-file", str(ready)], env=env, stdout=log, stderr=log)
        processes.append(process)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if process.poll() is not None:
                log.flush()
                assert False, f"Service exited before readiness: {(tmp_path / 'service.log').read_text()}"
            if ready.exists():
                return process, json.loads(ready.read_text())["endpoint"]
            time.sleep(0.05)
        raise AssertionError("service readiness timeout")

    def request(endpoint, operation, payload):
        completed = subprocess.run([sys.executable, "-m", "rsi_red", "--endpoint", endpoint,
            "--token-file", str(tmp_path / "token"), "request", operation,
            "--payload", json.dumps(payload), "--json"], env=env, capture_output=True, text=True, timeout=10)
        assert completed.returncode == 0, completed.stderr + completed.stdout
        result = json.loads(completed.stdout)
        assert result["error"] is None, result
        return result["data"]

    marker = tmp_path / "release-worker"
    output = tmp_path / "worker-finished"
    trainer = tmp_path / "train.py"
    trainer.write_text("import pathlib,sys,time\nmarker=pathlib.Path(sys.argv[1])\n"
                       "deadline=time.monotonic()+20\n"
                       "while not marker.exists():\n"
                       "    if time.monotonic()>deadline: raise SystemExit(9)\n"
                       "    time.sleep(.05)\n"
                       "pathlib.Path(sys.argv[2]).write_text('completed')\n")
    (tmp_path / "token").write_text("process-test-token")
    try:
        service, endpoint = start()
        protocol = request(endpoint, "protocol.register", {"name": "cpu-fixture", "visibility": "development",
            "items": [{"id": "q", "task": "fixture", "prompt": "x", "answer": "x"}],
            "evaluator_digest": "sha256:" + "1" * 64, "sampling": {"max_tokens": 1, "temperature": 0},
            "aggregation": "task_mean", "eval_seed": 1})
        campaign = request(endpoint, "campaign.create", {"name": "process-test", "members": ["operator"],
            "gpu_hours_budget": 1, "protocol_id": protocol["id"], "require_decontamination": False})
        job = request(endpoint, "job.submit", {"campaign_id": campaign["id"], "idempotency_key": "detached",
            "entrypoint": [sys.executable, str(trainer), str(marker), str(output)], "datasets": [], "parents": [],
            "code": {"uri": trainer.as_uri(), "digest": "sha256:" + __import__('hashlib').sha256(trainer.read_bytes()).hexdigest()},
            "resources": {"gpus": 0, "walltime_seconds": 30}, "training_seed": 1})
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            status = request(endpoint, "job.show", {"id": job["id"]})
            if status["state"] == "running":
                break
            time.sleep(0.1)
        assert status["state"] == "running"
        service.kill()
        service.wait(timeout=5)
        marker.write_text("go")
        service, endpoint = start()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            status = request(endpoint, "job.show", {"id": job["id"]})
            if status["state"] in {"succeeded", "failed"}:
                break
            time.sleep(0.1)
        assert status["state"] == "succeeded"
        assert output.read_text() == "completed"
        assert status["attempt_count"] == 1
    finally:
        marker.touch()
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        log.close()
