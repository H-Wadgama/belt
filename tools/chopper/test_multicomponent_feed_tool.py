"""
Tests for `multicomponent_feed_tool.py` -- the single stateful intake-and-
calculate tool the agent exposes. Exercises multi-turn accumulation via
plain function calls (no Ollama involved). See
tools/multicomponent-distillation-feed-phase-plan.md "Tests" items 4, 10.

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
    assert r['pending_request']['field'] == 'feed_temperature_or_feed_enthalpy_or_feed_quality'

    r = tool.update_multicomponent_feed(feed_temperature=350)
    assert r['pending_request']['field'] == 'feed_temperature_units'

    r = tool.update_multicomponent_feed(feed_temperature_units='K')
    assert r['complete'] is True
    assert r['phase'] in {'liquid', 'vapor', 'vapor_liquid'}
    assert 0 <= r['vapor_fraction'] <= 1
    assert set(r.keys()) == {'complete', 'valid', 'phase', 'vapor_fraction', 'liquid_fraction', 'message'}


def test_composition_basis_requested_when_composition_used():
    tool.update_multicomponent_feed(component_names=['Water', 'Ethanol', 'Methanol'])
    r = tool.update_multicomponent_feed(total_flow=100, total_flow_units='kmol/hr',
                                         composition={'Water': 0.3, 'Ethanol': 0.4})
    assert r['pending_request']['field'] == 'composition_basis'
    assert set(r['pending_request']['choices']) == {'mole', 'mass'}


def test_state_remembered_across_calls_no_resend_needed():
    tool.update_multicomponent_feed(component_names=['Water', 'Ethanol', 'Methanol'])
    tool.update_multicomponent_feed(component_flows={'Water': 30, 'Ethanol': 40, 'Methanol': 30})
    tool.update_multicomponent_feed(component_flow_units='kmol/hr')
    tool.update_multicomponent_feed(pressure=1.0, pressure_units='atm')
    r = tool.update_multicomponent_feed(feed_quality=0.5)
    assert r['complete'] is True
    assert r['vapor_fraction'] == pytest.approx(0.5, abs=1e-6)


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
    r = tool.update_multicomponent_feed(feed_quality=0.5)
    assert r['complete'] is False
    assert r['valid'] is False
    assert 'error' in r
