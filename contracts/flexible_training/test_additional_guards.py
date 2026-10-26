"""Negative paths for the same reviewed runtime/output contracts."""
import hashlib
import pytest

from tests.support import ALICE, OUTSIDER, Rig


def test_validate_does_not_write_blobs_and_preserves_authorization(tmp_path):
    r=Rig(tmp_path).setup()
    try:
        before=set((tmp_path/'blobs').iterdir())
        r.error('job.validate',r.job_request(),'FORBIDDEN',token=OUTSIDER)
        r.ok('job.validate',r.job_request(),token=ALICE)
        assert set((tmp_path/'blobs').iterdir())==before
    finally:
        r.close()


def test_backend_without_capability_rejects_runtime_and_outputs(tmp_path):
    r=Rig(tmp_path).setup()
    try:
        r.cluster.supports_runtime=False
        r.cluster.supports_outputs=False
        r.error('job.submit',r.job_request(runtime={}), 'UNSUPPORTED_RUNTIME')
        r.error('job.submit',r.job_request(output_manifest='out/manifest.json'),'UNSUPPORTED_OUTPUT_TRANSPORT')
        assert r.ok('job.list',{'campaign_id':r.campaign})['items']==[]
    finally:
        r.close()


def test_unrelated_custom_artifact_cannot_receive_fixture_model_scores(tmp_path):
    r=Rig(tmp_path).setup()
    try:
        path=r.file('report.txt','not a model')
        artifact=r.ok('artifact.register',{'campaign_id':r.campaign,'path':str(path.parent),'kind':'research_report',
            'files':[{'path':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}]})
        r.error('eval.submit',{'campaign_id':r.campaign,'model_id':artifact['id'],'protocol_id':r.protocol},
                'EVALUATION_UNSUPPORTED_ARTIFACT')
        assert r.evaluator.calls==[]
    finally:
        r.close()


def test_client_cannot_set_service_verified_output_marker(tmp_path):
    r=Rig(tmp_path).setup()
    try:
        path=r.file('report.txt','report')
        r.error('artifact.register',{'campaign_id':r.campaign,'path':str(path.parent),'kind':'report',
            'files':[{'path':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}],
            'provenance':{'verification':'service-collected','job_id':'invented'}},'FORBIDDEN')
    finally:
        r.close()


def test_validate_existing_idempotent_request_does_not_double_reserve_budget(tmp_path):
    r=Rig(tmp_path).setup(gpu_budget=1)
    try:
        request=r.job_request(resources={'gpus':1,'walltime_seconds':3600})
        r.ok('job.submit',request)
        result=r.ok('job.validate',request)
        assert result['valid'] is True
        assert r.ok('campaign.show',{'id':r.campaign})['usage']['reserved_gpu_seconds']==3600
    finally:
        r.close()


def test_local_cpu_preflight_rejects_gpu_before_queueing(tmp_path):
    from rsi_red.schedulers.local import LocalScheduler
    r=Rig(tmp_path).setup()
    try:
        r.service.scheduler=LocalScheduler(root=tmp_path/'workers',allow_cpu_only=True)
        r.error('job.validate',r.job_request(),'UNSUPPORTED_RESOURCES')
        assert r.ok('job.list',{'campaign_id':r.campaign})['items']==[]
    finally:
        r.close()


@pytest.mark.parametrize('operation',['job.validate','job.submit'])
@pytest.mark.parametrize('invalid',['missing_key','null_key','empty_program','boolean_walltime'])
def test_validate_and_submit_reject_the_same_malformed_requests(tmp_path,operation,invalid):
    r=Rig(tmp_path).setup()
    try:
        request=r.job_request()
        if invalid=='missing_key':
            request.pop('idempotency_key')
        elif invalid=='null_key':
            request['idempotency_key']=None
        elif invalid=='empty_program':
            request['entrypoint'][0]=''
        else:
            request['resources']['walltime_seconds']=True
        r.error(operation,request,'INVALID_REQUEST')
        assert r.ok('job.list',{'campaign_id':r.campaign})['items']==[]
    finally:
        r.close()


@pytest.mark.parametrize('managed', [{'runtime':{}}, {'output_manifest':'out/manifest.json'}])
def test_scheduler_success_without_shared_execution_receipt_is_not_success(tmp_path,managed):
    r=Rig(tmp_path).setup()
    try:
        job=r.submit(**managed)
        r.service.reconcile_jobs()
        sid=r.job(job['id'])['scheduler_id']
        r.cluster.set_state(sid,'succeeded')
        r.service.reconcile_jobs()
        result=r.job(job['id'])
        assert result['state']=='failed'
        assert result['reason'] in {'execution_receipt_unavailable','output_collection_failed'}
        if 'output_manifest' in managed:
            assert r.ok('job.outputs',{'id':job['id']})['state']=='failed'
    finally:
        r.close()


def test_empty_legacy_model_keeps_incomplete_model_error(tmp_path):
    r=Rig(tmp_path).setup()
    try:
        r.error('artifact.register',{'campaign_id':r.campaign,'path':str(tmp_path),
                                    'files':[],'kind':'model'},'INCOMPLETE_MODEL')
    finally:
        r.close()
