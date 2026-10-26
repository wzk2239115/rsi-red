"""Contract harness. Only external scheduler/evaluator are doubles, never product logic."""
from __future__ import annotations

import hashlib
import importlib
import json
from copy import deepcopy
from pathlib import Path

OPERATOR = "test-operator-token"
ALICE = "test-alice-token"
BOB = "test-bob-token"
OUTSIDER = "test-outsider-token"


class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class Scheduler:
    """In-memory external cluster: no state persistence, budget or policy decisions."""
    def __init__(self):
        self.jobs = {}
        self.submissions = []
        self.on_submit = None
        self.lose_response = False

    def find(self, submission_key):
        return next((j for j, v in self.jobs.items() if v["key"] == submission_key), None)

    def submit(self, request, *, submission_key):
        if self.on_submit:
            self.on_submit()
        job_id = f"scheduler-{len(self.jobs) + 1}"
        self.jobs[job_id] = {"key": submission_key, "state": "queued", "reason": None,
                             "gpu_seconds": 0, "request": deepcopy(request)}
        self.submissions.append(deepcopy(request))
        if self.lose_response:
            self.lose_response = False
            raise TimeoutError("submission accepted but response was lost")
        return job_id

    def status(self, job_id):
        return deepcopy(self.jobs[job_id])

    def cancel(self, job_id):
        self.jobs[job_id]["state"] = "cancelled"

    def logs(self, job_id, *, offset=0, limit=100):
        return ["step=1 loss=0.9", "step=2 loss=0.8"][offset:offset + limit]

    def set_state(self, job_id, state, *, reason=None, gpu_seconds=0):
        self.jobs[job_id].update(state=state, reason=reason, gpu_seconds=gpu_seconds)


class Evaluator:
    """Fixture predictions, explicitly NOT model inference or a GPU benchmark."""
    def __init__(self):
        self.calls = []

    def evaluate(self, model, protocol):
        self.calls.append((deepcopy(model), deepcopy(protocol)))
        return {"items": [
            {"id": "q1", "task": "math", "answer": "2", "score": 1.0,
             "finish_reason": "stop", "output_tokens": 1},
            {"id": "q2", "task": "logic", "answer": "loop loop loop", "score": 0.0,
             "finish_reason": "length", "output_tokens": 8},
        ]}


class Rig:
    def __init__(self, root: Path):
        self.root = root
        self.cluster = Scheduler()
        self.evaluator = Evaluator()
        self.clock = Clock()
        self.principals = {
            OPERATOR: {"id": "operator", "role": "operator"},
            ALICE: {"id": "alice", "role": "researcher"},
            BOB: {"id": "bob", "role": "researcher"},
            OUTSIDER: {"id": "outsider", "role": "researcher"},
        }
        self.open()

    def open(self):
        module = importlib.import_module("rsi_red.service")
        self.service = module.ResearchService(
            root=self.root, scheduler=self.cluster, evaluator=self.evaluator,
            clock=self.clock, principals=self.principals,
        )
        return self

    def close(self):
        self.service.close()

    def call(self, operation, payload=None, *, token=ALICE):
        result = self.service.dispatch(token=token, operation=operation, payload=payload or {})
        assert set(result) == {"schema_version", "request_id", "data", "error"}
        assert result["schema_version"] == "1"
        assert isinstance(result["request_id"], str) and result["request_id"]
        return result

    def ok(self, operation, payload=None, *, token=ALICE):
        result = self.call(operation, payload, token=token)
        assert result["error"] is None, result
        return result["data"]

    def error(self, operation, payload, code, *, token=ALICE):
        result = self.call(operation, payload, token=token)
        assert result["data"] is None
        assert result["error"]["code"] == code, result
        assert isinstance(result["error"]["retryable"], bool)
        return result["error"]

    def setup(self, *, gpu_budget=4.0):
        self.protocol = self.ok("protocol.register", {
            "name": "dev-v1", "visibility": "development", "items": [
                {"id": "q1", "task": "math", "prompt": "one plus one", "answer": "2"},
                {"id": "q2", "task": "logic", "prompt": "choose true", "answer": "true"},
            ], "evaluator_digest": "sha256:" + "1" * 64,
            "sampling": {"temperature": 0, "max_tokens": 8},
            "aggregation": "task_mean", "eval_seed": 42,
        }, token=OPERATOR)["id"]
        self.campaign = self.ok("campaign.create", {
            "name": "contract-research", "members": ["alice", "bob"],
            "gpu_hours_budget": gpu_budget, "protocol_id": self.protocol,
            "require_decontamination": False,
        }, token=OPERATOR)["id"]
        self.base = self.model("base")
        self.dataset = self.data([{"messages": [
            {"role": "user", "content": "one plus one"},
            {"role": "assistant", "content": "2"},
        ]}])
        code = self.file("train.py", "print('CPU contract fixture only')\n")
        self.code = {"digest": "sha256:" + hashlib.sha256(code.read_bytes()).hexdigest(),
                     "uri": code.as_uri()}
        return self

    def file(self, name, content):
        path = self.root / "inputs" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def data(self, rows, name="train.jsonl"):
        path = self.file(name, "".join(json.dumps(r) + "\n" for r in rows))
        return self.ok("data.import", {
            "campaign_id": self.campaign, "path": str(path), "source": "test-fixture",
            "revision": "fixture-v1", "license": "CC0-1.0",
        })["id"]

    def model(self, name, *, parents=None, files=None):
        paths = files or {"config.json": "{}", "tokenizer.json": "{}", "model.safetensors": "fixture"}
        manifest = []
        for filename, content in paths.items():
            path = self.file(f"{name}/{filename}", content)
            manifest.append({"path": filename, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        return self.ok("artifact.register", {
            "campaign_id": self.campaign, "path": str(self.root / "inputs" / name),
            "files": manifest, "parents": parents or [], "kind": "model",
            "provenance": {"source": "local-test-fixture", "not_real_weights": True},
        })["id"]

    def job_request(self, *, key="experiment-1", **updates):
        request = {"campaign_id": self.campaign, "idempotency_key": key,
                   "entrypoint": ["python", "train.py"],
                   "code": deepcopy(self.code),
                   "image": "example/train@sha256:" + "3" * 64,
                   "datasets": [self.dataset], "parents": [self.base],
                   "resources": {"gpus": 1, "walltime_seconds": 3600}, "training_seed": 7,
                   "env": {"LEARNING_RATE": "0.00001"}}
        request.update(updates)
        return request

    def submit(self, **updates):
        return self.ok("job.submit", self.job_request(**updates))

    def reconcile(self):
        self.service.reconcile()

    def job(self, job_id):
        return self.ok("job.show", {"id": job_id})

    def events(self, after=None, *, token=ALICE):
        return self.ok("events.list", {"campaign_id": self.campaign, "after": after, "limit": 1000},
                       token=token)["items"]

    def evaluate(self, *, model=None, protocol=None):
        result = self.ok("eval.submit", {"campaign_id": self.campaign,
                                         "model_id": model or self.base,
                                         "protocol_id": protocol or self.protocol})
        self.reconcile()
        return self.ok("eval.show", {"id": result["id"]})
