"""
Tests for `multicomponent_feed_state.py` -- the deterministic merge/
normalize/validate/completeness layer for multicomponent (>=3 component)
feed intake. See tools/multicomponent-distillation-feed-phase-plan.md
"Required Tests" items 1-4, 10, 12-19 (state-only parts).

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


def test_redundant_restatement_of_same_component_names_does_not_clear_quantities():
    """A tool-calling model cannot be relied on to omit already-known facts
    on every turn -- redundantly restating the SAME identity set (even in a
    different order) must never wipe out quantities already established."""
    result = _assess(
        {'component_names': ['Water', 'Ethanol', 'Methanol'],
         'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30}},
        {'component_names': ['Methanol', 'Water', 'Ethanol']},
    )
    assert result['state']['component_flows'] == {'Water': 30, 'Ethanol': 40, 'Methanol': 30}
    assert result['state']['total_flow'] == 100


def test_replacing_component_names_clears_quantities():
    result = _assess(
        {'component_names': ['Water', 'Ethanol', 'Methanol'],
         'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30}},
        {'component_names': ['Butanol', 'Propanol', 'Glycerol']},
    )
    assert result['state']['component_flows'] == {}
    assert result['state']['total_flow'] is None


# --- Direct per-component flows (3 and 5 components) ------------------------

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


# --- N-1 fractions + total flow, matching basis (no MW needed) -------------

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


def test_five_component_n_minus_1_fractions_derive_last():
    result = _assess({
        'component_names': ['A', 'B', 'C', 'D', 'E'],
        'total_flow': 100, 'total_flow_units': 'kmol/hr',
        'composition': {'A': 0.1, 'B': 0.2, 'C': 0.3, 'D': 0.15},
        'composition_basis': 'mole',
    })
    assert result['state']['composition']['E'] == pytest.approx(0.25)
    assert result['state']['component_flows']['E'] == pytest.approx(25)


# --- Composition-basis inference (Composition-Basis Rules 3-4) --------------

def test_bare_composition_plus_kmol_hr_total_infers_mole_basis():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'total_flow': 100, 'total_flow_units': 'kmol/hr',
        'composition': {'Water': 0.3, 'Ethanol': 0.4},
    })
    assert result['state']['composition_basis'] == 'mole'
    assert result['state']['composition_basis_provenance'] == 'inferred_from_total_flow_units'
    assert 'composition_basis' not in result['missing_inputs']
    # Basis inference must not block deriving the mathematically forced
    # complementary fraction and, since the basis matches kmol/hr's natural
    # basis, the component flows too.
    assert result['state']['composition']['Methanol'] == pytest.approx(0.3)
    assert result['state']['component_flows']['Methanol'] == pytest.approx(30)


def test_bare_composition_plus_kg_hr_total_infers_mass_basis():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'total_flow': 100, 'total_flow_units': 'kg/hr',
        'composition': {'Water': 0.3, 'Ethanol': 0.4},
    })
    assert result['state']['composition_basis'] == 'mass'
    assert result['state']['composition_basis_provenance'] == 'inferred_from_total_flow_units'


def test_bare_composition_without_flow_units_yet_asks_for_flow_units():
    """No total-flow units known yet -- basis inference is deferred, and the
    next question is for flow units, not composition basis (plan:
    "the next question is for total-flow units... infer the basis and
    continue without a redundant basis question")."""
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'total_flow': 100,
        'composition': {'Water': 0.3, 'Ethanol': 0.4},
    })
    assert result['state']['composition_basis'] is None
    assert result['missing_inputs'][0] == 'flow_units'


def test_explicit_basis_overrides_flow_unit_inference():
    """Explicit wt% composition against a molar total flow keeps the
    explicit mass basis -- never silently reinterpreted as mole basis just
    because the total flow is molar."""
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'total_flow': 100, 'total_flow_units': 'kmol/hr',
        'composition': {'Water': 0.2, 'Ethanol': 0.2},
        'composition_basis': 'mass',
    })
    assert result['state']['composition_basis'] == 'mass'
    assert result['state']['composition_basis_provenance'] == 'user_explicit'
    # Cross-basis (mass composition, molar total) -- component_flows are
    # NOT derivable without molecular weights, so feed_state correctly
    # leaves them undetermined; multicomponent_biosteam_feed.py handles it.
    assert 'Water' not in result['state']['component_flows']


def test_correction_to_flow_units_re_infers_basis():
    """A later correction to total_flow_units must re-infer the basis, not
    leave the OLD inferred basis stale (Test 18)."""
    state = empty_feed_state()
    state = apply_user_update(state, {
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'total_flow': 100, 'total_flow_units': 'kmol/hr',
        'composition': {'Water': 0.3, 'Ethanol': 0.4},
    })
    first = assess_feed_state(state)
    assert first['state']['composition_basis'] == 'mole'

    corrected = apply_user_update(first['state'], {'total_flow_units': 'kg/hr'})
    second = assess_feed_state(corrected)
    assert second['state']['composition_basis'] == 'mass'
    assert second['state']['composition_basis_provenance'] == 'inferred_from_total_flow_units'


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


# --- Invalid values fail clearly without calculation -------------------------

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


def test_nonpositive_pressure_is_invalid():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'pressure': 0.0, 'pressure_units': 'atm',
    })
    assert any('pressure must be positive' in e for e in result['validation_errors'])


def test_temperature_below_absolute_zero_is_invalid():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'feed_temperature': -300, 'feed_temperature_units': 'degC',
    })
    assert any('absolute zero' in e for e in result['validation_errors'])


def test_non_finite_flow_is_invalid():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': float('nan'), 'Ethanol': 40, 'Methanol': 30},
    })
    assert any('finite' in e for e in result['validation_errors'])


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


# --- Temperature: the only thermal input, never enthalpy/quality -----------

def test_no_enthalpy_or_quality_fields_exist():
    state = empty_feed_state()
    assert 'feed_enthalpy' not in state
    assert 'feed_quality' not in state


def test_missing_thermal_condition_reported():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30},
        'component_flow_units': 'kmol/hr',
        'pressure': 1.0, 'pressure_units': 'atm',
    })
    assert 'feed_temperature_value' in result['missing_inputs']


def test_thermal_units_missing_after_value_given():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30},
        'component_flow_units': 'kmol/hr',
        'pressure': 1.0, 'pressure_units': 'atm',
        'feed_temperature': 350,
    })
    assert result['missing_inputs'][0] == 'feed_temperature_units'


# --- Fully ready state; missing-input order ----------------------------------

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


def test_missing_input_order_names_then_quantity_then_units_then_pressure_then_temperature():
    assert _assess({}).get('missing_inputs') != []
    assert _assess({}).get('missing_inputs', ['x'])[0] == 'component_names'
    assert _assess({'component_names': ['Water', 'Ethanol', 'Methanol']}
                    )['missing_inputs'][0] == 'feed_quantity'
    assert _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30},
    })['missing_inputs'][0] == 'flow_units'
    assert _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30},
        'component_flow_units': 'kmol/hr',
    })['missing_inputs'][0] == 'pressure_value'


# --- Correction replaces stale derived values --------------------------------

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
