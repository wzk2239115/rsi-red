"""Real local Ray Jobs server tests; no fake client. Explicit invocation requires Ray extra."""

import hashlib
import sys
import time
import uuid

import pytest

from integration.ray.cluster import head


@pytest.fixture(scope="module")
def ray_client():
    with pytest.MonkeyPatch.context() as patch:
        import os

        local = os.environ.get("NO_PROXY", "") + ",127.0.0.1,localhost"
        patch.setenv("NO_PROXY", local)
        patch.setenv("no_proxy", local)
        with head() as instance:
            yield instance.client


def scheduler(client):
    from rsi_red.schedulers.ray import RayScheduler

    return RayScheduler(client=client, python_executable=sys.executable)


def wait(scheduler, key, terminal=None):
    terminal = terminal or {"succeeded", "failed", "cancelled", "timed_out"}
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        state = scheduler.status(key)
        if state["state"] in terminal:
            return state
        time.sleep(0.2)
    raise AssertionError("Ray job did not reach expected state: " + str(scheduler.status(key)))


def submit(client, tmp_path, code, *, seconds=30):
    path = tmp_path / "train.py"
    path.write_text(code)
    instance = scheduler(client)
    key = "rsi-" + uuid.uuid4().hex
    instance.submit(
        {
            "workdir": str(tmp_path),
            "entrypoint": ["python", "train.py"],
            "resources": {"gpus": 0, "cpus": 1, "walltime_seconds": seconds},
        },
        submission_key=key,
    )
    return instance, key


def test_real_ray_tasks_execute_and_logs_return(ray_client, tmp_path):
    instance, key = submit(
        ray_client,
        tmp_path,
        """import ray
ray.init(address="auto")
@ray.remote
def square(x): return x*x
print("ray-results", ray.get([square.remote(i) for i in range(4)]), flush=True)
""",
    )
    try:
        assert wait(instance, key)["state"] == "succeeded"
        assert "ray-results [0, 1, 4, 9]" in "\n".join(instance.logs(key))
        assert scheduler(ray_client).find(key) == key
    finally:
        instance.cancel(key)


def test_real_ray_cancel_running_job(ray_client, tmp_path):
    instance, key = submit(
        ray_client, tmp_path, 'import time\nprint("started",flush=True)\ntime.sleep(120)\n', seconds=150
    )
    try:
        wait(instance, key, {"running"})
        instance.cancel(key)
        assert wait(instance, key)["state"] == "cancelled"
    finally:
        instance.cancel(key)


def test_real_ray_failure_is_not_success(ray_client, tmp_path):
    instance, key = submit(ray_client, tmp_path, "raise SystemExit(7)\n")
    assert wait(instance, key)["state"] == "failed"


def test_real_ray_walltime_is_enforced(ray_client, tmp_path):
    instance, key = submit(ray_client, tmp_path, "import time\ntime.sleep(30)\n", seconds=1)
    try:
        assert wait(instance, key)["state"] == "timed_out"
    finally:
        instance.cancel(key)


def test_control_service_reopens_and_finds_same_ray_job(ray_client, tmp_path):
    from rsi_red.service import ResearchService
    from rsi_red.evaluation import UnconfiguredEvaluator

    root = tmp_path / "control"
    principals = {"token": {"id": "operator", "role": "operator"}}

    def open_service():
        return ResearchService(
            root=root,
            scheduler=scheduler(ray_client),
            evaluator=UnconfiguredEvaluator(),
            principals=principals,
        )

    service = open_service()
    release = tmp_path / "release"

    def call(operation, **payload):
        result = service.dispatch(token="token", operation=operation, payload=payload)
        assert result["error"] is None, result
        return result["data"]

    try:
        protocol = call(
            "protocol.register",
            name="ray-test",
            visibility="development",
            items=[{"id": "q", "task": "fixture", "prompt": "x", "answer": "x"}],
            evaluator_digest="sha256:" + "1" * 64,
            sampling={"max_tokens": 1, "temperature": 0},
            aggregation="task_mean",
            eval_seed=42,
        )
        campaign = call(
            "campaign.create",
            name="ray-real",
            members=["operator"],
            gpu_hours_budget=1,
            protocol_id=protocol["id"],
            require_decontamination=False,
        )
        output = tmp_path / "completed"
        source = tmp_path / "train.py"
        source.write_text(
            "import pathlib,time\n"
            f"p=pathlib.Path({str(release)!r})\n"
            "deadline=time.monotonic()+40\n"
            "while not p.exists():\n"
            "    if time.monotonic()>deadline: raise SystemExit(9)\n"
            "    time.sleep(.1)\n"
            f'pathlib.Path({str(output)!r}).write_text("done")\n'
        )
        job = call(
            "job.submit",
            campaign_id=campaign["id"],
            idempotency_key="restart",
            entrypoint=[sys.executable, str(source)],
            code={
                "uri": source.as_uri(),
                "digest": "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest(),
            },
            datasets=[],
            parents=[],
            resources={"gpus": 0, "cpus": 1, "walltime_seconds": 50},
            training_seed=42,
        )
        service.reconcile()
        initial = call("job.show", id=job["id"])
        sid = initial["scheduler_id"]
        assert sid
        service.close()
        release.touch()
        service = open_service()
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            service.reconcile()
            result = call("job.show", id=job["id"])
            if result["state"] in {"succeeded", "failed"}:
                break
            time.sleep(0.2)
        assert result["state"] == "succeeded"
        assert result["scheduler_id"] == sid
        assert result["attempt_count"] == 1
        assert output.read_text() == "done"
    finally:
        release.touch()
        service.close()


