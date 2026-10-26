"""Ray Jobs adapter. Ray manages job lifetime; the control plane keeps research provenance."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shlex
import sys
import time

TIMEOUT_MARKER = 'RSI_RAY_WALLTIME_EXCEEDED'


class RayScheduler:
    def __init__(self, *, client=None, address='http://127.0.0.1:8265', runtime_env=None, cluster_image=None):
        if client is None:
            from ray.job_submission import JobSubmissionClient
            client = JobSubmissionClient(address)
        self.client = client
        self.runtime_env = dict(runtime_env or {})
        self.cluster_image = cluster_image

    def _info(self, key):
        try:
            return self.client.get_job_info(key)
        except Exception as error:
            message = str(error).lower()
            if isinstance(error, RuntimeError) and ('does not exist' in message or 'not found' in message):
                return None
            raise TimeoutError('Ray job service could not be queried') from error

    def find(self, submission_key):
        return submission_key if self._info(submission_key) is not None else None

    def submit(self, request, *, submission_key):
        folder = Path(request['workdir']).resolve()
        if request.get('image') and request['image'] != self.cluster_image:
            raise ValueError('Ray node image must match the configured cluster_image; container images are not silently ignored')
        environment = dict(self.runtime_env)
        environment['working_dir'] = str(folder)
        environment['env_vars'] = dict(environment.get('env_vars', {}), **request.get('env', {}))
        argv = []
        for arg in request['entrypoint']:
            path = Path(arg)
            if path.is_absolute() and path.is_relative_to(folder):
                argv.append(str(path.relative_to(folder)))
            elif arg == sys.executable:
                argv.append('python')
            else:
                argv.append(arg)
        resources = request['resources']
        seconds = resources['walltime_seconds']
        if seconds <= 0 or resources.get('gpus', 0) < 0 or resources.get('cpus', 1) < 0:
            raise ValueError('Invalid Ray resources')
        wrapper = folder / ('_rsi_ray_' + hashlib.sha256(submission_key.encode()).hexdigest()[:16] + '.py')
        wrapper.write_text('''import json, os, signal, subprocess, sys
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
''' % (json.dumps(argv), seconds, TIMEOUT_MARKER))
        return self.client.submit_job(entrypoint=shlex.join(['python', wrapper.name]),
            submission_id=submission_key, runtime_env=environment,
            metadata={'rsi-red/submission-key': submission_key, 'rsi-red/gpus': str(resources.get('gpus', 0)),
                      'rsi-red/accounting': 'driver-reservation-estimate'},
            entrypoint_num_cpus=resources.get('cpus', 1), entrypoint_num_gpus=resources.get('gpus', 0))

    def status(self, job_id):
        info = self._info(job_id)
        if info is None:
            # Missing jobs are not proof of success, nor permission to retrain.
            return {'state': 'failed', 'reason': 'ray_job_lost', 'gpu_seconds': 0}
        raw = getattr(info.status, 'value', str(info.status))
        state = {'PENDING': 'queued', 'RUNNING': 'running', 'SUCCEEDED': 'succeeded',
                 'FAILED': 'failed', 'STOPPED': 'cancelled'}.get(raw, 'failed')
        reason = 'user_cancelled' if state == 'cancelled' else 'training_error' if state == 'failed' else None
        if state == 'failed' and TIMEOUT_MARKER in self.client.get_job_logs(job_id):
            state, reason = 'timed_out', 'walltime'
        begin = getattr(info, 'start_time', None)
        end = getattr(info, 'end_time', None)
        elapsed = max(0, ((end if end is not None else time.time() * 1000) - begin) / 1000) if begin else 0
        gpu_count = float((getattr(info, 'metadata', None) or {}).get('rsi-red/gpus', '0'))
        return {'state': state, 'reason': reason, 'gpu_seconds': elapsed * gpu_count,
                'accounting_estimate': True, 'accounting_scope': 'Ray job driver resources, not child actors'}

    def cancel(self, job_id):
        if self._info(job_id) is not None:
            self.client.stop_job(job_id)

    def logs(self, job_id, *, offset=0, limit=100):
        return self.client.get_job_logs(job_id).splitlines()[offset:offset + limit]
