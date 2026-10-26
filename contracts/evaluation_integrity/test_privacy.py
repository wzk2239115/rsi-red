"""Privacy projections and trusted, bounded verification before implementation."""
import json
from copy import deepcopy

import pytest

from tests.support import OPERATOR, Rig

AUDITOR = 'test-private-auditor'


@pytest.fixture
def rig(tmp_path):
    r = Rig(tmp_path).setup()
    r.principals[AUDITOR] = {'id':'auditor','role':'auditor'}
    r.close()
    r.open()
    try:
        yield r
    finally:
        r.close()


def configure(r, **extra):
    return r.ok('audit.configure', {'campaign_id':r.campaign,'protocol_id':r.protocol,
                'auditor_ids':['auditor'],'checks':['grader_consistency'],
                'grader_mode':'exact_match', **extra},token=OPERATOR)


def submit(r, policy, evaluation=None, key='case'):
    evaluation = evaluation or r.evaluate()
    return r.ok('audit.submit', {'campaign_id':r.campaign,'model_id':r.base,
        'eval_id':evaluation['id'],'policy_id':policy['id'],'idempotency_key':key})


def test_protocol_and_samples_do_not_reveal_questions(rig):
    protocol=rig.ok('protocol.show',{'id':rig.protocol})
    assert 'items' not in protocol.get('spec',{})
    assert 'one plus one' not in json.dumps(protocol)
    assert rig.ok('protocol.show',{'id':rig.protocol},token=OPERATOR)['spec']['items']
    evaluation=rig.evaluate()
    rig.error('eval.samples',{'id':evaluation['id']},'EVALUATION_DETAILS_RESTRICTED')
    assert rig.ok('eval.samples',{'id':evaluation['id']},token=OPERATOR)['items']


def test_eval_summary_drops_extra_evaluator_fields(rig):
    old=rig.evaluator.evaluate
    def malicious(model, protocol):
        result=old(model,protocol)
        result['items'][0]['prompt']='PRIVATE QUESTION'
        result['items'][0]['reference_answer']='PRIVATE ANSWER'
        return result
    rig.evaluator.evaluate=malicious
    result=rig.evaluate()
    assert 'PRIVATE' not in json.dumps(result)


def test_auditor_gets_only_granted_model_evaluation_summary(rig):
    configure(rig)
    evaluation=rig.evaluate()
    result=rig.ok('eval.show',{'id':evaluation['id']},token=AUDITOR)
    assert result['score']==evaluation['score']
    assert 'items' not in result
    rig.error('eval.samples',{'id':evaluation['id']},'EVALUATION_DETAILS_RESTRICTED',token=AUDITOR)


def test_untrusted_observation_text_never_reaches_training_feedback(rig):
    policy=configure(rig)
    case=submit(rig,policy)
    secret='PRIVATE QUESTION: one plus one; PRIVATE ANSWER: 2'
    finding=rig.ok('audit.observe',{'id':case['id'],'text':secret,
                    'evidence_ids':[case['eval_id']]},token=AUDITOR)
    assert finding['text']==secret
    for operation,payload in [('audit.show',{'id':case['id']}),
                              ('audit.feedback',{'campaign_id':rig.campaign}),
                              ('events.list',{'campaign_id':rig.campaign})]:
        public=rig.ok(operation,payload)
        assert 'PRIVATE' not in json.dumps(public)
        assert secret not in json.dumps(public)


def test_actual_exact_match_check_passes_and_allows_submission(rig):
    policy=configure(rig)
    case=submit(rig,policy)
    rig.service.reconcile_audits()
    result=rig.ok('audit.show',{'id':case['id']})
    assert result['state']=='checks_passed'
    assert result['checks'][0]['checker_digest'].startswith('sha256:')
    assert 'one plus one' not in json.dumps(result)
    assert rig.ok('campaign.submit',{'id':rig.campaign,'model_id':rig.base})['model_id']==rig.base


