import hashlib
import json

from tests.support import BOB, Rig


def test_dataset_is_snapshot_not_mutable_source_path(tmp_path):
    r = Rig(tmp_path).setup()
    before = r.ok("data.inspect", {"id": r.dataset})
    r.file("train.jsonl", '{"corrupted":true}\n')
    after = r.ok("data.inspect", {"id": r.dataset})
    assert before["digest"] == after["digest"]
    assert after["rows"] == 1
    samples = r.ok("data.sample", {"id": r.dataset, "count": 1, "seed": 42})["items"]
    assert samples[0]["messages"][1]["content"] == "2"


def test_changed_dataset_content_creates_different_version(tmp_path):
    r = Rig(tmp_path).setup()
    a = r.ok("data.inspect", {"id": r.dataset})
    other = r.data([{"messages": [{"role": "user", "content": "new question"},
                                  {"role": "assistant", "content": "new answer"}]}])
    b = r.ok("data.inspect", {"id": other})
    assert a["digest"] != b["digest"]
    assert a["id"] != b["id"]


def test_sampling_is_seeded_and_bounded(tmp_path):
    r = Rig(tmp_path).setup()
    ds = r.data([{"text": str(i)} for i in range(30)])
    payload = {"id": ds, "count": 3, "seed": 42}
    a = r.ok("data.sample", payload)["items"]
    b = r.ok("data.sample", payload)["items"]
    assert a == b
    assert len(a) == 3
    assert len({x["text"] for x in a}) == 3


def test_schema_check_reports_bad_sft_row_not_clean_data(tmp_path):
    r = Rig(tmp_path).setup()
    ds = r.data([{"messages": [{"role": "user", "content": "missing assistant"}]}])
    check = r.ok("data.check", {"id": ds, "profile": "sft"})
    assert check["valid"] is False
    assert check["invalid_rows"] == 1
    assert check["issues"][0]["row"] == 0


def test_unchecked_dataset_is_not_marked_decontaminated(tmp_path):
    r = Rig(tmp_path).setup()
    assert r.ok("data.inspect", {"id": r.dataset})["decontamination"]["status"] == "unchecked"


def test_published_model_copies_files_and_verifies_fetch_digest(tmp_path):
    r = Rig(tmp_path).setup()
    r.file("base/model.safetensors", "changed after publish")
    destination = tmp_path / "downloaded"
    r.ok("artifact.fetch", {"id": r.base, "output": str(destination)})
    assert (destination / "model.safetensors").read_text() == "fixture"
    manifest = r.ok("artifact.show", {"id": r.base})["files"]
    assert {x["path"] for x in manifest} == {"config.json", "tokenizer.json", "model.safetensors"}
    for entry in manifest:
        assert hashlib.sha256((destination / entry["path"]).read_bytes()).hexdigest() == entry["sha256"]


def test_artifact_checksum_mismatch_is_rejected(tmp_path):
    r = Rig(tmp_path).setup()
    r.error("artifact.register", {"campaign_id": r.campaign,
            "path": str(tmp_path / "inputs" / "base"), "kind": "model", "parents": [],
            "files": [{"path": "model.safetensors", "sha256": "0" * 64}],
            "provenance": {"source": "fixture"}}, "CHECKSUM_MISMATCH")


def test_incomplete_model_cannot_be_published(tmp_path):
    r = Rig(tmp_path).setup()
    path = r.file("incomplete/config.json", "{}")
    r.error("artifact.register", {"campaign_id": r.campaign, "path": str(path.parent),
            "kind": "model", "parents": [], "files": [
                {"path": "config.json", "sha256": hashlib.sha256(b"{}").hexdigest()}],
            "provenance": {"source": "fixture"}}, "INCOMPLETE_MODEL")


def test_artifact_manifest_cannot_escape_source_directory(tmp_path):
    r = Rig(tmp_path).setup()
    r.error("artifact.register", {"campaign_id": r.campaign,
            "path": str(tmp_path / "inputs" / "base"), "kind": "model", "parents": [],
            "files": [{"path": "../train.jsonl", "sha256": "0" * 64}]}, "INVALID_PATH")


def test_merge_lineage_contains_all_parents_and_ancestors(tmp_path):
    r = Rig(tmp_path).setup()
    a = r.model("fine-tuned-a", parents=[r.base])
    b = r.model("fine-tuned-b", parents=[r.base])
    merged = r.model("merged", parents=[a, b])
    lineage = r.ok("artifact.lineage", {"id": merged})
    assert {n["id"] for n in lineage["nodes"]} == {r.base, a, b, merged}
    assert {(e["parent"], e["child"]) for e in lineage["edges"]} == {
        (r.base, a), (r.base, b), (a, merged), (b, merged)}


def test_job_records_code_data_image_and_parents(tmp_path):
    r = Rig(tmp_path).setup()
    request = r.job_request()
    job = r.ok("job.submit", request)
    recorded = r.job(job["id"])["spec"]
    for key in ["code", "image", "datasets", "parents", "training_seed", "entrypoint"]:
        assert recorded[key] == request[key]


def test_event_cursor_replays_without_duplicates_after_restart(tmp_path):
    r = Rig(tmp_path).setup()
    first = r.events()
    cursor = first[-1]["id"]
    job = r.submit()
    later = r.events(cursor)
    assert any(e["entity_id"] == job["id"] for e in later)
    assert not ({e["id"] for e in first} & {e["id"] for e in later})
    r.close()
    r.open()
    assert r.events(cursor) == later


def test_team_notes_survive_restart_with_author_and_evidence(tmp_path):
    r = Rig(tmp_path).setup()
    job = r.submit()
    note = r.ok("note.add", {"campaign_id": r.campaign, "text": "hypothesis: inspect loops",
                             "evidence_ids": [job["id"]]})
    r.close()
    r.open()
    saved = r.ok("note.show", {"id": note["id"]}, token=BOB)
    assert saved["text"] == "hypothesis: inspect loops"
    assert saved["author"] == "alice"
    assert saved["evidence_ids"] == [job["id"]]


def test_submission_does_not_deploy_or_trigger_hidden_evaluation(tmp_path):
    r = Rig(tmp_path).setup()
    result = r.ok("campaign.submit", {"id": r.campaign, "model_id": r.base})
    assert result["model_id"] == r.base
    assert r.evaluator.calls == []
    assert r.cluster.submissions == []


def test_secret_values_do_not_enter_queryable_job_or_events(tmp_path):
    r = Rig(tmp_path).setup()
    secret = "secret-do-not-persist-123456"
    job = r.submit(env={"API_TOKEN": secret, "LEARNING_RATE": "0.1"})
    serialized = json.dumps({"job": r.job(job["id"]), "events": r.events()})
    assert secret not in serialized
    assert "0.1" in serialized
