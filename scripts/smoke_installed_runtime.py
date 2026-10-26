"""Run from a clean installed-wheel environment; exercises actual CPU task execution."""

import hashlib
import time
from pathlib import Path
from rsi_red.service import ResearchService
from rsi_red.schedulers.local import LocalScheduler
from rsi_red.evaluation import UnconfiguredEvaluator

root = Path("wheel-runtime")
root.mkdir()
s = ResearchService(
    root=root / "state",
    scheduler=LocalScheduler(root=root / "workers", allow_cpu_only=True),
    evaluator=UnconfiguredEvaluator(),
    principals={"fixture": {"id": "operator", "role": "operator"}},
)


def call(op, **payload):
    response = s.dispatch(token="fixture", operation=op, payload=payload)
    assert response["error"] is None, response
    return response["data"]


try:
    prot = call(
        "protocol.register",
        name="cpu-fixture",
        visibility="development",
        items=[{"id": "q", "task": "x", "prompt": "x", "answer": "x"}],
        sampling={"max_tokens": 1},
        evaluator_digest="sha256:" + "1" * 64,
        aggregation="task_mean",
        eval_seed=1,
    )
    camp = call(
        "campaign.create",
        name="installed-wheel",
        members=["operator"],
        protocol_id=prot["id"],
        gpu_hours_budget=1,
        require_decontamination=False,
    )
    script = (root / "custom.py").resolve()
    script.write_text(
        "import pathlib,json\np=pathlib.Path('out');p.mkdir()\n(p/'r.txt').write_text('installed wheel runtime')\n(p/'manifest.json').write_text(json.dumps({'items':[{'name':'report','path':'out/r.txt','kind':'report'}]}))\n"
    )
    req = (root / "requirements.txt").resolve()
    req.write_text("")
    payload = {
        "campaign_id": camp["id"],
        "idempotency_key": "wheel",
        "entrypoint": ["python", script.name],
        "code": {
            "uri": script.as_uri(),
            "digest": "sha256:" + hashlib.sha256(script.read_bytes()).hexdigest(),
        },
        "runtime": {
            "requirements": {
                "uri": req.as_uri(),
                "digest": "sha256:" + hashlib.sha256(req.read_bytes()).hexdigest(),
            }
        },
        "output_manifest": "out/manifest.json",
        "datasets": [],
        "parents": [],
        "resources": {"gpus": 0, "walltime_seconds": 20},
    }
    assert call("job.validate", **payload)["valid"]
    job = call("job.submit", **payload)
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        s.reconcile_jobs()
        state = call("job.show", id=job["id"])
        if state["state"] in {"succeeded", "failed", "timed_out"}:
            break
        time.sleep(0.05)
    assert state["state"] == "succeeded", state
    assert state["runtime"]["isolation"] == "job-venv"
    assert call("job.outputs", id=job["id"])["state"] == "published"
    print("Installed wheel runtime, private venv and output publication passed")
finally:
    s.close()
