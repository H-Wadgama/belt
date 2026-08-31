"""
Tests for `feed_partial_condensation.py` -- see
`tools/binary-distillation-feed-vapor-liquid.md` Step 16, Tests B-J, and
`tools/binary-distillation-vapor-liquid-dead-end.md` Step 16 (module-level
HX-screen behavior; pipeline-level two-phase routing tests live in
`test_binary_distillation_feed_vapor_liquid.py`).
"""
import biosteam as bst
import pytest

import feed_partial_condensation as fpc
from feed_partial_condensation import (
    LIQUEFACTION_THRESHOLD,
    PHASE_FRACTION_TOLERANCE,
    REFERENCE_TEMPERATURE_K,
    evaluate_vapor_feed_at_reference_temperature,
)


@pytest.fixture
def feed():
    """Butane (Tb ~272.6 K) / Water (Tb ~373.1 K) -- boiling points well on
    either side of the 313.15 K reference temperature, so cooling a vapor
    feed of this pair to 313.15 K at 1 atm produces genuine partial
    condensation (Butane stays vapor, Water condenses)."""
    bst.settings.set_thermo(['Butane', 'Water'], cache=True)
    return bst.Stream('feed', Butane=50, Water=50, units='kmol/hr', P=101325)


@pytest.fixture
def two_phase_feed():
    """Water (Tb ~373.1 K) / Ethanol (Tb ~351.4 K) at 355 K, 1 atm --
    tools/binary-distillation-vapor-liquid-dead-end.md Step 17's worked
    example. Genuinely vapor_liquid (not fully vapor) at these initial feed
    conditions (~25.5 mol% liquid / ~74.5 mol% vapor)."""
    bst.settings.set_thermo(['Water', 'Ethanol'], cache=True)
    return bst.Stream('two_phase_feed', Water=50, Ethanol=50, units='kmol/hr', P=101325)


class FakeOutlet:
    """Stand-in for the `HXutility` outlet MultiStream -- only the
    `imol['g'/'l', ID]` indexing the real function reads is implemented."""

    def __init__(self, mol):
        self.imol = mol


class FakeHX:
    def __init__(self, outlet):
        self.outs = [outlet]

    def simulate(self):
        pass


def _fake_hx_factory(mol):
    def factory(*, ins, T, rigorous=True):
        return FakeHX(FakeOutlet(mol))
    return factory


def _raising_hx_factory(message):
    def factory(*, ins, T, rigorous=True):
        raise RuntimeError(message)
    return factory


# ---------------------------------------------------------------------------
# Test B -- vapor feed hotter than 313.15 K -> cooling.
# ---------------------------------------------------------------------------

def test_hotter_feed_is_cooling(feed):
    result = evaluate_vapor_feed_at_reference_temperature(
        feed, pressure_Pa=101325, initial_temperature_K=405.0,
    )
    assert result['valid'] is True
    assert result['operation'] == 'cooling'


# ---------------------------------------------------------------------------
# Test C -- vapor feed colder than 313.15 K -> heating. Not prohibited merely
# because the device is called a heat exchanger.
# ---------------------------------------------------------------------------

def test_colder_feed_is_heating(feed):
    result = evaluate_vapor_feed_at_reference_temperature(
        feed, pressure_Pa=101325, initial_temperature_K=290.0,
    )
    assert result['valid'] is True
    assert result['operation'] == 'heating'


# ---------------------------------------------------------------------------
# Test D -- exactly 50% liquid must enter the >= 0.50 branch.
# ---------------------------------------------------------------------------

def test_exactly_50_percent_liquid_routes_to_both_pathways(feed, monkeypatch):
    mol = {('g', 'Butane'): 50.0, ('g', 'Water'): 0.0, ('l', 'Butane'): 0.0, ('l', 'Water'): 50.0}
    monkeypatch.setattr(fpc.bst.units, 'HXutility', _fake_hx_factory(mol))

    result = evaluate_vapor_feed_at_reference_temperature(
        feed, pressure_Pa=101325, initial_temperature_K=405.0,
    )
    assert result['valid'] is True
    assert result['liquid_fraction'] == pytest.approx(0.50)
    assert result['route'] == 'liquid_and_vapor_separation_future'
    assert result['implemented'] is False


