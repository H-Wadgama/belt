"""
Tests for `multicomponent_feed_state.py` -- the deterministic merge/
normalize/validate/completeness/transaction layer for multicomponent
(>=3 component) feed intake. See
tools/multicomponent-distillation-dialogue-robustness-plan.md.

Run with:
    pytest tools/chopper/test_multicomponent_feed_state.py -v
"""
import pytest

from multicomponent_feed_state import (
    apply_user_update,
    assess_candidate_transition,
    assess_feed_state,
    empty_feed_state,
    record_unit,
    record_value,
    shared_component_flow_unit,
)


def _assess(*updates):
    state = empty_feed_state()
    for update in updates:
        state = apply_user_update(state, update)
    return assess_feed_state(state)


def _msgs(issues):
    return [i['message'] for i in issues]


# --- Component identity -----------------------------------------------------

def test_component_names_only_incomplete():
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
        {'component_names': ['Methanol'], 'component_identity_op': 'add'},
    )
    assert result['state']['component_names'] == ['Water', 'Ethanol', 'Methanol']
    assert record_value(result['state']['component_flows']['Water']) == 30


def test_redundant_restatement_of_same_component_names_does_not_clear_quantities():
    """A tool-calling model cannot be relied on to omit already-known facts
    on every turn -- redundantly restating the SAME identity set (even in a
    different order) must never wipe out quantities already established."""
    result = _assess(
        {'component_names': ['Water', 'Ethanol', 'Methanol'],
         'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30}},
        {'component_names': ['Methanol', 'Water', 'Ethanol']},
    )
    assert record_value(result['state']['component_flows']['Water']) == 30
    assert record_value(result['state']['total_flow']) == 100


def test_explicit_replace_clears_quantities():
    result = _assess(
        {'component_names': ['Water', 'Ethanol', 'Methanol'],
         'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30}},
        {'component_names': ['Butanol', 'Propanol', 'Glycerol'], 'component_identity_op': 'replace'},
    )
    assert result['state']['component_flows'] == {}
    assert result['state']['total_flow'] is None
    assert result['state']['component_names'] == ['Butanol', 'Propanol', 'Glycerol']


def test_unclassified_differing_set_is_silently_ignored_not_a_replace():
    """Section 6: a differing component set with NO explicit
    component_identity_op is never treated as a replacement -- this is the
    state layer's defense-in-depth backstop (the conversation layer is
    expected to turn this into a clarification before it ever gets here)."""
    state = apply_user_update(empty_feed_state(), {
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30},
    })
    state = apply_user_update(state, {'component_names': ['Methanol']})
    assert state['component_names'] == ['Water', 'Ethanol', 'Methanol']
    assert record_value(state['component_flows']['Water']) == 30


def test_explicit_remove_drops_component_and_its_quantities():
    state = apply_user_update(empty_feed_state(), {
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30},
    })
    state = apply_user_update(state, {'component_names': ['Methanol'], 'component_identity_op': 'remove'})
    assert state['component_names'] == ['Water', 'Ethanol']
    assert 'Methanol' not in state['component_flows']
    assert record_value(state['component_flows']['Water']) == 30


def test_initialize_only_applies_to_empty_state():
    state = apply_user_update(empty_feed_state(), {
        'component_names': ['Water', 'Ethanol', 'Methanol'], 'component_identity_op': 'initialize',
    })
    assert state['component_names'] == ['Water', 'Ethanol', 'Methanol']
    # A second 'initialize' with a different set on an already-populated
    # identity must not silently apply (only 'replace' can change identity
    # once established).
    state2 = apply_user_update(state, {
        'component_names': ['Propanol', 'Butanol', 'Glycerol'], 'component_identity_op': 'initialize',
    })
    assert state2['component_names'] == ['Water', 'Ethanol', 'Methanol']


# --- Direct per-component flows (3 and 5 components) ------------------------

def test_three_component_flows_complete():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30},
    })
    assert record_value(result['state']['total_flow']) == 100
    assert result['state']['total_flow']['provenance'] == 'derived'
    composition = {n: record_value(r) for n, r in result['state']['composition'].items()}
    assert composition == {
        'Water': pytest.approx(0.30), 'Ethanol': pytest.approx(0.40), 'Methanol': pytest.approx(0.30),
    }


