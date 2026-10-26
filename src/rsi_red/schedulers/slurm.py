"""Slurm command adapter; all subprocesses use argv, bounded timeouts and checked exit codes."""
import re
import shlex
import subprocess
from pathlib import Path
import itertools


class SlurmScheduler:
    def __init__(self, *, runner=subprocess.run, partition=None, account=None, image_runner=None, **_):
        self.runner, self.partition, self.account = runner, partition, account
        self.image_runner = image_runner  # e.g. site-supported apptainer exec; never infer cluster policy

    def _run(self, argv, **kwargs):
        result = self.runner(argv, capture_output=True, text=True, timeout=30, shell=False, **kwargs)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or f"Slurm command failed: {argv[0]}")
        return result.stdout.strip()

    def submit(self, request, *, submission_key):
        argv = ["sbatch", "--parsable", "--comment", submission_key,
                "--time", str(max(1, int((request["resources"]["walltime_seconds"] + 59) // 60))),
                "--output", request.get("log_path", "slurm-%j.out")]
        if request["resources"]["gpus"]:
            argv += ["--gpus", str(request["resources"]["gpus"])]
        if self.partition:
            argv += ["--partition", self.partition]
        if self.account:
            argv += ["--account", self.account]
        command = request["entrypoint"]
        if request.get("image"):
            if not self.image_runner:
                raise RuntimeError("Pinned image requires an explicitly configured Slurm image_runner")
            command = [*self.image_runner, request["image"], *command]
        script = "#!/bin/bash\nset -euo pipefail\n"
        if request.get("workdir"):
            script += "cd " + shlex.quote(request["workdir"]) + "\n"
        for key, value in request.get("env", {}).items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                raise ValueError("Invalid environment variable name")
            script += "export " + key + "=" + shlex.quote(str(value)) + "\n"
        script += "exec " + shlex.join(command) + "\n"
        value = self._run(argv, input=script).split(";", 1)[0]
        if not re.fullmatch(r"\d+(?:_[\d]+)?", value):
            raise RuntimeError("Malformed sbatch response")
        return value

    def find(self, submission_key):
        active = self._run(["squeue", "--noheader", "--format=%i|%k"])
        history = self._run(["sacct", "--noheader", "--parsable2", "--allocations", "--starttime=now-7days",
                             "--format=JobIDRaw,Comment"])
        for line in (active + "\n" + history).splitlines():
            parts = line.split("|")
            if len(parts) >= 2 and parts[1].strip() == submission_key:
                return parts[0].strip()
        return None

    def status(self, job_id):
        # Query accounting even when the live queue is empty: disappearance is not success.
        self._run(["squeue", "--noheader", "--jobs", job_id, "--format=%i|%T"])
        records = self._run(["sacct", "--noheader", "--parsable2", "--jobs", job_id, "--allocations",
                             "--format=JobIDRaw,State,ExitCode,ElapsedRaw,AllocTRES"])
        for line in records.splitlines():
            parts = line.split("|")
            if len(parts) < 5 or parts[0].strip() != job_id:
                continue
            raw, exit_code = parts[1].strip().split()[0].rstrip("+"), parts[2].strip()
            state, reason = self.map_state(raw, exit_code)
            elapsed = int(parts[3] or 0)
            tres = parts[4]
            match = re.search(r"(?:^|,)gres/gpu=(\d+)", tres)
            gpu_count = int(match.group(1)) if match else (int(tres) if tres.isdigit() else 0)
            return {"state": state, "reason": reason, "gpu_seconds": elapsed * gpu_count}
        return {"state": "queued", "reason": "awaiting_accounting", "gpu_seconds": 0}

    @staticmethod
    def map_state(raw, exit_code="0:0"):
        if raw == "COMPLETED":
            return ("succeeded", None) if exit_code == "0:0" else ("failed", "training_error")
        if raw in {"RUNNING", "COMPLETING", "SUSPENDED"}:
            return "running", None
        if raw in {"PENDING", "CONFIGURING", "REQUEUED", "RESIZING"}:
            return "queued", None
        mapping = {"OUT_OF_MEMORY": ("failed", "oom"), "NODE_FAIL": ("failed", "node_lost"),
                   "PREEMPTED": ("failed", "preempted"), "TIMEOUT": ("timed_out", "walltime"),
                   "CANCELLED": ("cancelled", "user_cancelled"), "FAILED": ("failed", "training_error"),
                   "BOOT_FAIL": ("failed", "node_lost"), "DEADLINE": ("timed_out", "walltime")}
        return mapping.get(raw, ("failed", "unrecognized_scheduler_state"))

    def cancel(self, job_id):
        self._run(["scancel", job_id])

    def logs(self, job_id, *, offset=0, limit=100):
        output = self._run(["sacct", "--noheader", "--parsable2", "--jobs", job_id, "--allocations",
                            "--format=StdOut%4096"])
        filename = output.splitlines()[0].rstrip("|") if output else ""
        if not filename or not Path(filename).exists():
            return []
        with Path(filename).open(errors="replace") as stream:
            return [line.rstrip("\n") for line in itertools.islice(stream, offset, offset + limit)]
