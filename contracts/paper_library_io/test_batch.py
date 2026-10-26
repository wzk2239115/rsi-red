from collections import Counter
import time

from contracts.paper_library.support import CURATOR, CURATOR_TWO, VENUE


def poll(r, batch, *, terminal=True):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        r.reconcile()
        r.clock.advance(5)
        result = r.ok('paper.batch_show', {'id': batch['id']}, token=CURATOR)
        if terminal and result['state'] in {'completed', 'completed_with_errors'}:
            return result
        if not terminal and result['counts']['ready'] > 0:
            return result
        time.sleep(.01)
    raise AssertionError('Batch did not reach expected progress')


def test_thousand_papers_resume_without_redownloading_successful_items(rig):
    for i in range(1000):
        rig.source.add(f'large-{i:04d}')
    p = rig.policy()
    request = {'policy_id': p['id'], 'idempotency_key': 'large-1000',
               'records': [{'provider': 'openreview_v2', 'record_id': f'large-{i:04d}'} for i in range(1000)]}
    batch = rig.ok('paper.batch_submit', request, token=CURATOR)
    assert batch['state'] == 'queued' and rig.source.calls == []
    partial = poll(rig, batch, terminal=False)
    assert 0 < partial['counts']['ready'] < 1000
    completed_ids = {item['record_id'] for item in partial['items'] if item['state'] == 'ready'}
    calls = Counter(rig.source.calls)
    rig.close()
    rig.open()
    assert rig.ok('paper.batch_submit', request, token=CURATOR)['id'] == batch['id']
    final = poll(rig, batch)
    assert final['counts']['ready'] == final['counts']['total'] == 1000
    assert final['counts']['failed'] == 0
    assert 1 <= rig.source.peak <= p['spec']['max_parallel']
    for key in completed_ids:
        assert Counter(rig.source.calls)[('pdf', key)] == calls[('pdf', key)]
    assert rig.cluster.submissions == [] and rig.evaluator.calls == []


def test_two_curators_deduplicate_shared_catalog_without_granting_batch_access(rig):
    p = rig.policy()
    a = rig.ok('paper.batch_submit', {'policy_id': p['id'], 'idempotency_key': 'curator-a',
        'records': [{'provider': 'openreview_v2', 'record_id': 'paper-a'}]}, token=CURATOR)
    b = rig.ok('paper.batch_submit', {'policy_id': p['id'], 'idempotency_key': 'curator-b',
        'records': [{'provider': 'openreview_v2', 'record_id': 'paper-a'}]}, token=CURATOR_TWO)
    poll(rig, a)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        rig.reconcile()
        result = rig.ok('paper.batch_show', {'id': b['id']}, token=CURATOR_TWO)
        if result['state'] == 'completed':
            break
        time.sleep(.01)
    assert result['state'] == 'completed'
    assert result['counts']['ready'] + result['counts']['duplicate'] == 1
    listed = rig.ok('paper.list', {'eligible_only': True})['items']
    assert len(listed) == 1
    rig.error('paper.batch_show', {'id': a['id']}, 'FORBIDDEN', token=CURATOR_TWO)


def test_catalog_cursor_is_recorded_and_next_page_does_not_repeat(rig):
    p = rig.policy()
    a = rig.ok('paper.batch_submit', {'policy_id': p['id'], 'idempotency_key': 'catalog-page-1',
        'catalog': {'provider': 'openreview_v2', 'venue_id': VENUE, 'cursor': None, 'limit': 1}}, token=CURATOR)
    first = poll(rig, a)
    assert first['next_cursor'] and first['catalog_snapshot_digest']
    b = rig.ok('paper.batch_submit', {'policy_id': p['id'], 'idempotency_key': 'catalog-page-2',
        'catalog': {'provider': 'openreview_v2', 'venue_id': VENUE, 'cursor': first['next_cursor'], 'limit': 1}}, token=CURATOR)
    second = poll(rig, b)
    assert second['next_cursor'] is None
    assert {i['record_id'] for i in first['items']}.isdisjoint({i['record_id'] for i in second['items']})


def test_partial_failure_does_not_rollback_success_or_retry_bad_papers_forever(rig):
    p = rig.policy()
    rig.source.failures['paper-b'] = 1000
    batch = rig.ok('paper.batch_submit', {'policy_id': p['id'], 'idempotency_key': 'partial-failure',
        'records': [{'provider': 'openreview_v2', 'record_id': key} for key in ('paper-a', 'paper-b')]}, token=CURATOR)
    result = poll(rig, batch)
    assert result['state'] == 'completed_with_errors'
    assert result['counts']['ready'] == result['counts']['failed'] == 1
    failed = next(i for i in result['items'] if i['state'] == 'failed')
    assert failed['attempts'] <= p['spec']['retry_limit'] + 1
    ready_calls = Counter(rig.source.calls)[('pdf', 'paper-a')]
    rig.ok('paper.batch_retry', {'id': batch['id']}, token=CURATOR)
    poll(rig, batch)
    assert Counter(rig.source.calls)[('pdf', 'paper-a')] == ready_calls
    assert Counter(rig.source.calls)[('record', 'paper-b')] <= p['spec']['retry_limit'] + 1


def test_catalog_reserved_attempts_survive_crash_and_stay_bounded(rig):
    p = rig.policy(retry_limit=1)
    batch = rig.ok('paper.batch_submit', {'policy_id': p['id'], 'idempotency_key': 'catalog-crash',
        'catalog': {'provider': 'openreview_v2', 'venue_id': VENUE, 'cursor': None, 'limit': 1}}, token=CURATOR)
    with rig.service.store.transaction():
        stored = rig.service.store.get(batch['id'], 'paper_batch')
        stored['catalog_attempts'] = 2  # final attempt reserved, source response lost in crash
        rig.service.store.save('paper_batch', stored)
    rig.close()
    rig.open()
    rig.reconcile()
    final = rig.ok('paper.batch_show', {'id': batch['id']}, token=CURATOR)
    assert final['state'] == 'completed_with_errors'
    assert final['catalog_error']['code'] == 'RETRY_EXHAUSTED'
    assert rig.source.calls == []
