"""Ray Jobs adapter. Ray manages job lifetime; the control plane keeps research provenance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shlex
import time

TIMEOUT_MARKER = "RSI_RAY_WALLTIME_EXCEEDED"


class RayUnavailable(TimeoutError):
    def __init__(self, code="RAY_UNAVAILABLE"):
        self.code = code
        super().__init__(code)  # never include SDK body, credentials or arbitrary endpoint text


def bounded_client(*, address, headers, request_timeout):
    from ray.job_submission import JobSubmissionClient

    # Ray 2.59 SDK does not set an HTTP deadline. This pinned hook also bounds startup checks.
    class BoundedClient(JobSubmissionClient):
        def _do_request(self, method, endpoint, **kwargs):
            kwargs.setdefault("timeout", request_timeout)
            return super()._do_request(method, endpoint, **kwargs)

    return BoundedClient(address, headers=headers)


class RayScheduler:
    @property
    def supports_runtime(self):
        return self.shared_filesystem

    @property
    def supports_outputs(self):
        return self.shared_filesystem

    def __init__(
        self,
        *,
        client=None,
        address="http://127.0.0.1:8265",
        runtime_env=None,
        shared_filesystem=False,
        cluster_image=None,
        python_executable=None,
        auth_mode="auto",
        auth_token_file=None,
        request_timeout=10,
        client_factory=None,
    ):
        if auth_mode not in {"auto", "token", "disabled"}:
            raise ValueError("Invalid Ray authentication mode")
        if not 0 < request_timeout <= 300:
            raise ValueError("Invalid Ray HTTP timeout")
        if python_executable and not Path(python_executable).is_absolute():
            raise ValueError("python_executable must be an absolute path on Ray nodes")
        if auth_mode == "token" and not auth_token_file:
            raise ValueError("Token mode requires auth_token_file")
        if auth_mode == "disabled" and auth_token_file:
            raise ValueError("Disabled auth cannot have a token file")
        self.address, self.auth_mode = address, auth_mode
        self.auth_token_file, self.request_timeout = auth_token_file, request_timeout
        self._factory = client_factory or (bounded_client if client is None else None)
        self.client = client  # lazy connect: service can start while head is temporarily unavailable
        self.runtime_env = dict(runtime_env or {})
        self.cluster_image = cluster_image
        self.shared_filesystem = shared_filesystem
        self.python_executable = python_executable

    def reconnect(self):
        if self._factory is None:
            return
        headers = {}
        if self.auth_token_file:
            path = Path(self.auth_token_file)
            if path.stat().st_mode & 0o077:
                raise ValueError("Ray token file must not be group/world accessible")
            token = path.read_text().strip()
            if not token or any(ch.isspace() for ch in token):
                raise ValueError("Invalid Ray token file")
            headers["Authorization"] = "Bearer " + token
        elif self.auth_mode == "disabled":
            # Explicit empty header prevents SDK auto-loading a local token. Never changes head auth.
            headers["Authorization"] = ""
        self.client = self._factory(
            address=self.address, headers=headers, request_timeout=self.request_timeout
        )

    @staticmethod
    def _failure(error):
        if "authentication" in type(error).__name__.lower() or any(
            word in str(error).lower()
            for word in ("authentication token", "unauthorized", "status code 401", "status code 403")
        ):
            return RayUnavailable("RAY_AUTH_ERROR")
        return RayUnavailable()

    def _read(self, method, *args):
        for attempt in range(2):
            try:
                if self.client is None:
                    self.reconnect()
                return getattr(self.client, method)(*args)
            except Exception as error:
                failure = self._failure(error)
                if failure.code == "RAY_AUTH_ERROR":
                    self.client = None if self._factory else self.client
                    raise failure from None
                # Ray SDK uses RuntimeError for both missing IDs and other HTTP failures.
                if (
                    method == "get_job_info"
                    and isinstance(error, RuntimeError)
                    and (str(error).startswith("Job ") and "does not exist" in str(error))
                ):
                    return None
                # HTTP 404 is accepted only for this job endpoint, not an unavailable dashboard route.
                if (
                    method == "get_job_info"
                    and "status code 404" in str(error)
                    and "does not exist" in str(error)
                ):
                    return None
                if not self._factory or attempt:
                    raise failure from None
                self.client = None
        raise RayUnavailable()

    def _info(self, key):
        return self._read("get_job_info", key)

    def find(self, submission_key):
        return submission_key if self._info(submission_key) is not None else None

    def submit(self, request, *, submission_key):
        folder = Path(request["workdir"]).resolve()
        if request.get("image") and request["image"] != self.cluster_image:
            raise ValueError(
                "Requested image label differs from cluster_image; labels do not verify the running container"
            )
        environment = dict(self.runtime_env)
        environment["working_dir"] = str(folder)
        environment["env_vars"] = dict(environment.get("env_vars", {}), **request.get("env", {}))
        argv = list(request["entrypoint"])
        if self.python_executable:
            environment["env_vars"]["PATH"] = (
                str(Path(self.python_executable).parent)
                + ":"
                + environment["env_vars"].get("PATH", "/usr/local/bin:/usr/bin:/bin")
            )
            if not request.get("_result_dir") and Path(argv[0]).name.startswith("python"):
                argv[0] = self.python_executable
        for i, arg in enumerate(argv):
            path = Path(arg)
            # Preserve absolute interpreters; only staged input paths become portable.
            if i and path.is_absolute() and path.is_relative_to(folder):
                argv[i] = str(path.relative_to(folder))
        resources = request["resources"]
        seconds = resources["walltime_seconds"]
        if seconds <= 0 or resources.get("gpus", 0) < 0 or resources.get("cpus", 1) < 0:
            raise ValueError("Invalid Ray resources")
        wrapper = folder / ("_rsi_ray_" + hashlib.sha256(submission_key.encode()).hexdigest()[:16] + ".py")
        if request.get('_result_dir'):
            # Runner is shipped as source: the selected task venv need not install rsi-red.
            from .. import execution
            runner = folder / '_rsi_execution.py'
            runner.write_bytes(Path(execution.__file__).read_bytes())
            managed = dict(request, entrypoint=argv, workdir='.',
                           _default_python=self.python_executable or 'python')
            if managed.get('_requirements_file'):
                managed['_requirements_file'] = str(Path(managed['_requirements_file']).relative_to(folder))
            wrapper.write_text('import json,sys\nfrom _rsi_execution import execute\n'
                + 'request=json.loads(' + repr(json.dumps(managed)) + ')\n'
                + 'result=execute(request,sys.stdout)\n'
                + 'raise SystemExit(0 if result["state"]=="succeeded" else 124 if result["state"]=="timed_out" else 1)\n')
        else:
            wrapper.write_text(
                """import json, os, signal, subprocess, sys
