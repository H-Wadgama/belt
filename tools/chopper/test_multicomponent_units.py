"""
Tests for `multicomponent_units.py` -- the deterministic unit alias/
conversion registry the multicomponent feed-phase intake pipeline uses.
Enthalpy is intentionally not supported here (see "Scope Boundaries" in
tools/multicomponent-distillation-feed-phase-plan.md) -- there are no
enthalpy tests in this file.

Run with:
    pytest tools/chopper/test_multicomponent_units.py -v
"""
import pytest

from multicomponent_units import (
    flow_unit_basis,
    is_mass_flow_unit,
    is_molar_flow_unit,
    normalize_flow_unit,
    normalize_pressure_unit,
    normalize_temperature_unit,
    pressure_to_Pa,
    temperature_to_K,
)


@pytest.mark.parametrize('raw,expected', [
    ('kmol/hr', 'kmol/hr'), ('KMOL/HR', 'kmol/hr'), ('kmol per hour', 'kmol/hr'),
    ('kilomoles per hour', 'kmol/hr'),
    ('mol/hr', 'mol/hr'), ('mol per hr', 'mol/hr'),
    ('kg/hr', 'kg/hr'), ('kilograms per hour', 'kg/hr'),
])
def test_flow_unit_aliases_normalize(raw, expected):
    assert normalize_flow_unit(raw) == expected


def test_flow_unit_unrecognized_returns_none():
    assert normalize_flow_unit('lb/hr') is None
    assert normalize_flow_unit(None) is None


@pytest.mark.parametrize('raw,expected', [
    ('Pa', 'Pa'), ('pascal', 'Pa'),
    ('kPa', 'kPa'), ('kilopascals', 'kPa'),
    ('bar', 'bar'), ('BAR', 'bar'),
    ('atm', 'atm'), ('atmosphere', 'atm'), ('atmospheres', 'atm'),
])
def test_pressure_unit_aliases_normalize(raw, expected):
    assert normalize_pressure_unit(raw) == expected


def test_pressure_unit_unrecognized_returns_none():
    assert normalize_pressure_unit('psi') is None


@pytest.mark.parametrize('raw,expected', [
    ('K', 'K'), ('kelvin', 'K'),
    ('degC', 'degC'), ('C', 'degC'), ('Celsius', 'degC'), ('degrees C', 'degC'),
])
def test_temperature_unit_aliases_normalize(raw, expected):
    assert normalize_temperature_unit(raw) == expected


def test_temperature_unit_unrecognized_returns_none():
    assert normalize_temperature_unit('F') is None


def test_pressure_to_Pa_conversions():
    assert pressure_to_Pa(1.0, 'Pa') == pytest.approx(1.0)
    assert pressure_to_Pa(1.0, 'kPa') == pytest.approx(1000.0)
    assert pressure_to_Pa(1.0, 'bar') == pytest.approx(1e5)
    assert pressure_to_Pa(1.0, 'atm') == pytest.approx(101325.0)


def test_pressure_to_Pa_unsupported_unit_raises():
    with pytest.raises(ValueError):
        pressure_to_Pa(1.0, 'psi')


def test_temperature_to_K_conversions():
    assert temperature_to_K(300.0, 'K') == pytest.approx(300.0)
    assert temperature_to_K(25.0, 'degC') == pytest.approx(298.15)


def test_temperature_to_K_unsupported_unit_raises():
    with pytest.raises(ValueError):
        temperature_to_K(100.0, 'F')


# --- Molar/mass flow-unit basis helpers (Composition-Basis Rules 3-4) -------

def test_flow_unit_basis_molar_units():
    assert flow_unit_basis('kmol/hr') == 'mole'
    assert flow_unit_basis('mol/hr') == 'mole'


def test_flow_unit_basis_mass_units():
    assert flow_unit_basis('kg/hr') == 'mass'


def test_flow_unit_basis_unrecognized_returns_none():
    assert flow_unit_basis('lb/hr') is None
    assert flow_unit_basis(None) is None


def test_is_molar_and_mass_flow_unit():
    assert is_molar_flow_unit('kmol/hr') is True
    assert is_molar_flow_unit('mol/hr') is True
    assert is_molar_flow_unit('kg/hr') is False
    assert is_mass_flow_unit('kg/hr') is True
    assert is_mass_flow_unit('kmol/hr') is False