# ---------------------------------------------------------------------------
# Test E -- more than 50% liquid: both fractions reported, both future
# routes represented, no downstream separator simulated (implemented=False).
# ---------------------------------------------------------------------------

def test_more_than_50_percent_liquid(feed, monkeypatch):
    mol = {('g', 'Butane'): 30.0, ('g', 'Water'): 0.0, ('l', 'Butane'): 20.0, ('l', 'Water'): 50.0}
    monkeypatch.setattr(fpc.bst.units, 'HXutility', _fake_hx_factory(mol))

    result = evaluate_vapor_feed_at_reference_temperature(
        feed, pressure_Pa=101325, initial_temperature_K=405.0,
    )
    assert result['valid'] is True
    assert result['liquid_fraction'] == pytest.approx(0.70)
    assert result['vapor_fraction'] == pytest.approx(0.30)
    assert result['liquid_percent'] == pytest.approx(70.0)
    assert result['vapor_percent'] == pytest.approx(30.0)
    assert result['route'] == 'liquid_and_vapor_separation_future'
    assert result['implemented'] is False


# ---------------------------------------------------------------------------
# Test F -- less than 50% liquid: vapor-phase separation advisable, marked
# unimplemented.
# ---------------------------------------------------------------------------

def test_less_than_50_percent_liquid(feed, monkeypatch):
    mol = {('g', 'Butane'): 50.0, ('g', 'Water'): 30.0, ('l', 'Butane'): 0.0, ('l', 'Water'): 20.0}
    monkeypatch.setattr(fpc.bst.units, 'HXutility', _fake_hx_factory(mol))

    result = evaluate_vapor_feed_at_reference_temperature(
        feed, pressure_Pa=101325, initial_temperature_K=405.0,
    )
    assert result['valid'] is True
    assert result['liquid_fraction'] == pytest.approx(0.20)
    assert result['vapor_fraction'] == pytest.approx(0.80)
    assert result['route'] == 'vapor_separation_advisable'
    assert result['implemented'] is False


# ---------------------------------------------------------------------------
# tools/binary-distillation-condensation-edge-case.md -- complete-condensation
# edge case. Exact 0.0 vapor fraction, a near-zero (within-tolerance) vapor
# fraction, and a just-above-tolerance vapor fraction must all be routed
# correctly, with the exact-equality/tolerance boundary never hard-coded.
# ---------------------------------------------------------------------------

def test_complete_condensation_routes_to_liquid_only(feed, monkeypatch):
    mol = {('g', 'Butane'): 0.0, ('g', 'Water'): 0.0, ('l', 'Butane'): 50.0, ('l', 'Water'): 50.0}
    monkeypatch.setattr(fpc.bst.units, 'HXutility', _fake_hx_factory(mol))

    result = evaluate_vapor_feed_at_reference_temperature(
        feed, pressure_Pa=101325, initial_temperature_K=405.0,
    )
    assert result['valid'] is True
    assert result['liquid_fraction'] == pytest.approx(1.0)
    assert result['vapor_fraction'] == pytest.approx(0.0)
    assert result['route'] == 'liquid_phase_separation'
    assert result['implemented'] is False
    assert 'substantial partial condensation' not in result['message']
    assert 'effectively fully liquid' in result['message']
    assert 'no meaningful vapor phase remains' in result['message'].lower()


def test_near_zero_vapor_fraction_within_tolerance_routes_to_liquid_only(feed, monkeypatch):
    tiny_vapor = 1e-12
    mol = {
        ('g', 'Butane'): tiny_vapor, ('g', 'Water'): 0.0,
        ('l', 'Butane'): 50.0 - tiny_vapor, ('l', 'Water'): 50.0,
    }
    monkeypatch.setattr(fpc.bst.units, 'HXutility', _fake_hx_factory(mol))

    result = evaluate_vapor_feed_at_reference_temperature(
        feed, pressure_Pa=101325, initial_temperature_K=405.0,
    )
    assert result['valid'] is True
    assert result['vapor_fraction'] < PHASE_FRACTION_TOLERANCE
    assert result['route'] == 'liquid_phase_separation'
    assert result['implemented'] is False


