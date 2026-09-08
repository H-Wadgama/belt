"""Ideal-liquid adjacent-pair relative-volatility evaluation.

The normal-boiling-point order is supplied by the deterministic ordering
step and remains an internal prerequisite.  Saturation pressures are
evaluated at the committed feed temperature and relative volatility is
calculated as ``Psat(light) / Psat(heavy)`` for each adjacent pair.

No LLM calls -- this module must never import ``ollama`` or ``openai``.
"""
import math

import biosteam as bst


CHECK_NAME = 'multicomponent_relative_volatility'


def _finite_positive(value):
    return (
        isinstance(value, (int, float)) and not isinstance(value, bool)
        and math.isfinite(value) and value > 0
    )


def _empty_result(temperature_K, **overrides):
    result = {
        'check': CHECK_NAME,
        'valid': False,
        'status': 'failed',
        'temperature_K': temperature_K,
        'ideal_liquid_assumption': True,
        'saturation_pressures': [],
        'adjacent_pairs': [],
        'error': None,
        'message': None,
    }
    result.update(overrides)
    return result


def calculate_adjacent_relative_volatilities(component_names, order_low_to_high, temperature_K):
    """Return component Psat values and adjacent-pair ideal-liquid alphas.

    ``component_names`` controls the saturation-pressure reporting order.
    ``order_low_to_high`` controls which pairs are adjacent and orients each
    pair from the more volatile (lower normal boiling point) component to the
    less volatile component.
    """
    component_names = list(component_names or [])
    order_low_to_high = list(order_low_to_high or [])

    if not _finite_positive(temperature_K):
        return _empty_result(
            temperature_K, error='invalid_temperature',
            message=f'Feed temperature must be a finite positive value in K; got {temperature_K!r}.',
        )
    if (len(component_names) < 2 or len(order_low_to_high) != len(component_names)
            or set(order_low_to_high) != set(component_names)):
        return _empty_result(
            float(temperature_K), error='invalid_component_order',
            message='The internal boiling-point order does not match the feed components.',
        )

    try:
        bst.settings.set_thermo(component_names, cache=True)
        chemicals = bst.settings.chemicals
    except Exception as err:
        return _empty_result(
            float(temperature_K), error='thermo_build_failed', message=str(err),
        )

    psat_by_name = {}
    saturation_pressures = []
    failures = []
    for name in component_names:
        try:
            psat = chemicals[name].Psat(float(temperature_K))
        except Exception as err:
            failures.append({'component': name, 'reason': str(err)})
            continue
        if not _finite_positive(psat):
            failures.append({
                'component': name,
                'reason': f'saturation pressure unavailable or invalid (Psat={psat!r})',
            })
            continue
        psat = float(psat)
        psat_by_name[name] = psat
        saturation_pressures.append({
            'component': name,
            'Psat_Pa': psat,
            'property_source': 'chemical.Psat(T)',
        })

    if failures:
        return _empty_result(
            float(temperature_K), saturation_pressures=saturation_pressures,
            error='missing_saturation_pressure',
            message=(
                f'Cannot determine saturation pressure at {float(temperature_K):g} K for: '
                + ', '.join(f['component'] for f in failures) + '.'
            ),
            failures=failures,
        )

    adjacent_pairs = []
    for more_volatile, less_volatile in zip(order_low_to_high, order_low_to_high[1:]):
        adjacent_pairs.append({
            'more_volatile_component': more_volatile,
            'less_volatile_component': less_volatile,
            'relative_volatility': psat_by_name[more_volatile] / psat_by_name[less_volatile],
            'definition': 'Psat_more_volatile/Psat_less_volatile',
        })

    return {
        'check': CHECK_NAME,
        'valid': True,
        'status': 'complete',
        'temperature_K': float(temperature_K),
        'ideal_liquid_assumption': True,
        'saturation_pressures': saturation_pressures,
        'adjacent_pairs': adjacent_pairs,
        'failures': [],
        'error': None,
        'message': None,
    }
