"""Peer recipe evidence and actual node telemetry contracts."""
import importlib
from types import SimpleNamespace


from tests.support import ALICE, BOB, OPERATOR, OUTSIDER, Rig


def recipe(rig):
    return rig.ok('recipe.create', {'campaign_id': rig.campaign, 'title': 'rollout ablation',
        'hypothesis': 'reduce repetition', 'method': 'grpo', 'datasets': [rig.dataset],
        'parents': [rig.base], 'parameters': {'temperature': .7}})


def test_recipe_is_owned_by_authenticated_peer_and_durable(tmp_path):
    r = Rig(tmp_path).setup()
    try:
        item = recipe(r)
        assert item['owner'] == 'alice'
        assert item['source'] == 'agent_report'
        assert item['state'] == 'planned'
        r.close()
        r.open()
        assert r.ok('recipe.show', {'id': item['id']}, token=BOB)['hypothesis'] == 'reduce repetition'
        r.error('recipe.show', {'id': item['id']}, 'FORBIDDEN', token=OUTSIDER)
    finally:
        r.close()


def test_recipe_revision_preserves_history_and_blocks_peer_write(tmp_path):
    r = Rig(tmp_path).setup()
    try:
        item = recipe(r)
        r.error('recipe.update', {'id': item['id'], 'state': 'abandoned', 'observation': 'no gain'},
                'FORBIDDEN', token=BOB)
        revised = r.ok('recipe.update', {'id': item['id'], 'state': 'abandoned', 'observation': 'no gain'})
        assert len(revised['history']) == 2
        assert revised['history'][0]['state'] == 'planned'
        assert revised['history'][1]['observation'] == 'no gain'
    finally:
        r.close()


def test_jobs_can_only_bind_own_recipe_with_matching_inputs(tmp_path):
    r = Rig(tmp_path).setup()
    try:
        item = recipe(r)
        request = r.job_request(recipe_id=item['id'])
        r.error('job.submit', request, 'FORBIDDEN', token=BOB)
        r.error('job.submit', dict(request, datasets=[]), 'RECIPE_INPUT_MISMATCH')
        job = r.ok('job.submit', request)
        shown = r.ok('recipe.show', {'id': item['id']})
        assert shown['jobs'][0]['id'] == job['id']
        assert shown['jobs'][0]['state'] == 'accepted'
    finally:
        r.close()


def test_recipe_cannot_import_cross_campaign_model(tmp_path):
    r = Rig(tmp_path).setup()
    try:
        campaign = r.ok('campaign.create', {'name': 'other', 'members': ['alice'],
            'protocol_id': r.protocol, 'gpu_hours_budget': 1}, token=OPERATOR)
        r.error('recipe.create', {'campaign_id': campaign['id'], 'title': 'bad', 'hypothesis': 'bad',
            'method': 'sft', 'parents': [r.base], 'datasets': []}, 'FORBIDDEN')
    finally:
        r.close()


def test_resource_requires_operator_and_missing_telemetry_is_not_zero(tmp_path):
    r = Rig(tmp_path).setup()
    try:
        result = r.ok('resource.show', token=OPERATOR)
        assert result['telemetry']['status'] == 'unavailable'
        assert result['telemetry']['gpus'] == []
        r.error('resource.show', {}, 'FORBIDDEN', token=ALICE)
    finally:
        r.close()


def test_nvidia_collector_parses_real_units_and_timestamp():
    module = importlib.import_module('rsi_red.telemetry')
    commands = []
    def runner(argv, **kwargs):
        commands.append(argv)
        assert kwargs['timeout'] <= 5
        assert not kwargs.get('shell')
        return SimpleNamespace(stdout='GPU-123, 0, NVIDIA H100, 72, 32000, 81559, 210.5\n')
    result = module.NvidiaTelemetry(runner=runner, clock=lambda: 100).sample()
    assert result['source'] == 'nvidia-smi'
    assert result['sampled_at'] == 100
    gpu = result['gpus'][0]
    assert gpu['utilization_percent'] == 72
    assert gpu['memory_used_mib'] == 32000
    assert gpu['power_watts'] == 210.5
    assert commands[0][0] == 'nvidia-smi'


def test_missing_or_na_gpu_metrics_never_become_zero():
    module = importlib.import_module('rsi_red.telemetry')
    def absent(*args, **kwargs):
        raise FileNotFoundError()
    assert module.NvidiaTelemetry(runner=absent).sample()['status'] == 'unavailable'
    def na(*args, **kwargs):
        return SimpleNamespace(stdout='GPU-123, 0, H100, [N/A], 0, 80000, [N/A]\n')
    gpu = module.NvidiaTelemetry(runner=na).sample()['gpus'][0]
    assert gpu['utilization_percent'] is None
    assert gpu['power_watts'] is None


def test_dashboard_groups_by_peer_and_separates_request_from_utilization(tmp_path):
    from rsi_red.kanban import snapshot
    r = Rig(tmp_path).setup()
    try:
        item = recipe(r)
        r.submit(recipe_id=item['id'])
        state = snapshot(lambda op, p: r.ok(op, p, token=OPERATOR))
        alice = next(agent for agent in state['agents'] if agent['id'] == 'alice')
        assert alice['recipes'][0]['id'] == item['id']
        assert alice['requested_gpus'] == 1
        assert state['resources']['telemetry']['gpus'] == []
        assert state['resources']['telemetry']['status'] == 'unavailable'
    finally:
        r.close()


def test_researcher_dashboard_handles_operator_only_resources(tmp_path):
    from rsi_red.kanban import snapshot
    r = Rig(tmp_path).setup()
    try:
        def request(op, p):
            result = r.call(op, p)
            if result['error']:
                raise RuntimeError(result['error']['code'])
            return result['data']
        result = snapshot(request)
        assert result['resources']['telemetry']['status'] == 'restricted'
    finally:
        r.close()
