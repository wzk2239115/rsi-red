"""Additional RED tests derived from failure windows, not implementation shapes."""
from copy import deepcopy
import hashlib
import importlib
import sys
import threading
import time

import pytest

from tests.support import OPERATOR, Rig


def test_running_reservation_does_not_double_count_consumption(tmp_path):
    r = Rig(tmp_path).setup(gpu_budget=2)
    first = r.submit()
    r.reconcile()
    r.cluster.set_state(r.job(first["id"])["scheduler_id"], "running", gpu_seconds=1800)
    r.reconcile()
    second = r.submit(key="second")
    assert second["state"] == "accepted"  # two one-hour reservations exactly fill two GPU hours


def test_data_text_in_messages_is_included_in_decontamination(tmp_path):
    r = Rig(tmp_path).setup()
    text = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen"
    spec = deepcopy(r.ok("protocol.show", {"id": r.protocol}, token=OPERATOR)["spec"])
    spec["items"][0]["prompt"] = text
    r.ok("protocol.register", spec, token=OPERATOR)
    ds = r.data([{"messages": [{"role": "user", "content": text}, {"role": "assistant", "content": "ok"}]}])
    result = r.ok("data.decontaminate", {"id": ds, "campaign_id": r.campaign})
    assert result["removed_count"] == 1


def test_code_blob_is_used_after_source_is_edited(tmp_path):
    r = Rig(tmp_path).setup()
    local = importlib.import_module("rsi_red.schedulers.local").LocalScheduler(
        root=tmp_path / "local", allow_cpu_only=True)
    r.service.scheduler = local
    output = tmp_path / "executed.txt"
    source = r.file("immutable.py", f"from pathlib import Path\nPath({str(output)!r}).write_text('original')\n")
    code = {"uri": source.as_uri(), "digest": "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()}
    job = r.submit(entrypoint=[sys.executable, str(source)], code=code,
                   resources={"gpus": 0, "walltime_seconds": 10})
    source.write_text(f"from pathlib import Path\nPath({str(output)!r}).write_text('mutated')\n")
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        r.reconcile()
        if r.job(job["id"])["state"] in {"succeeded", "failed"}:
            break
        time.sleep(.05)
    assert r.job(job["id"])["state"] == "succeeded"
    assert output.read_text() == "original"


def test_slow_evaluation_does_not_block_other_agent_requests(tmp_path):
    r = Rig(tmp_path).setup()
    entered, release = threading.Event(), threading.Event()
    original = r.evaluator.evaluate
    def slow(*args):
        entered.set()
        assert release.wait(3)
        return original(*args)
    r.evaluator.evaluate = slow
    r.ok("eval.submit", {"campaign_id": r.campaign, "model_id": r.base, "protocol_id": r.protocol})
    thread = threading.Thread(target=r.reconcile)
    thread.start()
    try:
        assert entered.wait(2)
        request_done = threading.Event()
        def query():
            r.ok("campaign.show", {"id": r.campaign})
            request_done.set()
        reader = threading.Thread(target=query)
        reader.start()
        try:
            assert request_done.wait(.5), "A slow evaluator must not hold the control-plane request lock"
        finally:
            release.set()
            reader.join(timeout=5)
    finally:
        release.set()
        thread.join(timeout=5)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "nan", "wrong_task", "out_of_range"])
def test_bad_evaluator_output_fails_without_partial_score(tmp_path, mutation):
    r = Rig(tmp_path).setup()
    original = r.evaluator.evaluate
    def bad(model, protocol):
        result = original(model, protocol)
        if mutation == "missing":
            result["items"].pop()
        elif mutation == "duplicate":
            result["items"].append(deepcopy(result["items"][0]))
        elif mutation == "nan":
            result["items"][0]["score"] = float("nan")
        elif mutation == "wrong_task":
            result["items"][0]["task"] = "invented"
        else:
            result["items"][0]["score"] = 5
        return result
    r.evaluator.evaluate = bad
    result = r.evaluate()
    assert result["state"] == "failed"
    assert result["reason"] == "INVALID_EVALUATION"
    assert "score" not in result


