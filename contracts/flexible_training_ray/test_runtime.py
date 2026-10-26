"""New-feature RED on a real Ray Jobs server. CPU only; no model downloads."""

import hashlib
import sys
import time

import pytest

from integration.ray.cluster import head
from tests.support import Rig


@pytest.fixture(scope="module")
def ray_scheduler():
    with head() as instance:
        yield instance


@pytest.fixture
def rig(tmp_path, ray_scheduler):
    r = Rig(tmp_path).setup()
    r.service.scheduler = ray_scheduler
    try:
        yield r
    finally:
        r.close()


def execute(r, code, requirements):
    source = r.file("experiment.py", code)
    req = r.file("requirements.txt", requirements)
    job = r.submit(
        entrypoint=[sys.executable, "experiment.py"],
        code={"uri": source.as_uri(), "digest": "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()},
        resources={"gpus": 0, "cpus": 1, "walltime_seconds": 45},
        runtime={
            "requirements": {
                "uri": req.as_uri(),
                "digest": "sha256:" + hashlib.sha256(req.read_bytes()).hexdigest(),
            }
        },
        output_manifest="outputs/manifest.json",
    )
    deadline = time.monotonic() + 60
    try:
        while time.monotonic() < deadline:
            r.service.reconcile_jobs()
            state = r.job(job["id"])
            if state["state"] in {"succeeded", "failed", "timed_out", "cancelled"}:
                return state
            time.sleep(0.2)
        raise AssertionError("Ray job did not finish: " + str(state))
    finally:
        # No global ray stop; only this submitted job may be cancelled.
        r.service.dispatch(token="test-alice-token", operation="job.cancel", payload={"id": job["id"]})


def test_real_ray_task_uses_private_runtime_and_publishes_generated_output(rig, tmp_path):
    code = """import json,pathlib,sys
p=pathlib.Path('outputs');p.mkdir()
(p/'report.txt').write_text('venv='+str(sys.prefix!=sys.base_prefix))
(p/'manifest.json').write_text(json.dumps({'items':[{'name':'runtime-result','path':'outputs/report.txt','kind':'research_report'}]}))
"""
    job = execute(rig, code, "")
    assert job["state"] == "succeeded", job
    assert job["runtime"]["state"] == "ready"
    assert job["runtime"]["isolation"] == "job-venv"
    outputs = rig.ok("job.outputs", {"id": job["id"]})
    assert outputs["state"] == "published"
    destination = tmp_path / "fetched"
    rig.ok("artifact.fetch", {"id": outputs["items"][0]["artifact_id"], "output": str(destination)})
    assert (destination / "report.txt").read_text() == "venv=True"


def test_real_ray_dependency_failure_cannot_fall_through_to_training(rig):
    code = 'print("TRAINING_MUST_NOT_START",flush=True)\n'
    job = execute(rig, code, "--rsi-intentionally-invalid-pip-option\n")
    assert job["state"] == "failed", job
    assert job["reason"] == "runtime_setup_failed"
    assert "TRAINING_MUST_NOT_START" not in "\n".join(rig.ok("job.logs", {"id": job["id"]})["items"])
