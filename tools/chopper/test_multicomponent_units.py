"""
Tests for `multicomponent_units.py` -- the deterministic unit alias/
conversion registry the multicomponent feed-phase intake pipeline uses.

Run with:
    pytest tools/chopper/test_multicomponent_units.py -v
"""
import pytest

from multicomponent_units import (
    normalize_enthalpy_unit,
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


@pytest.mark.parametrize('raw,expected', [
    ('kJ/hr', 'kJ/hr'), ('kj per hour', 'kJ/hr'),
])
def test_enthalpy_unit_aliases_normalize(raw, expected):
    assert normalize_enthalpy_unit(raw) == expected


def test_enthalpy_unit_unrecognized_returns_none():
    assert normalize_enthalpy_unit('BTU/hr') is None


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
