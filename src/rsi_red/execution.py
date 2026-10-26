"""Standard-library task runner, also staged verbatim for Ray workers.

One deadline includes environment preparation, execution and collection. Shared
result directories are an operator-declared transport, not a security sandbox.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp.' + str(os.getpid()))
    with temporary.open('w') as stream:
        json.dump(value, stream, sort_keys=True, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def fingerprint(value):
    return 'sha256:' + hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class Stopped(Exception):
    def __init__(self, reason):
        self.reason = reason


class SetupFailed(Exception):
    pass


def execute(request, output):
    root = Path(request['_result_dir'])
    root.mkdir(parents=True, exist_ok=True)
    receipt = root / 'result.json'
    if receipt.exists():
        return json.loads(receipt.read_text())
    cwd = Path(request.get('workdir', '.')).resolve()
    deadline = time.monotonic() + request['resources']['walltime_seconds']
    env = dict(os.environ, **request.get('env', {}))
    env['PIP_DISABLE_PIP_VERSION_CHECK'] = '1'
    active = None
    record = {'state': 'running', 'reason': None, 'stage': 'runtime', 'job_id': request['_job_id'],
              'runtime': {'state': 'preparing'}, 'outputs': {'state': 'pending', 'items': []}}

    def progress():
        write(root / 'progress.json', record)

    def check():
        if request.get('_cancel_path') and Path(request['_cancel_path']).exists():
            raise Stopped('user_cancelled')
        if time.monotonic() >= deadline:
            raise Stopped('walltime')

    def run(argv, capture=None):
        nonlocal active
        check()
        active = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                  stdout=capture if capture is not None else output,
                                  stderr=output, start_new_session=True)
        try:
            while active.poll() is None:
                check()
                time.sleep(.03)
            return active.returncode
        finally:
            if active.poll() is None:
                os.killpg(active.pid, signal.SIGTERM)
                try:
                    active.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(active.pid, signal.SIGKILL)
                    active.wait()
            active = None

    old_handler = signal.getsignal(signal.SIGTERM)
    def terminate(*_):
        raise Stopped('user_cancelled')
    signal.signal(signal.SIGTERM, terminate)
    try:
        progress()
        config = request.get('runtime', {})
        python = config.get('python_executable') or request.get('_default_python') or sys.executable
        if request.get('_requirements_file'):
            # The harness sets PYTHONPATH to import its own worker. Do not let
            # inherited site-packages override dependencies in a task venv.
            for key in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONUSERBASE', 'PIP_TARGET', 'PIP_PREFIX', 'PIP_USER'):
                if key not in request.get('env', {}):
                    env.pop(key, None)
            if run([python, '-m', 'venv', str(root / 'venv')]) != 0:
                raise SetupFailed()
            python = str(root / 'venv' / 'bin' / 'python')
            env['VIRTUAL_ENV'] = str(root / 'venv')
            if run([python, '-m', 'pip', 'install', '-r', request['_requirements_file']]) != 0:
                raise SetupFailed()
            isolation = 'job-venv'
        else:
            isolation = 'inherited'
        # Inspect the selected Python, rather than labelling an unexecuted declaration as reality.
        inspect_code = ('import sys,json,importlib.metadata as m; '
                        'print(json.dumps({"actual_python":sys.executable,"packages":'
                        'sorted([(d.metadata.get("Name",""),d.version) for d in m.distributions()])}))')
        with (root / 'environment.raw.json').open('wb') as captured:
            if run([python, '-c', inspect_code], captured) != 0:
                raise SetupFailed()
        manifest = json.loads((root / 'environment.raw.json').read_text())
        record['runtime'] = {'state': 'ready', 'actual_python': manifest['actual_python'],
                             'packages': manifest['packages'], 'packages_digest': fingerprint(manifest['packages']),
                             'isolation': isolation, 'requested_python': config.get('python_executable'),
                             'requirements_digest': config.get('requirements', {}).get('digest')}
        record['runtime']['manifest_digest'] = fingerprint(record['runtime'])
        env['PATH'] = str(Path(python).parent) + os.pathsep + env.get('PATH', '')
        argv = list(request['entrypoint'])
        if re.fullmatch(r'python(?:\d+(?:\.\d+)*)?', Path(argv[0]).name):
            argv[0] = python
        record['stage'] = 'training'
        progress()
        exit_code = run(argv)
        record['exit_code'] = exit_code
        if exit_code:
            record.update(state='failed', reason='training_error')
        else:
            record['stage'] = 'collection'
            progress()
            record['outputs'] = collect(request, root, cwd, check)
            record.update(state='succeeded', reason=None, stage='completed')
    except Stopped as error:
        record.update(state='cancelled' if error.reason == 'user_cancelled' else 'timed_out', reason=error.reason)
        if record['runtime']['state'] == 'preparing':
            record['runtime']['state'] = 'failed'
    except Exception as error:
        reason = {'runtime': 'runtime_setup_failed', 'collection': 'output_collection_failed'}.get(record['stage'], 'launch_error')
        record.update(state='failed', reason=reason, diagnostic=type(error).__name__)
        if record['stage'] == 'runtime':
            record['runtime']['state'] = 'failed'
        if record['stage'] == 'collection':
            record['outputs'] = {'state': 'failed', 'items': [], 'reason': reason}
    finally:
        signal.signal(signal.SIGTERM, old_handler)
        write(receipt, record)
    return record


def collect(request, root, cwd, check):
    if not request.get('output_manifest'):
        return {'state': 'not_requested', 'items': []}
    def safe(relative):
        path = Path(relative)
        if path.is_absolute() or '..' in path.parts:
            raise ValueError('Output escapes workdir')
        target = cwd / path
        if not target.resolve().is_relative_to(cwd) or any(p.is_symlink() for p in [target, *target.parents] if p.is_relative_to(cwd)):
            raise ValueError('Symlink output')
        return target
    manifest = json.loads(safe(request['output_manifest']).read_text())
    items = manifest['items']
    if not isinstance(items, list) or not items:
        raise ValueError('Nonempty output manifest required')
    found, outputs = set(), []
    for index, item in enumerate(items):
        check()
        name, kind = item['name'], item['kind']
        if not isinstance(name, str) or not name or name in found or not isinstance(kind, str) or not kind:
            raise ValueError('Invalid output name or kind')
        found.add(name)
        target = safe(item['path'])
        files = [target] if target.is_file() else sorted(target.rglob('*')) if target.is_dir() else []
        snapshots = []
        destination = root / 'collected' / str(index)
        for file in files:
            check()
            if file.is_symlink():
                raise ValueError('Symlink output')
            if file.is_dir():
                continue
            safe(str(file.relative_to(cwd)))
            relative = file.relative_to(target) if target.is_dir() else Path(file.name)
            copied = destination / relative
            copied.parent.mkdir(parents=True, exist_ok=True)
            # Copy in bounded chunks, including collection time in the same deadline.
            hasher = hashlib.sha256()
            with file.open('rb') as source, copied.open('wb') as sink:
                while chunk := source.read(1024 * 1024):
                    check()
                    sink.write(chunk)
                    hasher.update(chunk)
            snapshots.append({'path': str(relative), 'sha256': hasher.hexdigest()})
        if not snapshots:
            raise ValueError('No output files')
        outputs.append({'name': name, 'kind': kind, 'path': str(destination), 'files': snapshots})
    return {'state': 'collected', 'items': outputs}
