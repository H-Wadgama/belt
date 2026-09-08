"""
Deterministic normal-boiling-point lookup and ordering for a completed
multicomponent distillation feed.

See tools/multicomponent-distillation-boiling-point-order-plan.md. Once a
feed is complete (see `multicomponent_feed_state.assess_feed_state`),
`multicomponent_feed_tool.advance_feed_state` calls
`calculate_multicomponent_boiling_point_order` here as an internal prerequisite
for adjacent-pair selection. This module never reads
feed quantity, pressure, or temperature -- only the committed component
identity list -- since the "normal" boiling point is defined at ONE fixed
documented reference pressure (`REFERENCE_PRESSURE_PA`, 101325 Pa / 1 atm),
independent of the feed's own operating pressure.

Qwen never supplies, estimates, ranks, or repairs a boiling point -- every
value here comes from the project's ThermoSTEAM/BioSTEAM chemical property
system (`chemical.Tb`, itself defined at the normal-boiling-point reference
pressure), and every failure is returned as a structured result rather than
raised, so a caller can report it without corrupting committed feed state.

No LLM calls -- this module must never import `ollama` or `openai`.
"""
import math

import biosteam as bst

MIN_COMPONENTS = 3
REFERENCE_PRESSURE_PA = 101325.0
CHECK_NAME = 'multicomponent_boiling_point_order'


def _empty_result(**overrides):
    result = {
        'check': CHECK_NAME,
        'valid': False,
        'status': 'failed',
        'reference_pressure_Pa': REFERENCE_PRESSURE_PA,
        'components': [],
        'failures': [],
        'order_low_to_high': [],
        'ties': [],
        'error': None,
        'message': None,
    }
    result.update(overrides)
    return result


def _finite_positive(value):
    return (
        isinstance(value, (int, float)) and not isinstance(value, bool)
        and math.isfinite(value) and value > 0
    )


def calculate_multicomponent_boiling_point_order(component_names):
    """
    Look up each component's normal boiling point (K, at
    `REFERENCE_PRESSURE_PA`) and return them sorted from lowest to highest.

    Parameters
    ----------
    component_names : list[str]
        The feed's committed, nonzero-flow component identities, in their
        established (first-stated) spelling and committed order -- normally
        `feed_state['component_names']` from an already-`ready` state.

    Returns
    -------
    dict
        Always contains 'check', 'valid', 'status', 'reference_pressure_Pa',
        'components', 'failures', 'order_low_to_high', 'ties' -- plus
        'error'/'message' when `valid` is False. `components` lists every
        component that resolved to a usable normal boiling point (even on
        failure, for diagnostics); `failures` lists
        `{'component', 'reason'}` for any that did not. `valid` is True
        only when EVERY given component resolved -- a partial ordering is
        never returned as if it were complete. Ties (exactly equal normal
        boiling points) are reported as
        `{'normal_boiling_point_K', 'components'}` groups; the stable sort
        below preserves `component_names`' committed order within a tie.
    """
    component_names = list(component_names or [])

    if len(component_names) < MIN_COMPONENTS:
        return _empty_result(
            error='unsupported_component_count',
            message=(
                f'calculate_multicomponent_boiling_point_order requires at '
                f'least {MIN_COMPONENTS} components; got '
                f'{len(component_names)}: {component_names}.'
            ),
        )

    try:
        bst.settings.set_thermo(component_names, cache=True)
        chemicals = bst.settings.chemicals
    except Exception as err:
        return _empty_result(error='thermo_build_failed', message=str(err))

    components = []
    failures = []
    for name in component_names:
        try:
            Tb = chemicals[name].Tb
        except Exception as err:
            failures.append({'component': name, 'reason': str(err)})
            continue
        if not _finite_positive(Tb):
            failures.append({
                'component': name,
                'reason': f'normal boiling point unavailable or invalid (Tb={Tb!r})',
            })
            continue
        components.append({
            'component': name,
            'normal_boiling_point_K': float(Tb),
            'property_source': 'chemical.Tb',
        })

    if failures:
        return _empty_result(
            components=components, failures=failures,
            error='missing_boiling_point',
            message=(
                'Cannot determine the normal boiling point for: '
                + ', '.join(f['component'] for f in failures) + '.'
            ),
        )

    # sorted() is stable: components sharing a normal boiling point keep
    # their relative order from component_names (the committed feed order).
    ordered = sorted(components, key=lambda c: c['normal_boiling_point_K'])
    order_low_to_high = [c['component'] for c in ordered]

    groups = {}
    for c in components:
        groups.setdefault(c['normal_boiling_point_K'], []).append(c['component'])
    ties = [
        {'normal_boiling_point_K': Tb_value, 'components': names_at_value}
        for Tb_value, names_at_value in groups.items()
        if len(names_at_value) > 1
    ]

    return {
        'check': CHECK_NAME,
        'valid': True,
        'status': 'complete',
        'reference_pressure_Pa': REFERENCE_PRESSURE_PA,
        'components': components,
        'failures': [],
        'order_low_to_high': order_low_to_high,
        'ties': ties,
        'error': None,
        'message': None,
    }


if __name__ == '__main__':
    import json

    print(json.dumps(
        calculate_multicomponent_boiling_point_order(['Water', 'Ethanol', 'Methanol']),
        indent=2,
    ))
