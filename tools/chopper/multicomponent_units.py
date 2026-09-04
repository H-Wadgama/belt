"""
Deterministic unit alias/conversion registry for the multicomponent
feed-phase intake agent.

See tools/multicomponent-distillation-context.md ("Initially Supported
Units") and tools/multicomponent-distillation-feed-phase-plan.md
("Supported Units"). Every accepted unit alias and every physical
conversion used anywhere in the multicomponent intake pipeline lives here,
in one place -- no other module should hardcode a conversion factor or an
alias spelling. An unrecognized alias normalizes to None so callers can
report it as unsupported rather than guessing.

Enthalpy is intentionally NOT supported here -- the multicomponent plan
accepts only a temperature-based feed thermal condition (see
tools/multicomponent-distillation-feed-phase-plan.md "Scope Boundaries").
The shared binary VLE core (`feed_phase.py`) still accepts enthalpy/quality
internally, but nothing in the multicomponent pipeline may propose them.

No BioSTEAM calls and no LLM calls -- pure data/functions.
"""

FLOW_UNIT_ALIASES = {
    'kmol/hr': 'kmol/hr', 'kmol/h': 'kmol/hr', 'kmol per hr': 'kmol/hr',
    'kmol per hour': 'kmol/hr', 'kilomol/hr': 'kmol/hr',
    'kilomole/hr': 'kmol/hr', 'kilomole per hour': 'kmol/hr',
    'kilomoles per hour': 'kmol/hr', 'kilomoles/hr': 'kmol/hr',

    'mol/hr': 'mol/hr', 'mol/h': 'mol/hr', 'mol per hr': 'mol/hr',
    'mol per hour': 'mol/hr', 'mole/hr': 'mol/hr', 'moles/hr': 'mol/hr',
    'moles per hour': 'mol/hr',

    'kg/hr': 'kg/hr', 'kg/h': 'kg/hr', 'kg per hr': 'kg/hr',
    'kg per hour': 'kg/hr', 'kilogram per hour': 'kg/hr',
    'kilograms per hour': 'kg/hr', 'kilograms/hr': 'kg/hr',
}
SUPPORTED_FLOW_UNITS = ('kmol/hr', 'mol/hr', 'kg/hr')

# tools/multicomponent-distillation-feed-phase-plan.md "Canonical
# Molar-Flow Conversion" step 4 -- which SUPPORTED_FLOW_UNITS are molar vs.
# mass, used both for the mass<->mole composition-basis inference rule and
# for the MW-aware canonical conversion in multicomponent_biosteam_feed.py.
MOLAR_FLOW_UNITS = ('kmol/hr', 'mol/hr')
MASS_FLOW_UNITS = ('kg/hr',)

PRESSURE_UNIT_ALIASES = {
    'pa': 'Pa', 'pascal': 'Pa', 'pascals': 'Pa',
    'kpa': 'kPa', 'kilopascal': 'kPa', 'kilopascals': 'kPa',
    'bar': 'bar', 'bars': 'bar',
    'atm': 'atm', 'atmosphere': 'atm', 'atmospheres': 'atm',
}
SUPPORTED_PRESSURE_UNITS = ('Pa', 'kPa', 'bar', 'atm')
_PRESSURE_TO_PA = {'Pa': 1.0, 'kPa': 1000.0, 'bar': 1e5, 'atm': 101325.0}

TEMPERATURE_UNIT_ALIASES = {
    'k': 'K', 'kelvin': 'K',
    'degc': 'degC', 'c': 'degC', 'celsius': 'degC', 'degrees c': 'degC',
    'degrees celsius': 'degC', 'deg c': 'degC', '°c': 'degC',
}
SUPPORTED_TEMPERATURE_UNITS = ('K', 'degC')


def _normalize(raw, alias_table):
    if raw is None:
        return None
    return alias_table.get(str(raw).strip().lower())


def normalize_flow_unit(raw):
    """Map a flow-unit phrasing to one of SUPPORTED_FLOW_UNITS, or None if unrecognized."""
    return _normalize(raw, FLOW_UNIT_ALIASES)


def normalize_pressure_unit(raw):
    """Map a pressure-unit phrasing to one of SUPPORTED_PRESSURE_UNITS, or None if unrecognized."""
    return _normalize(raw, PRESSURE_UNIT_ALIASES)


def normalize_temperature_unit(raw):
    """Map a temperature-unit phrasing to one of SUPPORTED_TEMPERATURE_UNITS, or None if unrecognized."""
    return _normalize(raw, TEMPERATURE_UNIT_ALIASES)


def flow_unit_basis(canonical_flow_unit):
    """'mole' for a molar SUPPORTED_FLOW_UNITS value, 'mass' for a mass one, else None."""
    if canonical_flow_unit in MOLAR_FLOW_UNITS:
        return 'mole'
    if canonical_flow_unit in MASS_FLOW_UNITS:
        return 'mass'
    return None


def is_molar_flow_unit(canonical_flow_unit):
    return canonical_flow_unit in MOLAR_FLOW_UNITS


def is_mass_flow_unit(canonical_flow_unit):
    return canonical_flow_unit in MASS_FLOW_UNITS


def pressure_to_Pa(value, unit):
    """Convert `value` (in `unit`, any supported pressure unit/alias) to Pa."""
    canonical = normalize_pressure_unit(unit)
    if canonical is None:
        raise ValueError(f'Unsupported pressure unit: {unit!r}')
    return value * _PRESSURE_TO_PA[canonical]


def temperature_to_K(value, unit):
    """Convert `value` (in `unit`, any supported temperature unit/alias) to K."""
    canonical = normalize_temperature_unit(unit)
    if canonical is None:
        raise ValueError(f'Unsupported temperature unit: {unit!r}')
    return value + 273.15 if canonical == 'degC' else value
