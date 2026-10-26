"""Planning contracts: real service boundary, only external execution is doubled."""

from copy import deepcopy
import hashlib
import json

import pytest

from tests.support import OPERATOR, Rig


@pytest.fixture
def rig(tmp_path):
    r = Rig(tmp_path).setup()
    try:
        yield r
    finally:
        r.close()


def requirements(r, text="example-package==1.0\n"):
    path = r.file("requirements.txt", text)
    return {"uri": path.as_uri(), "digest": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.mark.parametrize(
    "method", ["new_loss_v7", "reward_search", "data_synthesis", "architecture_experiment"]
)
def test_method_and_training_reward_have_no_starter_allowlist(rig, method):
    params = {
        "loss": {"name": method, "coefficient": 0.3},
        "training_reward": "custom-v1",
        "unusual": [1, {"x": True}],
    }
    recipe = rig.ok(
        "recipe.create",
        {
            "campaign_id": rig.campaign,
            "title": "open research",
            "hypothesis": "test an unfamiliar method",
            "method": method,
            "datasets": [rig.dataset],
            "parents": [rig.base],
            "parameters": params,
        },
    )
    assert recipe["method"] == method
    assert recipe["parameters"] == params
    assert rig.submit(recipe_id=recipe["id"])["state"] == "accepted"
    assert rig.cluster.submissions == []


def test_shell_command_is_preserved_as_argv(rig):
    argv = ["/bin/sh", "-c", 'printf "%s" "$1"', "custom-experiment", "a; b && c"]
    job = rig.submit(entrypoint=argv)
    rig.service.reconcile_jobs()
    assert rig.cluster.submissions[0]["entrypoint"] == argv
    assert rig.job(job["id"])["state"] == "queued"


def test_formal_protocol_remains_operator_only_while_reward_is_free(rig):
    before = rig.ok("protocol.show", {"id": rig.protocol}, token=OPERATOR)
    rig.error("protocol.register", before["spec"], "FORBIDDEN")
    rig.submit(env={"TRAINING_REWARD": "custom-not-a-formal-evaluator"})
    assert rig.ok("protocol.show", {"id": rig.protocol}, token=OPERATOR) == before


def test_validate_has_no_execution_or_metadata_side_effects(rig):
    request = rig.job_request(execution={"mode": "command", "nodes": 1})
    events = rig.events()
    usage = rig.ok("campaign.show", {"id": rig.campaign})["usage"]
    for _ in range(2):
        result = rig.ok("job.validate", request)
        assert result["valid"] is True
        assert result["normalized"]["entrypoint"] == request["entrypoint"]
        assert isinstance(result["warnings"], list)
    assert rig.ok("job.list", {"campaign_id": rig.campaign})["items"] == []
    assert rig.events() == events
    assert rig.ok("campaign.show", {"id": rig.campaign})["usage"] == usage
    assert rig.cluster.submissions == []


@pytest.mark.parametrize("operation", ["job.validate", "job.submit"])
@pytest.mark.parametrize("execution", [{"mode": "command", "nodes": 2}, {"mode": "ray_tasks", "nodes": 1}])
def test_unsupported_topology_is_not_silently_accepted(rig, operation, execution):
    rig.error(operation, rig.job_request(execution=execution), "UNSUPPORTED_EXECUTION_TOPOLOGY")
    assert rig.ok("job.list", {"campaign_id": rig.campaign})["items"] == []
    assert rig.ok("campaign.show", {"id": rig.campaign})["usage"]["reserved_gpu_seconds"] == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("runtime", {"requirements_typo": "ignored?"}),
        ("execution", {"mode": "command", "nodes": 1, "typo": True}),
    ],
)
def test_unknown_control_fields_fail_before_acceptance(rig, field, value):
    rig.error("job.submit", rig.job_request(**{field: value}), "INVALID_REQUEST")


def test_single_node_eight_gpu_launcher_remains_framework_agnostic(rig):
    # External scheduler double checks the control contract, never claims CUDA ran.
    argv = ["torchrun", "--standalone", "--nproc_per_node=8", "train.py", "--loss", "custom-loss"]
    request = rig.job_request(
        entrypoint=argv,
        execution={"mode": "command", "nodes": 1},
        resources={"gpus": 8, "cpus": 16, "walltime_seconds": 60},
    )
    result = rig.ok("job.validate", request)
    assert result["valid"] is True
    job = rig.ok("job.submit", request)
    rig.service.reconcile_jobs()
    assert rig.cluster.submissions[0]["entrypoint"] == argv
    assert rig.cluster.submissions[0]["resources"]["gpus"] == 8
    assert rig.job(job["id"])["state"] == "queued"


