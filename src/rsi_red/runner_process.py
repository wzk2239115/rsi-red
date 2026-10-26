"""Staged stdlib benchmark supervisor. Outer worker owns the overall deadline."""
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time


def write(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as stream:
        json.dump(value, stream, allow_nan=False, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def main():
    config = json.loads(Path(sys.argv[1]).read_text())
    root = Path(config['bindings']['config_path']).parent
    environment = {'python_version': platform.python_version(), 'packages': sorted(
        [(d.metadata.get('Name', ''), d.version) for d in importlib.metadata.distributions()]),
        'requirements_digest': config['environment']['requirements_digest']}
    receipt = {'started_at': time.time(), 'environment': environment, 'exit_code': None, 'stage': 'environment'}
    try:
        write(root / 'runner-receipt.json', receipt)
        if environment['python_version'] != config['environment']['python_version']:
            raise ValueError('Python version mismatch')
        env = dict(os.environ)
        for key, reference in config.get('secret_refs', {}).items():
            env[key] = os.environ[reference.removeprefix('env:')]
        command = list(config['command'])
        if command[0] == config['environment']['python_executable']:
            command[0] = sys.executable
        receipt.update(stage='execution', actual_command=command, actual_python=sys.executable, workdir=str(Path.cwd()))
        write(root / 'runner-receipt.json', receipt)
        code = subprocess.call(command, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL if config.get('secret_refs') else None,
                               stderr=subprocess.DEVNULL if config.get('secret_refs') else None)
        receipt['exit_code'] = code
        if code:
            return code
        receipt['stage'] = 'collection'
        output = Path(config['bindings']['output_path'])
        source = root / 'source'
        if not output.resolve().is_relative_to(source.resolve()) or output.is_symlink():
            raise ValueError('Output escapes source')
        raw = output.read_bytes()
        inputs = [json.loads(line) for line in Path(config['bindings']['input_path']).read_text().splitlines()]
        expected = {i['id']: i['task'] for i in inputs}
        rows, seen = [], set()
        for line in raw.decode().splitlines():
            row = json.loads(line)
            key = row['id']
            if key in seen or key not in expected or row['task'] != expected[key] or not isinstance(row['prediction'], str):
                raise ValueError('Invalid item identity or prediction')
            if type(row['score']) not in (int, float) or not math.isfinite(row['score']) or not 0 <= row['score'] <= 1:
                raise ValueError('Invalid raw score')
            if not isinstance(row['finish_reason'], str) or not row['finish_reason']:
                raise ValueError('Invalid finish reason')
            if 'output_tokens' in row and (type(row['output_tokens']) is not int or row['output_tokens'] < 0):
                raise ValueError('Invalid token count')
            seen.add(key)
            rows.append({k: row[k] for k in ('id', 'task', 'prediction', 'score', 'finish_reason', 'output_tokens') if k in row} |
                        {'answer': row['prediction']})
        if seen != set(expected):
            raise ValueError('Incomplete evaluation')
        write(root / 'validated-output.json', rows)
        receipt.update(stage='completed', output_sha256=hashlib.sha256(raw).hexdigest())
        return 0
    except Exception as error:
        receipt['error'] = type(error).__name__
        return 65
    finally:
        receipt['finished_at'] = time.time()
        write(root / 'runner-receipt.json', receipt)


if __name__ == '__main__':
    raise SystemExit(main())
