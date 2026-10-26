"""Static material integrity, distinct from the as-yet-unimplemented research service."""
import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1] / 'research/inspiration'


def test_seed_cards_have_traceable_sources_and_no_unearned_validation():
    sources = {source['id']: source for source in json.loads((ROOT / 'sources.json').read_text())['sources']}
    cards = json.loads((ROOT / 'cards.json').read_text())['cards']
    assert len(cards) >= 8
    assert len({card['id'] for card in cards}) == len(cards)
    required = {'source_finding','hypothesis','representation_bridge','preconditions','minimal_trial',
                'equal_budget_control','falsifier','risks','security_transfer','requirements','tags'}
    for card in cards:
        assert required <= set(card)
        assert all(card[field] for field in required)
        assert card['source_id'] in sources
        assert card['evidence_status'] == 'ai_hypothesis'
        assert card['local_validation'] == 'not_tested'
        assert card['executable'] is False
        assert card['requirements']['cost_tier'] in {'small','medium','large'}
        source = sources[card['source_id']]
        assert urlparse(source['url']).scheme == 'https'
        assert source['locator'] and source['version'] and source['verification']


def test_material_preserves_negative_results_and_representation_limits():
    cards = {card['id']: card for card in json.loads((ROOT / 'cards.json').read_text())['cards']}
    assert cards['structured-state-representation']['requirements']['architecture_change'] is True
    assert cards['decode-train-mismatch']['requirements']['editable_rollout'] is True
    assert cards['verified-self-generated-data']['requirements']['verifier'] is True
    assert cards['research-workflow-archive']['falsifier']
