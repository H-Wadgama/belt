"""
Tests for `feed_phase.py` -- see
`tools/binary-distillation-feed-phase-evaluation.md` Step 11.
"""
import biosteam as bst
import pytest

from feed_phase import evaluate_feed_phase


@pytest.fixture
def feed():
    bst.settings.set_thermo(['Water', 'Methanol'], cache=True)
    return bst.Stream('feed', Water=50, Methanol=50, units='kmol/hr', P=101325)


def test_tp_binary_feed(feed):
    """Test 1 -- binary feed at TP conditions."""
    result = evaluate_feed_phase(feed, pressure_Pa=101325, feed_temperature_K=350.0)
    assert result['valid'] is True
    assert 0 <= result['vapor_fraction'] <= 1
    assert result['phase'] in {'liquid', 'vapor', 'vapor_liquid'}
    assert result['calculation'] == {'type': 'VLE', 'specification': 'T_P'}
    assert set(result['components']) == {'Water', 'Methanol'}


def test_liquid_phase_classification(feed):
    """Test 2 -- conditions well below the bubble point classify as liquid."""
    bp = feed.bubble_point_at_P()
    result = evaluate_feed_phase(feed, pressure_Pa=101325, feed_temperature_K=bp.T - 20)
    assert result['valid'] is True
    assert result['vapor_fraction'] == pytest.approx(0, abs=1e-6)
    assert result['phase'] == 'liquid'


def test_vapor_phase_classification(feed):
    """Test 3 -- conditions well above the dew point classify as vapor."""
    dp = feed.dew_point_at_P()
    result = evaluate_feed_phase(feed, pressure_Pa=101325, feed_temperature_K=dp.T + 20)
    assert result['valid'] is True
    assert result['vapor_fraction'] == pytest.approx(1, abs=1e-6)
    assert result['phase'] == 'vapor'


def test_two_phase_classification(feed):
    """Test 4 -- a temperature strictly between bubble and dew point
    classifies as vapor_liquid."""
    bp = feed.bubble_point_at_P()
    dp = feed.dew_point_at_P()
    T_mid = (bp.T + dp.T) / 2
    result = evaluate_feed_phase(feed, pressure_Pa=101325, feed_temperature_K=T_mid)
    assert result['valid'] is True
    assert 0 < result['vapor_fraction'] < 1
    assert result['phase'] == 'vapor_liquid'


def test_quality_based_state(feed):
    """Test 5 -- feed_quality + pressure_Pa; achieved vapor_fraction matches
    the specified quality."""
    result = evaluate_feed_phase(feed, pressure_Pa=101325, feed_quality=0.5)
    assert result['valid'] is True
    assert result['vapor_fraction'] == pytest.approx(0.5, abs=1e-6)
    assert result['calculation'] == {'type': 'VLE', 'specification': 'V_P'}


def test_invalid_thermal_specification_multiple_given(feed):
    """Test 6 -- more than one thermal-condition field given is rejected."""
    result = evaluate_feed_phase(
        feed, pressure_Pa=101325, feed_temperature_K=350.0, feed_quality=0.5,
    )
    assert result['valid'] is False
    assert result['error'] == 'invalid_thermal_specification'


def test_missing_thermal_specification(feed):
    """Test 7 -- none of the thermal-condition fields given; the function
    must not invent one."""
    result = evaluate_feed_phase(feed, pressure_Pa=101325)
    assert result['valid'] is False
    assert result['error'] == 'invalid_thermal_specification'


def test_unsupported_component_count():
    """Test 8 -- defensive calculation-layer check: more than 2 nonzero-flow
    components passed directly to evaluate_feed_phase is rejected, even
    though the upstream workflow should normally prevent this."""
    bst.settings.set_thermo(['Water', 'Methanol', 'Glycerol'], cache=True)
    feed = bst.Stream('feed3', Water=30, Methanol=30, Glycerol=30, units='kmol/hr', P=101325)
    result = evaluate_feed_phase(feed, pressure_Pa=101325, feed_temperature_K=350.0)
    assert result['valid'] is False
    assert result['error'] == 'unsupported_component_count'


def test_enthalpy_based_state(feed):
    """Enthalpy-pressure phase evaluation -- supported and tested (Step 18)."""
    equilibrium_feed = feed.copy()
    equilibrium_feed.vle(V=0.4, P=101325)
    H = equilibrium_feed.H

    result = evaluate_feed_phase(feed, pressure_Pa=101325, feed_enthalpy_kJ_per_hr=H)
    assert result['valid'] is True
    assert result['calculation'] == {'type': 'VLE', 'specification': 'H_P'}
    assert result['vapor_fraction'] == pytest.approx(0.4, abs=1e-3)