def test_false_positive_score_is_blocked_without_leaking_answer(rig):
    policy=configure(rig)
    old=rig.evaluator.evaluate
    def hacked(model,protocol):
        result=old(model,protocol)
        result['items'][0].update(answer='incorrect but rewarded',score=1.0)
        return result
    rig.evaluator.evaluate=hacked
    case=submit(rig,policy)
    rig.service.reconcile_audits()
    result=rig.ok('audit.show',{'id':case['id']})
    assert result['state']=='blocked'
    assert 'incorrect but rewarded' not in json.dumps(result)
    rig.error('campaign.submit',{'id':rig.campaign,'model_id':rig.base},'AUDIT_REQUIRED')
    feedback=rig.ok('audit.feedback',{'campaign_id':rig.campaign})['items']
    assert feedback[-1]['status']=='confirmed_issue'
    assert 'one plus one' not in json.dumps(feedback)


def test_missing_checker_is_incomplete_not_passed(rig):
    policy=configure(rig,checks=['grader_consistency','format_robustness'])
    case=submit(rig,policy)
    rig.service.reconcile_audits()
    assert rig.ok('audit.show',{'id':case['id']})['state']=='incomplete'
    rig.error('campaign.submit',{'id':rig.campaign,'model_id':rig.base},'AUDIT_REQUIRED')


def test_retry_is_idempotent_and_case_budget_is_enforced(rig):
    policy=configure(rig,max_cases=1)
    evaluation=rig.evaluate()
    case=submit(rig,policy,evaluation)
    assert submit(rig,policy,evaluation)['id']==case['id']
    rig.error('audit.submit',{'campaign_id':rig.campaign,'model_id':rig.base,
        'eval_id':evaluation['id'],'policy_id':policy['id'],'idempotency_key':'another'},'AUDIT_BUDGET_EXCEEDED')


def test_replaced_policy_invalidates_old_pass(rig):
    policy=configure(rig)
    case=submit(rig,policy)
    rig.service.reconcile_audits()
    assert rig.ok('audit.show',{'id':case['id']})['state']=='checks_passed'
    configure(rig,checks=['format_robustness'])
    rig.error('campaign.submit',{'id':rig.campaign,'model_id':rig.base},'AUDIT_REQUIRED')


def test_protected_evaluation_budget_limits_adaptive_queries(rig):
    configure(rig,max_evaluations=1)
    rig.evaluate()
    rig.error('eval.submit',{'campaign_id':rig.campaign,'model_id':rig.base,
                           'protocol_id':rig.protocol},'EVALUATION_BUDGET_EXCEEDED')


def test_model_report_has_no_held_out_or_raw_answers(rig):
    configure(rig)
    rig.evaluate()
    spec=deepcopy(rig.ok('protocol.show',{'id':rig.protocol},token=OPERATOR)['spec'])
    spec.update(name='sealed-final',visibility='held_out')
    hidden=rig.ok('protocol.register',spec,token=OPERATOR)
    evaluation=rig.ok('eval.submit',{'campaign_id':rig.campaign,'model_id':rig.base,
                                    'protocol_id':hidden['id']},token=OPERATOR)
    rig.reconcile()
    report=rig.ok('eval.model',{'id':rig.base})
    assert len(report['evaluations'])==1
    assert hidden['id'] not in json.dumps(report)
    assert evaluation['id'] not in json.dumps(report)
    assert 'one plus one' not in json.dumps(report)


def test_private_checker_evidence_is_operator_only(rig):
    policy=configure(rig)
    case=submit(rig,policy)
    rig.service.reconcile_audits()
    private=rig.ok('audit.show',{'id':case['id']},token=OPERATOR)
    assert private['private_evidence'][0]['items'][0]['id']=='q1'
    assert private['checks'][0]['eval_seed']==42
    assert private['checks'][0]['additional_model_calls']==0
    for token in (AUDITOR, next(t for t,a in rig.principals.items() if a['id']=='alice')):
        result=rig.ok('audit.show',{'id':case['id']},token=token)
        assert 'private_evidence' not in result
        assert 'q1' not in json.dumps(result)
