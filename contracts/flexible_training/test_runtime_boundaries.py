"""Executable boundaries added before implementing runtime and output collection."""
import hashlib
import importlib.util
import sys
import time
import zipfile

from contracts.flexible_training.test_process_contract import runtime
import pytest
from rsi_red.schedulers.local import LocalScheduler
from tests.support import Rig


@pytest.fixture
def rig(tmp_path):
    r = Rig(tmp_path).setup()
    r.service.scheduler = LocalScheduler(root=tmp_path/'workers', allow_cpu_only=True)
    try:
        yield r
    finally:
        r.close()


def make_wheel(folder, version):
    path = folder / f'flexfixture-{version}-py3-none-any.whl'
    dist = f'flexfixture-{version}.dist-info'
    entries = {'flexfixture/__init__.py':f'VERSION = {version!r}\n',
               dist+'/METADATA': f'Metadata-Version: 2.1\nName: flexfixture\nVersion: {version}\n',
               dist+'/WHEEL':'Wheel-Version: 1.0\nGenerator: rsi-contract\nRoot-Is-Purelib: true\nTag: py3-none-any\n'}
    entries[dist+'/RECORD']=''.join(name+',,\n' for name in entries)+dist+'/RECORD,,\n'
    with zipfile.ZipFile(path,'w') as wheel:
        for name, content in entries.items():
            wheel.writestr(name,content)
    return path


def test_two_offline_dependencies_have_separate_environments(rig,tmp_path):
    jobs=[]
    for version in ['1.0','2.0']:
        wheel=make_wheel(tmp_path,version)
        script=rig.file('train-'+version+'.py','import flexfixture\nprint(flexfixture.VERSION,flush=True)\n')
        req=rig.file('req-'+version+'.txt','--no-index\n'+wheel.as_uri()+'\n')
        job=rig.submit(key=version,entrypoint=[sys.executable,script.name],
            code={'uri':script.as_uri(),'digest':'sha256:'+hashlib.sha256(script.read_bytes()).hexdigest()},
            runtime={'requirements':{'uri':req.as_uri(),'digest':'sha256:'+hashlib.sha256(req.read_bytes()).hexdigest()}},
            resources={'gpus':0,'walltime_seconds':30})
        jobs.append(job)
    deadline=time.monotonic()+35
    while time.monotonic()<deadline:
        rig.service.reconcile_jobs()
        results=[rig.job(j['id']) for j in jobs]
        if all(j['state'] in {'succeeded','failed','timed_out'} for j in results):
            break
        time.sleep(.05)
    assert all(j['state']=='succeeded' for j in results),results
    assert len({j['runtime']['actual_python'] for j in results})==2
    for version,job in zip(['1.0','2.0'],results):
        assert version in '\n'.join(rig.ok('job.logs',{'id':job['id']})['items'])
    assert importlib.util.find_spec('flexfixture') is None


def test_runtime_preparation_is_inside_walltime(rig,tmp_path):
    slow=tmp_path/'slow-python'
    slow.write_text('#!/bin/sh\nsleep 30\n')
    slow.chmod(0o700)
    script=rig.file('deadline.py','print("TRAINER_MUST_NOT_START")\n')
    job=rig.submit(entrypoint=[sys.executable,script.name],runtime={**runtime(rig,''),'python_executable':str(slow)},
        code={'uri':script.as_uri(),'digest':'sha256:'+hashlib.sha256(script.read_bytes()).hexdigest()},
        resources={'gpus':0,'walltime_seconds':.3})
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        rig.service.reconcile_jobs()
        result=rig.job(job['id'])
        if result['state'] in {'timed_out','failed','succeeded'}:
            break
        time.sleep(.03)
    assert result['state']=='timed_out',result
    assert 'TRAINER_MUST_NOT_START' not in '\n'.join(rig.ok('job.logs',{'id':job['id']})['items'])


def test_requirements_source_change_cannot_change_queued_execution(rig):
    req=runtime(rig,'')
    script=rig.file('frozen.py','import sys\nprint("FROZEN",sys.prefix!=sys.base_prefix,flush=True)\n')
    job=rig.submit(runtime=req,entrypoint=[sys.executable,script.name],
        code={'uri':script.as_uri(),'digest':'sha256:'+hashlib.sha256(script.read_bytes()).hexdigest()},
        resources={'gpus':0,'walltime_seconds':20})
    rig.file('requirements.txt','--invalid-after-submission\n')
    deadline=time.monotonic()+25
    while time.monotonic()<deadline:
        rig.service.reconcile_jobs()
        result=rig.job(job['id'])
        if result['state'] in {'succeeded','failed','timed_out'}:
            break
        time.sleep(.04)
    assert result['state']=='succeeded'
    assert result['runtime']['isolation']=='job-venv'
    assert 'FROZEN True' in '\n'.join(rig.ok('job.logs',{'id':job['id']})['items'])


