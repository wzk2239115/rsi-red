import importlib
from types import SimpleNamespace

import pytest


class Client:
    def __init__(self):
        self.jobs = {}
        self.submissions = []
        self.stopped = []
        self.info_calls = []

    def submit_job(self, **kwargs):
        key = kwargs['submission_id']
        if key in self.jobs:
            raise RuntimeError('already exists')
        self.submissions.append(kwargs)
        self.jobs[key] = SimpleNamespace(status='PENDING', start_time=1000, end_time=None,
            metadata=kwargs['metadata'], message=None)
        return key

    def get_job_info(self, key):
        self.info_calls.append(key)
        if key not in self.jobs:
            raise RuntimeError(f'Job {key} does not exist')
        return self.jobs[key]

    def stop_job(self, key):
        self.stopped.append(key)
        self.jobs[key].status = 'STOPPED'
        return True

    def get_job_logs(self, key):
        return 'first\nsecond\nthird\n'


def adapter(client):
    return importlib.import_module('rsi_red.schedulers.ray').RayScheduler(client=client)


def request(folder):
    return {'entrypoint': ['python', 'train.py', '--name', 'a; touch /tmp/never'],
            'workdir': str(folder), 'env': {'RATE': '0.1'},
            'resources': {'gpus': 0, 'cpus': 1, 'walltime_seconds': 60}}


def test_submission_is_stable_and_working_directory_is_uploaded(tmp_path):
    client = Client()
    scheduler = adapter(client)
    assert scheduler.submit(request(tmp_path), submission_key='request-1') == 'request-1'
    submitted = client.submissions[0]
    assert submitted['submission_id'] == 'request-1'
    assert submitted['runtime_env']['working_dir'] == str(tmp_path)
    assert submitted['runtime_env']['env_vars']['RATE'] == '0.1'
    assert submitted['entrypoint_num_cpus'] == 1
    assert submitted['entrypoint_num_gpus'] == 0
    assert submitted['metadata']['rsi-red/submission-key'] == 'request-1'
    wrapper = list(tmp_path.glob('_rsi_ray_*.py'))
    assert len(wrapper) == 1
    text = wrapper[0].read_text()
    assert 'a; touch /tmp/never' in text
    assert 'shell=True' not in text


def test_absolute_staged_code_path_is_made_portable(tmp_path):
    client = Client()
    req = request(tmp_path)
    req['entrypoint'][1] = str(tmp_path / 'train.py')
    adapter(client).submit(req, submission_key='portable')
    assert str(tmp_path / 'train.py') not in next(tmp_path.glob('_rsi_ray_*.py')).read_text()


def test_find_recovers_existing_submission_without_resubmit(tmp_path):
    client = Client()
    first = adapter(client)
    first.submit(request(tmp_path), submission_key='request-2')
    assert adapter(client).find('request-2') == 'request-2'
    assert len(client.submissions) == 1
    assert adapter(client).find('missing') is None


@pytest.mark.parametrize('raw,expected', [
    ('PENDING', 'queued'), ('RUNNING', 'running'), ('SUCCEEDED', 'succeeded'),
    ('FAILED', 'failed'), ('STOPPED', 'cancelled')])
def test_state_mapping(raw, expected, tmp_path):
    client = Client()
    scheduler = adapter(client)
    scheduler.submit(request(tmp_path), submission_key='job')
    client.jobs['job'].status = raw
    assert scheduler.status('job')['state'] == expected


def test_cancel_and_log_pagination(tmp_path):
    client = Client()
    scheduler = adapter(client)
    scheduler.submit(request(tmp_path), submission_key='job')
    scheduler.cancel('job')
    assert client.stopped == ['job']
    assert scheduler.logs('job', offset=1, limit=1) == ['second']


def test_connection_failure_is_not_interpreted_as_missing_job():
    client = Client()
    def broken(key):
        raise ConnectionError('dashboard unreachable')
    client.get_job_info = broken
    with pytest.raises(TimeoutError):
        adapter(client).find('job')


def test_unconfigured_container_image_is_rejected(tmp_path):
    req = request(tmp_path)
    req['image'] = 'train@sha256:' + '1' * 64
    with pytest.raises(ValueError, match='image'):
        adapter(Client()).submit(req, submission_key='job')