def test_tokenizer_and_length_parameters_survive_redaction(rig):
    params = {"max_tokens": 4096, "tokenizer_name": "custom-vocab", "loss": {"temperature": 0.3}}
    recipe = rig.ok(
        "recipe.create",
        {
            "campaign_id": rig.campaign,
            "title": "parameter fidelity",
            "hypothesis": "change lengths",
            "method": "custom",
            "parameters": params,
        },
    )
    assert recipe["parameters"] == params
    environment = {"MAX_TOKENS": "4096", "TOKENIZERS_PARALLELISM": "false", "TOKENIZER_NAME": "custom-vocab"}
    job = rig.submit(env=environment)
    assert job["spec"]["env"] == environment
    rig.service.reconcile_jobs()
    assert rig.cluster.submissions[0]["env"] == environment


def test_true_credentials_still_do_not_enter_shared_records(rig):
    job = rig.submit(env={"API_KEY": "fixture-secret", "ACCESS_TOKEN": "another-fixture", "NORMAL": "yes"})
    assert "fixture-secret" not in json.dumps(job)
    assert "another-fixture" not in json.dumps(job)
    assert job["spec"]["env"]["NORMAL"] == "yes"


def test_requirements_are_frozen_without_running_installation(rig):
    ref = requirements(rig)
    job = rig.submit(runtime={"requirements": ref})
    rig.file("requirements.txt", "changed-package==99\n")
    frozen = rig.job(job["id"])
    assert frozen["runtime"]["requirements_digest"] == ref["digest"]
    assert frozen["runtime"]["state"] == "pending"
    assert rig.cluster.submissions == []


@pytest.mark.parametrize("operation", ["job.validate", "job.submit"])
def test_invalid_requirements_digest_cannot_be_ignored(rig, operation):
    ref = requirements(rig)
    ref["digest"] = "sha256:" + "0" * 64
    rig.error(operation, rig.job_request(runtime={"requirements": ref}), "CHECKSUM_MISMATCH")
    assert rig.ok("job.list", {"campaign_id": rig.campaign})["items"] == []


def test_validate_checks_code_snapshot(rig):
    request = rig.job_request()
    request["code"]["digest"] = "sha256:" + "0" * 64
    rig.error("job.validate", request, "CHECKSUM_MISMATCH")


def test_changed_runtime_conflicts_under_same_idempotency_key(rig):
    request = rig.job_request(runtime={"requirements": requirements(rig)})
    rig.ok("job.submit", request)
    changed = deepcopy(request)
    changed["runtime"]["requirements"] = requirements(rig, "another-package==2\n")
    rig.error("job.submit", changed, "IDEMPOTENCY_CONFLICT")


@pytest.mark.parametrize(
    "kind,filename",
    [
        ("adapter", "adapter.bin"),
        ("custom_checkpoint", "state.dat"),
        ("generated_dataset", "rows.jsonl"),
        ("research_report", "report.txt"),
    ],
)
def test_non_hf_research_outputs_register_and_fetch(rig, tmp_path, kind, filename):
    path = rig.file("generic/" + filename, "content for " + kind)
    artifact = rig.ok(
        "artifact.register",
        {
            "campaign_id": rig.campaign,
            "kind": kind,
            "path": str(path.parent),
            "parents": [rig.base],
            "files": [{"path": filename, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}],
        },
    )
    assert artifact["kind"] == kind
    destination = tmp_path / "fetched"
    rig.ok("artifact.fetch", {"id": artifact["id"], "output": str(destination)})
    assert (destination / filename).read_bytes() == path.read_bytes()


def test_legacy_hf_model_integrity_is_not_weakened(rig):
    path = rig.file("broken/config.json", "{}")
    rig.error(
        "artifact.register",
        {
            "campaign_id": rig.campaign,
            "path": str(path.parent),
            "kind": "model",
            "files": [{"path": "config.json", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}],
        },
        "INCOMPLETE_MODEL",
    )


def test_legacy_job_outputs_are_explicitly_not_requested(rig):
    job = rig.submit()
    result = rig.ok("job.outputs", {"id": job["id"]})
    assert result == {"state": "not_requested", "items": []}


@pytest.mark.parametrize("verb", ["validate", "outputs"])
def test_dedicated_cli_routes_new_operations(monkeypatch, tmp_path, verb, capsys):
    from rsi_red.cli import main

    monkeypatch.setenv("RSI_TOKEN", "fixture-token")
    monkeypatch.delenv("RSI_TOKEN_FILE", raising=False)
    calls = []

    def call(endpoint, token, operation, payload, timeout):
        calls.append((operation, payload))
        return {"data": {}, "error": None}

    monkeypatch.setattr("rsi_red.cli.call", call)
    path = tmp_path / "job.json"
    path.write_text(json.dumps({"campaign_id": "fixture-campaign"}))
    args = (
        ["job", "validate", "--spec", str(path)] if verb == "validate" else ["job", "outputs", "fixture-job"]
    )
    assert main(args) == 0
    assert calls == [
        ("job." + verb, {"campaign_id": "fixture-campaign"} if verb == "validate" else {"id": "fixture-job"})
    ]
    capsys.readouterr()


def test_changed_training_length_is_not_mistaken_for_idempotent_retry(rig):
    rig.submit(env={"MAX_TOKENS": "1024"})
    rig.error("job.submit", rig.job_request(env={"MAX_TOKENS": "4096"}), "IDEMPOTENCY_CONFLICT")
