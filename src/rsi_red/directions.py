"""Explicit objective metadata and operator-owned, immutable authorization receipts."""
from copy import deepcopy

from .errors import ResearchError, require
from .store import digest

NORMALIZATION = 'bounded-complement-v1'
FIELDS = {'direction', 'metric', 'role'}


def validate_metadata(meta, *, require_direction=True):
    require(isinstance(meta, dict) and set(meta) <= FIELDS, 'INVALID_REQUEST', 'Invalid objective fields')
    if require_direction or 'direction' in meta:
        require(meta.get('direction') in ('minimize', 'maximize'), 'INVALID_REQUEST', 'Explicit direction required')
    if 'role' in meta:
        require(meta['role'] in ('policy', 'judge'), 'INVALID_REQUEST', 'Invalid semantic role')
    if 'metric' in meta:
        require(isinstance(meta['metric'], str) and meta['metric'].strip(), 'INVALID_REQUEST', 'Metric name required')


def task_metadata(spec):
    defaults = {k: spec[k] for k in FIELDS if k in spec}
    # Invalid defaults must fail even when every item overrides them.
    validate_metadata(defaults, require_direction=False)
    tasks = {}
    for item in spec['items']:
        task = item.get('task')
        require(isinstance(task, str) and task.strip(), 'INVALID_REQUEST', 'Task name required')
        meta = defaults | {k: item[k] for k in FIELDS if k in item}
        validate_metadata(meta)
        require(task not in tasks or tasks[task] == meta, 'INVALID_REQUEST', 'Conflicting task objectives')
        tasks[task] = meta
    require(bool(tasks), 'INVALID_REQUEST', 'Task objectives required')
    return tasks


class DirectionMixin:
    def op_direction_authorize(self, p, actor):
        self._operator(actor)
        require(set(p) == {'tasks', 'goal', 'source_protocol_digest'}, 'INVALID_REQUEST', 'Exact authorization fields required')
        require(isinstance(p['goal'], str) and p['goal'].strip() and len(p['goal']) <= 10000,
                'INVALID_REQUEST', 'Human objective statement required')
        require(p['source_protocol_digest'] is None or
                (isinstance(p['source_protocol_digest'], str) and p['source_protocol_digest']),
                'INVALID_REQUEST', 'Source digest must be explicit')
        require(isinstance(p['tasks'], dict) and p['tasks'], 'INVALID_REQUEST', 'Task mapping required')
        for task, meta in p['tasks'].items():
            require(isinstance(task, str) and task.strip(), 'INVALID_REQUEST', 'Task name required')
            validate_metadata(meta)
        item = self.store.create('direction_authorization', dict(p, digest=digest(p),
            authorized_by=actor['id'], authorized_at=self.clock()))
        self._event('direction.authorized', item, actor)
        return item

    def _check_direction_authorization(self, spec, source=None):
        tasks = task_metadata(spec)
        key = spec.get('direction_authorization_id')
        require(isinstance(key, str) and key, 'DIRECTION_AUTHORIZATION_REQUIRED', 'Human direction authorization required')
        try:
            grant = self.store.get(key, 'direction_authorization')
        except ResearchError:
            raise ResearchError('DIRECTION_AUTHORIZATION_MISMATCH', 'Authorization does not match objective') from None
        require(grant['tasks'] == tasks and grant['source_protocol_digest'] == source,
                'DIRECTION_AUTHORIZATION_MISMATCH', 'Authorization does not match objective or source')
        return tasks

    def _direction_ready(self, protocol):
        require(protocol['spec'].get('direction_authorization_id'), 'DIRECTION_UNCONFIGURED',
                'Legacy protocol needs explicit authorization, derivation and new evaluation')
        return self._check_direction_authorization(protocol['spec'], protocol.get('source_protocol_digest'))

    def op_protocol_derive(self, p, actor):
        self._operator(actor)
        require(set(p) == {'id', 'direction_authorization_id', 'task_overrides'},
                'INVALID_REQUEST', 'Only direction metadata can be derived')
        source = self.store.get(p['id'], 'protocol')
        overrides = p['task_overrides']
        tasks = {i['task'] for i in source['spec']['items']}
        require(isinstance(overrides, dict) and set(overrides) <= tasks,
                'INVALID_REQUEST', 'Unknown task override')
        for meta in overrides.values():
            require(isinstance(meta, dict) and meta and set(meta) <= FIELDS, 'INVALID_REQUEST', 'Invalid task override')
        spec = deepcopy(source['spec'])
        for item in spec['items']:
            item.update(overrides.get(item['task'], {}))
        spec['direction_authorization_id'] = p['direction_authorization_id']
        self._check_direction_authorization(spec, source['digest'])
        spec['normalization'] = NORMALIZATION
        result = self.store.create('protocol', {'spec': spec, 'digest': digest(spec),
            'source_protocol_id': source['id'], 'source_protocol_digest': source['digest']})
        self._event('protocol.derived', result, actor)
        return result
