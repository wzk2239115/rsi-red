"""Immutable benchmark configurations and private asynchronous execution records."""
from copy import deepcopy
import hashlib
import io
import json
import math
from pathlib import Path
import re
import string
import subprocess
import tarfile
import time

from .audit import evaluation_summary
from .errors import ResearchError, require
from .evaluation import summarize
from .schedulers.local import LocalScheduler, write_json
from .store import digest

TERMINAL = {'succeeded', 'failed', 'cancelled', 'timed_out'}


def shape(value, required, optional=()):
    require(isinstance(value, dict) and set(required) <= value.keys()
            and value.keys() <= set(required) | set(optional), 'INVALID_REQUEST', 'Invalid configuration fields')


def sha(content):
    return hashlib.sha256(content).hexdigest()


def relative(value):
    require(isinstance(value, str) and value and not Path(value).is_absolute()
            and '..' not in Path(value).parts and value != '.', 'INVALID_REQUEST', 'Relative file path required')
    return value


def compatible(left, right):
    require(left['protocol_digest'] == right['protocol_digest'], 'PROTOCOL_MISMATCH', 'Frozen protocol differs')
    require(left.get('runner_digest') == right.get('runner_digest'), 'RUNNER_MISMATCH', 'Frozen runner differs')
    require(left.get('comparison_digest') == right.get('comparison_digest'),
            'EVALUATION_CONFIG_MISMATCH', 'Actual execution configuration differs')


