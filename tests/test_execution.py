from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.support import ALICE, BOB, OPERATOR, OUTSIDER, Rig


def test_submission_returns_before_external_scheduler_runs(tmp_path):
    r = Rig(tmp_path).setup()
    job = r.submit()
    assert job["state"] == "accepted"
    assert r.cluster.submissions == []
    assert job["id"] and job["experiment_id"]


def test_request_is_durable_before_scheduler_side_effect(tmp_path):
    r = Rig(tmp_path).setup()
    job = r.submit()
    def inspect_journal():
        events = r.events()
        assert any(e["type"] == "job.accepted" and e["entity_id"] == job["id"] for e in events)
    r.cluster.on_submit = inspect_journal
    r.reconcile()
    assert len(r.cluster.submissions) == 1


def test_same_key_and_payload_returns_existing_job(tmp_path):
    r = Rig(tmp_path).setup()
    a, b = r.submit(), r.submit()
    assert a["id"] == b["id"]
    r.reconcile()
    assert len(r.cluster.submissions) == 1


def test_same_key_different_payload_is_conflict(tmp_path):
    r = Rig(tmp_path).setup()
    r.submit()
    r.error("job.submit", r.job_request(training_seed=8), "IDEMPOTENCY_CONFLICT")


def test_concurrent_submissions_are_deduplicated(tmp_path):
    r = Rig(tmp_path).setup()
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(lambda _: r.submit()["id"], range(8)))
    assert len(set(ids)) == 1
    r.reconcile()
    assert len(r.cluster.submissions) == 1


def test_submission_response_loss_does_not_duplicate_gpu_job(tmp_path):
    r = Rig(tmp_path).setup()
    job = r.submit()
    r.cluster.lose_response = True
    r.reconcile()
    r.close()
    r.open().reconcile()
    assert len(r.cluster.submissions) == 1
    assert r.job(job["id"])["scheduler_id"] == "scheduler-1"


def test_service_restart_preserves_running_job_and_reconciles(tmp_path):
    r = Rig(tmp_path).setup()
    job = r.submit()
    r.reconcile()
    sid = r.job(job["id"])["scheduler_id"]
    r.close()
    r.cluster.set_state(sid, "succeeded", gpu_seconds=120)
    r.open().reconcile()
    assert r.job(job["id"])["state"] == "succeeded"
    assert len(r.cluster.submissions) == 1


@pytest.mark.parametrize("state,reason", [
    ("failed", "oom"), ("failed", "training_error"),
    ("failed", "node_lost"), ("failed", "preempted"), ("timed_out", "walltime"),
])
def test_external_failure_reason_is_preserved(tmp_path, state, reason):
    r = Rig(tmp_path).setup()
    job = r.submit()
    r.reconcile()
    r.cluster.set_state(r.job(job["id"])["scheduler_id"], state, reason=reason, gpu_seconds=30)
    r.reconcile()
    final = r.job(job["id"])
    assert (final["state"], final["reason"]) == (state, reason)
    assert len(r.cluster.submissions) == 1  # no blind automatic retries


def test_cancel_queued_job_never_starts_it(tmp_path):
    r = Rig(tmp_path).setup()
    job = r.submit()
    r.ok("job.cancel", {"id": job["id"]})
    r.reconcile()
    assert r.job(job["id"])["state"] == "cancelled"
    assert r.cluster.submissions == []


def test_cancel_running_job_releases_external_resources(tmp_path):
    r = Rig(tmp_path).setup()
    job = r.submit()
    r.reconcile()
    sid = r.job(job["id"])["scheduler_id"]
    r.ok("job.cancel", {"id": job["id"]})
    r.reconcile()
    assert r.cluster.status(sid)["state"] == "cancelled"
    assert r.job(job["id"])["state"] == "cancelled"


def test_queued_reservations_count_against_budget(tmp_path):
    r = Rig(tmp_path).setup(gpu_budget=1)
    r.submit(key="first")
    r.error("job.submit", r.job_request(key="second"), "BUDGET_EXCEEDED")
    assert r.cluster.submissions == []


def test_concurrent_budget_reservation_cannot_overbook(tmp_path):
    r = Rig(tmp_path).setup(gpu_budget=1)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda i: r.call("job.submit", r.job_request(key=f"exp-{i}")), range(4)))
    assert sum(result["error"] is None for result in results) == 1
    assert [result["error"]["code"] for result in results if result["error"]] == ["BUDGET_EXCEEDED"] * 3


def test_finished_usage_is_charged_once_across_reconcile_and_restart(tmp_path):
    r = Rig(tmp_path).setup()
    job = r.submit()
    r.reconcile()
    r.cluster.set_state(r.job(job["id"])["scheduler_id"], "succeeded", gpu_seconds=120)
    r.reconcile()
    r.reconcile()
    r.close()
    r.open().reconcile()
    usage = r.ok("campaign.show", {"id": r.campaign})["usage"]
    assert usage["gpu_seconds"] == 120
    assert usage["reserved_gpu_seconds"] == 0


def test_invalid_resources_are_rejected_before_submission(tmp_path):
    r = Rig(tmp_path).setup()
    r.error("job.submit", r.job_request(resources={"gpus": -1, "walltime_seconds": 0}), "INVALID_REQUEST")
    assert r.cluster.submissions == []


def test_unknown_parent_cannot_enter_training(tmp_path):
    r = Rig(tmp_path).setup()
    r.error("job.submit", r.job_request(parents=["model-missing"]), "NOT_FOUND")


def test_dependent_job_waits_for_successful_parent(tmp_path):
    r = Rig(tmp_path).setup()
    a = r.submit(key="a")
    b = r.submit(key="b", depends_on=[a["id"]])
    r.reconcile()
    assert len(r.cluster.submissions) == 1
    r.cluster.set_state(r.job(a["id"])["scheduler_id"], "succeeded")
    r.reconcile()
    r.reconcile()
    assert r.job(b["id"])["scheduler_id"]
    assert len(r.cluster.submissions) == 2


def test_failed_dependency_blocks_child_without_spending_gpu(tmp_path):
    r = Rig(tmp_path).setup()
    a = r.submit(key="a")
    b = r.submit(key="b", depends_on=[a["id"]])
    r.reconcile()
    r.cluster.set_state(r.job(a["id"])["scheduler_id"], "failed", reason="training_error")
    r.reconcile()
    assert r.job(b["id"])["state"] == "failed"
    assert r.job(b["id"])["reason"] == "dependency_failed"
    assert len(r.cluster.submissions) == 1


def test_team_member_sees_results_but_outsider_cannot(tmp_path):
    r = Rig(tmp_path).setup()
    job = r.submit()
    assert r.ok("job.show", {"id": job["id"]}, token=BOB)["id"] == job["id"]
    r.error("job.show", {"id": job["id"]}, "FORBIDDEN", token=OUTSIDER)


def test_researcher_cannot_create_campaign_or_spoof_operator(tmp_path):
    r = Rig(tmp_path)
    r.error("campaign.create", {"name": "forged", "role": "operator"}, "FORBIDDEN", token=ALICE)


def test_unknown_token_is_rejected(tmp_path):
    r = Rig(tmp_path)
    r.error("campaign.list", {}, "UNAUTHENTICATED", token="wrong-token")


def test_unknown_operation_is_structured_error(tmp_path):
    r = Rig(tmp_path)
    r.error("job.magic", {}, "UNKNOWN_OPERATION", token=OPERATOR)
