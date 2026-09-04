"""
Tests for `multicomponent_grounding.py` -- the deterministic boundary
between a model's proposed feed update and the persistent
`multicomponent_feed_state`, plus read-only query verification. See
tools/multicomponent-distillation-dialogue-robustness-plan.md.

Run with:
    pytest tools/chopper/test_multicomponent_grounding.py -v
"""
from multicomponent_grounding import (
    detect_mixed_composition_basis,
    detect_mixed_flow_units,
    ground_proposed_update,
    ground_query_target_field,
    number_evidence,
    unit_evidence,
)


# --- The plan's exact worked example -----------------------------------------

def test_component_names_and_temperature_grounded_pressure_and_flows_are_not():
    """"separate Ethanol, Methanol, and Water at 335 K" -- component names
    and temperature enter state; a fabricated pressure and fabricated
    component flows the message never stated must be rejected."""
    message = 'separate Ethanol, Methanol, and Water at 335 K'
    proposed = {
        'component_names': ['Ethanol', 'Methanol', 'Water'],
        'feed_temperature': 335,
        'feed_temperature_units': 'K',
        'pressure': 101325,
        'pressure_units': 'Pa',
        'component_flows': {'Ethanol': 30, 'Methanol': 30, 'Water': 40},
    }
    grounded, evidence, rejected = ground_proposed_update(message, proposed)

    assert grounded['component_names'] == ['Ethanol', 'Methanol', 'Water']
    assert grounded['feed_temperature'] == 335
    assert grounded['feed_temperature_units'] == 'K'
    assert 'pressure' not in grounded
    assert 'pressure_units' not in grounded
    assert 'component_flows' not in grounded
    assert 'pressure' in rejected
    assert evidence['feed_temperature'] == '335'


# --- Component identity grounding --------------------------------------------

def test_ungrounded_component_name_rejects_whole_list():
    message = 'separate water and ethanol'
    proposed = {'component_names': ['Water', 'Ethanol', 'Glycerol']}
    grounded, _evidence, rejected = ground_proposed_update(message, proposed)
    assert 'component_names' not in grounded
    assert 'component_names' in rejected


def test_grounded_component_names_case_insensitive():
    message = 'I want to separate WATER, Ethanol, and methanol'
    proposed = {'component_names': ['Water', 'Ethanol', 'Methanol']}
    grounded, _evidence, _rejected = ground_proposed_update(message, proposed)
    assert grounded['component_names'] == ['Water', 'Ethanol', 'Methanol']


def test_component_identity_op_passes_through_only_when_names_ground():
    message = 'also include propanol'
    proposed = {'component_names': ['Propanol'], 'component_identity_op': 'add'}
    grounded, _evidence, _rejected = ground_proposed_update(
        message, proposed, known_component_names=('Water', 'Ethanol'),
    )
    assert grounded['component_names'] == ['Propanol']
    assert grounded['component_identity_op'] == 'add'


# --- Numeric grounding, including percentage transform -----------------------

def test_percentage_token_grounds_its_decimal_fraction():
    message = '20% Water, 40% Ethanol, 40% Methanol'
    proposed = {'composition': {'Water': 0.20, 'Ethanol': 0.40, 'Methanol': 0.40}}
    grounded, evidence, _rejected = ground_proposed_update(message, proposed)
    assert grounded['composition'] == {'Water': 0.20, 'Ethanol': 0.40, 'Methanol': 0.40}
    assert evidence['composition']['Water'] == '20%'


def test_fabricated_numeric_value_rejected_per_entry():
    message = 'Water is 30 kmol/hr'
    proposed = {'component_flows': {'Water': 30, 'Ethanol': 999}}
    grounded, _evidence, rejected = ground_proposed_update(message, proposed)
    assert grounded['component_flows'] == {'Water': 30}
    assert 'component_flows[Ethanol]' in rejected


def test_fabricated_total_flow_rejected():
    message = 'separate water and ethanol and methanol'
    proposed = {'total_flow': 12345}
    grounded, _evidence, rejected = ground_proposed_update(message, proposed)
    assert 'total_flow' not in grounded
    assert 'total_flow' in rejected


# --- Unit grounding ------------------------------------------------------------

def test_unit_grounded_when_alias_present():
    message = 'pressure is 1 atm'
    proposed = {'pressure': 1, 'pressure_units': 'atm'}
    grounded, _evidence, _rejected = ground_proposed_update(message, proposed)
    assert grounded['pressure_units'] == 'atm'


def test_unit_rejected_when_alias_absent():
    message = 'pressure is 1'
    proposed = {'pressure': 1, 'pressure_units': 'atm'}
    grounded, _evidence, rejected = ground_proposed_update(message, proposed)
    assert 'pressure_units' not in grounded
    assert 'pressure_units' in rejected


def test_temperature_unit_never_grounds_pressure_field():
    message = 'the feed is at 335 K'
    proposed = {'pressure_units': 'K'}
    grounded, _evidence, rejected = ground_proposed_update(message, proposed)
    assert 'pressure_units' not in grounded
    assert 'pressure_units' in rejected


