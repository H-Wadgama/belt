"""
Deterministic feed-phase (VLE) evaluation for multicomponent distillation.

See tools/multicomponent-distillation-context.md and
tools/multicomponent-distillation-feed-phase-plan.md. Thin multicomponent
(>=3 nonzero-flow components) wrapper around the shared VLE core in
`feed_phase._run_vle_and_classify` -- the same underlying calculation the
binary `feed_phase.evaluate_feed_phase` (exactly 2 components) uses. This
wrapper exposes ONLY the T/P (temperature-based) branch of that core --
enthalpy and quality are scope-excluded for the multicomponent agent (see
"Scope Boundaries" in the plan); the shared core itself still supports
them internally for the binary workflow, which is unaffected.

`calculate_multicomponent_feed_phase` is the top-level orchestration entry
point: given an already-`ready` (see
`multicomponent_feed_state.assess_feed_state`) feed state, it builds the
BioSTEAM feed (`multicomponent_biosteam_feed.py`), converts pressure/
temperature to canonical Pa/K, and runs the VLE evaluation below.

No LLM calls -- this module must never import `ollama` or `openai`.
"""
from feed_phase import _run_vle_and_classify
from multicomponent_biosteam_feed import (
    MulticomponentBiosteamFeedError,
    build_multicomponent_biosteam_feed,
)
from multicomponent_units import temperature_to_K

MIN_COMPONENTS = 3


def evaluate_multicomponent_feed_phase(
    feed,
    *,
    pressure_Pa,
    feed_temperature_K,
    phase_tolerance=1e-6,
):
    """
    Deterministically evaluate the equilibrium phase of a >=3-component
    `feed` at the given pressure and temperature. Same contract as
    `feed_phase.evaluate_feed_phase`'s T/P branch, except it requires at
    least MIN_COMPONENTS nonzero-flow components instead of exactly 2, and
    accepts only a temperature -- never enthalpy or quality.

    Parameters
    ----------
    feed : bst.Stream
        A >=3-component feed, e.g. from `build_multicomponent_biosteam_feed`.
        Never mutated -- a copy is used for the equilibrium calculation.
    pressure_Pa : float
        Feed pressure, Pa.
    feed_temperature_K : float
        Feed temperature, K. Required -- never defaulted (e.g. never
        silently set to bubble point).
    phase_tolerance : float, optional
        Vapor-fraction tolerance for classifying a result as purely liquid
        or purely vapor rather than vapor_liquid.

    Returns
    -------
    dict
        Same schema as `feed_phase.evaluate_feed_phase`, with
        `check == 'multicomponent_feed_phase'`.
    """
    if feed_temperature_K is None:
        return {
            'check': 'multicomponent_feed_phase',
            'valid': False,
            'error': 'invalid_thermal_specification',
            'message': (
                'feed_temperature_K must be given; this agent accepts only a '
                'temperature-based feed thermal condition.'
            ),
        }

    try:
        component_names = [
            ID for ID in feed.chemicals.IDs if feed.imol[ID] > 1e-9
        ]
        if len(component_names) < MIN_COMPONENTS:
            return {
                'check': 'multicomponent_feed_phase',
                'valid': False,
                'error': 'unsupported_component_count',
                'message': (
                    f'evaluate_multicomponent_feed_phase requires at least '
                    f'{MIN_COMPONENTS} nonzero-flow components; got '
                    f'{len(component_names)}: {component_names}.'
                ),
            }

        return _run_vle_and_classify(
            feed, component_names,
            pressure_Pa=pressure_Pa, feed_temperature_K=feed_temperature_K,
            feed_quality=None, feed_enthalpy_kJ_per_hr=None,
            phase_tolerance=phase_tolerance, check_name='multicomponent_feed_phase',
        )
    except Exception as err:
        return {
            'check': 'multicomponent_feed_phase',
            'valid': False,
            'error': 'phase_calculation_failed',
            'message': str(err),
        }


def calculate_multicomponent_feed_phase(state):
    """
    Build a BioSTEAM feed from `state` (an already-normalized, `ready`
    multicomponent feed state -- see
    `multicomponent_feed_state.assess_feed_state`) and run the
    deterministic T/P VLE phase evaluation above. Converts pressure and
    the feed temperature to canonical Pa/K via `multicomponent_units`.

    Returns
    -------
    dict
        The `evaluate_multicomponent_feed_phase` result, or
        `{'check': 'multicomponent_feed_phase', 'valid': False,
        'error': 'feed_build_failed', 'message': str}` if the feed itself
        could not be built (see `build_multicomponent_biosteam_feed`).
    """
    try:
        feed, pressure_Pa = build_multicomponent_biosteam_feed(state)
    except Exception as err:
        # Catches both MulticomponentBiosteamFeedError (an incomplete
        # state -- should not normally reach here once the caller has
        # checked assess_feed_state()['ready']) and any exception BioSTEAM
        # itself raises while building the feed, e.g. an unrecognized
        # component name `bst.settings.set_thermo` cannot find
        # thermodynamic data for -- something no pure state-layer
        # validation could have caught in advance.
        return {
            'check': 'multicomponent_feed_phase',
            'valid': False,
            'error': 'feed_build_failed',
            'message': str(err),
        }

    feed_temperature_K = temperature_to_K(
        state['feed_temperature'], state['feed_temperature_units'],
    )

    return evaluate_multicomponent_feed_phase(
        feed, pressure_Pa=pressure_Pa, feed_temperature_K=feed_temperature_K,
    )


if __name__ == '__main__':
    import json

    import biosteam as bst

    bst.settings.set_thermo(['Water', 'Ethanol', 'Methanol'], cache=True)
    feed = bst.Stream(
        'feed', Water=30, Ethanol=40, Methanol=30, units='kmol/hr', P=101325,
    )
    result = evaluate_multicomponent_feed_phase(
        feed, pressure_Pa=101325, feed_temperature_K=360,
    )
    print(json.dumps(result, indent=2))
