"""
Tests for `multicomponent_biosteam_feed.py` -- the ONLY module in the
multicomponent intake pipeline that performs molecular-weight-aware
canonical conversion to component kmol/hr. See
tools/multicomponent-distillation-feed-phase-plan.md "Canonical
Molar-Flow Conversion" and "Required Tests" items 5-8, 11.

Run with:
    pytest tools/chopper/test_multicomponent_biosteam_feed.py -v
"""
import biosteam as bst
import pytest

from multicomponent_biosteam_feed import (
    MulticomponentBiosteamFeedError,
    build_multicomponent_biosteam_feed,
)


# --- Mode A: direct component flows, all three supported units -------------

def test_direct_kmol_hr_flows():
    state = {
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30},
        'component_flow_units': 'kmol/hr',
        'pressure': 1.0, 'pressure_units': 'atm',
    }
    feed, _ = build_multicomponent_biosteam_feed(state)
    assert feed.imol['Water'] == pytest.approx(30)
    assert feed.imol['Ethanol'] == pytest.approx(40)
    assert feed.imol['Methanol'] == pytest.approx(30)


def test_direct_mol_hr_flows_equivalent_to_kmol_hr():
    state = {
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': 30000, 'Ethanol': 40000, 'Methanol': 30000},
        'component_flow_units': 'mol/hr',
        'pressure': 1.0, 'pressure_units': 'atm',
    }
    feed, _ = build_multicomponent_biosteam_feed(state)
    assert feed.imol['Water'] == pytest.approx(30)
    assert feed.imol['Ethanol'] == pytest.approx(40)
    assert feed.imol['Methanol'] == pytest.approx(30)


def test_direct_kg_hr_flows_convert_via_molecular_weight():
    bst.settings.set_thermo(['Water', 'Ethanol', 'Methanol'], cache=True)
    chemicals = bst.settings.chemicals
    kg_flows = {n: 10 * chemicals[n].MW for n in ('Water', 'Ethanol', 'Methanol')}
    state = {
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': kg_flows,
        'component_flow_units': 'kg/hr',
        'pressure': 1.0, 'pressure_units': 'atm',
    }
    feed, _ = build_multicomponent_biosteam_feed(state)
    assert feed.imol['Water'] == pytest.approx(10, rel=1e-6)
    assert feed.imol['Ethanol'] == pytest.approx(10, rel=1e-6)
    assert feed.imol['Methanol'] == pytest.approx(10, rel=1e-6)


# --- Mode B: total flow + composition, matching basis (no MW needed) -------

def test_total_flow_molar_plus_mole_composition():
    state = {
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'total_flow': 100, 'total_flow_units': 'kmol/hr',
        'composition': {'Water': 0.3, 'Ethanol': 0.4, 'Methanol': 0.3},
        'composition_basis': 'mole',
        'pressure': 1.0, 'pressure_units': 'atm',
    }
    feed, _ = build_multicomponent_biosteam_feed(state)
    assert feed.imol['Water'] == pytest.approx(30)
    assert feed.imol['Ethanol'] == pytest.approx(40)
    assert feed.imol['Methanol'] == pytest.approx(30)


# --- Mode B, cross-basis: the required regression example -------------------

def test_weight_percent_composition_plus_molar_total_flow_regression():
    """tools/multicomponent-distillation-feed-phase-plan.md "Canonical
    Molar-Flow Conversion" regression example: 20/20/60 wt%
    Water/Methanol/Ethanol at a 100 kmol/hr total flow."""
    state = {
        'component_names': ['Water', 'Methanol', 'Ethanol'],
        'total_flow': 100, 'total_flow_units': 'kmol/hr',
        'composition': {'Water': 0.20, 'Methanol': 0.20, 'Ethanol': 0.60},
        'composition_basis': 'mass',
        'pressure': 1.0, 'pressure_units': 'atm',
    }
    feed, _ = build_multicomponent_biosteam_feed(state)
    assert feed.imol['Water'] == pytest.approx(36.56, abs=0.05)
    assert feed.imol['Methanol'] == pytest.approx(20.55, abs=0.05)
    assert feed.imol['Ethanol'] == pytest.approx(42.89, abs=0.05)


def test_mole_percent_composition_plus_mass_total_flow_converts_correctly():
    bst.settings.set_thermo(['Water', 'Ethanol', 'Methanol'], cache=True)
    chemicals = bst.settings.chemicals
    mole_fractions = {'Water': 0.3, 'Ethanol': 0.4, 'Methanol': 0.3}
    mixture_MW = sum(x * chemicals[n].MW for n, x in mole_fractions.items())
    total_kg_hr = 100 * mixture_MW  # 100 kmol/hr worth, expressed as kg/hr

    state = {
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'total_flow': total_kg_hr, 'total_flow_units': 'kg/hr',
        'composition': dict(mole_fractions),
        'composition_basis': 'mole',
        'pressure': 1.0, 'pressure_units': 'atm',
    }
    feed, _ = build_multicomponent_biosteam_feed(state)
    assert feed.imol['Water'] == pytest.approx(30, rel=1e-4)
    assert feed.imol['Ethanol'] == pytest.approx(40, rel=1e-4)
    assert feed.imol['Methanol'] == pytest.approx(30, rel=1e-4)


# --- Errors -------------------------------------------------------------------

def test_below_minimum_components_raises():
    state = {
        'component_names': ['Water', 'Ethanol'],
        'component_flows': {'Water': 30, 'Ethanol': 40},
        'component_flow_units': 'kmol/hr',
        'pressure': 1.0, 'pressure_units': 'atm',
    }
    with pytest.raises(MulticomponentBiosteamFeedError):
        build_multicomponent_biosteam_feed(state)


def test_missing_pressure_raises():
    state = {
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30},
        'component_flow_units': 'kmol/hr',
    }
    with pytest.raises(MulticomponentBiosteamFeedError):
        build_multicomponent_biosteam_feed(state)


def test_incomplete_quantity_specification_raises():
    state = {
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': 30, 'Ethanol': 40},
        'component_flow_units': 'kmol/hr',
        'pressure': 1.0, 'pressure_units': 'atm',
    }
    with pytest.raises(MulticomponentBiosteamFeedError):
        build_multicomponent_biosteam_feed(state)


def test_pressure_converted_to_Pa():
    state = {
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30},
        'component_flow_units': 'kmol/hr',
        'pressure': 1.0, 'pressure_units': 'atm',
    }
    _, pressure_Pa = build_multicomponent_biosteam_feed(state)
    assert pressure_Pa == pytest.approx(101325.0)