class RunnerMixin:
    def _runner_access(self, runner, actor):
        self.op_protocol_show({'id': runner['protocol_id']}, actor)
        return runner

    def _runner_view(self, runner, actor):
        self._runner_access(runner, actor)
        if actor['role'] == 'operator':
            return runner
        return {k: runner[k] for k in ('id', 'name', 'digest', 'protocol_id', 'protocol_digest')}

    def op_runner_show(self, p, actor):
        return self._runner_view(self.store.get(p['id'], 'runner'), actor)

    def op_runner_list(self, p, actor):
        found = []
        for runner in self.store.list('runner'):
            if p.get('protocol_id') and p['protocol_id'] != runner['protocol_id']:
                continue
            try:
                found.append(self._runner_view(runner, actor))
            except ResearchError as error:
                if error.code != 'FORBIDDEN':
                    raise
        return {'items': found}

    def op_runner_register(self, p, actor):
        self._operator(actor)
        shape(p, ('name', 'protocol_id', 'source', 'judge', 'dataset', 'decoding', 'environment',
                  'execution', 'command', 'output_schema'), ('secret_refs',))
        require(isinstance(p['name'], str) and p['name'], 'INVALID_REQUEST', 'Runner name required')
        protocol = self._protocol(p['protocol_id'], actor)
        self._direction_ready(protocol)
        shape(p['source'], ('repository', 'commit', 'path', 'tree_digest'))
        source = p['source']
        require(isinstance(source['commit'], str) and re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', source['commit']),
                'INVALID_REQUEST', 'Full immutable commit required')
        require(isinstance(source['repository'], str) and source['repository'] and
                not re.search(r'://[^/]*@|[?&#]', source['repository']), 'INVALID_REQUEST', 'Credential-free repository required')
        shape(p['environment'], ('python_executable', 'python_version', 'requirements', 'requirements_digest'))
        env = p['environment']
        require(isinstance(env['python_executable'], str) and Path(env['python_executable']).is_absolute()
                and isinstance(env['python_version'], str) and re.fullmatch(r'\d+\.\d+\.\d+', env['python_version'])
                and isinstance(env['requirements'], str), 'INVALID_REQUEST', 'Pinned Python environment required')
        require(sha(env['requirements'].encode()) == env['requirements_digest'], 'INVALID_REQUEST', 'Requirements digest differs')
        # Only pinned distribution requirements; arbitrary pip options/URLs can contain secrets or mutable sources.
        require(all(not line.strip() or line.lstrip().startswith('#') or
                    re.fullmatch(r'[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?==[A-Za-z0-9_.+!-]+', line.strip())
                    for line in env['requirements'].splitlines()), 'INVALID_REQUEST', 'Requirements must be exact package pins')
        shape(p['execution'], ('backend', 'resources'))
        backend, resources = p['execution']['backend'], p['execution']['resources']
        shape(resources, ('gpus', 'cpus', 'walltime_seconds'))
        require(backend in {'local', 'ray'}, 'INVALID_REQUEST', 'Unsupported runner backend')
        require(type(resources['gpus']) is int and resources['gpus'] >= 0 and
                all(type(resources[k]) in (int, float) and math.isfinite(resources[k]) and
                    (resources[k] >= 0 if k == 'cpus' else resources[k] > 0)
                    for k in ('cpus', 'walltime_seconds')), 'INVALID_REQUEST', 'Invalid resources')
        require(backend != 'local' or resources['gpus'] == 0, 'UNSUPPORTED_RESOURCES', 'Local runner is CPU only')
        shape(p['output_schema'], ('format', 'path'))
        require(p['output_schema']['format'] == 'rsi-predictions-jsonl-v1', 'INVALID_REQUEST', 'Unsupported output schema')
        relative(p['output_schema']['path'])
        require(isinstance(p['command'], list) and p['command'] and p['command'][0] and all(isinstance(a, str) for a in p['command']),
                'INVALID_REQUEST', 'Command must be structured argv')
        for arg in p['command']:
            for _, field, spec, conversion in string.Formatter().parse(arg):
                require(field is None or (field in {'python', 'model', 'input', 'output', 'run_config'}
                        and not spec and not conversion), 'INVALID_REQUEST', 'Unsupported command placeholder')
        require(isinstance(p.get('secret_refs', {}), dict) and all(
            re.fullmatch(r'[A-Z_][A-Z0-9_]*', k) and isinstance(v, str) and
            re.fullmatch(r'env:[A-Z_][A-Z0-9_]*', v) for k, v in p.get('secret_refs', {}).items()),
            'INVALID_REQUEST', 'Secrets must be environment references')
        require(not any(re.search(r'(?i)(?:token|password|api[_-]?key|secret)\s*[=:]|://[^/]*@', arg)
                        for arg in p['command']), 'INVALID_REQUEST', 'Use secret references')
        spec = protocol['spec']
        require(p['dataset'] == dict(spec.get('benchmark', {}), items_digest=digest(spec['items'])) and
                bool(spec.get('benchmark')) and p['decoding'] == dict(spec['sampling'], eval_seed=spec['eval_seed']),
                'RUNNER_PROTOCOL_MISMATCH', 'Dataset or decoding differs from protocol')
        judge = p['judge']
        shape(judge, ('kind', 'revision', 'code_digest'),
              ('artifact_id', 'artifact_digest', 'template', 'template_digest'))
        require(judge['kind'] in {'code', 'model'} and isinstance(judge['revision'], str) and judge['revision'],
                'INVALID_REQUEST', 'Immutable judge required')
        require(judge['code_digest'] == spec['evaluator_digest'], 'RUNNER_PROTOCOL_MISMATCH', 'Judge code differs')
        if judge['kind'] == 'model':
            require(judge == spec.get('judge'), 'RUNNER_PROTOCOL_MISMATCH', 'Model judge differs')
            artifact = self.store.get(judge['artifact_id'], 'artifact')
            require(artifact['digest'] == judge['artifact_digest'] and sha(judge['template'].encode()) ==
                    judge['template_digest'].removeprefix('sha256:'), 'CHECKSUM_MISMATCH', 'Judge identity differs')
            for file in artifact['files']:
                self.store.read_blob(file['sha256'])
        else:
            shape(judge, ('kind', 'revision', 'code_digest'))
        path = Path(source['path']).resolve()
        def git(*args):
            return subprocess.check_output(['git', '-C', str(path), *args], stderr=subprocess.DEVNULL, timeout=30)
        try:
            require(git('rev-parse', 'HEAD').decode().strip() == source['commit'] and
                    git('remote', 'get-url', 'origin').decode().strip() == source['repository'] and
                    not git('status', '--porcelain', '--untracked-files=all').strip(),
                    'RUNNER_SOURCE_MISMATCH', 'Clean pinned source required')
            archive = git('archive', '--format=tar', source['commit'])
        except (subprocess.SubprocessError, OSError):
            raise ResearchError('RUNNER_SOURCE_MISMATCH', 'Pinned checkout unavailable') from None
        files, manifest = [], []
        with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
            for member in sorted(stream.getmembers(), key=lambda m: m.name):
                if member.isdir():
                    continue
                relative(member.name)
                require(member.isfile(), 'INVALID_REQUEST', 'Source links and special files are unsupported')
                content = stream.extractfile(member).read()
                key = self.store.blob(content)
                files.append({'path': member.name, 'sha256': key, 'mode': member.mode})
                manifest.append({'path': member.name, 'sha256': key})
        require(files and digest(manifest) == source['tree_digest'], 'RUNNER_SOURCE_MISMATCH', 'Source content differs')
        if judge['kind'] == 'code':
            require(judge['revision'] == source['commit'], 'RUNNER_PROTOCOL_MISMATCH', 'Code judge revision differs')
        p['source'].pop('path')
        runner = self.store.create('runner', {'name': p['name'], 'protocol_id': protocol['id'],
            'protocol_digest': protocol['digest'], 'digest': digest(p), 'spec': p, 'files': files})
        self._event('runner.registered', runner, actor)
        return runner

    def _allocation(self, campaign_id):
        rows = [e for kind in ('job', 'eval') for e in self.store.list(kind)
                if e['campaign_id'] == campaign_id and 'reservation' in e]
        return sum(e.get('gpu_seconds', 0) if e['state'] in TERMINAL else
                   max(e.get('gpu_seconds', 0), e['reservation']) for e in rows)

    def _runner_submit(self, p, actor):
        shape(p, ('runner_id', 'model_id'), ('campaign_id', 'protocol_id', 'idempotency_key'))
        runner = self._runner_access(self.store.get(p['runner_id'], 'runner'), actor)
        model = self._entity(p['model_id'], 'artifact', actor)
        campaign = self._campaign(p.get('campaign_id', model['campaign_id']), actor)
        require(model['campaign_id'] == campaign['id'], 'FORBIDDEN', 'Model belongs to another campaign')
        require(p.get('protocol_id', runner['protocol_id']) == runner['protocol_id'],
                'RUNNER_PROTOCOL_MISMATCH', 'Explicit protocol conflicts with runner')
        require(campaign['state'] == 'open', 'CAMPAIGN_CLOSED', 'Research window is closed')
        protocol = self._protocol(runner['protocol_id'], actor)
        tasks = self._direction_ready(protocol)
        require(model.get('kind', 'model') in protocol['spec'].get('artifact_kinds', ['model']),
                'EVALUATION_UNSUPPORTED_ARTIFACT', 'Unsupported model format')
        request_digest = digest(dict(campaign_id=campaign['id'], runner_id=runner['id'], model_id=model['id']))
        key = p.get('idempotency_key')
        if key is not None:
            require(isinstance(key, str) and 0 < len(key) <= 200, 'INVALID_REQUEST', 'Invalid idempotency key')
            for e in self.store.list('eval'):
                if e.get('idempotency_key') == key and e.get('author') == actor['id'] and e['campaign_id'] == campaign['id']:
                    require(e['request_digest'] == request_digest, 'IDEMPOTENCY_CONFLICT', 'Key already used')
                    return evaluation_summary(e)
        self._audit_eval_budget(campaign['id'], protocol['id'])
        resources = runner['spec']['execution']['resources']
        reservation = resources['gpus'] * resources['walltime_seconds']
        require(self._allocation(campaign['id']) + reservation <= campaign['gpu_hours_budget'] * 3600,
                'BUDGET_EXCEEDED', 'Campaign GPU budget exhausted')
        if runner['spec']['execution']['backend'] == 'ray':
            require(getattr(self.scheduler, 'shared_filesystem', False), 'UNSUPPORTED_RUNNER_BACKEND',
                    'Ray runner requires a shared private filesystem')
        e = self.store.create('eval', dict(campaign_id=campaign['id'], model_id=model['id'], protocol_id=protocol['id'],
            model_digest=model['digest'], protocol_digest=protocol['digest'], runner_id=runner['id'], runner_digest=runner['digest'],
            state='accepted', visibility=protocol['spec']['visibility'], reason=None, task_metrics=tasks,
            normalization=protocol['spec']['normalization'], eval_seed=protocol['spec']['eval_seed'],
            repeat_index=sum(x['model_id'] == model['id'] and x['protocol_id'] == protocol['id'] for x in self.store.list('eval')),
            author=actor['id'], idempotency_key=key, request_digest=request_digest, reservation=reservation, gpu_seconds=0,
            created_at=time.time(), scheduler_id=None, submission_attempted=False))
        root = self.store.root / 'evaluations' / e['id']
        bindings = {k: str(root / v) for k, v in dict(input_path='inputs.jsonl', model_path='model',
                    output_path='source/' + runner['spec']['output_schema']['path'], config_path='run-config.json').items()}
        if runner['spec']['judge']['kind'] == 'model':
            bindings['judge_path'] = str(root / 'judge')
        spec = runner['spec']
        config = dict(schema_version=1, runner={'id': runner['id'], 'digest': runner['digest']},
                      protocol={'id': protocol['id'], 'digest': protocol['digest']},
                      model={'id': model['id'], 'digest': model['digest']},
                      **{k: deepcopy(spec[k]) for k in ('source', 'judge', 'dataset', 'decoding', 'environment')},
                      resources=deepcopy(resources), backend=spec['execution']['backend'], output_schema=deepcopy(spec['output_schema']),
                      bindings=bindings, secret_refs=spec.get('secret_refs', {}))
        replacements = dict(python=spec['environment']['python_executable'], model=bindings['model_path'],
                            input=bindings['input_path'], output=bindings['output_path'], run_config=bindings['config_path'])
        config['command'] = [a.format(**replacements) for a in spec['command']]
        e.update(run_config=config, run_config_digest=digest(config), execution_receipt=None)
        self.store.save('eval', e)
        self._event('eval.accepted', e, actor)
        return evaluation_summary(e)

    def op_eval_config(self, p, actor):
        e = self._eval(p['id'], actor)
        require(actor['role'] == 'operator', 'EVALUATION_DETAILS_RESTRICTED', 'Run evidence is operator-only')
        require('runner_id' in e, 'RUN_CONFIG_UNAVAILABLE', 'Legacy evaluation has no execution snapshot')
        return {k: e.get(k) for k in ('run_config', 'run_config_digest', 'execution_receipt', 'output_digest')}

    def op_eval_logs(self, p, actor):
        e = self._eval(p['id'], actor)
        require(actor['role'] == 'operator', 'EVALUATION_DETAILS_RESTRICTED', 'Logs are operator-only')
        require('runner_id' in e, 'RUN_CONFIG_UNAVAILABLE', 'No runner execution')
        require(type(p.get('offset', 0)) is int and p.get('offset', 0) >= 0 and type(p.get('limit', 100)) is int
                and 0 < p.get('limit', 100) <= 1000, 'INVALID_ARGUMENT', 'Invalid pagination')
        if (e.get('execution_receipt') or {}).get('log_blob'):
            lines = self.store.read_blob(e['execution_receipt']['log_blob']).decode().splitlines()
            return {'items': lines[p.get('offset', 0):p.get('offset', 0) + p.get('limit', 100)]}
        scheduler = self._runner_scheduler(e)
        return {'items': scheduler.logs(e['scheduler_id'], offset=p.get('offset', 0), limit=p.get('limit', 100))
                if e.get('scheduler_id') else []}

    def op_eval_cancel(self, p, actor):
        e = self._eval(p['id'], actor)
        require('runner_id' in e, 'INVALID_REQUEST', 'Cancellation requires a runner evaluation')
        require(actor['role'] == 'operator' or actor['id'] == e['author'], 'FORBIDDEN', 'Submitting owner required')
        if e['state'] not in TERMINAL:
            # Reconciler owns scheduler I/O; request cancellation is a durable local write.
            e['cancel_requested'] = True
            if not e['submission_attempted']:
                e.update(state='cancelled', reason='user_cancelled', execution_receipt={'state': 'cancelled', 'stage': 'accepted'})
            self.store.save('eval', e)
            self._event('eval.cancel_requested', e, actor)
        return evaluation_summary(e)

    def _runner_scheduler(self, e):
        if self.store.get(e['runner_id'], 'runner')['spec']['execution']['backend'] == 'local':
            return LocalScheduler(root=self.store.root / 'evaluation-workers', allow_cpu_only=True)
        return self.scheduler

    def _restore_runner_files(self, files, root):
        for f in files:
            target = root / relative(f['path'])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.store.read_blob(f['sha256']))
            target.chmod(f.get('mode', 0o600) & 0o777)

    def _prepare_runner(self, e, runner):
        config = e['run_config']
        root = Path(config['bindings']['config_path']).parent
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        source = root / 'source'
        source.mkdir(exist_ok=True)
        self._restore_runner_files(runner['files'], source)
        self._restore_runner_files(self.store.get(e['model_id'], 'artifact')['files'], root / 'model')
        if 'judge_path' in config['bindings']:
            judge = self.store.get(config['judge']['artifact_id'], 'artifact')
            self._restore_runner_files(judge['files'], root / 'judge')
        protocol = self.store.get(e['protocol_id'], 'protocol')
        Path(config['bindings']['input_path']).write_text(''.join(json.dumps(i) + '\n' for i in protocol['spec']['items']))
        write_json(Path(config['bindings']['config_path']), config)
        driver = root / '_rsi_runner.py'
        driver.write_bytes(Path(__file__).with_name('runner_process.py').read_bytes())
        result = root / 'execution'
        request = dict(entrypoint=[config['environment']['python_executable'], str(driver), config['bindings']['config_path']],
                       workdir=str(source), resources=deepcopy(config['resources']), runtime={'python_executable': config['environment']['python_executable'],
                       'requirements': {'digest': config['environment']['requirements_digest']}},
                       _result_dir=str(result), _job_id=e['id'])
        if config['environment']['requirements'].strip():
            req = source / '_rsi_requirements.txt'
            req.write_text(config['environment']['requirements'])
            request['_requirements_file'] = str(req)
        return request

    def _runner_finish(self, e, status):
        root = Path(e['run_config']['bindings']['config_path']).parent
        path = root / 'execution' / 'result.json'
        actual = json.loads(path.read_text()) if path.exists() else status
        private = root / 'runner-receipt.json'
        receipt = json.loads(private.read_text()) if private.exists() else {}
        try:
            lines = self._runner_scheduler(e).logs(e['scheduler_id'], offset=0, limit=10000)
            content = '\n'.join(lines).encode()[:1024 * 1024]
            receipt.update(log_blob=self.store.blob(content), log_snapshot_limit_bytes=1024 * 1024,
                           log_snapshot_limit_lines=10000)
        except Exception:
            receipt['log_state'] = 'unavailable'
        receipt.update(started_at=e.get('started_at'), gpu_seconds=e.get('gpu_seconds', 0),
                       accounting='scheduler-driver-reservation-estimate', backend=self.store.get(e['runner_id'], 'runner')['spec']['execution']['backend'],
                       execution=actual, collected_at=time.time(),
                       finished_at=receipt.get('finished_at') or time.time(), state=actual['state'])
        if receipt.get('exit_code') is None:
            receipt['exit_code'] = actual.get('exit_code')
        receipt['signal'] = -receipt['exit_code'] if isinstance(receipt.get('exit_code'), int) and receipt['exit_code'] < 0 else None
        receipt['timed_out'] = actual['state'] == 'timed_out'
        if receipt.get('environment'):
            receipt['python_version'] = receipt['environment']['python_version']
        e.update(state=actual['state'], execution_receipt=receipt, reason=actual.get('reason'))
        if e['state'] == 'succeeded':
            raw = (root / 'validated-output.json').read_bytes()
            rows = json.loads(raw)
            values = summarize(rows, self.store.get(e['protocol_id'], 'protocol'))
            e.update(values, items=rows, output_digest=self.store.blob(raw), simulation=False)
            config = e['run_config']
            e['comparison_digest'] = digest(dict(runner=e['runner_digest'], protocol=e['protocol_digest'],
                **{k: config[k] for k in ('source', 'judge', 'dataset', 'decoding', 'resources')},
                environment=receipt['environment'], output_schema=self.store.get(e['runner_id'], 'runner')['spec']['output_schema']))
        return e

    def _reconcile_runner(self, initial):
        # All expensive I/O and external calls are outside the SQLite/request lock.
        with self.store.transaction():
            e = self.store.get(initial['id'], 'eval')
            if e['state'] in TERMINAL:
                return
            runner = self.store.get(e['runner_id'], 'runner')
        scheduler = self._runner_scheduler(e)
        try:
            if not e['submission_attempted']:
                e['started_at'] = time.time()
                request = self._prepare_runner(e, runner)
                with self.store.transaction():
                    current = self.store.get(e['id'], 'eval')
                    if current['state'] in TERMINAL:
                        return
                    remaining = e['run_config']['resources']['walltime_seconds'] - (time.time() - e['started_at'])
                    if remaining <= 0:
                        e.update(state='timed_out', reason='walltime', execution_receipt={
                            'state': 'timed_out', 'stage': 'preparation', 'started_at': e['started_at'],
                            'finished_at': time.time(), 'timed_out': True})
                        self.store.save('eval', e)
                        self._event('eval.timed_out', e, 'service')
                        return
                    request['resources']['walltime_seconds'] = remaining
                    e.update(submission_attempted=True, state='running')
                    self.store.save('eval', e)
                # Durable attempt marker before remote write; never resubmit an ambiguous write.
                e['scheduler_id'] = scheduler.submit(request, submission_key=e['id'])
            elif not e['scheduler_id']:
                e['scheduler_id'] = scheduler.find(e['id'])
                if e['scheduler_id'] is None:
                    raise ResearchError('RUNNER_SUBMISSION_LOST', 'Ambiguous submission not replayed')
            if e.get('cancel_requested'):
                scheduler.cancel(e['scheduler_id'])
            if time.time() - e.get('started_at', time.time()) > e['run_config']['resources']['walltime_seconds']:
                e['deadline_exceeded'] = True
                scheduler.cancel(e['scheduler_id'])
            if isinstance(scheduler, LocalScheduler):
                scheduler.find(e['scheduler_id'])
            status = scheduler.status(e['scheduler_id'])
            e['gpu_seconds'] = max(e['gpu_seconds'], status.get('gpu_seconds', 0))
            if status['state'] in TERMINAL:
                e = self._runner_finish(e, status)
                if e.get('deadline_exceeded') and not (
                        e['state'] == 'succeeded' and e['execution_receipt']['finished_at'] <=
                        e['started_at'] + e['run_config']['resources']['walltime_seconds']):
                    e.update(state='timed_out', reason='walltime')
        except TimeoutError as error:
            # A definitive missing job is terminal; unavailable reads retain the reservation.
            if getattr(error, 'code', None) == 'RAY_JOB_LOST':
                e.update(state='failed', reason='RAY_JOB_LOST', execution_receipt={
                    'backend': runner['spec']['execution']['backend'], 'state': 'failed',
                    'error': 'RAY_JOB_LOST', 'finished_at': time.time()})
            else:
                e['health'] = 'scheduler_unavailable'
        except Exception as error:
            e.update(state='failed', reason=getattr(error, 'code', 'runner_error'),
                     execution_receipt=dict(state='failed', stage='preparation_or_collection',
                     error=getattr(error, 'code', type(error).__name__), finished_at=time.time(),
                     previous=e.get('execution_receipt')))
        if e['state'] != 'succeeded':
            for key in ('score', 'raw_score', 'normalized_score', 'items', 'task_scores', 'raw_task_scores',
                        'normalized_task_scores', 'comparison_digest', 'output_digest'):
                e.pop(key, None)
        with self.store.transaction():
            current = self.store.get(e['id'], 'eval')
            if current['state'] in TERMINAL:
                return
            if current.get('cancel_requested'):
                e['cancel_requested'] = True
                if e['state'] in TERMINAL:
                    e.update(state='cancelled', reason='user_cancelled')
                    for key in ('score', 'raw_score', 'normalized_score', 'items', 'task_scores', 'raw_task_scores',
                                'normalized_task_scores', 'comparison_digest', 'output_digest'):
                        e.pop(key, None)
            if e.get('execution_receipt'):
                e['execution_receipt']['controller_state'] = e['state']
                e['execution_receipt']['controller_reason'] = e.get('reason')
            self.store.save('eval', e)
            if e['state'] in TERMINAL:
                self._event('eval.' + e['state'], e, 'service')

    def _evaluation_group(self, rows, p):
        p = dict(p)
        if rows and not p.get('runner_id') and not p.get('comparison_digest'):
            campaign = self.store.get(rows[0]['campaign_id'], 'campaign')
            if campaign.get('audit_policy_id'):
                policy = self.store.get(campaign['audit_policy_id'], 'audit_policy')
                if policy.get('runner_id'):
                    p['runner_id'] = policy['runner_id']
        rows = [e for e in rows if (not p.get('runner_id') or e.get('runner_id') == p['runner_id']) and
                (not p.get('comparison_digest') or e.get('comparison_digest') == p['comparison_digest'])]
        groups = {(e.get('runner_digest'), e.get('comparison_digest')) for e in rows}
        require(len(groups) <= 1, 'EVALUATION_GROUP_REQUIRED', 'Select one runner and actual execution group')
        return rows