argv = json.loads(%r)
process = subprocess.Popen(argv, start_new_session=True)
try:
    code = process.wait(timeout=%r)
except subprocess.TimeoutExpired:
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
    print(%r, flush=True)
    code = 124
raise SystemExit(code)

"""
                % (json.dumps(argv), seconds, TIMEOUT_MARKER)
            )
        if self.client is None:
            try:
                self.reconnect()
            except Exception as error:
                raise self._failure(error) from None
        try:
            return self.client.submit_job(
                entrypoint=shlex.join([self.python_executable or "python", wrapper.name]),
                submission_id=submission_key,
                runtime_env=environment,
                metadata={
                    "rsi-red/submission-key": submission_key,
                    "rsi-red/gpus": str(resources.get("gpus", 0)),
                    "rsi-red/accounting": "driver-reservation-estimate",
                    "rsi-red/environment-verification": "operator-declared-label-only",
                },
                entrypoint_num_cpus=resources.get("cpus", 1),
                entrypoint_num_gpus=resources.get("gpus", 0),
            )
        except Exception as error:
            # Submission is a write: reconnect later and look up the stable ID, never replay here.
            self.client = None if self._factory else self.client
            raise self._failure(error) from None

    def status(self, job_id):
        info = self._info(job_id)
        if info is None:
            # Missing jobs are not proof of success, nor permission to retrain.
            raise RayUnavailable("RAY_JOB_LOST")
        raw = getattr(info.status, "value", str(info.status))
        state = {
            "PENDING": "queued",
            "RUNNING": "running",
            "SUCCEEDED": "succeeded",
            "FAILED": "failed",
            "STOPPED": "cancelled",
        }.get(raw, "failed")
        reason = "user_cancelled" if state == "cancelled" else "training_error" if state == "failed" else None
        try:
            logs = self._read("get_job_logs", job_id) if state == "failed" else ""
        except RayUnavailable:
            logs = ""
        if state == "failed" and TIMEOUT_MARKER in logs:
            state, reason = "timed_out", "walltime"
        error_type = getattr(info, "error_type", None)
        if state == "failed" and error_type == "RUNTIME_ENV_SETUP_FAILURE":
            reason = "runtime_env_setup_failed"
        begin = getattr(info, "start_time", None)
        end = getattr(info, "end_time", None)
        elapsed = max(0, ((end if end is not None else time.time() * 1000) - begin) / 1000) if begin else 0
        gpu_count = float((getattr(info, "metadata", None) or {}).get("rsi-red/gpus", "0"))
        return {
            "state": state,
            "reason": reason,
            "gpu_seconds": elapsed * gpu_count,
            "exit_code": getattr(info, "driver_exit_code", None),
            "diagnostic": self._diagnostic(info) if state == "failed" else None,
            "scheduler_error_type": error_type,
            "environment_verification": "operator-declared-label-only",
            "accounting_estimate": True,
            "accounting_scope": "Ray job driver resources, not child actors",
        }

    def cancel(self, job_id):
        if self._info(job_id) is not None:
            try:
                self.client.stop_job(job_id)
            except Exception as error:
                raise self._failure(error) from None

    def logs(self, job_id, *, offset=0, limit=100):
        lines = self._read("get_job_logs", job_id).splitlines()
        if not lines:
            info = self._info(job_id)
            if info and self._diagnostic(info):
                lines = ["[ray diagnostic] " + self._diagnostic(info)]
        return lines[offset : offset + limit]

    def _diagnostic(self, info):
        text = str(getattr(info, "message", None) or "")[:4000]
        # SDK runtime-env errors may contain command/env text. Redact credentials known to this adapter.
        if self.auth_token_file:
            try:
                token = Path(self.auth_token_file).read_text().strip()
                if token:
                    text = text.replace(token, "[REDACTED]")
            except OSError:
                pass
        import re

        text = re.sub(r"(?i)(bearer\s+)[^\s,;]+", r"\1[REDACTED]", text)
        text = re.sub(
            r'(?i)((?:token|password|secret|api_key)["\']?\s*[:=]\s*["\']?)[^\s,;"\']+', r"\1[REDACTED]", text
        )
        return text