# --- composition_basis grounding ---------------------------------------------

def test_composition_basis_grounded_by_explicit_wording():
    message = '20 wt% Water, 30 wt% Ethanol, 50 wt% Methanol'
    proposed = {'composition_basis': 'mass', 'composition': {'Water': 0.2, 'Ethanol': 0.3}}
    grounded, _evidence, _rejected = ground_proposed_update(message, proposed)
    assert grounded['composition_basis'] == 'mass'


def test_composition_basis_rejected_without_explicit_wording():
    message = 'Water is 20%, Ethanol is 30%'
    proposed = {'composition_basis': 'mole'}
    grounded, _evidence, rejected = ground_proposed_update(message, proposed)
    assert 'composition_basis' not in grounded
    assert 'composition_basis' in rejected


# --- Mixed unit / mixed basis detection ---------------------------------------

def test_detect_mixed_flow_units():
    message = 'Water 30 kg/hr, Ethanol 40 mol/hr, Methanol 30 kmol/hr'
    mixed = detect_mixed_flow_units(message)
    assert mixed == {'kg/hr', 'mol/hr', 'kmol/hr'}


def test_single_flow_unit_is_not_mixed():
    message = 'Water 30 kmol/hr, Ethanol 40 kmol/hr, Methanol 30 kmol/hr'
    assert detect_mixed_flow_units(message) == {'kmol/hr'}


def test_kmol_hr_does_not_false_positive_as_mol_hr():
    message = 'total flow is 100 kmol/hr'
    assert detect_mixed_flow_units(message) == {'kmol/hr'}


def test_mixed_component_flow_units_rejects_flow_fields():
    message = 'Water 30 kg/hr, Ethanol 40 mol/hr, Methanol 30 kmol/hr'
    proposed = {
        'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30},
        'component_flow_units': 'kg/hr',
    }
    grounded, _evidence, rejected = ground_proposed_update(message, proposed)
    assert 'component_flow_units' not in grounded
    assert 'component_flow_units' in rejected


def test_detect_mixed_composition_basis():
    message = '20 wt% Water, 40 mol% Ethanol, 40 mol% Methanol'
    mixed = detect_mixed_composition_basis(message)
    assert mixed == {'mass', 'mole'}


def test_single_composition_basis_is_not_mixed():
    message = '20 mol% Water, 40 mol% Ethanol, 40 mol% Methanol'
    assert detect_mixed_composition_basis(message) == {'mole'}


def test_mixed_composition_basis_rejects_composition_and_basis_fields():
    message = '20 wt% Water, 40 mol% Ethanol, 40 mol% Methanol'
    proposed = {
        'composition': {'Water': 0.2, 'Ethanol': 0.4, 'Methanol': 0.4},
        'composition_basis': 'mole',
    }
    grounded, _evidence, rejected = ground_proposed_update(message, proposed)
    assert 'composition' not in grounded
    assert 'composition_basis' not in grounded
    assert 'composition' in rejected
    assert 'composition_basis' in rejected


# --- Evidence-span capture (Section 5/7) --------------------------------------

def test_number_evidence_returns_the_literal_matched_span():
    assert number_evidence(1, 'the pressure is 1') == '1'
    assert number_evidence(0.20, '20% water') == '20%'
    assert number_evidence(5, 'no numbers relevant here except six') is None


def test_unit_evidence_returns_the_literal_alias():
    from multicomponent_units import PRESSURE_UNIT_ALIASES
    assert unit_evidence('atm', 'pressure is 1 atm', PRESSURE_UNIT_ALIASES) == 'atm'
    assert unit_evidence('atm', 'pressure is 1', PRESSURE_UNIT_ALIASES) is None


# --- Two identical values for two different components stay independent -----

def test_identical_numeric_values_for_different_components_both_ground():
    message = 'Water is 30 kmol/hr and Ethanol is 30 kmol/hr'
    proposed = {'component_flows': {'Water': 30, 'Ethanol': 30}}
    grounded, evidence, _rejected = ground_proposed_update(message, proposed)
    assert grounded['component_flows'] == {'Water': 30, 'Ethanol': 30}
    assert evidence['component_flows'] == {'Water': '30', 'Ethanol': '30'}


# --- Read-only query verification ("verify questions too") -------------------

def test_query_target_field_confirmed_when_named_in_message():
    assert ground_query_target_field('what is the feed pressure?', 'pressure') is True


def test_query_target_field_rejected_when_not_named_in_message():
    """The model claiming target_field='pressure' for a message that never
    mentions pressure must not be trusted -- confirm before answering."""
    assert ground_query_target_field('what is the total flow?', 'pressure') is False


def test_query_target_field_rejected_for_unregistered_field():
    assert ground_query_target_field('what is the pressure?', 'not_a_real_field') is False


def test_query_target_field_temperature_aliases():
    assert ground_query_target_field('what temperature did I give?', 'feed_temperature') is True
    assert ground_query_target_field('what is the pressure?', 'feed_temperature') is False