def test_authenticated_head_coexists_and_uses_explicit_interpreter(ray_client, tmp_path):
    with head(auth_mode="token") as instance:
        (tmp_path / "train.py").write_text('import sys\nprint("worker-python",sys.executable,flush=True)\n')
        key = "rsi-auth-" + uuid.uuid4().hex
        instance.submit(
            {
                "workdir": str(tmp_path),
                "entrypoint": ["python", "train.py"],
                "resources": {"gpus": 0, "cpus": 1, "walltime_seconds": 20},
            },
            submission_key=key,
        )
        assert wait(instance, key)["state"] == "succeeded"
        assert sys.executable in "\n".join(instance.logs(key))
        from rsi_red.schedulers.ray import RayScheduler, RayUnavailable

        with pytest.raises(RayUnavailable) as error:
            RayScheduler(address=instance.address, auth_mode="disabled", request_timeout=2).find(key)
        assert error.value.code == "RAY_AUTH_ERROR"
        assert isinstance(ray_client.list_jobs(), list)  # original head remains alive


def test_invalid_interpreter_reports_failure_without_training_stdout(ray_client, tmp_path):
    from rsi_red.schedulers.ray import RayScheduler

    instance = RayScheduler(client=ray_client, python_executable="/rsi-not-present/python")
    key = "rsi-bad-python-" + uuid.uuid4().hex
    instance.submit(
        {
            "workdir": str(tmp_path),
            "entrypoint": ["python", "train.py"],
            "resources": {"gpus": 0, "cpus": 1, "walltime_seconds": 10},
        },
        submission_key=key,
    )
    result = wait(instance, key)
    assert result["state"] == "failed"
    assert result["diagnostic"]
    assert instance.logs(key)


def test_head_restarts_at_same_url_without_replaying_old_jobs(ray_client, tmp_path):
    from integration.ray.cluster import unused_port

    port = unused_port()
    with head(dashboard_port=port) as instance:
        (tmp_path / "train.py").write_text('print("completed-before-head-restart",flush=True)\n')
        key = "rsi-restart-" + uuid.uuid4().hex
        instance.submit(
            {
                "workdir": str(tmp_path),
                "entrypoint": ["python", "train.py"],
                "resources": {"gpus": 0, "cpus": 1, "walltime_seconds": 20},
            },
            submission_key=key,
        )
        assert wait(instance, key)["state"] == "succeeded"
        assert instance.find(key) == key
    with head(dashboard_port=port) as replacement:
        # Keep the old adapter/client. Fresh head has no historical jobs, even at same URL.
        assert instance.find(key) is None
        from rsi_red.schedulers.ray import RayUnavailable

        with pytest.raises(RayUnavailable) as lost:
            instance.status(key)
        assert lost.value.code == "RAY_JOB_LOST"
        assert replacement.client.list_jobs() == []
        assert isinstance(ray_client.list_jobs(), list)


def test_real_sdk_http_requests_have_deadlines():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import json
    import threading
    from rsi_red.schedulers.ray import RayScheduler, RayUnavailable

    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if self.path == "/api/version":
                body = json.dumps({"ray_version": "2.59.0"}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                release.wait(5)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        instance = RayScheduler(
            address=f"http://127.0.0.1:{server.server_port}", auth_mode="disabled", request_timeout=0.1
        )
        started = time.monotonic()
        with pytest.raises(RayUnavailable):
            instance.find("hung-request")
        assert time.monotonic() - started < 3
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join()
