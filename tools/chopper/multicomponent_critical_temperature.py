"""Deterministic feed-temperature versus critical-temperature screening.

This check gates the ordinary-distillation/ideal-liquid Psat path. It does
not participate in, or prevent, the independent feed-phase calculation.
"""
import math

import biosteam as bst


CHECK_NAME = 'multicomponent_critical_temperature'


def _finite_positive(value):
    return (
        isinstance(value, (int, float)) and not isinstance(value, bool)
        and math.isfinite(value) and value > 0
    )


def _empty_result(feed_temperature_K, **overrides):
    result = {
        'check': CHECK_NAME,
        'valid': False,
        'status': 'failed',
        'feed_temperature_K': feed_temperature_K,
        'components': [],
        'violations': [],
        'ordinary_distillation_feasible': None,
        'failures': [],
        'error': None,
        'message': None,
    }
    result.update(overrides)
    return result


def evaluate_critical_temperatures(component_names, feed_temperature_K):
    """Look up every ``chemical.Tc`` and compare it with feed temperature."""
    component_names = list(component_names or [])
    if not component_names:
        return _empty_result(
            feed_temperature_K, error='missing_components',
            message='No feed components were supplied for critical-temperature evaluation.',
        )
    if not _finite_positive(feed_temperature_K):
        return _empty_result(
            feed_temperature_K, error='invalid_temperature',
            message=f'Feed temperature must be a finite positive value in K; got {feed_temperature_K!r}.',
        )

    feed_temperature_K = float(feed_temperature_K)
    try:
        bst.settings.set_thermo(component_names, cache=True)
        chemicals = bst.settings.chemicals
    except Exception as err:
        return _empty_result(
            feed_temperature_K, error='thermo_build_failed', message=str(err),
        )

    components = []
    failures = []
    for name in component_names:
        try:
            critical_temperature_K = chemicals[name].Tc
        except Exception as err:
            failures.append({'component': name, 'reason': str(err)})
            continue
        if not _finite_positive(critical_temperature_K):
            failures.append({
                'component': name,
                'reason': (
                    'critical temperature unavailable or invalid '
                    f'(Tc={critical_temperature_K!r})'
                ),
            })
            continue
        critical_temperature_K = float(critical_temperature_K)
        components.append({
            'component': name,
            'critical_temperature_K': critical_temperature_K,
            'feed_temperature_exceeds_critical': feed_temperature_K > critical_temperature_K,
            'property_source': 'chemical.Tc',
        })

    if failures:
        return _empty_result(
            feed_temperature_K, components=components, failures=failures,
            error='missing_critical_temperature',
            message=(
                'Cannot determine the critical temperature for: '
                + ', '.join(item['component'] for item in failures) + '.'
            ),
        )

    violations = [
        {
            'component': item['component'],
            'feed_temperature_K': feed_temperature_K,
            'critical_temperature_K': item['critical_temperature_K'],
        }
        for item in components if item['feed_temperature_exceeds_critical']
    ]
    feasible = not violations
    return {
        'check': CHECK_NAME,
        'valid': True,
        'status': 'complete',
        'feed_temperature_K': feed_temperature_K,
        'components': components,
        'violations': violations,
        'ordinary_distillation_feasible': feasible,
        'failures': [],
        'error': None,
        'message': None,
    }
