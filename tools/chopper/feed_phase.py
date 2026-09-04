"""
Deterministic feed-phase (VLE) evaluation for binary distillation.

See `tools/binary-distillation-feed-phase-evaluation.md` Steps 3-8.
Given a canonical BioSTEAM feed (from `biosteam_feed.build_biosteam_feed`)
and the feed's thermal specification, runs the one applicable BioSTEAM VLE
calculation and deterministically classifies the result as liquid, vapor,
or vapor_liquid. The model is never asked to interpret a vapor fraction or
pick which VLE calculation to run -- exactly one branch executes, selected
only by which thermal-condition field is present.

`_run_vle_and_classify` below is the component-count-independent core of
this calculation (see tools/multicomponent-distillation-feed-phase-plan.md
"2. Generic equilibrium calculation") -- `evaluate_feed_phase` wraps it
with the binary (exactly 2 nonzero-flow components) gate;
`multicomponent_feed_phase.evaluate_multicomponent_feed_phase` wraps the
same core with a >=3 components gate. Neither wrapper's public behavior
changed by this extraction.

No LLM calls -- this module must never import `ollama` or `openai`.
"""

_THERMAL_FIELDS = ('feed_temperature_K', 'feed_quality', 'feed_enthalpy_kJ_per_hr')


def _run_vle_and_classify(
    feed, component_names, *, pressure_Pa, feed_temperature_K, feed_quality,
    feed_enthalpy_kJ_per_hr, phase_tolerance, check_name='feed_phase',
):
    """
    Component-count-independent VLE core: runs exactly one BioSTEAM VLE
    specification (T/P, V/P, or H/P -- selected only by which thermal
    argument is not None) on a copy of `feed` and deterministically
    classifies the result. Callers are responsible for validating the
    thermal specification and component count before calling this, and for
    catching any exception it raises.
    """
    equilibrium_feed = feed.copy()

    if feed_temperature_K is not None:
        equilibrium_feed.vle(T=feed_temperature_K, P=pressure_Pa)
        specification = 'T_P'
    elif feed_quality is not None:
        equilibrium_feed.vle(V=feed_quality, P=pressure_Pa)
        specification = 'V_P'
    else:
        equilibrium_feed.vle(H=feed_enthalpy_kJ_per_hr, P=pressure_Pa)
        specification = 'H_P'

    V = float(equilibrium_feed.vapor_fraction)
    if V <= phase_tolerance:
        phase = 'liquid'
    elif V >= 1.0 - phase_tolerance:
        phase = 'vapor'
    else:
        phase = 'vapor_liquid'
    liquid_fraction = 1.0 - V

    vapor_mol = {ID: float(equilibrium_feed.imol['g', ID]) for ID in component_names}
    liquid_mol = {ID: float(equilibrium_feed.imol['l', ID]) for ID in component_names}

    message = {
        'liquid': 'Feed is entirely liquid at the specified feed conditions.',
        'vapor': 'Feed is entirely vapor at the specified feed conditions.',
        'vapor_liquid': 'Feed is a vapor-liquid mixture at the specified feed conditions.',
    }[phase]

    return {
        'check': check_name,
        'valid': True,
        'phase': phase,
        'vapor_fraction': V,
        'liquid_fraction': liquid_fraction,
        'temperature_K': float(equilibrium_feed.T),
        'pressure_Pa': float(pressure_Pa),
        'components': component_names,
        'vapor_mol': vapor_mol,
        'liquid_mol': liquid_mol,
        'calculation': {'type': 'VLE', 'specification': specification},
        'message': message,
    }


def evaluate_feed_phase(
    feed,
    *,
    pressure_Pa,
    feed_temperature_K=None,
    feed_quality=None,
    feed_enthalpy_kJ_per_hr=None,
    phase_tolerance=1e-6,
):
    """
    Deterministically evaluate the equilibrium phase of `feed` at the
    given pressure and thermal condition.

    Parameters
    ----------
    feed : bst.Stream
        A 2-component feed, e.g. from `biosteam_feed.build_biosteam_feed`.
        Never mutated -- a copy is used for the equilibrium calculation.
    pressure_Pa : float
        Column/feed pressure, Pa.
    feed_temperature_K, feed_quality, feed_enthalpy_kJ_per_hr : float, optional
        Exactly one must be given -- the feed's thermal specification.
        Never defaulted (e.g. never silently set to bubble point).
    phase_tolerance : float, optional
        Vapor-fraction tolerance for classifying a result as purely liquid
        or purely vapor rather than vapor_liquid.

    Returns
    -------
    dict
        JSON-friendly result. On success: `{'check', 'valid': True,
        'phase', 'vapor_fraction', 'liquid_fraction', 'temperature_K',
        'pressure_Pa', 'components', 'vapor_mol', 'liquid_mol',
        'calculation', 'message'}`. On failure: `{'check', 'valid': False,
        'error', 'message'}`.
    """
    thermal_values = {
        'feed_temperature_K': feed_temperature_K,
        'feed_quality': feed_quality,
        'feed_enthalpy_kJ_per_hr': feed_enthalpy_kJ_per_hr,
    }
    given = [f for f in _THERMAL_FIELDS if thermal_values[f] is not None]
    if len(given) != 1:
        return {
            'check': 'feed_phase',
            'valid': False,
            'error': 'invalid_thermal_specification',
            'message': (
                'Exactly one of feed_temperature_K, feed_quality, '
                'feed_enthalpy_kJ_per_hr must be given; got '
                f'{len(given)}: {given}.'
            ),
        }

    try:
        component_names = [
            ID for ID in feed.chemicals.IDs if feed.imol[ID] > 1e-9
        ]
        if len(component_names) != 2:
            return {
                'check': 'feed_phase',
                'valid': False,
                'error': 'unsupported_component_count',
                'message': (
                    f'evaluate_feed_phase requires exactly 2 nonzero-flow '
                    f'components; got {len(component_names)}: '
                    f'{component_names}.'
                ),
            }

        return _run_vle_and_classify(
            feed, component_names,
            pressure_Pa=pressure_Pa, feed_temperature_K=feed_temperature_K,
            feed_quality=feed_quality, feed_enthalpy_kJ_per_hr=feed_enthalpy_kJ_per_hr,
            phase_tolerance=phase_tolerance, check_name='feed_phase',
        )
    except Exception as err:
        return {
            'check': 'feed_phase',
            'valid': False,
            'error': 'phase_calculation_failed',
            'message': str(err),
        }


if __name__ == '__main__':
    import biosteam as bst

    bst.settings.set_thermo(['Butane', 'Acetaldehyde'], cache=True)
    feed = bst.Stream('feed', Butane=50, Acetaldehyde=50, units='kmol/hr', P=101325)

    result = evaluate_feed_phase(feed, pressure_Pa=101325, feed_temperature_K=405)
    import json
    print(json.dumps(result, indent=2))
