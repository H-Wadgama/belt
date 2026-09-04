"""
Tests for `multicomponent_feed_phase.py` -- the T/P-only multicomponent VLE
wrapper. See tools/multicomponent-distillation-feed-phase-plan.md
"Required Tests" (architectural regression) and "Scope Boundaries" (no
enthalpy/quality). Molecular-weight-aware conversion is covered separately
in test_multicomponent_biosteam_feed.py.

Run with:
    pytest tools/chopper/test_multicomponent_feed_phase.py -v
"""
import biosteam as bst
import pytest

from feed_phase import evaluate_feed_phase
from multicomponent_feed_phase import (
    calculate_multicomponent_feed_phase,
    evaluate_multicomponent_feed_phase,
)
from multicomponent_feed_state import apply_user_update, empty_feed_state


@pytest.fixture
def feed3():
    bst.settings.set_thermo(['Water', 'Ethanol', 'Methanol'], cache=True)
    return bst.Stream(
        'feed3', Water=30, Ethanol=40, Methanol=30, units='kmol/hr', P=101325,
    )


@pytest.fixture
def feed5():
    bst.settings.set_thermo(['Water', 'Ethanol', 'Methanol', 'Glycerol', 'Acetone'], cache=True)
    return bst.Stream(
        'feed5', Water=20, Ethanol=20, Methanol=20, Glycerol=20, Acetone=20,
        units='kmol/hr', P=101325,
    )


# --- Three- and five-component feeds both calculate successfully -----------

def test_three_component_feed_TP(feed3):
    result = evaluate_multicomponent_feed_phase(feed3, pressure_Pa=101325, feed_temperature_K=350.0)
    assert result['valid'] is True
    assert result['check'] == 'multicomponent_feed_phase'
    assert set(result['components']) == {'Water', 'Ethanol', 'Methanol'}
    assert 0 <= result['vapor_fraction'] <= 1


def test_five_component_feed_TP(feed5):
    result = evaluate_multicomponent_feed_phase(feed5, pressure_Pa=101325, feed_temperature_K=350.0)
    assert result['valid'] is True
    assert set(result['components']) == {'Water', 'Ethanol', 'Methanol', 'Glycerol', 'Acetone'}


def test_temperature_based_calculation(feed3):
    result = evaluate_multicomponent_feed_phase(feed3, pressure_Pa=101325, feed_temperature_K=350.0)
    assert result['calculation'] == {'type': 'VLE', 'specification': 'T_P'}


# --- Scope boundary: only T/P is exposed, never enthalpy/quality -----------

def test_missing_temperature_rejected(feed3):
    result = evaluate_multicomponent_feed_phase(feed3, pressure_Pa=101325, feed_temperature_K=None)
    assert result['valid'] is False
    assert result['error'] == 'invalid_thermal_specification'


def test_no_quality_or_enthalpy_keyword_accepted(feed3):
    with pytest.raises(TypeError):
        evaluate_multicomponent_feed_phase(feed3, pressure_Pa=101325, feed_quality=0.5)


# --- Component count gate ----------------------------------------------------

def test_below_minimum_component_count_rejected():
    bst.settings.set_thermo(['Water', 'Ethanol'], cache=True)
    feed = bst.Stream('feed2', Water=50, Ethanol=50, units='kmol/hr', P=101325)
    result = evaluate_multicomponent_feed_phase(feed, pressure_Pa=101325, feed_temperature_K=350.0)
    assert result['valid'] is False
    assert result['error'] == 'unsupported_component_count'


# --- Shared-core extraction preserved the binary wrapper's exact result ----

def test_binary_wrapper_still_supports_full_thermal_options():
    """The shared VLE core the multicomponent wrapper reuses must not have
    lost the binary wrapper's own enthalpy/quality support -- only the
    multicomponent wrapper is scope-restricted to T/P."""
    bst.settings.set_thermo(['Water', 'Methanol'], cache=True)
    feed = bst.Stream('feed_bin', Water=50, Methanol=50, units='kmol/hr', P=101325)
    result_T = evaluate_feed_phase(feed, pressure_Pa=101325, feed_temperature_K=350.0)
    assert result_T['valid'] is True
    assert result_T['calculation'] == {'type': 'VLE', 'specification': 'T_P'}

    result_V = evaluate_feed_phase(feed, pressure_Pa=101325, feed_quality=0.4)
    assert result_V['valid'] is True
    assert result_V['calculation'] == {'type': 'VLE', 'specification': 'V_P'}


# --- calculate_multicomponent_feed_phase (full orchestration, incl. degC) ---

def test_calculate_multicomponent_feed_phase_full_state_with_degC():
    state = apply_user_update(empty_feed_state(), {
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30},
        'component_flow_units': 'kmol/hr',
        'pressure': 101.325,
        'pressure_units': 'kPa',
        'feed_temperature': 76.85,
        'feed_temperature_units': 'degC',
    })
    result = calculate_multicomponent_feed_phase(state)
    assert result['valid'] is True
    assert result['temperature_K'] == pytest.approx(350.0, abs=1e-6)
    assert result['pressure_Pa'] == pytest.approx(101325.0, abs=1e-3)


def test_calculate_multicomponent_feed_phase_unbuildable_state_reports_error():
    state = apply_user_update(empty_feed_state(), {
        'component_names': ['Water', 'Ethanol'],
        'component_flows': {'Water': 30, 'Ethanol': 40},
        'component_flow_units': 'kmol/hr',
        'pressure': 1.0, 'pressure_units': 'atm',
    })
    result = calculate_multicomponent_feed_phase(state)
    assert result['valid'] is False
    assert result['error'] == 'feed_build_failed'