def test_five_component_flows_complete():
    names = ['A', 'B', 'C', 'D', 'E']
    flows = {'A': 10, 'B': 20, 'C': 30, 'D': 15, 'E': 25}
    result = _assess({'component_names': names, 'component_flows': flows})
    assert record_value(result['state']['total_flow']) == 100
    for n, f in flows.items():
        assert record_value(result['state']['composition'][n]) == pytest.approx(f / 100)


# --- N-1 fractions + total flow, matching basis (no MW needed) -------------

def test_n_minus_1_mole_fractions_plus_total_flow_derives_last_and_flows():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'total_flow': 100, 'total_flow_units': 'kmol/hr',
        'composition': {'Water': 0.3, 'Ethanol': 0.4},
        'composition_basis': 'mole',
    })
    comp = result['state']['composition']
    assert record_value(comp['Methanol']) == pytest.approx(0.3)
    assert comp['Methanol']['provenance'] == 'derived'
    flows = {n: record_value(r) for n, r in result['state']['component_flows'].items()}
    assert flows == {
        'Water': pytest.approx(30), 'Ethanol': pytest.approx(40), 'Methanol': pytest.approx(30),
    }
    for n in ('Water', 'Ethanol', 'Methanol'):
        assert result['state']['component_flows'][n]['provenance'] == 'derived'


def test_n_minus_1_mass_fractions_plus_total_mass_flow_derives_last_and_flows():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Glycerol'],
        'total_flow': 200, 'total_flow_units': 'kg/hr',
        'composition': {'Water': 0.5, 'Ethanol': 0.25},
        'composition_basis': 'mass',
    })
    assert record_value(result['state']['composition']['Glycerol']) == pytest.approx(0.25)
    flows = {n: record_value(r) for n, r in result['state']['component_flows'].items()}
    assert flows == {
        'Water': pytest.approx(100), 'Ethanol': pytest.approx(50), 'Glycerol': pytest.approx(50),
    }


def test_five_component_n_minus_1_fractions_derive_last():
    result = _assess({
        'component_names': ['A', 'B', 'C', 'D', 'E'],
        'total_flow': 100, 'total_flow_units': 'kmol/hr',
        'composition': {'A': 0.1, 'B': 0.2, 'C': 0.3, 'D': 0.15},
        'composition_basis': 'mole',
    })
    assert record_value(result['state']['composition']['E']) == pytest.approx(0.25)
    assert record_value(result['state']['component_flows']['E']) == pytest.approx(25)


# --- Composition-basis inference (Composition-Basis Rules 3-4) --------------

def test_bare_composition_plus_kmol_hr_total_infers_mole_basis():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'total_flow': 100, 'total_flow_units': 'kmol/hr',
        'composition': {'Water': 0.3, 'Ethanol': 0.4},
    })
    assert record_value(result['state']['composition_basis']) == 'mole'
    assert result['state']['composition_basis']['provenance'] == 'inferred_from_total_flow_units'
    assert 'composition_basis' not in result['missing_inputs']
    assert record_value(result['state']['composition']['Methanol']) == pytest.approx(0.3)
    assert record_value(result['state']['component_flows']['Methanol']) == pytest.approx(30)


def test_bare_composition_plus_kg_hr_total_infers_mass_basis():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'total_flow': 100, 'total_flow_units': 'kg/hr',
        'composition': {'Water': 0.3, 'Ethanol': 0.4},
    })
    assert record_value(result['state']['composition_basis']) == 'mass'
    assert result['state']['composition_basis']['provenance'] == 'inferred_from_total_flow_units'


def test_bare_composition_without_flow_units_yet_asks_for_flow_units():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'total_flow': 100,
        'composition': {'Water': 0.3, 'Ethanol': 0.4},
    })
    assert result['state']['composition_basis'] is None
    assert result['missing_inputs'][0] == 'flow_units'


def test_explicit_basis_overrides_flow_unit_inference():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'total_flow': 100, 'total_flow_units': 'kmol/hr',
        'composition': {'Water': 0.2, 'Ethanol': 0.2},
        'composition_basis': 'mass',
    })
    assert record_value(result['state']['composition_basis']) == 'mass'
    assert result['state']['composition_basis']['provenance'] == 'user_explicit'
    assert 'Water' not in result['state']['component_flows']


