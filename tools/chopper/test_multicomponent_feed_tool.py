"""
Tests for `multicomponent_feed_tool.py` -- the single stateful intake-and-
calculate tool the agent exposes. Exercises multi-turn accumulation via
plain function calls (no Ollama involved). See
tools/multicomponent-distillation-feed-phase-plan.md "Required Tests"
items 4, 16.

Run with:
    pytest tools/chopper/test_multicomponent_feed_tool.py -v
"""
import pytest

import multicomponent_feed_tool as tool


@pytest.fixture(autouse=True)
def _reset():
    tool.reset_multicomponent_feed_session()
    yield
    tool.reset_multicomponent_feed_session()


def test_first_call_asks_for_components():
    result = tool.update_multicomponent_feed()
    assert result['complete'] is False
    assert result['pending_request']['field'] == 'component_names'


def test_multiturn_collection_reaches_completion():
    r = tool.update_multicomponent_feed(component_names=['Water', 'Ethanol', 'Methanol'])
    assert r['pending_request']['field'] == 'component_flows_or_total_flow_and_composition'

    r = tool.update_multicomponent_feed(
        component_flows={'Water': 30, 'Ethanol': 40, 'Methanol': 30},
    )
    assert r['pending_request']['field'] == 'component_flow_units_or_total_flow_units'

    r = tool.update_multicomponent_feed(component_flow_units='kmol/hr')
    assert r['pending_request']['field'] == 'pressure'

    r = tool.update_multicomponent_feed(pressure=1.0)
    assert r['pending_request']['field'] == 'pressure_units'

    r = tool.update_multicomponent_feed(pressure_units='atm')
    assert r['pending_request']['field'] == 'feed_temperature'

    r = tool.update_multicomponent_feed(feed_temperature=350)
    assert r['pending_request']['field'] == 'feed_temperature_units'

    r = tool.update_multicomponent_feed(feed_temperature_units='K')
    assert r['complete'] is True
    assert r['phase'] in {'liquid', 'vapor', 'vapor_liquid'}
    assert 0 <= r['vapor_fraction'] <= 1
    assert set(r.keys()) == {'complete', 'valid', 'phase', 'vapor_fraction', 'liquid_fraction', 'message'}


def test_bare_percent_composition_infers_basis_without_asking():
    """Once total-flow units are known, a bare-percentage composition's
    basis is inferred automatically -- no composition_basis question."""
    tool.update_multicomponent_feed(component_names=['Water', 'Ethanol', 'Methanol'])
    r = tool.update_multicomponent_feed(
        total_flow=100, total_flow_units='kmol/hr',
        composition={'Water': 0.3, 'Ethanol': 0.4},
    )
    assert r['pending_request']['field'] == 'pressure'


def test_composition_before_flow_units_asks_for_flow_units_next():
    tool.update_multicomponent_feed(component_names=['Water', 'Ethanol', 'Methanol'])
    r = tool.update_multicomponent_feed(
        total_flow=100, composition={'Water': 0.3, 'Ethanol': 0.4},
    )
    assert r['pending_request']['field'] == 'component_flow_units_or_total_flow_units'


def test_state_remembered_across_calls_no_resend_needed():
    tool.update_multicomponent_feed(component_names=['Water', 'Ethanol', 'Methanol'])
    tool.update_multicomponent_feed(component_flows={'Water': 30, 'Ethanol': 40, 'Methanol': 30})
    tool.update_multicomponent_feed(component_flow_units='kmol/hr')
    tool.update_multicomponent_feed(pressure=1.0, pressure_units='atm')
    r = tool.update_multicomponent_feed(feed_temperature=350, feed_temperature_units='K')
    assert r['complete'] is True


def test_conflicting_information_reported_without_calculation():
    tool.update_multicomponent_feed(component_names=['Water', 'Ethanol', 'Methanol'])
    r = tool.update_multicomponent_feed(
        component_flows={'Water': 30, 'Ethanol': 40, 'Methanol': 30}, total_flow=500,
    )
    assert r['complete'] is False
    assert r['valid'] is False
    assert r['conflicts']


def test_invalid_information_reported_without_calculation():
    r = tool.update_multicomponent_feed(
        component_names=['Water', 'Ethanol', 'Methanol'],
        component_flows={'Water': -10, 'Ethanol': 40, 'Methanol': 30},
    )
    assert r['complete'] is False
    assert r['valid'] is False
    assert r['validation_errors']


def test_reset_clears_accumulated_state():
    tool.update_multicomponent_feed(component_names=['Water', 'Ethanol', 'Methanol'])
    reset_result = tool.reset_multicomponent_feed_session()
    assert reset_result['reset'] is True
    r = tool.update_multicomponent_feed()
    assert r['pending_request']['field'] == 'component_names'


def test_unrecognized_component_reports_calculation_error_not_crash():
    tool.update_multicomponent_feed(component_names=['Water', 'Ethanol', 'NotAChemical123'])
    tool.update_multicomponent_feed(
        component_flows={'Water': 30, 'Ethanol': 40, 'NotAChemical123': 30},
        component_flow_units='kmol/hr',
    )
    tool.update_multicomponent_feed(pressure=1.0, pressure_units='atm')
    r = tool.update_multicomponent_feed(feed_temperature=350, feed_temperature_units='K')
    assert r['complete'] is False
    assert r['valid'] is False
    assert 'error' in r


# --- No enthalpy/quality arguments exist at all (Required Tests item 16) ---

def test_update_multicomponent_feed_has_no_enthalpy_or_quality_arguments():
    import inspect
    params = inspect.signature(tool.update_multicomponent_feed).parameters
    assert 'feed_enthalpy' not in params
    assert 'feed_enthalpy_units' not in params
    assert 'feed_quality' not in params


def test_never_defaults_to_bubble_point_stays_pending_without_temperature():
    tool.update_multicomponent_feed(component_names=['Water', 'Ethanol', 'Methanol'])
    tool.update_multicomponent_feed(component_flows={'Water': 30, 'Ethanol': 40, 'Methanol': 30})
    tool.update_multicomponent_feed(component_flow_units='kmol/hr')
    r = tool.update_multicomponent_feed(pressure=1.0, pressure_units='atm')
    assert r['complete'] is False
    assert r['pending_request']['field'] == 'feed_temperature'
