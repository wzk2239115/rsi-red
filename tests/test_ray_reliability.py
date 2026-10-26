"""Fault injection at the external Ray boundary; no cluster credentials required."""

import importlib
import sys

import pytest

from tests.test_ray_scheduler import Client, request
from tests.support import Rig


def adapter(**kwargs):
    return importlib.import_module("rsi_red.schedulers.ray").RayScheduler(**kwargs)


def test_read_reconnect_rebuilds_client_without_resubmitting(tmp_path):
    first, second = Client(), Client()
    second.submit_job(submission_id="job", metadata={})

    def broken(key):
        raise ConnectionError("old endpoint")

    first.get_job_info = broken
    clients = iter([first, second])
    scheduler = adapter(client_factory=lambda **kwargs: next(clients))
    assert scheduler.find("job") == "job"
    assert len(second.submissions) == 1


def test_explicit_python_overrides_bare_python_and_is_preserved(tmp_path):
    client = Client()
    scheduler = adapter(client=client, python_executable="/opt/train/bin/python")
    scheduler.submit(request(tmp_path), submission_key="job")
    assert client.submissions[0]["entrypoint"].startswith("/opt/train/bin/python ")
    assert "/opt/train/bin/python" in next(tmp_path.glob("_rsi_ray_*.py")).read_text()
    assert client.submissions[0]["runtime_env"]["env_vars"]["PATH"].startswith("/opt/train/bin:")


def test_default_absolute_interpreter_is_not_replaced_with_bare_python(tmp_path):
    client = Client()
    req = request(tmp_path)
    req["entrypoint"][0] = sys.executable
    adapter(client=client).submit(req, submission_key="job")
    assert sys.executable in next(tmp_path.glob("_rsi_ray_*.py")).read_text()


def test_runtime_env_failure_has_diagnostic_even_without_logs(tmp_path):
    client = Client()
    scheduler = adapter(client=client)
    scheduler.submit(request(tmp_path), submission_key="job")
    client.jobs["job"].status = "FAILED"
    client.jobs["job"].error_type = "RUNTIME_ENV_SETUP_FAILURE"
    client.jobs["job"].message = "working_dir package download failed"
    client.get_job_logs = lambda key: ""
    status = scheduler.status("job")
    assert status["reason"] == "runtime_env_setup_failed"
    assert status["diagnostic"] == "working_dir package download failed"
    assert any("working_dir package download failed" in line for line in scheduler.logs("job"))


