from copy import deepcopy
import importlib

import pytest

from tests.support import ALICE, OPERATOR, Rig


def test_development_eval_is_async_and_returns_item_evidence(tmp_path):
    r = Rig(tmp_path).setup()
    pending = r.ok("eval.submit", {"campaign_id": r.campaign, "model_id": r.base,
                                   "protocol_id": r.protocol})
    assert pending["state"] == "accepted"
    assert r.evaluator.calls == []
    r.reconcile()
    result = r.ok("eval.show", {"id": pending["id"]})
    assert result["state"] == "succeeded"
    assert result["task_scores"] == {"math": 1.0, "logic": 0.0}
    assert result["score"] == 0.5
    rows = r.ok("eval.samples", {"id": pending["id"], "limit": 100})["items"]
    assert {x["id"] for x in rows} == {"q1", "q2"}
    assert all("answer" in x and "finish_reason" in x for x in rows)


def test_truncated_sample_filter_supports_diagnosis(tmp_path):
    r = Rig(tmp_path).setup()
    result = r.evaluate()
    samples = r.ok("eval.samples", {"id": result["id"], "filter": "truncated", "limit": 10})["items"]
    assert len(samples) == 1
    assert samples[0]["id"] == "q2"
    assert samples[0]["finish_reason"] == "length"


def test_protocol_change_has_new_digest_and_does_not_mutate_existing(tmp_path):
    r = Rig(tmp_path).setup()
    original = r.ok("protocol.show", {"id": r.protocol}, token=OPERATOR)
    changed = deepcopy(original["spec"])
    changed["sampling"]["max_tokens"] = 32
    new = r.ok("protocol.register", changed, token=OPERATOR)
    assert new["id"] != r.protocol
    assert new["digest"] != original["digest"]
    assert r.ok("protocol.show", {"id": r.protocol}, token=OPERATOR)["spec"] == original["spec"]


def test_cross_protocol_comparison_is_rejected(tmp_path):
    r = Rig(tmp_path).setup()
    a = r.evaluate()
    spec = deepcopy(r.ok("protocol.show", {"id": r.protocol}, token=OPERATOR)["spec"])
    spec["sampling"]["max_tokens"] = 32
    protocol = r.ok("protocol.register", spec, token=OPERATOR)["id"]
    b = r.evaluate(protocol=protocol)
    r.error("eval.compare", {"left": a["id"], "right": b["id"]}, "PROTOCOL_MISMATCH")


def test_repeat_evaluations_do_not_overwrite_prior_results(tmp_path):
    r = Rig(tmp_path).setup()
    a, b = r.evaluate(), r.evaluate()
    assert a["id"] != b["id"]
    assert a["model_id"] == b["model_id"]
    assert a["protocol_digest"] == b["protocol_digest"]
    assert r.ok("eval.show", {"id": a["id"]}) == a


def test_researcher_cannot_register_evaluator(tmp_path):
    r = Rig(tmp_path).setup()
    r.error("protocol.register", {"name": "cheating-evaluator"}, "FORBIDDEN", token=ALICE)


def test_held_out_protocol_is_not_listed_to_researcher(tmp_path):
    r = Rig(tmp_path).setup()
    spec = deepcopy(r.ok("protocol.show", {"id": r.protocol}, token=OPERATOR)["spec"])
    spec.update(name="sealed-final", visibility="held_out")
    hidden = r.ok("protocol.register", spec, token=OPERATOR)["id"]
    visible = r.ok("protocol.list", {"campaign_id": r.campaign})["items"]
    assert hidden not in {x["id"] for x in visible}
    r.error("protocol.show", {"id": hidden}, "FORBIDDEN")
    r.error("eval.submit", {"campaign_id": r.campaign, "model_id": r.base,
                            "protocol_id": hidden}, "FORBIDDEN")


def test_eval_uses_frozen_model_and_protocol_reference(tmp_path):
    r = Rig(tmp_path).setup()
    result = r.evaluate()
    model, protocol = r.evaluator.calls[0]
    assert model["id"] == r.base
    assert protocol["id"] == r.protocol
    assert result["protocol_digest"] == protocol["digest"]
    assert result["model_digest"] == model["digest"]


@pytest.mark.parametrize("candidate,expected_removed", [
    ("ONE two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen", True),
    ("completely unrelated harmless training example with enough words to avoid accidental short matching", False),
])
def test_paper_shingle_rule_matches_normalized_overlap(candidate, expected_removed):
    module = importlib.import_module("rsi_red.decontamination")
    benchmark = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen"
    report = module.filter_rows([{"text": candidate}], [benchmark], text_field="text", shingle_size=13,
                                overlap_threshold=0.5)
    assert report["removed_count"] == int(expected_removed)
    assert len(report["rows"]) == int(not expected_removed)


def test_short_benchmark_item_is_reported_uncovered_not_certified_clean():
    module = importlib.import_module("rsi_red.decontamination")
    report = module.filter_rows([{"text": "short question"}], ["short question"], text_field="text",
                                shingle_size=13, overlap_threshold=0.5)
    assert report["uncovered_items"] == 1
    assert report["removed_count"] == 0
    assert report["semantic_contamination_free"] is False


def test_decontamination_reports_counts_without_hidden_questions(tmp_path):
    r = Rig(tmp_path).setup()
    result = r.ok("data.decontaminate", {"id": r.dataset, "campaign_id": r.campaign})
    assert result["output_dataset_id"] != r.dataset
    assert "removed_count" in result
    for forbidden in ["matched_items", "held_out_items", "benchmark_text", "answer"]:
        assert forbidden not in result


def test_campaign_policy_rejects_unchecked_training_data(tmp_path):
    r = Rig(tmp_path).setup()
    campaign = r.ok("campaign.create", {"name": "strict-data", "members": ["alice"],
                    "gpu_hours_budget": 4, "protocol_id": r.protocol,
                    "require_decontamination": True}, token=OPERATOR)["id"]
    r.campaign = campaign
    r.base = r.model("strict-base")
    ds = r.data([{"text": "a row"}])
    r.error("job.submit", r.job_request(campaign_id=campaign, datasets=[ds]), "DATA_NOT_CLEARED")
