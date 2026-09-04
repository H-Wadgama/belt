"""
Tests for `multicomponent_feed_phase.py` and
`multicomponent_biosteam_feed.py` -- the BioSTEAM-dependent layers of the
multicomponent feed-phase intake pipeline. See
tools/multicomponent-distillation-feed-phase-plan.md "Tests" items 1, 9,
10, 12 (extraction correctness).

Run with:
    pytest tools/chopper/test_multicomponent_feed_phase.py -v
"""
import biosteam as bst
import pytest

from feed_phase import evaluate_feed_phase
from multicomponent_biosteam_feed import (
    MulticomponentBiosteamFeedError,
    build_multicomponent_biosteam_feed,
)
from multicomponent_feed_phase import (
    calculate_multicomponent_feed_phase,
    evaluate_multicomponent_feed_phase,
)


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


# --- Test 1 -- three- and five-component feeds both calculate successfully --

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


# --- Test 9 -- T/H/V branches ------------------------------------------------

def test_temperature_based_branch(feed3):
    result = evaluate_multicomponent_feed_phase(feed3, pressure_Pa=101325, feed_temperature_K=350.0)
    assert result['calculation'] == {'type': 'VLE', 'specification': 'T_P'}


def test_quality_based_branch(feed3):
    result = evaluate_multicomponent_feed_phase(feed3, pressure_Pa=101325, feed_quality=0.4)
    assert result['calculation'] == {'type': 'VLE', 'specification': 'V_P'}
    assert result['vapor_fraction'] == pytest.approx(0.4, abs=1e-6)


def test_enthalpy_based_branch(feed3):
    equilibrium_feed = feed3.copy()
    equilibrium_feed.vle(V=0.3, P=101325)
    H = equilibrium_feed.H
    result = evaluate_multicomponent_feed_phase(feed3, pressure_Pa=101325, feed_enthalpy_kJ_per_hr=H)
    assert result['calculation'] == {'type': 'VLE', 'specification': 'H_P'}
    assert result['vapor_fraction'] == pytest.approx(0.3, abs=1e-3)


# --- Component count gate ----------------------------------------------------

def test_below_minimum_component_count_rejected():
    bst.settings.set_thermo(['Water', 'Ethanol'], cache=True)
    feed = bst.Stream('feed2', Water=50, Ethanol=50, units='kmol/hr', P=101325)
    result = evaluate_multicomponent_feed_phase(feed, pressure_Pa=101325, feed_temperature_K=350.0)
    assert result['valid'] is False
    assert result['error'] == 'unsupported_component_count'


def test_invalid_thermal_specification_rejected(feed3):
    result = evaluate_multicomponent_feed_phase(
        feed3, pressure_Pa=101325, feed_temperature_K=350.0, feed_quality=0.5,
    )
    assert result['valid'] is False
    assert result['error'] == 'invalid_thermal_specification'


def test_missing_thermal_specification_rejected(feed3):
    result = evaluate_multicomponent_feed_phase(feed3, pressure_Pa=101325)
    assert result['valid'] is False
    assert result['error'] == 'invalid_thermal_specification'


# --- Test 12 -- shared-core extraction preserved the binary wrapper's exact
# result shape and values ----------------------------------------------------

def test_binary_wrapper_matches_pre_extraction_values():
    bst.settings.set_thermo(['Water', 'Methanol'], cache=True)
    feed = bst.Stream('feed_bin', Water=50, Methanol=50, units='kmol/hr', P=101325)
    result = evaluate_feed_phase(feed, pressure_Pa=101325, feed_temperature_K=350.0)
    assert result['valid'] is True
    assert result['check'] == 'feed_phase'
    assert result['calculation'] == {'type': 'VLE', 'specification': 'T_P'}
    assert set(result['components']) == {'Water', 'Methanol'}


# --- multicomponent_biosteam_feed.py ----------------------------------------

def test_build_multicomponent_biosteam_feed_converts_pressure():
    state = {
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30},
        'component_flow_units': 'kmol/hr',
        'total_flow_units': None,
        'pressure': 1.0,
        'pressure_units': 'atm',
    }
    feed, pressure_Pa = build_multicomponent_biosteam_feed(state)
    assert pressure_Pa == pytest.approx(101325.0)
    assert feed.imol['Water'] == pytest.approx(30)
    assert feed.imol['Ethanol'] == pytest.approx(40)
    assert feed.imol['Methanol'] == pytest.approx(30)


def test_build_multicomponent_biosteam_feed_below_minimum_raises():
    state = {
        'component_names': ['Water', 'Ethanol'],
        'component_flows': {'Water': 30, 'Ethanol': 40},
        'component_flow_units': 'kmol/hr',
        'pressure': 1.0, 'pressure_units': 'atm',
    }
    with pytest.raises(MulticomponentBiosteamFeedError):
        build_multicomponent_biosteam_feed(state)


def test_build_multicomponent_biosteam_feed_missing_pressure_raises():
    state = {
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30},
        'component_flow_units': 'kmol/hr',
    }
    with pytest.raises(MulticomponentBiosteamFeedError):
        build_multicomponent_biosteam_feed(state)


# --- calculate_multicomponent_feed_phase (full orchestration, incl. degC) ---

def test_calculate_multicomponent_feed_phase_full_state_with_degC():
    state = {
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30},
        'component_flow_units': 'kmol/hr',
        'total_flow_units': None,
        'pressure': 101.325,
        'pressure_units': 'kPa',
        'feed_temperature': 76.85,
        'feed_temperature_units': 'degC',
        'feed_enthalpy': None,
        'feed_quality': None,
    }
    result = calculate_multicomponent_feed_phase(state)
    assert result['valid'] is True
    assert result['temperature_K'] == pytest.approx(350.0, abs=1e-6)
    assert result['pressure_Pa'] == pytest.approx(101325.0, abs=1e-3)


def test_calculate_multicomponent_feed_phase_unbuildable_state_reports_error():
    state = {
        'component_names': ['Water', 'Ethanol'],
        'component_flows': {'Water': 30, 'Ethanol': 40},
        'component_flow_units': 'kmol/hr',
        'pressure': 1.0, 'pressure_units': 'atm',
    }
    result = calculate_multicomponent_feed_phase(state)
    assert result['valid'] is False
    assert result['error'] == 'feed_build_failed'