def test_token_file_is_in_header_not_runtime_env_or_metadata(tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("private-auth-fixture")
    token_file.chmod(0o600)
    seen = []
    client = Client()

    def factory(**kwargs):
        seen.append(kwargs)
        return client

    scheduler = adapter(client_factory=factory, auth_mode="token", auth_token_file=str(token_file))
    scheduler.submit(request(tmp_path), submission_key="job")
    assert seen[0]["headers"]["Authorization"] == "Bearer private-auth-fixture"
    assert "private-auth-fixture" not in str(client.submissions)
    token_file.write_text("rotated-fixture")
    scheduler.reconnect()
    assert seen[-1]["headers"]["Authorization"] == "Bearer rotated-fixture"


def test_auth_error_is_visible_and_does_not_become_missing_job():
    client = Client()

    class AuthenticationError(ConnectionError):
        pass

    def denied(key):
        raise AuthenticationError("Missing authentication token: secret-value")

    client.get_job_info = denied
    with pytest.raises(TimeoutError) as error:
        adapter(client=client).find("job")
    assert error.value.code == "RAY_AUTH_ERROR"
    assert "secret-value" not in str(error.value)


def test_ambiguous_submit_is_never_retried_by_adapter(tmp_path):
    client = Client()
    attempts = []

    def lost(**kwargs):
        attempts.append(kwargs)
        raise ConnectionError("accepted, response lost")

    client.submit_job = lost
    with pytest.raises(TimeoutError):
        adapter(client=client).submit(request(tmp_path), submission_key="job")
    assert len(attempts) == 1


def test_transient_scheduler_failure_is_visible_stalls_and_recovers(tmp_path):
    rig = Rig(tmp_path).setup()
    try:
        job = rig.submit()
        real_find = rig.cluster.find

        def broken(*args):
            raise TimeoutError("offline")

        rig.cluster.find = broken
        rig.reconcile()
        state = rig.job(job["id"])
        assert state["scheduler_health"]["status"] == "degraded"
        rig.clock.advance(301)
        rig.reconcile()
        assert rig.job(job["id"])["scheduler_health"]["status"] == "stalled"
        events = [e for e in rig.events() if e["type"] == "job.scheduler_stalled"]
        assert len(events) == 1
        rig.cluster.find = real_find
        rig.reconcile()
        assert rig.job(job["id"])["scheduler_health"]["status"] == "healthy"
        assert len(rig.cluster.submissions) == 1
    finally:
        rig.close()


def test_ambiguous_submission_remains_reserved_and_alerted(tmp_path):
    rig = Rig(tmp_path).setup()
    try:
        rig.cluster.lose_response = True
        job = rig.submit()
        rig.reconcile()
        rig.cluster.jobs.clear()  # lost external records are not permission to retrain
        rig.clock.advance(301)
        rig.reconcile()
        state = rig.job(job["id"])
        assert state["scheduler_health"]["status"] == "stalled"
        assert state["scheduler_health"]["code"] == "SUBMISSION_UNRESOLVED"
        assert len(rig.cluster.submissions) == 1
        assert state["state"] not in {"failed", "timed_out"}
    finally:
        rig.close()


def test_terminal_scheduler_details_survive_service_and_restart(tmp_path):
    rig = Rig(tmp_path).setup()
    try:
        job = rig.submit()
        rig.reconcile()
        sid = rig.job(job["id"])["scheduler_id"]
        rig.cluster.jobs[sid].update(
            state="failed",
            reason="runtime_env_setup_failed",
            exit_code=7,
            diagnostic="package unavailable",
            accounting_estimate=True,
            accounting_scope="driver only",
        )
        rig.reconcile()
        rig.close()
        rig.open()
        result = rig.job(job["id"])
        assert result["diagnostic"] == "package unavailable"
        assert result["exit_code"] == 7
        assert result["accounting_estimate"] is True
    finally:
        rig.close()


def test_dashboard_route_404_is_not_proof_job_is_missing():
    client = Client()

    def missing_route(key):
        raise RuntimeError("Request failed with status code 404: dashboard not found")

    client.get_job_info = missing_route
    with pytest.raises(TimeoutError):
        adapter(client=client).find("job")


def test_ray_job_endpoint_404_is_a_missing_job():
    client = Client()

    def missing(key):
        raise RuntimeError("Request failed with status code 404: Job job does not exist")

    client.get_job_info = missing
    assert adapter(client=client).find("job") is None


def test_diagnostic_redacts_credentials_in_runtime_setup_failure(tmp_path):
    client = Client()
    scheduler = adapter(client=client)
    scheduler.submit(request(tmp_path), submission_key="job")
    client.jobs["job"].status = "FAILED"
    client.jobs["job"].message = "token=private-value Bearer private-bearer package missing"
    diagnostic = scheduler.status("job")["diagnostic"]
    assert "private-value" not in diagnostic
    assert "private-bearer" not in diagnostic
    assert "package missing" in diagnostic


def test_status_remains_terminal_if_log_endpoint_fails(tmp_path):
    client = Client()
    scheduler = adapter(client=client)
    scheduler.submit(request(tmp_path), submission_key="job")
    client.jobs["job"].status = "FAILED"
    client.jobs["job"].message = "runtime failure"

    def broken(*args):
        raise ConnectionError("logs offline")

    client.get_job_logs = broken
    assert scheduler.status("job")["state"] == "failed"


def test_missing_ray_record_is_not_proof_gpu_job_stopped():
    from rsi_red.schedulers.ray import RayUnavailable

    with pytest.raises(RayUnavailable) as error:
        adapter(client=Client()).status("lost-job")
    assert error.value.code == "RAY_JOB_LOST"


def test_lost_external_record_keeps_reservation_and_requests_operator(tmp_path):
    from rsi_red.schedulers.ray import RayUnavailable

    rig = Rig(tmp_path).setup()
    try:
        job = rig.submit()
        rig.reconcile()

        def lost(key):
            raise RayUnavailable("RAY_JOB_LOST")

        rig.cluster.status = lost
        rig.reconcile()
        state = rig.job(job["id"])
        assert state["state"] == "queued"
        assert state["scheduler_health"]["needs_operator"] is True
        assert rig.ok("campaign.show", {"id": rig.campaign})["usage"]["reserved_gpu_seconds"] == 3600
    finally:
        rig.close()