def test_just_above_tolerance_vapor_fraction_routes_to_both_pathways(feed, monkeypatch):
    # PHASE_FRACTION_TOLERANCE == 1e-9; 1e-6 total vapor (out of 100 total
    # feed mol) is intentionally well above that tolerance, proving the
    # implementation checks a real numerical boundary rather than depending
    # on exact 0.0.
    small_vapor = 1e-4
    mol = {
        ('g', 'Butane'): small_vapor, ('g', 'Water'): 0.0,
        ('l', 'Butane'): 50.0 - small_vapor, ('l', 'Water'): 50.0,
    }
    monkeypatch.setattr(fpc.bst.units, 'HXutility', _fake_hx_factory(mol))

    result = evaluate_vapor_feed_at_reference_temperature(
        feed, pressure_Pa=101325, initial_temperature_K=405.0,
    )
    assert result['valid'] is True
    assert result['vapor_fraction'] > PHASE_FRACTION_TOLERANCE
    assert result['liquid_fraction'] >= LIQUEFACTION_THRESHOLD
    assert result['route'] == 'liquid_and_vapor_separation_future'


def test_phase_fraction_tolerance_is_a_small_deterministic_constant():
    assert PHASE_FRACTION_TOLERANCE == 1e-9


# ---------------------------------------------------------------------------
# Test H -- the canonical feed passed in must not be mutated by the screen.
# ---------------------------------------------------------------------------

def test_original_feed_unchanged(feed):
    original_T = feed.T
    original_P = feed.P
    original_phase = feed.phase
    original_flows = {ID: float(feed.imol[ID]) for ID in ('Butane', 'Water')}

    evaluate_vapor_feed_at_reference_temperature(
        feed, pressure_Pa=101325, initial_temperature_K=405.0,
    )

    assert feed.T == original_T
    assert feed.P == original_P
    assert feed.phase == original_phase
    assert {ID: float(feed.imol[ID]) for ID in ('Butane', 'Water')} == original_flows