def test_correction_to_flow_units_re_infers_basis():
    state = empty_feed_state()
    state = apply_user_update(state, {
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'total_flow': 100, 'total_flow_units': 'kmol/hr',
        'composition': {'Water': 0.3, 'Ethanol': 0.4},
    })
    first = assess_feed_state(state)
    assert record_value(first['state']['composition_basis']) == 'mole'

    corrected = apply_user_update(first['state'], {'total_flow_units': 'kg/hr'})
    second = assess_feed_state(corrected)
    assert record_value(second['state']['composition_basis']) == 'mass'
    assert second['state']['composition_basis']['provenance'] == 'inferred_from_total_flow_units'


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
    assert any('positive' in m for m in _msgs(result['validation_errors']))


def test_negative_total_flow_is_invalid():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'total_flow': -50,
    })
    assert any('positive' in m for m in _msgs(result['validation_errors']))


def test_out_of_range_composition_fraction_is_invalid():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'composition': {'Water': 1.5}, 'composition_basis': 'mole',
    })
    assert any('between 0 and 1' in m for m in _msgs(result['validation_errors']))


def test_nonpositive_pressure_is_invalid():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'pressure': 0.0, 'pressure_units': 'atm',
    })
    assert any('pressure must be positive' in m for m in _msgs(result['validation_errors']))


def test_temperature_below_absolute_zero_is_invalid():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'feed_temperature': -300, 'feed_temperature_units': 'degC',
    })
    assert any('absolute zero' in m for m in _msgs(result['validation_errors']))


def test_non_finite_flow_is_invalid():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': float('nan'), 'Ethanol': 40, 'Methanol': 30},
    })
    assert any('finite' in m for m in _msgs(result['validation_errors']))


def test_unsupported_flow_unit_is_invalid():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30},
        'component_flow_units': 'lb/hr',
    })
    assert any('Unsupported flow unit' in m for m in _msgs(result['validation_errors']))


def test_unsupported_pressure_unit_is_invalid():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'pressure': 1.0, 'pressure_units': 'psi',
    })
    assert any('Unsupported pressure unit' in m for m in _msgs(result['validation_errors']))


def test_conflicting_redundant_flow_and_total_is_a_conflict():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30},
        'total_flow': 500,
    })
    assert result['ready'] is False
    assert any('sum to' in m for m in _msgs(result['conflicts']))
    assert all(c['group'] == 'quantity' for c in result['conflicts'])


def test_all_n_fractions_given_must_sum_to_one():
    result = _assess({
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'composition': {'Water': 0.3, 'Ethanol': 0.3, 'Methanol': 0.3},
        'composition_basis': 'mole',
    })
    assert any('sum to' in m for m in _msgs(result['conflicts']))


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
    assert record_value(first['state']['total_flow']) == 100
    assert first['state']['total_flow']['provenance'] == 'derived'

    state = apply_user_update(first['state'], {'component_flows': {'Ethanol': 60}})
    second = assess_feed_state(state)
    assert record_value(second['state']['component_flows']['Ethanol']) == 60
    assert second['state']['component_flows']['Ethanol']['provenance'] == 'user_explicit'
    assert record_value(second['state']['total_flow']) == 120


# --- Per-measurement units and provenance (Section 7) ------------------------

def test_partial_component_flows_preserve_individual_units_and_evidence():
    state = apply_user_update(empty_feed_state(), {
        'component_names': ['Methanol', 'Ethanol', 'Water'],
    }, turn_number=1)
    state = apply_user_update(state, {
        'component_flows': {'Methanol': 30}, 'component_flow_units': 'kg/hr',
    }, turn_number=2, evidence={'component_flows': {'Methanol': '30 kg/hr'}})
    record = state['component_flows']['Methanol']
    assert record['value'] == 30
    assert record['unit'] == 'kg/hr'
    assert record['source_turn'] == 2
    assert record['evidence'] == '30 kg/hr'