def test_changed_policy_invalidates_previous_data_clearance(tmp_path):
    r = Rig(tmp_path).setup()
    clean = r.ok("data.decontaminate", {"id": r.dataset, "campaign_id": r.campaign})["output_dataset_id"]
    campaign = r.ok("campaign.create", {"name": "strict", "members": ["alice"], "gpu_hours_budget": 4,
        "protocol_id": r.protocol, "require_decontamination": True}, token=OPERATOR)["id"]
    # Exercise the strict policy in the same campaign by importing and clearing anew.
    r.campaign = campaign
    r.base = r.model("strict-model")
    ds = r.data([{"text": "independent public corpus"}])
    clean = r.ok("data.decontaminate", {"id": ds, "campaign_id": campaign})["output_dataset_id"]
    protocol = deepcopy(r.ok("protocol.show", {"id": r.protocol}, token=OPERATOR)["spec"])
    protocol["sampling"]["max_tokens"] += 1
    r.ok("protocol.register", protocol, token=OPERATOR)
    r.error("job.submit", r.job_request(datasets=[clean]), "DATA_NOT_CLEARED")


def test_protocol_items_are_not_mutable_through_returned_object(tmp_path):
    r = Rig(tmp_path).setup()
    result = r.ok("protocol.show", {"id": r.protocol}, token=OPERATOR)
    result["spec"]["items"][0]["answer"] = "corrupt"
    assert r.ok("protocol.show", {"id": r.protocol}, token=OPERATOR)["spec"]["items"][0]["answer"] == "2"


def test_paired_comparison_exposes_task_regression_without_false_equivalence():
    compare = importlib.import_module("rsi_red.evaluation").paired_comparison
    left = {"protocol_digest": "fixed", "items": [
        {"id": "a", "task": "math", "score": 1}, {"id": "b", "task": "code", "score": 0}]}
    right = {"protocol_digest": "fixed", "items": [
        {"id": "a", "task": "math", "score": 0}, {"id": "b", "task": "code", "score": 1}]}
    left['task_metrics'] = right['task_metrics'] = {
        'math': {'direction': 'maximize'}, 'code': {'direction': 'maximize'}}
    result = compare(left, right)
    assert result["delta"] == 0
    assert result["task_deltas"] == {"math": -1, "code": 1}
    assert result["regressions"] == ["math"]
    assert result["confidence_interval"][0] <= 0 <= result["confidence_interval"][1]
    assert "equivalence proof" in result["interpretation"]


def test_repeat_aggregate_labels_repeat_uncertainty_separately(tmp_path):
    r = Rig(tmp_path).setup()
    a, b = r.evaluate(), r.evaluate()
    result = r.ok("eval.aggregate", {"ids": [a["id"], b["id"]]})
    assert result["count"] == 2
    assert result["mean"] == .5
    assert result["standard_error_over_eval_repeats"] == 0
    assert result["independent_training_runs"] is False


def test_failed_request_rolls_back_budget_and_job_record(tmp_path):
    r = Rig(tmp_path).setup(gpu_budget=1)
    before = r.ok("campaign.show", {"id": r.campaign})["usage"]
    r.error("job.submit", r.job_request(code={"uri": (tmp_path / "missing").as_uri(),
            "digest": "sha256:" + "0" * 64}), "INVALID_REQUEST")
    after = r.ok("campaign.show", {"id": r.campaign})["usage"]
    assert after == before
    assert r.ok("job.list", {"campaign_id": r.campaign})["items"] == []


@pytest.mark.parametrize("raw,state,reason", [
    ("RUNNING", "running", None), ("PENDING", "queued", None),
    ("OUT_OF_MEMORY", "failed", "oom"), ("PREEMPTED", "failed", "preempted"),
    ("NODE_FAIL", "failed", "node_lost"), ("TIMEOUT", "timed_out", "walltime"),
    ("CANCELLED", "cancelled", "user_cancelled"), ("FAILED", "failed", "training_error"),
])
def test_slurm_state_mapping_does_not_assume_completion(raw, state, reason):
    adapter = importlib.import_module("rsi_red.schedulers.slurm").SlurmScheduler
    assert adapter.map_state(raw) == (state, reason)


def test_cancel_before_launch_emits_terminal_event_for_watcher(tmp_path):
    r = Rig(tmp_path).setup()
    job = r.submit()
    r.ok("job.cancel", {"id": job["id"]})
    assert any(event["type"] == "job.cancelled" and event["entity_id"] == job["id"] for event in r.events())
