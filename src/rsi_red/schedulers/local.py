"""CPU development backend with durable worker identity; never pretends to allocate GPUs."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import threading


def write_json(path, value):
    temporary = path.with_suffix(".tmp." + str(os.getpid()))
    with temporary.open("w") as stream:
        json.dump(value, stream, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


class LocalScheduler:
    cpu_only = True
    supports_runtime = True
    supports_outputs = True
    def __init__(self, *, root, allow_cpu_only=False):
        if not allow_cpu_only:
            raise ValueError("Local backend requires explicit allow_cpu_only=true")
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)


    def _folder(self, key):
        if not key or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in key):
            raise ValueError("Invalid local job identity")
        return self.root / key

    def _launch(self, folder):
        # Worker owns an OS file lock. Duplicate wrapper launches cannot launch a second trainer.
        if (folder / "result.json").exists():
            return
        import fcntl
        with (folder / "worker.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            fcntl.flock(lock, fcntl.LOCK_UN)
        with (folder / "worker.log").open("ab") as log:
            environment = dict(os.environ)
            environment["PYTHONPATH"] = os.pathsep.join(str(p) for p in sys.path if p)
            child = subprocess.Popen([sys.executable, "-m", "rsi_red.worker", str(folder)],
                stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True, close_fds=True,
                env=environment)
        # Retain and reap wrappers without tying trainer lifetime to this scheduler object.
        threading.Thread(target=child.wait, daemon=True).start()

    def submit(self, request, *, submission_key):
        if request["resources"]["gpus"] != 0:
            raise ValueError("Local CPU backend cannot allocate GPUs")
        folder = self._folder(submission_key)
        folder.mkdir(exist_ok=True)
        if not (folder / "request.json").exists():
            write_json(folder / "request.json", request)
        self._launch(folder)
        return submission_key

    def find(self, submission_key):
        folder = self._folder(submission_key)
        if not (folder / "request.json").exists():
            return None
        self._launch(folder)
        return submission_key

    def status(self, job_id):
        folder = self._folder(job_id)
        for name in ["result.json", "state.json"]:
            path = folder / name
            if path.exists():
                record = json.loads(path.read_text())
                if name == "state.json":
                    record["elapsed_seconds"] = max(0, time.time() - record["started_at"])
                return record
        return {"state": "queued", "reason": None, "gpu_seconds": 0, "backend": "local-cpu"}

    def cancel(self, job_id):
        (self._folder(job_id) / "cancel.request").touch()

    def logs(self, job_id, *, offset=0, limit=100):
        path = self._folder(job_id) / "output.log"
        if not path.exists():
            return []
        # Bound returned lines. Disk quota/rotation are deployment concerns.
        with path.open(errors="replace") as stream:
            import itertools
            return [line.rstrip("\n") for line in itertools.islice(stream, offset, offset + limit)]
