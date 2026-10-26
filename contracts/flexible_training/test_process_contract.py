"""CPU process acceptance contracts; no CUDA, pip network or simulated trainer scores."""

import hashlib
import json
import sys
import time

import pytest

from rsi_red.schedulers.local import LocalScheduler
from tests.support import Rig


@pytest.fixture
def rig(tmp_path):
    r = Rig(tmp_path).setup()
    r.service.scheduler = LocalScheduler(root=tmp_path / "workers", allow_cpu_only=True)
    try:
        yield r
    finally:
        r.close()


def launch(r, code, **extra):
    script = r.file("experiment.py", code)
    job = r.submit(
        entrypoint=[sys.executable, "experiment.py"],
        code={"uri": script.as_uri(), "digest": "sha256:" + hashlib.sha256(script.read_bytes()).hexdigest()},
        resources={"gpus": 0, "walltime_seconds": 10},
        **extra,
    )
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        r.service.reconcile_jobs()
        result = r.job(job["id"])
        if result["state"] in {"succeeded", "failed", "timed_out", "cancelled"}:
            return result
        time.sleep(0.03)
    raise AssertionError("Real CPU job did not finish: " + str(result))


def runtime(r, text):
    path = r.file("requirements.txt", text)
    return {
        "requirements": {
            "uri": path.as_uri(),
            "digest": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    }


def test_empty_requirements_still_use_a_job_environment_and_record_actual_python(rig):
    result = launch(
        rig,
        'import sys\nprint("PRIVATE_VENV",sys.prefix!=sys.base_prefix,flush=True)\n',
        runtime=runtime(rig, ""),
    )
    assert result["state"] == "succeeded"
    assert result["runtime"]["state"] == "ready"
    assert result["runtime"]["isolation"] == "job-venv"
    assert result["runtime"]["actual_python"]
    assert result["runtime"]["packages_digest"]
    logs = rig.ok("job.logs", {"id": result["id"]})["items"]
    assert "PRIVATE_VENV True" in "\n".join(logs)


def test_dependency_setup_failure_never_runs_training_entrypoint(rig):
    result = launch(
        rig,
        'print("TRAINER_MUST_NOT_RUN",flush=True)\n',
        runtime=runtime(rig, "--rsi-intentionally-invalid-pip-option\n"),
    )
    assert result["state"] == "failed"
    assert result["reason"] == "runtime_setup_failed"
    assert "TRAINER_MUST_NOT_RUN" not in "\n".join(rig.ok("job.logs", {"id": result["id"]})["items"])


def test_runtime_generated_output_is_published_with_job_provenance_and_survives_restart(rig, tmp_path):
    code = """import json,pathlib
p=pathlib.Path('outputs');p.mkdir()
(p/'report.txt').write_text('actual CPU research output')
(p/'manifest.json').write_text(json.dumps({'items':[{'name':'generated-at-runtime','path':'outputs/report.txt','kind':'research_report'}]}))
"""
    result = launch(rig, code, output_manifest="outputs/manifest.json")
    assert result["state"] == "succeeded"
    outputs = rig.ok("job.outputs", {"id": result["id"]})
    assert outputs["state"] == "published"
    item = outputs["items"][0]
    assert item["name"] == "generated-at-runtime"
    artifact = rig.ok("artifact.show", {"id": item["artifact_id"]})
    assert artifact["provenance"]["job_id"] == result["id"]
    assert artifact["provenance"]["code_digest"] == result["spec"]["code"]["digest"]
    assert artifact["parents"] == [rig.base]
    destination = tmp_path / "downloaded-output"
    rig.ok("artifact.fetch", {"id": item["artifact_id"], "output": str(destination)})
    assert (destination / "report.txt").read_text() == "actual CPU research output"
    rig.close()
    rig.open()
    rig.service.reconcile_jobs()
    assert rig.ok("job.outputs", {"id": result["id"]}) == outputs
    campaign = rig.ok("campaign.show", {"id": rig.campaign})
    assert "submission" not in campaign
    assert "score" not in rig.job(result["id"])


@pytest.mark.parametrize("problem", ["missing_manifest", "missing_file", "escape", "duplicate_name"])
def test_invalid_output_manifest_does_not_report_task_success(rig, problem):
    items = [{"name": "a", "path": "outputs/report.txt", "kind": "research_report"}]
    if problem == "missing_file":
        items[0]["path"] = "outputs/not-created.txt"
    if problem == "escape":
        items[0]["path"] = "../outside.txt"
    if problem == "duplicate_name":
        items.append(dict(items[0]))
    code = "import pathlib,json\np=pathlib.Path('outputs');p.mkdir()\n(p/'report.txt').write_text('result')\n"
    if problem != "missing_manifest":
        code += "(p/'manifest.json').write_text(" + repr(json.dumps({"items": items})) + ")\n"
    result = launch(rig, code, output_manifest="outputs/manifest.json")
    assert result["state"] == "failed"
    assert result["reason"] == "output_collection_failed"
    assert result["exit_code"] == 0  # successful trainer, failed collection must be distinguishable
