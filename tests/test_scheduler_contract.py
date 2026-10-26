"""Adapters talk only to fake external command/API boundaries; never to real clusters."""
import importlib
import subprocess

import pytest


class SlurmRunner:
    def __init__(self):
        self.calls = []
        self.fail_submit = False

    def __call__(self, argv, **kwargs):
        assert isinstance(argv, list) and all(isinstance(x, str) for x in argv)
        assert kwargs.get("shell", False) is False
        self.calls.append((argv, kwargs))
        executable = argv[0].split("/")[-1]
        if executable == "sbatch":
            if self.fail_submit:
                return subprocess.CompletedProcess(argv, 1, "", "invalid partition")
            return subprocess.CompletedProcess(argv, 0, "901;fixture-cluster\n", "")
        if executable == "squeue":
            return subprocess.CompletedProcess(argv, 0, "", "")
        if executable == "sacct":
            return subprocess.CompletedProcess(argv, 0, "901|COMPLETED|0:0|120|1\n", "")
        if executable == "scancel":
            return subprocess.CompletedProcess(argv, 0, "", "")
        raise AssertionError(f"Unexpected external executable: {argv}")


def slurm(runner):
    return importlib.import_module("rsi_red.schedulers.slurm").SlurmScheduler(runner=runner)


def test_slurm_submission_uses_parsable_id_and_preserves_argv():
    runner = SlurmRunner()
    adapter = slurm(runner)
    request = {"entrypoint": ["python", "train.py", "--name", "a; touch /tmp/never"],
               "resources": {"gpus": 2, "walltime_seconds": 3600}, "log_path": "/tmp/rsi.log"}
    assert adapter.submit(request, submission_key="request-1") == "901"
    argv, kwargs = next(call for call in runner.calls if call[0][0].endswith("sbatch"))
    assert "--parsable" in argv
    script = kwargs.get("input", "")
    assert "request-1" in " ".join(argv) + script
    assert "a; touch /tmp/never" in script  # one quoted argument, no shell injection
    assert "'a; touch /tmp/never'" in script


def test_slurm_uses_accounting_when_job_leaves_queue():
    runner = SlurmRunner()
    state = slurm(runner).status("901")
    assert state["state"] == "succeeded"
    assert state["gpu_seconds"] == 120
    assert any(argv[0].endswith("sacct") for argv, _ in runner.calls)


def test_slurm_failed_submit_does_not_invent_job_id():
    runner = SlurmRunner()
    runner.fail_submit = True
    with pytest.raises(Exception, match="invalid partition"):
        slurm(runner).submit({"entrypoint": ["false"], "resources": {"gpus": 1, "walltime_seconds": 60}},
                             submission_key="failed-request")


def test_slurm_cancel_uses_exact_scheduler_id():
    runner = SlurmRunner()
    slurm(runner).cancel("901")
    assert any(argv == ["scancel", "901"] for argv, _ in runner.calls)


class KubernetesAPI:
    def __init__(self):
        self.created = []
        self.deleted = []

    def create_namespaced_job(self, namespace, body):
        self.created.append((namespace, body))
        return body

    def delete_namespaced_job(self, name, namespace, **kwargs):
        self.deleted.append((name, namespace, kwargs))


def kubernetes(api):
    return importlib.import_module("rsi_red.schedulers.kubernetes").KubernetesScheduler(
        api=api, namespace="research")


def test_kubernetes_preserves_argv_gpu_limit_and_submission_label():
    api = KubernetesAPI()
    job_id = kubernetes(api).submit({"entrypoint": ["python", "train.py", "--name", "a b"],
        "image": "train@sha256:" + "1" * 64,
        "resources": {"gpus": 2, "walltime_seconds": 3600}}, submission_key="request-1")
    namespace, body = api.created[0]
    assert namespace == "research"
    container = body["spec"]["template"]["spec"]["containers"][0]
    assert container["command"] + container.get("args", []) == ["python", "train.py", "--name", "a b"]
    assert container["resources"]["limits"]["nvidia.com/gpu"] == 2
    assert body["metadata"]["labels"]["rsi-red/submission-key"] == "request-1"
    assert body["spec"]["activeDeadlineSeconds"] == 3600
    assert body["spec"]["backoffLimit"] == 0
    assert job_id == body["metadata"]["name"]


def test_kubernetes_cancel_deletes_dependents():
    api = KubernetesAPI()
    kubernetes(api).cancel("rsi-request-1")
    name, namespace, kwargs = api.deleted[0]
    assert (name, namespace) == ("rsi-request-1", "research")
    assert kwargs["propagation_policy"] == "Foreground"


def test_unsupported_scheduler_is_not_silently_local():
    factory = importlib.import_module("rsi_red.schedulers").create_scheduler
    with pytest.raises(ValueError, match="unsupported"):
        factory({"backend": "not-a-cluster"})
