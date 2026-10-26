"""New-feature RED on a real Ray Jobs server. CPU only; no model downloads."""

import hashlib
import os
import sys
import time

import pytest

from integration.ray.cluster import head
from tests.support import Rig


@pytest.fixture(scope="module")
def ray_scheduler():
    with pytest.MonkeyPatch.context() as patch:
        local = os.environ.get("NO_PROXY", "") + ",127.0.0.1,localhost"
        patch.setenv("NO_PROXY", local)
        patch.setenv("no_proxy", local)
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


def execute(r, code, requirements, *, python_executable=None, entrypoint=None):
    source = r.file("experiment.py", code)
    req = r.file("requirements.txt", requirements)
    job = r.submit(
        entrypoint=entrypoint or [sys.executable, "experiment.py"],
        code={"uri": source.as_uri(), "digest": "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()},
        image=None,  # CPU fixture has no declared GPU container label; do not fail before submission.
        resources={"gpus": 0, "cpus": 1, "walltime_seconds": 45},
        runtime={
            **({"python_executable": python_executable} if python_executable else {}),
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
                assert state["scheduler_id"] is not None, state
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


def test_task_python_overrides_ray_global_default(rig, tmp_path):
    import shlex
    marker = tmp_path / 'selected-interpreter'
    shim = tmp_path / 'task-python'
    shim.write_text('#!/bin/sh\nprintf selected > '+shlex.quote(str(marker))+'\nexec '+shlex.quote(sys.executable)+' "$@"\n')
    shim.chmod(0o700)
    code = """import pathlib,json
p=pathlib.Path('outputs');p.mkdir()
(p/'manifest.json').write_text(json.dumps({'items':[{'name':'report','path':'outputs/report.txt','kind':'report'}]}))
(p/'report.txt').write_text('done')
"""
    job = execute(rig, code, '', python_executable=str(shim))
    assert job['state']=='succeeded',job
    assert marker.read_text()=='selected'
    assert job['runtime']['requested_python']==str(shim)
    assert job['runtime']['isolation']=='job-venv'


def test_managed_shell_and_cpu_multiprocess_launcher(rig):
    code = """import pathlib,json,subprocess,sys
for rank in range(2):
    subprocess.run([sys.executable,'-c',f'print("CPU-RANK={rank}",flush=True)'],check=True)
p=pathlib.Path('outputs');p.mkdir()
(p/'report.txt').write_text('two CPU child processes, no GPU claim')
(p/'manifest.json').write_text(json.dumps({'items':[{'name':'launcher-report','path':'outputs/report.txt','kind':'report'}]}))
"""
    job=execute(rig,code,'',entrypoint=['/bin/sh','-c','exec python experiment.py'])
    assert job['state']=='succeeded',job
    logs='\n'.join(rig.ok('job.logs',{'id':job['id']})['items'])
    assert 'CPU-RANK=0' in logs and 'CPU-RANK=1' in logs
    assert job['spec']['resources']['gpus']==0
    assert rig.ok('job.outputs',{'id':job['id']})['state']=='published'


def test_ray_output_publication_recovers_with_new_controller_and_client(rig, tmp_path):
    from rsi_red.schedulers.ray import RayScheduler
    scheduler=rig.service.scheduler
    source=rig.file('produce.py', '''import pathlib,json
p=pathlib.Path('out');p.mkdir()
(p/'report.txt').write_text('completed before controller restart')
(p/'manifest.json').write_text(json.dumps({'items':[{'name':'report','path':'out/report.txt','kind':'report'}]}))
''')
    job=rig.submit(entrypoint=[sys.executable,source.name],image=None,output_manifest='out/manifest.json',
        code={'uri':source.as_uri(),'digest':'sha256:'+hashlib.sha256(source.read_bytes()).hexdigest()},
        resources={'gpus':0,'cpus':1,'walltime_seconds':45})
    rig.service.reconcile_jobs()
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        state=scheduler.status(job['id'])
        if state['state'] in {'succeeded','failed','timed_out'}:
            break
        time.sleep(.2)
    assert state['state']=='succeeded',state
    rig.close()
    rig.open()
    rig.service.scheduler=RayScheduler(address=scheduler.address,auth_mode='disabled',
        shared_filesystem=True,python_executable=sys.executable)
    rig.service.reconcile_jobs()
    first=rig.ok('job.outputs',{'id':job['id']})
    assert first['state']=='published'
    rig.service.reconcile_jobs()
    assert rig.ok('job.outputs',{'id':job['id']})==first
    assert rig.job(job['id'])['attempt_count']==1
    destination=tmp_path/'recovered'
    rig.ok('artifact.fetch',{'id':first['items'][0]['artifact_id'],'output':str(destination)})
    assert (destination/'report.txt').read_text()=='completed before controller restart'
