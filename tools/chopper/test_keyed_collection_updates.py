"""
tools/binary-distillation-issues-9-1-2026-sixth.md Part 11 -- focused tests
for the new `items`-collection TurnIntent update shape (multi-entity keyed
field extraction, e.g. `component_flows`), on top of the existing scalar
shape. No live LLM: builds TurnIntent dicts directly, same convention as
test_turn_transaction.py.

Run with:
    pytest tools/chopper/test_keyed_collection_updates.py -v
"""
import binary_distillation_workflow_agent as agent  # binds ACTION_REGISTRY['*']['run']
from problem_field_registry import ACTIVE_WORKFLOW_SCHEMA
from turn_transaction import normalize_turn_intent_updates, validate_turn_intent


def _intent(updates=None, queries=None, action=None):
    return {'version': 1, 'updates': updates or [], 'queries': queries or [], 'action': action}


def _upd(field, value, entity=None, units=None):
    return {'field': field, 'entity': entity, 'subject': None, 'value': value, 'units': units, 'basis': None}


def _collection_upd(field, items, subject=None):
    return {'field': field, 'subject': subject, 'items': items}


def _item(entity, value, units=None, basis=None):
    return {'entity': entity, 'value': value, 'units': units, 'basis': basis}


# ---------------------------------------------------------------------------
# normalize_turn_intent_updates -- pure shape expansion, no registry.
# ---------------------------------------------------------------------------

def test_normalize_scalar_update_passes_through_as_one_entry():
    normalized = normalize_turn_intent_updates([_upd('component_flows', 50, entity='Ethanol', units='kmol/hr')])
    assert len(normalized) == 1
    entry = normalized[0]
    assert entry['field'] == 'component_flows'
    assert entry['entity'] == 'Ethanol'
    assert entry['value'] == 50
    assert entry['units'] == 'kmol/hr'
    assert '_shape_error' not in entry


def test_normalize_collection_update_expands_to_one_entry_per_item():
    normalized = normalize_turn_intent_updates([_collection_upd('component_flows', [
        _item('Ethanol', 50, units='kmol/hr'),
        _item('Water', 50, units='kmol/hr'),
    ])])
    assert len(normalized) == 2
    assert {(n['entity'], n['value']) for n in normalized} == {('Ethanol', 50), ('Water', 50)}
    assert all(n['field'] == 'component_flows' for n in normalized)
    assert all(n['update_index'] == 0 for n in normalized)  # both came from the SAME original update


def test_normalize_items_with_top_level_value_is_a_shape_error():
    raw = {'field': 'component_flows', 'value': 50, 'items': [_item('Ethanol', 50)]}
    normalized = normalize_turn_intent_updates([raw])
    assert len(normalized) == 1
    assert normalized[0]['_shape_error'] == 'items_cannot_coexist_with_entity_or_value'
    assert normalized[0]['source_update'] is raw


def test_normalize_items_with_top_level_entity_is_a_shape_error():
    raw = {'field': 'component_flows', 'entity': 'Ethanol', 'items': [_item('Water', 50)]}
    normalized = normalize_turn_intent_updates([raw])
    assert normalized[0]['_shape_error'] == 'items_cannot_coexist_with_entity_or_value'


def test_normalize_empty_items_is_a_shape_error():
    normalized = normalize_turn_intent_updates([_collection_upd('component_flows', [])])
    assert normalized[0]['_shape_error'] == 'items_must_be_a_non_empty_list'


def test_normalize_item_missing_entity_is_a_shape_error():
    normalized = normalize_turn_intent_updates([_collection_upd('component_flows', [
        _item('Ethanol', 50), {'entity': None, 'value': 60},
    ])])
    assert len(normalized) == 1
    assert normalized[0]['_shape_error'] == 'missing_entity'


# ---------------------------------------------------------------------------
# Single keyed value still works (scalar shape, unchanged behavior).
# ---------------------------------------------------------------------------

def test_single_keyed_scalar_update_still_works():
    transaction = validate_turn_intent(_intent(updates=[
        _upd('component_flows', 50, entity='Ethanol', units='kmol/hr'),
    ]), ACTIVE_WORKFLOW_SCHEMA)
    assert transaction['update_kwargs'] == {
        'component_flows': {'Ethanol': 50.0},
        'component_flow_units': 'kmol/hr',
    }
    assert transaction['invalid_updates'] == []


# ---------------------------------------------------------------------------
# Multi-item keyed update works -- the primary fix.
# ---------------------------------------------------------------------------

