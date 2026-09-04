"""
Tests for `multicomponent_feed_state.py` -- the deterministic merge/
normalize/validate/completeness layer for multicomponent (>=3 component)
feed intake. See tools/multicomponent-distillation-feed-phase-plan.md
"Tests" items 2, 3, 5, 6, 7 (state-only parts), 8, 11.

Run with:
    pytest tools/chopper/test_multicomponent_feed_state.py -v
"""
import pytest

from multicomponent_feed_state import apply_user_update, assess_feed_state, empty_feed_state


def _assess(*updates):
    state = empty_feed_state()
    for update in updates:
        state = apply_user_update(state, update)
    return assess_feed_state(state)


# --- Component identity -----------------------------------------------------

def test_component_names_only_incomplete():
    """Naming three components alone is not yet a complete feed."""
    result = _assess({'component_names': ['Water', 'Ethanol', 'Methanol']})
    assert result['ready'] is False
    assert result['missing_inputs'][0] == 'feed_quantity'


def test_fewer_than_three_components_remains_incomplete():
    """Test 6 -- fewer than three components never becomes ready, and is
    reported as the first missing thing regardless of what else is given."""
    result = _assess({
        'component_names': ['Water', 'Ethanol'],
        'component_flows': {'Water': 30, 'Ethanol': 40},
        'component_flow_units': 'kmol/hr',
        'pressure': 1.0, 'pressure_units': 'atm',
        'feed_temperature': 350, 'feed_temperature_units': 'K',
    })
    assert result['ready'] is False
    assert result['missing_inputs'] == ['component_names']


def test_add_component_names_appends_without_clearing_quantities():
    result = _assess(
        {'component_names': ['Water', 'Ethanol'], 'component_flows': {'Water': 30}},
        {'add_component_names': ['Methanol']},
    )
    assert result['state']['component_names'] == ['Water', 'Ethanol', 'Methanol']
    assert result['state']['component_flows'] == {'Water': 30}


def test_replacing_component_names_clears_quantities():
    result = _assess(
        {'component_names': ['Water', 'Ethanol', 'Methanol'],
         'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30}},
        {'component_names': ['Butanol', 'Propanol', 'Glycerol']},
    )
    assert result['state']['component_flows'] == {}
    assert result['state']['total_flow'] is None


# --- Test 1 -- direct per-component flows (3 and 5 components) --------------

def test_three_component_flows_complete():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30},
    })
    assert result['state']['total_flow'] == 100
    assert result['state']['total_flow_provenance'] == 'derived'
    assert result['state']['composition'] == {
        'Water': pytest.approx(0.30), 'Ethanol': pytest.approx(0.40), 'Methanol': pytest.approx(0.30),
    }


def test_five_component_flows_complete():
    names = ['A', 'B', 'C', 'D', 'E']
    flows = {'A': 10, 'B': 20, 'C': 30, 'D': 15, 'E': 25}
    result = _assess({'component_names': names, 'component_flows': flows})
    assert result['state']['total_flow'] == 100
    for n, f in flows.items():
        assert result['state']['composition'][n] == pytest.approx(f / 100)


# --- Test 2 -- N-1 mole fractions + total molar flow -------------------------

def test_n_minus_1_mole_fractions_plus_total_flow_derives_last_and_flows():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'total_flow': 100, 'total_flow_units': 'kmol/hr',
        'composition': {'Water': 0.3, 'Ethanol': 0.4},
        'composition_basis': 'mole',
    })
    assert result['state']['composition']['Methanol'] == pytest.approx(0.3)
    assert result['state']['composition_provenance']['Methanol'] == 'derived'
    assert result['state']['component_flows'] == {
        'Water': pytest.approx(30), 'Ethanol': pytest.approx(40), 'Methanol': pytest.approx(30),
    }
    for n in ('Water', 'Ethanol', 'Methanol'):
        assert result['state']['component_flows_provenance'][n] == 'derived'


# --- Test 3 -- N-1 mass fractions + total mass flow --------------------------

def test_n_minus_1_mass_fractions_plus_total_mass_flow_derives_last_and_flows():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Glycerol'],
        'total_flow': 200, 'total_flow_units': 'kg/hr',
        'composition': {'Water': 0.5, 'Ethanol': 0.25},
        'composition_basis': 'mass',
    })
    assert result['state']['composition']['Glycerol'] == pytest.approx(0.25)
    assert result['state']['component_flows'] == {
        'Water': pytest.approx(100), 'Ethanol': pytest.approx(50), 'Glycerol': pytest.approx(50),
    }


# --- Missing units --------------------------------------------------------

def test_missing_flow_units_reported_once_quantity_complete():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30},
    })
    assert 'flow_units' in result['missing_inputs']


def test_missing_pressure_value_and_units():
    state = {
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30},
        'component_flow_units': 'kmol/hr',
    }
    result = _assess(state)
    assert result['missing_inputs'][0] == 'pressure_value'

    result2 = _assess(state, {'pressure': 1.0})
    assert result2['missing_inputs'][0] == 'pressure_units'