def test_cross_turn_conflicting_units_surface_without_reinterpreting_prior_values():
    state = apply_user_update(empty_feed_state(), {'component_names': ['Methanol', 'Ethanol', 'Water']})
    state = apply_user_update(state, {'component_flows': {'Methanol': 30}, 'component_flow_units': 'kg/hr'})
    state = apply_user_update(state, {
        'component_flows': {'Water': 50, 'Ethanol': 20}, 'component_flow_units': 'kmol/hr',
    })
    # Neither prior value is silently reinterpreted -- both remain exactly
    # as given, in their own units.
    assert record_value(state['component_flows']['Methanol']) == 30
    assert record_unit(state['component_flows']['Methanol']) == 'kg/hr'
    assert record_value(state['component_flows']['Water']) == 50
    assert record_unit(state['component_flows']['Water']) == 'kmol/hr'
    assert shared_component_flow_unit(state) is None

    result = assess_feed_state(state)
    assert any('more than one unit' in m for m in _msgs(result['conflicts']))


def test_complete_common_unit_restatement_atomically_replaces_conflicted_group():
    state = apply_user_update(empty_feed_state(), {'component_names': ['Methanol', 'Ethanol', 'Water']})
    state = apply_user_update(state, {'component_flows': {'Methanol': 30}, 'component_flow_units': 'kg/hr'})
    state = apply_user_update(state, {'component_flows': {'Water': 50}, 'component_flow_units': 'kmol/hr'})
    assert shared_component_flow_unit(state) is None

    # A complete restatement of all three, in one shared unit, in one call.
    state = apply_user_update(state, {
        'component_flows': {'Methanol': 30, 'Ethanol': 20, 'Water': 50},
        'component_flow_units': 'kmol/hr',
    })
    assert shared_component_flow_unit(state) == 'kmol/hr'
    result = assess_feed_state(state)
    assert result['conflicts'] == []


def test_shared_component_flow_unit_none_until_units_agree():
    state = apply_user_update(empty_feed_state(), {
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': 30},
    })
    assert shared_component_flow_unit(state) is None
    state = apply_user_update(state, {'component_flow_units': 'kmol/hr'})
    assert shared_component_flow_unit(state) == 'kmol/hr'


def test_unit_only_answer_completes_a_pending_measurement():
    state = apply_user_update(empty_feed_state(), {'pressure': 1})
    assert state['pressure']['status'] == 'awaiting_unit'
    assert record_unit(state['pressure']) is None
    state = apply_user_update(state, {'pressure_units': 'atm'})
    assert state['pressure']['status'] == 'complete'
    assert record_value(state['pressure']) == 1
    assert record_unit(state['pressure']) == 'atm'


# --- Transactional candidate/commit (Section 8) -------------------------------

def test_independent_groups_commit_while_a_conflicting_group_is_rejected():
    state = apply_user_update(empty_feed_state(), {'component_names': ['Water', 'Ethanol', 'Methanol']})
    checked_facts = {
        'pressure': 1, 'pressure_units': 'atm',
        'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30},
        'component_flow_units': 'kmol/hr',
        'total_flow': 999, 'total_flow_units': 'kmol/hr',  # deliberately wrong sum
    }
    transition = assess_candidate_transition(state, checked_facts, turn_number=2)
    assert transition['accepted_groups'] == ['pressure']
    assert 'quantity' in transition['rejected_groups']
    assert record_value(transition['committed_state']['pressure']) == 1
    assert transition['committed_state']['component_flows'] == {}


def test_rejected_candidate_leaves_previously_committed_state_unchanged():
    state = apply_user_update(empty_feed_state(), {
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'pressure': 1, 'pressure_units': 'atm',
    })
    transition = assess_candidate_transition(state, {'pressure': -5}, turn_number=2)
    assert 'pressure' in transition['rejected_groups']
    assert record_value(transition['committed_state']['pressure']) == 1


def test_identity_and_quantity_groups_commit_together_in_order():
    state = empty_feed_state()
    checked_facts = {
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30},
        'component_flow_units': 'kmol/hr',
    }
    transition = assess_candidate_transition(state, checked_facts, turn_number=1)
    assert transition['accepted_groups'] == ['identity', 'quantity']
    assert transition['committed_state']['component_names'] == ['Water', 'Ethanol', 'Methanol']
    assert record_value(transition['committed_state']['component_flows']['Water']) == 30


def test_empty_checked_facts_is_a_no_op():
    state = apply_user_update(empty_feed_state(), {'component_names': ['Water', 'Ethanol', 'Methanol']})
    transition = assess_candidate_transition(state, {}, turn_number=2)
    assert transition['accepted_groups'] == []
    assert transition['rejected_groups'] == {}
    assert transition['committed_state']['component_names'] == ['Water', 'Ethanol', 'Methanol']