# ---------------------------------------------------------------------------
# Test I -- fraction conservation for every successful screen.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('initial_temperature_K', [290.0, 313.15, 350.0, 405.0])
def test_fraction_conservation(feed, initial_temperature_K):
    result = evaluate_vapor_feed_at_reference_temperature(
        feed, pressure_Pa=101325, initial_temperature_K=initial_temperature_K,
    )
    assert result['valid'] is True
    assert abs(result['liquid_fraction'] + result['vapor_fraction'] - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# Test J -- a BioSTEAM/HX failure returns a deterministic failure dict; no
# route is fabricated.
# ---------------------------------------------------------------------------

def test_biosteam_failure_reported_deterministically(feed, monkeypatch):
    monkeypatch.setattr(fpc.bst.units, 'HXutility', _raising_hx_factory('boom'))

    result = evaluate_vapor_feed_at_reference_temperature(
        feed, pressure_Pa=101325, initial_temperature_K=405.0,
    )
    assert result['valid'] is False
    assert result['error'] == 'reference_temperature_flash_failed'
    assert 'boom' in result['message']
    assert 'route' not in result


# ---------------------------------------------------------------------------
# Defensive checks not in the doc's lettered list, but covering the same
# "handle malformed input deterministically" requirement (Step 5).
# ---------------------------------------------------------------------------

def test_unsupported_component_count():
    bst.settings.set_thermo(['Butane', 'Water', 'Methanol'], cache=True)
    feed3 = bst.Stream('feed3', Butane=30, Water=30, Methanol=30, units='kmol/hr', P=101325)
    result = evaluate_vapor_feed_at_reference_temperature(
        feed3, pressure_Pa=101325, initial_temperature_K=405.0,
    )
    assert result['valid'] is False
    assert result['error'] == 'unsupported_component_count'


def test_zero_flow_handled_deterministically(feed, monkeypatch):
    mol = {('g', 'Butane'): 0.0, ('g', 'Water'): 0.0, ('l', 'Butane'): 0.0, ('l', 'Water'): 0.0}
    monkeypatch.setattr(fpc.bst.units, 'HXutility', _fake_hx_factory(mol))

    result = evaluate_vapor_feed_at_reference_temperature(
        feed, pressure_Pa=101325, initial_temperature_K=405.0,
    )
    assert result['valid'] is False
    assert result['error'] == 'zero_flow'


def test_default_reference_temperature_is_constant(feed):
    result = evaluate_vapor_feed_at_reference_temperature(
        feed, pressure_Pa=101325, initial_temperature_K=405.0,
    )
    assert result['target_temperature_K'] == REFERENCE_TEMPERATURE_K
    assert REFERENCE_TEMPERATURE_K == 313.15
    assert LIQUEFACTION_THRESHOLD == 0.50


# ---------------------------------------------------------------------------
# tools/binary-distillation-vapor-liquid-dead-end.md Step 16 -- this function
# must also work correctly when the feed is already a vapor-liquid mixture
# (not fully vapor) at `initial_temperature_K`, and must condition the whole
# feed rather than only its initial vapor portion.
# ---------------------------------------------------------------------------

def test_two_phase_initial_feed_conditions_the_whole_feed(two_phase_feed):
    """The full component molar flow (both the original vapor and liquid
    portions) must reach the exchanger -- not only the ~74.5 mol% that was
    vapor at the initial 355 K/101325 Pa conditions."""
    result = evaluate_vapor_feed_at_reference_temperature(
        two_phase_feed, pressure_Pa=101325, initial_temperature_K=355.0,
    )
    assert result['valid'] is True
    total_water = result['vapor_mol']['Water'] + result['liquid_mol']['Water']
    total_ethanol = result['vapor_mol']['Ethanol'] + result['liquid_mol']['Ethanol']
    assert total_water == pytest.approx(50.0, abs=1e-6)
    assert total_ethanol == pytest.approx(50.0, abs=1e-6)


def test_two_phase_initial_feed_unchanged(two_phase_feed):
    original_T = two_phase_feed.T
    original_P = two_phase_feed.P
    original_phase = two_phase_feed.phase
    original_flows = {ID: float(two_phase_feed.imol[ID]) for ID in ('Water', 'Ethanol')}

    evaluate_vapor_feed_at_reference_temperature(
        two_phase_feed, pressure_Pa=101325, initial_temperature_K=355.0,
    )

    assert two_phase_feed.T == original_T
    assert two_phase_feed.P == original_P
    assert two_phase_feed.phase == original_phase
    assert {ID: float(two_phase_feed.imol[ID]) for ID in ('Water', 'Ethanol')} == original_flows


@pytest.mark.parametrize('initial_temperature_K', [355.0])
def test_two_phase_initial_feed_fraction_conservation(two_phase_feed, initial_temperature_K):
    result = evaluate_vapor_feed_at_reference_temperature(
        two_phase_feed, pressure_Pa=101325, initial_temperature_K=initial_temperature_K,
    )
    assert result['valid'] is True
    assert abs(result['liquid_fraction'] + result['vapor_fraction'] - 1.0) < 1e-6


def test_two_phase_initial_feed_conditioning_failure_reported_deterministically(two_phase_feed, monkeypatch):
    monkeypatch.setattr(fpc.bst.units, 'HXutility', _raising_hx_factory('boom'))

    result = evaluate_vapor_feed_at_reference_temperature(
        two_phase_feed, pressure_Pa=101325, initial_temperature_K=355.0,
    )
    assert result['valid'] is False
    assert result['error'] == 'reference_temperature_flash_failed'
    assert 'boom' in result['message']
    assert 'route' not in result


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