# --- Test 5 -- missing composition basis never guessed ----------------------

def test_missing_composition_basis_reported_and_never_guessed():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'total_flow': 100, 'total_flow_units': 'kmol/hr',
        'composition': {'Water': 0.3, 'Ethanol': 0.4},
    })
    assert result['state']['composition_basis'] is None
    assert 'composition_basis' in result['missing_inputs']
    # Basis missing must not block deriving the mathematically forced
    # complementary fraction -- only the basis label itself is unknown.
    assert result['state']['composition']['Methanol'] == pytest.approx(0.3)


# --- Test 7 -- invalid values fail clearly without calculation --------------

def test_negative_flow_is_invalid():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': -10, 'Ethanol': 40, 'Methanol': 30},
    })
    assert result['ready'] is False
    assert any('positive' in e for e in result['validation_errors'])


def test_negative_total_flow_is_invalid():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'total_flow': -50,
    })
    assert any('positive' in e for e in result['validation_errors'])


def test_out_of_range_composition_fraction_is_invalid():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'composition': {'Water': 1.5}, 'composition_basis': 'mole',
    })
    assert any('between 0 and 1' in e for e in result['validation_errors'])


def test_out_of_range_quality_is_invalid():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'feed_quality': 1.5,
    })
    assert any('feed_quality' in e for e in result['validation_errors'])


def test_unsupported_flow_unit_is_invalid():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30},
        'component_flow_units': 'lb/hr',
    })
    assert any('Unsupported flow unit' in e for e in result['validation_errors'])


def test_unsupported_pressure_unit_is_invalid():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'pressure': 1.0, 'pressure_units': 'psi',
    })
    assert any('Unsupported pressure unit' in e for e in result['validation_errors'])


def test_conflicting_redundant_flow_and_total_is_a_conflict():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30},
        'total_flow': 500,
    })
    assert result['ready'] is False
    assert any('sum to' in c for c in result['conflicts'])


def test_all_n_fractions_given_must_sum_to_one():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'composition': {'Water': 0.3, 'Ethanol': 0.3, 'Methanol': 0.3},
        'composition_basis': 'mole',
    })
    assert any('sum to' in c for c in result['conflicts'])


def test_all_n_fractions_given_summing_to_one_is_accepted():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'composition': {'Water': 0.3, 'Ethanol': 0.3, 'Methanol': 0.4},
        'composition_basis': 'mole',
    })
    assert result['conflicts'] == []


# --- Test 8 -- two thermal specifications rejected until resolved -----------

def test_two_thermal_specifications_in_one_call_keeps_only_the_latest():
    """A single update giving two thermal fields at once cannot happen via
    apply_user_update's own mutual-exclusion (each new thermal field clears
    the other two) -- verify that exclusion, and that supplying quality
    after temperature switches cleanly with no lingering invalid state."""
    result = _assess(
        {'component_names': ['Water', 'Ethanol', 'Methanol'],
         'feed_temperature': 350, 'feed_temperature_units': 'K'},
        {'feed_quality': 0.5},
    )
    assert result['state']['feed_temperature'] is None
    assert result['state']['feed_quality'] == 0.5
    assert not any('thermal condition' in e for e in result['validation_errors'])


def test_missing_thermal_condition_reported():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30},
        'component_flow_units': 'kmol/hr',
        'pressure': 1.0, 'pressure_units': 'atm',
    })
    assert 'feed_thermal_condition' in result['missing_inputs']


def test_thermal_units_missing_after_value_given():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30},
        'component_flow_units': 'kmol/hr',
        'pressure': 1.0, 'pressure_units': 'atm',
        'feed_temperature': 350,
    })
    assert result['missing_inputs'][0] == 'feed_temperature_units'


# --- Fully ready state -------------------------------------------------------

def test_fully_specified_three_component_feed_is_ready():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30},
        'component_flow_units': 'kmol/hr',
        'pressure': 1.0, 'pressure_units': 'atm',
        'feed_temperature': 350, 'feed_temperature_units': 'K',
    })
    assert result['ready'] is True
    assert result['missing_inputs'] == []
    assert result['conflicts'] == []
    assert result['validation_errors'] == []


# --- Test 11 -- a correction on a later turn replaces stale derived values --

def test_correction_replaces_stale_derived_value():
    state = empty_feed_state()
    state = apply_user_update(state, {
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30},
    })
    first = assess_feed_state(state)
    assert first['state']['total_flow'] == 100
    assert first['state']['total_flow_provenance'] == 'derived'

    # Correct Ethanol's flow -- total_flow must be RE-derived (not stuck at
    # the stale 100), and the new value must be user_explicit provenance.
    state = apply_user_update(first['state'], {'component_flows': {'Ethanol': 60}})
    second = assess_feed_state(state)
    assert second['state']['component_flows']['Ethanol'] == 60
    assert second['state']['component_flows_provenance']['Ethanol'] == 'user_explicit'
    assert second['state']['total_flow'] == 120