def test_multi_item_keyed_update_works():
    transaction = validate_turn_intent(_intent(updates=[
        _collection_upd('component_flows', [
            _item('Ethanol', 50, units='kmol/hr'),
            _item('Water', 50, units='kmol/hr'),
        ]),
    ]), ACTIVE_WORKFLOW_SCHEMA)
    assert transaction['update_kwargs'] == {
        'component_flows': {'Ethanol': 50.0, 'Water': 50.0},
        'component_flow_units': 'kmol/hr',
    }
    assert transaction['invalid_updates'] == []
    assert transaction['conflicts'] == []


def test_full_failing_prompt_produces_exact_write_kwargs():
    """The original reported failure, once Qwen emits the collection shape:
    'Separate water and ethanol at 355 K and 101325 Pa pressure. The feed
    flow rates are 50 kmol/hr ethanol and 50 kmol/hr water.'"""
    transaction = validate_turn_intent(_intent(updates=[
        _collection_upd('component_flows', [
            _item('Ethanol', 50, units='kmol/hr'),
            _item('Water', 50, units='kmol/hr'),
        ]),
        _upd('feed_temperature_K', 355),
        _upd('pressure_Pa', 101325),
    ]), ACTIVE_WORKFLOW_SCHEMA)
    assert transaction['update_kwargs'] == {
        'component_flows': {'Ethanol': 50.0, 'Water': 50.0},
        'component_flow_units': 'kmol/hr',
        'feed_temperature_K': 355,
        'pressure_Pa': 101325,
    }


# ---------------------------------------------------------------------------
# Invalid keyed item rejects atomically.
# ---------------------------------------------------------------------------

def test_invalid_keyed_item_rejects_whole_batch():
    transaction = validate_turn_intent(_intent(updates=[
        _collection_upd('component_flows', [
            _item('Ethanol', 50),
            {'entity': None, 'value': 60},  # missing entity
        ]),
    ]), ACTIVE_WORKFLOW_SCHEMA)
    assert transaction['update_kwargs'] == {}
    assert len(transaction['invalid_updates']) == 1
    assert transaction['invalid_updates'][0]['reason'] == 'missing_entity'


# ---------------------------------------------------------------------------
# Conflicting duplicate entity within one collection.
# ---------------------------------------------------------------------------

def test_conflicting_duplicate_entity_within_items_rejects():
    transaction = validate_turn_intent(_intent(updates=[
        _collection_upd('component_flows', [
            _item('Ethanol', 50),
            _item('Ethanol', 60),
        ]),
    ]), ACTIVE_WORKFLOW_SCHEMA)
    assert transaction['update_kwargs'] == {}
    assert len(transaction['conflicts']) == 1
    assert transaction['conflicts'][0]['field'] == 'component_flows'
    assert transaction['conflicts'][0]['entity'] == 'Ethanol'


def test_identical_duplicate_entity_within_items_collapses():
    transaction = validate_turn_intent(_intent(updates=[
        _collection_upd('component_flows', [
            _item('Ethanol', 50), _item('Ethanol', 50),
        ]),
    ]), ACTIVE_WORKFLOW_SCHEMA)
    assert transaction['update_kwargs'] == {'component_flows': {'Ethanol': 50.0}}
    assert transaction['conflicts'] == []


# ---------------------------------------------------------------------------
# Mixed units within one collection -- must not silently combine.
# ---------------------------------------------------------------------------

def test_mixed_units_within_items_rejects_as_conflict():
    transaction = validate_turn_intent(_intent(updates=[
        _collection_upd('component_flows', [
            _item('Ethanol', 50, units='kmol/hr'),
            _item('Water', 100, units='kg/hr'),
        ]),
    ]), ACTIVE_WORKFLOW_SCHEMA)
    assert transaction['update_kwargs'] == {}
    assert any(c['field'] == 'component_flows' and c.get('kind') == 'units' for c in transaction['conflicts'])


# ---------------------------------------------------------------------------
# Collection on a non-keyed field must reject.
# ---------------------------------------------------------------------------

def test_collection_on_non_keyed_field_rejects():
    transaction = validate_turn_intent(_intent(updates=[
        _collection_upd('pressure_Pa', [_item('irrelevant', 101325)]),
    ]), ACTIVE_WORKFLOW_SCHEMA)
    assert transaction['update_kwargs'] == {}
    assert len(transaction['invalid_updates']) == 1
    assert transaction['invalid_updates'][0]['reason'] == 'items_not_supported_for_field'
