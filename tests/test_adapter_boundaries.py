from datetime import datetime, timedelta, timezone
import importlib
import subprocess

import pytest


def test_slurm_parses_gpu_tres_and_does_not_count_cpus_as_gpus():
    from rsi_red.schedulers.slurm import SlurmScheduler
    def runner(argv, **kwargs):
        output = "901|RUNNING|0:0|120|billing=8,cpu=8,gres/gpu=2,mem=32G\n" if argv[0] == "sacct" else ""
        return subprocess.CompletedProcess(argv, 0, output, "")
    result = SlurmScheduler(runner=runner).status("901")
    assert result["state"] == "running"
    assert result["gpu_seconds"] == 240


def test_slurm_reads_actual_shared_log_with_bounded_lines(tmp_path):
    from rsi_red.schedulers.slurm import SlurmScheduler
    log = tmp_path / "job.log"
    log.write_text("line0\nline1\nline2\n")
    def runner(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, str(log) + "|\n", "")
    assert SlurmScheduler(runner=runner).logs("901", offset=1, limit=1) == ["line1"]


def test_kubernetes_maps_deadline_and_allocated_gpu_time():
    from rsi_red.schedulers.kubernetes import KubernetesScheduler
    begin = datetime.now(timezone.utc) - timedelta(seconds=30)
    class API:
        def read_namespaced_job(self, *args):
            return {"spec": {"template": {"spec": {"containers": [
                {"resources": {"limits": {"nvidia.com/gpu": 2}}}]}}},
                "status": {"start_time": begin, "completion_time": begin + timedelta(seconds=30),
                    "conditions": [{"type": "Failed", "status": "True", "reason": "DeadlineExceeded"}]}}
    result = KubernetesScheduler(api=API(), namespace="test").status("job")
    assert result["state"] == "timed_out"
    assert result["gpu_seconds"] == 60


def test_kubernetes_rejects_ambiguous_submission_identity():
    module = importlib.import_module("rsi_red.schedulers.kubernetes")
    class API:
        def list_namespaced_job(self, **kwargs):
            return {"items": [{"metadata": {"name": "one"}}, {"metadata": {"name": "two"}}]}
    with pytest.raises(RuntimeError, match="Multiple"):
        module.KubernetesScheduler(api=API(), namespace="test").find("same-key")
