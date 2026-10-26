"""Detached CPU worker: owns execution and writes completion independently of control service."""
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from .schedulers.local import write_json


def main():
    folder = Path(sys.argv[1])
    with (folder / "worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        if (folder / "result.json").exists():
            return
        previous = folder / "state.json"
        if previous.exists():
            # A previous worker died after starting execution: do not rerun an ambiguous trainer.
            write_json(folder / "result.json", {"state": "failed", "reason": "worker_lost",
                                                "gpu_seconds": 0, "backend": "local-cpu"})
            return
        request = json.loads((folder / "request.json").read_text())
        started = time.time()
        record = {"state": "running", "reason": None, "gpu_seconds": 0,
                  "started_at": started, "worker_pid": os.getpid(), "backend": "local-cpu"}
        if request.get('_result_dir'):
            from .execution import execute
            request['_cancel_path'] = str(folder / 'cancel.request')
            write_json(previous, record)
            with (folder / 'output.log').open('ab') as output:
                record.update(execute(request, output))
            record['elapsed_seconds'] = time.time() - started
            write_json(folder / 'result.json', record)
            return
        process = None
        try:
            with (folder / "output.log").open("ab") as output:
                process = subprocess.Popen(request["entrypoint"], cwd=request.get("workdir"),
                    env=dict(os.environ, **request.get("env", {})), stdin=subprocess.DEVNULL,
                    stdout=output, stderr=output, start_new_session=True)
                record["child_pid"] = process.pid
                write_json(previous, record)
                reason = None
                deadline = time.monotonic() + request["resources"]["walltime_seconds"]
                while process.poll() is None:
                    if (folder / "cancel.request").exists():
                        reason = "user_cancelled"
                        break
                    if time.monotonic() >= deadline:
                        reason = "walltime"
                        break
                    time.sleep(.05)
                if reason:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=2)
                else:
                    process.wait()
                record.update(exit_code=process.returncode,
                              state="cancelled" if reason == "user_cancelled" else "timed_out" if reason else
                                    "succeeded" if process.returncode == 0 else "failed",
                              reason=reason or (None if process.returncode == 0 else "training_error"))
        except Exception as error:
            record.update(state="failed", reason="launch_error", diagnostic=type(error).__name__)
        finally:
            if process is not None and process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            record["elapsed_seconds"] = time.time() - started
            write_json(folder / "result.json", record)


if __name__ == "__main__":
    main()
