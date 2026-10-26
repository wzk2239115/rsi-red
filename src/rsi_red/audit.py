"""Development-only integrity cases. Clients cannot mint trusted checker receipts.

This is a control-plane boundary, not an OS sandbox. A pass describes only the
selected deterministic checks on stored development outputs, never general safety.
"""
from pathlib import Path
import hashlib
import threading

from .errors import require
from .store import digest

CHECKS = {'grader_consistency', 'format_robustness', 'data_overlap'}
AUDITOR_OPERATIONS = {'audit.show', 'audit.list', 'audit.observe', 'audit.feedback',
                      'audit.record', 'eval.show', 'eval.model', 'eval.samples',
                      'protocol.show', 'protocol.list'}
EVAL_FIELDS = ('id', 'campaign_id', 'model_id', 'protocol_id', 'model_digest', 'protocol_digest',
               'state', 'visibility', 'eval_seed', 'repeat_index', 'score', 'task_scores', 'simulation',
               'raw_score', 'raw_task_scores', 'normalized_score', 'normalized_task_scores', 'normalization', 'task_metrics')


def evaluation_summary(item):
    # No extension fields or arbitrary evaluator messages cross this projection.
    result = {key: item[key] for key in EVAL_FIELDS if key in item}
    if item['state'] == 'failed':
        result['reason'] = item.get('reason') if item.get('reason') in {
            'INVALID_EVALUATION', 'EVALUATOR_UNAVAILABLE', 'evaluator_error'} else 'evaluation_failed'
    elif 'reason' in item:
        result['reason'] = None
    return result


