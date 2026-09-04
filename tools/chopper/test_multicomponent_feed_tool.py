"""
Tests for `multicomponent_feed_tool.py` -- the feed-state entry points the
conversation layer calls with already-checked facts. See
tools/multicomponent-distillation-dialogue-robustness-plan.md, point 3
("strict layering"): every function here takes only a `feed_state` plus
plain structured facts -- never a raw message, a model proposal, an
`intent`, or a `target_field`.

Run with:
    pytest tools/chopper/test_multicomponent_feed_tool.py -v
"""
import inspect

import pytest

import multicomponent_feed_tool as tool
from multicomponent_feed_state import empty_feed_state, record_value


def test_first_call_asks_for_components():
    result = tool.advance_feed_state(empty_feed_state(), {})
    assert result['complete'] is False
    assert result['missing_field'] == 'component_names'


def test_multiturn_collection_reaches_completion():
    state = empty_feed_state()

    r = tool.advance_feed_state(state, {'component_names': ['Water', 'Ethanol', 'Methanol']})
    assert r['missing_field'] == 'feed_quantity'
    state = r['feed_state']

    r = tool.advance_feed_state(state, {'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30}})
    assert r['missing_field'] == 'flow_units'
    state = r['feed_state']

    r = tool.advance_feed_state(state, {'component_flow_units': 'kmol/hr'})
    assert r['missing_field'] == 'pressure_value'
    state = r['feed_state']

    r = tool.advance_feed_state(state, {'pressure': 1.0})
    assert r['missing_field'] == 'pressure_units'
    state = r['feed_state']

    r = tool.advance_feed_state(state, {'pressure_units': 'atm'})
    assert r['missing_field'] == 'feed_temperature_value'
    state = r['feed_state']

    r = tool.advance_feed_state(state, {'feed_temperature': 350})
    assert r['missing_field'] == 'feed_temperature_units'
    state = r['feed_state']

    r = tool.advance_feed_state(state, {'feed_temperature_units': 'K'})
    assert r['complete'] is True
    assert r['phase'] in {'liquid', 'vapor', 'vapor_liquid'}
    assert 0 <= r['vapor_fraction'] <= 1
    assert 0 <= r['liquid_fraction'] <= 1


def test_bare_percent_composition_infers_basis_without_asking():
    state = empty_feed_state()
    r = tool.advance_feed_state(state, {'component_names': ['Water', 'Ethanol', 'Methanol']})
    r = tool.advance_feed_state(r['feed_state'], {
        'total_flow': 100, 'total_flow_units': 'kmol/hr',
        'composition': {'Water': 0.3, 'Ethanol': 0.4},
    })
    assert r['missing_field'] == 'pressure_value'


def test_composition_before_flow_units_asks_for_flow_units_next():
    state = empty_feed_state()
    r = tool.advance_feed_state(state, {'component_names': ['Water', 'Ethanol', 'Methanol']})
    r = tool.advance_feed_state(r['feed_state'], {
        'total_flow': 100, 'composition': {'Water': 0.3, 'Ethanol': 0.4},
    })
    assert r['missing_field'] == 'flow_units'


def test_conflicting_information_reported_without_calculation():
    state = empty_feed_state()
    r = tool.advance_feed_state(state, {'component_names': ['Water', 'Ethanol', 'Methanol']})
    r = tool.advance_feed_state(r['feed_state'], {
        'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30}, 'total_flow': 500,
    })
    assert r['complete'] is False
    assert r['valid'] is False
    assert r['conflicts']


def test_invalid_information_reported_without_calculation():
    r = tool.advance_feed_state(empty_feed_state(), {
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': -10, 'Ethanol': 40, 'Methanol': 30},
    })
    assert r['complete'] is False
    assert r['valid'] is False
    assert r['validation_errors']


def test_reset_returns_a_fresh_empty_state():
    fresh = tool.reset_multicomponent_feed_session()
    assert fresh['component_names'] == []
    r = tool.advance_feed_state(fresh, {})
    assert r['missing_field'] == 'component_names'


def test_unrecognized_component_reports_calculation_error_not_crash():
    state = empty_feed_state()
    r = tool.advance_feed_state(state, {'component_names': ['Water', 'Ethanol', 'NotAChemical123']})
    r = tool.advance_feed_state(r['feed_state'], {
        'component_flows': {'Water': 30, 'Ethanol': 40, 'NotAChemical123': 30},
        'component_flow_units': 'kmol/hr',
    })
    r = tool.advance_feed_state(r['feed_state'], {'pressure': 1.0, 'pressure_units': 'atm'})
    r = tool.advance_feed_state(r['feed_state'], {'feed_temperature': 350, 'feed_temperature_units': 'K'})
    assert r['complete'] is False
    assert r['valid'] is False
    assert 'error' in r


def test_never_defaults_to_bubble_point_stays_pending_without_temperature():
    state = empty_feed_state()
    r = tool.advance_feed_state(state, {'component_names': ['Water', 'Ethanol', 'Methanol']})
    r = tool.advance_feed_state(r['feed_state'], {'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30}})
    r = tool.advance_feed_state(r['feed_state'], {'component_flow_units': 'kmol/hr'})
    r = tool.advance_feed_state(r['feed_state'], {'pressure': 1.0, 'pressure_units': 'atm'})
    assert r['complete'] is False
    assert r['missing_field'] == 'feed_temperature_value'


# --- Read-only query never mutates and never runs the VLE path ---------------

def test_query_feed_state_returns_a_copy_and_never_mutates():
    state = empty_feed_state()
    snapshot = tool.query_feed_state(state, 'pressure')
    snapshot['pressure'] = {'value': 999}
    assert state['pressure'] is None


def test_query_feed_state_does_not_require_readiness():
    state = empty_feed_state()
    # Deliberately incomplete state -- query must still work, never raise,
    # never attempt a VLE calculation.
    snapshot = tool.query_feed_state(state, 'pressure')
    assert record_value(snapshot['pressure']) is None


# --- Strict layering: no function here accepts message/model-shaped input ---

def test_advance_feed_state_signature_has_no_message_or_intent_params():
    params = set(inspect.signature(tool.advance_feed_state).parameters)
    for forbidden in ('message', 'user_message', 'intent', 'target_field', 'proposal'):
        assert forbidden not in params


def test_query_feed_state_signature_has_no_message_or_intent_params():
    params = set(inspect.signature(tool.query_feed_state).parameters)
    for forbidden in ('message', 'user_message', 'intent', 'proposal'):
        assert forbidden not in params


def test_update_multicomponent_feed_has_no_enthalpy_or_quality_arguments():
    params = inspect.signature(tool.update_multicomponent_feed).parameters
    assert 'feed_enthalpy' not in params
    assert 'feed_enthalpy_units' not in params
    assert 'feed_quality' not in params