def test_restart_after_worker_completion_before_control_plane_publication(tmp_path):
    from rsi_red.schedulers.local import LocalScheduler
    r=Rig(tmp_path).setup()
    scheduler=LocalScheduler(root=tmp_path/'workers',allow_cpu_only=True)
    r.service.scheduler=scheduler
    code='''import pathlib,json
p=pathlib.Path('out');p.mkdir()
(p/'value.txt').write_text('immutable')
(p/'manifest.json').write_text(json.dumps({'items':[{'name':'v','path':'out/value.txt','kind':'report'}]}))
'''
    source=r.file('produce.py',code)
    try:
        job=r.submit(entrypoint=[sys.executable,source.name],output_manifest='out/manifest.json',
            code={'uri':source.as_uri(),'digest':'sha256:'+hashlib.sha256(source.read_bytes()).hexdigest()},
            resources={'gpus':0,'walltime_seconds':20})
        r.service.reconcile_jobs()
        deadline=time.monotonic()+10
        while time.monotonic()<deadline and scheduler.status(job['id'])['state'] not in {'succeeded','failed'}:
            time.sleep(.05)
        assert scheduler.status(job['id'])['state']=='succeeded'
        r.close()
        r.open()
        r.service.scheduler=scheduler
        r.service.reconcile_jobs()
        first=r.ok('job.outputs',{'id':job['id']})
        assert first['state']=='published'
        r.service.reconcile_jobs()
        assert r.ok('job.outputs',{'id':job['id']})==first
        artifact=r.ok('artifact.show',{'id':first['items'][0]['artifact_id']})
        assert artifact['provenance']['job_id']==job['id']
        assert artifact['provenance']['datasets']==[r.dataset]
        assert artifact['provenance']['runtime_manifest_digest']
        # Original worker output may change without mutating registered content.
        for path in (tmp_path/'execution').rglob('value.txt'):
            path.write_text('changed')
        dest=tmp_path/'recovered'
        r.ok('artifact.fetch',{'id':artifact['id'],'output':str(dest)})
        assert (dest/'value.txt').read_text()=='immutable'
    finally:
        r.close()


def test_output_publication_is_atomic_when_later_model_is_incomplete(rig):
    from contracts.flexible_training.test_process_contract import launch
    before=[e for e in rig.events() if e['type']=='artifact.registered']
    code='''import pathlib,json
p=pathlib.Path('out');p.mkdir()
(p/'r.txt').write_text('report')
(p/'broken.bin').write_text('incomplete model')
(p/'manifest.json').write_text(json.dumps({'items':[{'name':'report','path':'out/r.txt','kind':'report'},{'name':'broken','path':'out/broken.bin','kind':'model'}]}))
'''
    result=launch(rig,code,output_manifest='out/manifest.json')
    assert result['state']=='failed'
    assert result['reason']=='output_collection_failed'
    assert result['exit_code']==0
    assert rig.ok('job.outputs',{'id':result['id']})['items']==[]
    assert [e for e in rig.events() if e['type']=='artifact.registered']==before


def test_private_venv_does_not_inherit_worker_pythonpath(rig,tmp_path,monkeypatch):
    from contracts.flexible_training.test_process_contract import launch
    wheel=make_wheel(tmp_path,'1.0')
    shadow=tmp_path/'shared-path'
    module=shadow/'flexfixture'
    module.mkdir(parents=True)
    (module/'__init__.py').write_text('VERSION="inherited-wrong-version"\n')
    monkeypatch.syspath_prepend(str(shadow))
    result=launch(rig,'import flexfixture\nprint("ACTUAL",flexfixture.VERSION,flush=True)\n',
                  runtime=runtime(rig,'--no-index\n'+wheel.as_uri()+'\n'))
    assert result['state']=='succeeded',result
    logs='\n'.join(rig.ok('job.logs',{'id':result['id']})['items'])
    assert 'ACTUAL 1.0' in logs
    assert 'inherited-wrong-version' not in logs