class AuditMixin:
    def _audit_access(self, campaign_id, protocol_id, actor):
        if actor['role'] != 'auditor':
            return self._campaign(campaign_id, actor)
        campaign = self.store.get(campaign_id, 'campaign')
        policy = self.store.get(campaign.get('audit_policy_id'), 'audit_policy') if campaign.get('audit_policy_id') else None
        require(policy is not None and actor['id'] in policy['auditor_ids']
                and protocol_id == policy['protocol_id'], 'FORBIDDEN', 'Audit scope not granted')
        return campaign

    def op_audit_configure(self, p, actor):
        self._operator(actor)
        campaign = self._campaign(p['campaign_id'], actor)
        protocol = self.store.get(p['protocol_id'], 'protocol')
        require(protocol['spec']['visibility'] == 'development', 'HIDDEN_AUDIT_FORBIDDEN', 'Development audits only')
        require(protocol['id'] == campaign['protocol_id'], 'AUDIT_EVIDENCE_MISMATCH', 'Campaign protocol required')
        auditors = p['auditor_ids']
        valid = {a['id'] for a in self.principals.values() if a['role'] == 'auditor'}
        require(isinstance(auditors, list) and auditors and all(a in valid for a in auditors),
                'INVALID_REQUEST', 'Registered auditor identities required')
        checks = p['checks']
        require(isinstance(checks, list) and checks and all(c in CHECKS for c in checks)
                and len(set(checks)) == len(checks), 'INVALID_REQUEST', 'Select distinct supported checks')
        spec = {key: p[key] for key in ('campaign_id', 'protocol_id', 'auditor_ids', 'checks')}
        spec['grader_mode'] = p.get('grader_mode', 'unconfigured')
        require(spec['grader_mode'] in {'unconfigured', 'exact_match'}, 'INVALID_REQUEST', 'Unsupported grader mode')
        for name, default in [('max_cases', 20), ('max_evaluations', 100)]:
            value = p.get(name, default)
            require(type(value) is int and value > 0, 'INVALID_REQUEST', 'Positive integer budget required')
            spec[name] = value
        policy = self.store.create('audit_policy', dict(spec, digest=digest(spec)))
        campaign['audit_policy_id'] = policy['id']
        self.store.save('campaign', campaign)
        self._event('audit.configured', policy, actor)
        return policy

    def _audit_case(self, key, actor):
        case = self.store.get(key, 'audit')
        self._audit_access(case['campaign_id'], case['protocol_id'], actor)
        return case

    def _case_view(self, case, actor):
        public = {key: case[key] for key in ('id', 'campaign_id', 'model_id', 'model_digest',
                  'protocol_id', 'protocol_digest', 'eval_id', 'policy_id', 'policy_digest', 'state', 'checks')}
        if actor['role'] in {'operator', 'auditor'}:
            public['observations'] = [f for f in self.store.list('audit_finding') if f['case_id'] == case['id']]
        if actor['role'] == 'operator':
            public['private_evidence'] = case.get('private_evidence', [])
        return public

    def op_audit_submit(self, p, actor):
        campaign = self._campaign(p['campaign_id'], actor)
        policy = self.store.get(p['policy_id'], 'audit_policy')
        require(policy['campaign_id'] == campaign['id'] and policy['id'] == campaign.get('audit_policy_id'),
                'AUDIT_EVIDENCE_MISMATCH', 'Active campaign policy required')
        evaluation = self.store.get(p['eval_id'], 'eval')
        require(evaluation['visibility'] == 'development', 'HIDDEN_AUDIT_FORBIDDEN', 'Development audits only')
        model = self._entity(p['model_id'], 'artifact', actor)
        require(model['campaign_id'] == campaign['id'] == evaluation['campaign_id']
                and evaluation['model_id'] == model['id'] and evaluation['model_digest'] == model['digest']
                and evaluation['protocol_id'] == policy['protocol_id'],
                'AUDIT_EVIDENCE_MISMATCH', 'Evaluation must match candidate and policy')
        protocol = self.store.get(policy['protocol_id'], 'protocol')
        require(evaluation['protocol_digest'] == protocol['digest'], 'AUDIT_EVIDENCE_MISMATCH', 'Protocol digest mismatch')
        require(evaluation['state'] == 'succeeded', 'EVALUATION_NOT_READY', 'Completed evaluation required')
        key = p['idempotency_key']
        require(isinstance(key, str) and 0 < len(key) <= 200, 'INVALID_REQUEST', 'Idempotency key required')
        fingerprint = digest({k: p[k] for k in ('campaign_id', 'model_id', 'eval_id', 'policy_id')})
        cases = [c for c in self.store.list('audit') if c['campaign_id'] == campaign['id']]
        for case in cases:
            if case['idempotency_key'] == key:
                require(case['request_digest'] == fingerprint, 'IDEMPOTENCY_CONFLICT', 'Key already used')
                return self._case_view(case, actor)
        require(len(cases) < policy['max_cases'], 'AUDIT_BUDGET_EXCEEDED', 'Campaign audit budget exhausted')
        case = self.store.create('audit', {**{k: evaluation[k] for k in
            ('campaign_id', 'model_id', 'model_digest', 'protocol_id', 'protocol_digest')},
            'eval_id': evaluation['id'], 'policy_id': policy['id'], 'policy_digest': policy['digest'],
            'state': 'pending', 'checks': [], 'idempotency_key': key, 'request_digest': fingerprint})
        self._event('audit.pending', case, actor)
        return self._case_view(case, actor)

    def op_audit_show(self, p, actor):
        return self._case_view(self._audit_case(p['id'], actor), actor)

    def op_audit_list(self, p, actor):
        campaign = self.store.get(p['campaign_id'], 'campaign')
        self._audit_access(campaign['id'], campaign['protocol_id'], actor)
        return {'items': [self._case_view(c, actor) for c in self.store.list('audit')
                          if c['campaign_id'] == campaign['id']]}

    def op_audit_record(self, p, actor):
        require(False, 'FORBIDDEN', 'Only the internal reconciler records trusted checks')

    def _feedback(self, case, source, status, reason):
        campaign = self.store.get(case['campaign_id'], 'campaign')
        item = self.store.create('audit_feedback', {
            **{k: case[k] for k in ('campaign_id', 'model_id', 'model_digest', 'protocol_id', 'protocol_digest')},
            'case_id': case['id'], 'source': source, 'status': status, 'reason': reason,
            'evidence_ids': [case['eval_id']],
            'recommendation': {'suspected': 'Request independent review; do not infer answers from feedback.',
                'confirmed_issue': 'Investigate grading and rerun a corrected, frozen development protocol.',
                'incomplete': 'Ask the operator to configure the missing trusted checks.',
                'checks_passed': 'Selected checks passed; broader integrity remains unproven.'}[status],
            'recipients': list(campaign['members']), 'acknowledgements': {}, 'time': self.clock()})
        self._event('audit.feedback_available', item, 'service')
        return item

    def op_audit_observe(self, p, actor):
        require(actor['role'] == 'auditor', 'FORBIDDEN', 'Assigned auditor required')
        case = self._audit_case(p['id'], actor)
        text, evidence = p['text'], p.get('evidence_ids', [])
        require(isinstance(text, str) and 0 < len(text.encode()) <= 65536,
                'INVALID_REQUEST', 'Bounded observation required')
        require(isinstance(evidence, list) and all(k in {case['eval_id'], case['model_id'], case['id']} for k in evidence),
                'FORBIDDEN', 'Evidence outside case')
        require(sum(f['case_id'] == case['id'] for f in self.store.list('audit_finding')) < 100,
                'AUDIT_BUDGET_EXCEEDED', 'Observation budget exhausted')
        feedback = self._feedback(case, 'auditor_hypothesis', 'suspected', 'independent_review_requested')
        return self.store.create('audit_finding', {'campaign_id': case['campaign_id'], 'case_id': case['id'],
            'author': actor['id'], 'source': 'auditor_hypothesis', 'text': text,
            'evidence_ids': evidence, 'feedback_id': feedback['id'], 'time': self.clock()})

    def op_audit_feedback(self, p, actor):
        campaign = self.store.get(p['campaign_id'], 'campaign')
        self._audit_access(campaign['id'], campaign['protocol_id'], actor)
        rows = [f for f in self.store.list('audit_feedback') if f['campaign_id'] == campaign['id']]
        after = p.get('after')
        if after:
            ids = [f['id'] for f in rows]
            require(after in ids, 'INVALID_ARGUMENT', 'Unknown feedback cursor')
            rows = rows[ids.index(after) + 1:]
        limit = p.get('limit', 100)
        require(type(limit) is int and 0 < limit <= 1000, 'INVALID_ARGUMENT', 'Invalid page limit')
        return {'items': [dict(f, acknowledged=actor['id'] in f['acknowledgements']) for f in rows[:limit]]}

    def op_audit_ack(self, p, actor):
        feedback = self.store.get(p['id'], 'audit_feedback')
        self._campaign(feedback['campaign_id'], actor)
        require(actor['id'] in feedback['recipients'], 'FORBIDDEN', 'Recipient identity required')
        if actor['id'] not in feedback['acknowledgements']:
            feedback['acknowledgements'][actor['id']] = self.clock()
            self.store.save('audit_feedback', feedback)
            self._event('audit.feedback_acknowledged', feedback, actor)
        return {'id': feedback['id'], 'acknowledged': True, 'time': feedback['acknowledgements'][actor['id']]}

    def _audit_submission_gate(self, campaign, model):
        if not campaign.get('audit_policy_id'):
            return
        policy = self.store.get(campaign['audit_policy_id'], 'audit_policy')
        cases = [c for c in self.store.list('audit') if c['campaign_id'] == campaign['id']
                 and c['model_id'] == model['id'] and c['model_digest'] == model['digest']
                 and c['policy_id'] == policy['id'] and c['policy_digest'] == policy['digest']]
        # A later confirmed failure supersedes a prior pass; pending checks do not certify a new candidate.
        require(bool(cases) and cases[-1]['state'] == 'checks_passed', 'AUDIT_REQUIRED',
                'Current candidate requires completed trusted checks under active policy')

    def _audit_eval_budget(self, campaign_id, protocol_id):
        campaign = self.store.get(campaign_id, 'campaign')
        if campaign.get('audit_policy_id'):
            policy = self.store.get(campaign['audit_policy_id'], 'audit_policy')
            if protocol_id == policy['protocol_id']:
                count = sum(e['campaign_id'] == campaign_id and e['protocol_id'] == protocol_id
                            for e in self.store.list('eval'))
                require(count < policy['max_evaluations'], 'EVALUATION_BUDGET_EXCEEDED', 'Development query budget exhausted')

    def op_eval_model(self, p, actor):
        model = self.store.get(p['id'], 'artifact')
        campaign = self.store.get(model['campaign_id'], 'campaign')
        self._audit_access(campaign['id'], campaign['protocol_id'], actor)
        evaluations = [e for e in self.store.list('eval') if e['model_id'] == model['id']
                       and e['visibility'] == 'development'
                       and (actor['role'] != 'auditor' or e['protocol_id'] == campaign['protocol_id'])]
        return {'model_id': model['id'], 'model_digest': model['digest'],
                'evaluations': [evaluation_summary(e) for e in evaluations],
                'audits': [self._case_view(c, actor) for c in self.store.list('audit') if c['model_id'] == model['id']]}

    def reconcile_audits(self):
        if not self.audit_lock.acquire(blocking=False):
            return
        try:
            with self.store.lock:
                cases = [c for c in self.store.list('audit') if c['state'] in {'pending', 'running'}]
            for case in cases:
                with self.store.transaction():
                    case['state'] = 'running'
                    self.store.save('audit', case)
                    policy = self.store.get(case['policy_id'], 'audit_policy')
                    evaluation = self.store.get(case['eval_id'], 'eval')
                    protocol = self.store.get(case['protocol_id'], 'protocol')
                checks, private_evidence = [], []
                code_digest = 'sha256:' + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
                for name in policy['checks']:
                    state = 'unavailable'
                    scope = 'not_configured'
                    if name == 'grader_consistency' and policy['grader_mode'] == 'exact_match':
                        answers = {i['id']: i['answer'] for i in protocol['spec']['items']}
                        evidence = [{'id': i['id'], 'recorded_score': i['score'],
                                     'recomputed_score': float(i['answer'] == answers[i['id']])}
                                    for i in evaluation['items']]
                        private_evidence.append({'check': name, 'eval_id': evaluation['id'], 'items': evidence})
                        correct = all(i['recorded_score'] == i['recomputed_score'] for i in evidence)
                        state = 'passed' if correct else 'failed'
                        scope = 'exact_match_on_stored_development_outputs'
                    checks.append({'name': name, 'state': state, 'scope': scope, 'checker_digest': code_digest,
                                   'model_digest': case['model_digest'], 'protocol_digest': case['protocol_digest'],
                                   'eval_id': case['eval_id'], 'policy_digest': case['policy_digest'],
                                   'eval_seed': evaluation['eval_seed'], 'additional_model_calls': 0,
                                   'transform': 'none', 'checked_at': self.clock()})
                case['checks'] = checks
                case['private_evidence'] = private_evidence
                case['state'] = ('blocked' if any(c['state'] == 'failed' for c in checks) else
                                 'checks_passed' if all(c['state'] == 'passed' for c in checks) else 'incomplete')
                with self.store.transaction():
                    self.store.save('audit', case)
                    self._event('audit.' + case['state'], case, 'service')
                    status = {'blocked': 'confirmed_issue', 'checks_passed': 'checks_passed', 'incomplete': 'incomplete'}[case['state']]
                    self._feedback(case, 'trusted_checker', status, 'selected_checks_' + case['state'])
        finally:
            self.audit_lock.release()

    def _init_audits(self):
        self.audit_lock = threading.Lock()
