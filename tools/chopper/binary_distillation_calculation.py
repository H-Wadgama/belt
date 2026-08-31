"""
Deterministic calculation-pipeline entry point for binary distillation.

See `tools/binary-distillation-feed-phase-evaluation.md` Step 9. Chains
the existing workflow-only checker (`binary_distillation_workflow.py`) with
the new BioSTEAM feed adapter (`biosteam_feed.py`) and feed-phase evaluator
(`feed_phase.py`): a calculation only ever runs once the workflow reports
`status == 'ready_for_calculation'`.

This is a separate downstream layer from the workflow-only agent -- see
that module's docstring and `tools/binary-distillation-feed-phase-evaluation.md`
Step 10. `binary_distillation_workflow_agent.py` must never import this
module or anything it imports.

No LLM calls -- this module must never import `ollama` or `openai`.
"""
from binary_distillation_workflow import assess_binary_distillation_problem
from biosteam_feed import BiosteamFeedError, build_biosteam_feed
from feed_partial_condensation import (
    REFERENCE_TEMPERATURE_K,
    evaluate_vapor_feed_at_reference_temperature,
)
from feed_phase import evaluate_feed_phase

# tools/binary-distillation-whats-next.md Step 2 -- stable, machine-readable
# calculation-step IDs. Only STEP_FEED_PHASE and STEP_VAPOR_CONDENSATION_SCREEN
# are executable today; the rest are recognized future steps so
# calculation-progress reporting has something stable to name even before
# they're implemented.
STEP_FEED_PHASE = 'feed_phase'

# tools/binary-distillation-feed-vapor-liquid.md Step 12 -- deterministic
# post-feed-phase routing steps. STEP_VAPOR_CONDENSATION_SCREEN is the only
# one of these that actually runs BioSTEAM; the separation-pathway steps are
# recognized-but-not-implemented endpoints this pipeline intentionally stops
# at (see that doc's "Expected architecture after this change").
STEP_VAPOR_CONDENSATION_SCREEN = 'vapor_condensation_screen'
STEP_LIQUID_PHASE_SEPARATION = 'liquid_phase_separation'
STEP_VAPOR_PHASE_SEPARATION = 'vapor_phase_separation'
STEP_TWO_PHASE_ROUTING = 'two_phase_feed_routing'

# Reserved for once a Wankat Case A-D design step (case_design.py) is wired
# into this pipeline -- not reachable today, since post-feed-phase routing
# (below) always stops at a separation-pathway step first.
STEP_CASE_A_DESIGN = 'case_A_design'
STEP_CASE_B_DESIGN = 'case_B_design'
STEP_CASE_C_DESIGN = 'case_C_design'
STEP_CASE_D_DESIGN = 'case_D_design'


def build_calculation_progress(*, assessment, checks):
    """
    Deterministically derive calculation-progress state from an already-
    computed workflow `assessment` and `checks` dict -- see
    tools/binary-distillation-whats-next.md Step 3. Never asks the LLM what
    has been completed; every field here is derived from `assessment`/
    `checks` alone.

    Parameters
    ----------
    assessment : dict
        The `assess_binary_distillation_problem(spec)` result. Must have
        `status == 'ready_for_calculation'` -- callers with an earlier
        status build the `workflow_not_ready` progress dict directly (Step
        5), never through this function.
    checks : dict
        The `checks` dict `calculate_binary_distillation_problem` is about
        to return, e.g. `{'feed_phase': <result dict>}`.

    Returns
    -------
    dict
        `{'completed_steps', 'next_step', 'next_step_available',
        'remaining_steps', 'remaining_outputs', 'blocked_reason',
        'message'}`.
    """
    feed_phase = checks.get('feed_phase')
    feed_phase_ok = isinstance(feed_phase, dict) and feed_phase.get('valid') is True

    completed_steps = [STEP_FEED_PHASE] if feed_phase_ok else []

    # Reserved for when a downstream design/separation step actually ships.
    next_step = None
    next_step_available = False

    if not feed_phase_ok:
        if feed_phase is not None:
            # The workflow was ready_for_calculation, but the feed-phase
            # check itself failed to run (e.g. feed_build_failed) -- this is
            # a calculation failure, never a missing-input situation, so it
            # must not be reported as needing new inputs.
            blocked_reason = 'calculation_failed'
            message = (
                'The feed-phase calculation did not complete: '
                f"{feed_phase.get('message') or feed_phase.get('error') or 'unknown error'}"
            )
        else:
            blocked_reason = 'not_started'
            message = 'No calculation has been performed for the current binary-distillation problem yet.'
        return {
            'completed_steps': completed_steps,
            'next_step': next_step,
            'next_step_available': next_step_available,
            'remaining_steps': [],
            'remaining_outputs': [],
            'blocked_reason': blocked_reason,
            'message': message,
        }

    # tools/binary-distillation-feed-vapor-liquid.md Step 12 -- once
    # feed-phase evaluation itself succeeded, deterministic routing (not the
    # old case-design assumption) determines what remains. Every branch here
    # is an intentionally unimplemented downstream pathway -- see that doc's
    # "Expected architecture after this change".
    phase = feed_phase['phase']
    routing = checks.get('routing')

    if phase == 'liquid':
        remaining_steps = [STEP_LIQUID_PHASE_SEPARATION]
        blocked_reason = 'not_implemented'
        message = (routing or {}).get('message') or 'Feed-phase evaluation is complete.'
    elif phase == 'vapor':
        screen = checks.get('vapor_condensation_screen')
        if isinstance(screen, dict) and screen.get('valid'):
            completed_steps.append(STEP_VAPOR_CONDENSATION_SCREEN)
            if screen['route'] == 'liquid_and_vapor_separation_future':
                remaining_steps = [STEP_LIQUID_PHASE_SEPARATION, STEP_VAPOR_PHASE_SEPARATION]
            else:
                remaining_steps = [STEP_VAPOR_PHASE_SEPARATION]
            blocked_reason = 'not_implemented'
            message = screen['message']
        else:
            # The workflow/feed-phase check succeeded, but the reference-
            # temperature screen itself failed -- a calculation failure, not
            # a missing-input situation.
            remaining_steps = []
            blocked_reason = 'calculation_failed'
            error_detail = (screen or {}).get('message') or (screen or {}).get('error') or 'unknown error'
            message = f'The reference-temperature vapor-condensation screen did not complete: {error_detail}'
    elif phase == 'vapor_liquid':
        remaining_steps = [STEP_TWO_PHASE_ROUTING]
        blocked_reason = 'not_implemented'
        message = (routing or {}).get('message') or 'Feed-phase evaluation is complete.'
    else:
        # Defensive -- evaluate_feed_phase only ever returns one of the
        # three phases above when valid=True.
        remaining_steps = []
        blocked_reason = None
        message = 'Feed-phase evaluation is complete.'

    # No `would_calculate`-equivalent output list exists yet for any of
    # these not-yet-implemented separation pathways.
    remaining_outputs = []

    return {
        'completed_steps': completed_steps,
        'next_step': next_step,
        'next_step_available': next_step_available,
        'remaining_steps': remaining_steps,
        'remaining_outputs': remaining_outputs,
        'blocked_reason': blocked_reason,
        'message': message,
    }


def _liquid_phase_routing_result():
    """tools/binary-distillation-feed-vapor-liquid.md Step 10 -- an initial
    liquid feed stops immediately; the HX reference-temperature screen is
    never called for this branch."""
    return {
        'valid': True,
        'check': 'routing',
        'route': 'liquid_phase_separation',
        'implemented': False,
        'message': (
            'The feed is liquid at the specified feed conditions. It should '
            'proceed to the liquid-phase separation pathway. Liquid-phase '
            'separation calculations are not implemented in this pipeline yet.'
        ),
    }


def _two_phase_routing_result(phase_result):
    """tools/binary-distillation-feed-vapor-liquid.md Step 11 -- an initially
    two-phase feed is reported with its already-known liquid/vapor fractions,
    but is not routed further."""
    return {
        'valid': True,
        'check': 'routing',
        'route': 'two_phase_feed',
        'implemented': False,
        'liquid_fraction': phase_result['liquid_fraction'],
        'vapor_fraction': phase_result['vapor_fraction'],
        'message': (
            'The feed is already a vapor-liquid mixture at the specified '
            'feed conditions. Routing of an initially two-phase feed is not '
            'implemented yet.'
        ),
    }


def calculate_binary_distillation_problem(spec):
    """
    Run the deterministic calculation pipeline for a binary-distillation
    problem spec: assess the workflow state, and -- only once it is
    `ready_for_calculation` -- build a canonical BioSTEAM feed and
    evaluate its equilibrium phase.

    Parameters
    ----------
    spec : dict
        Same accumulated problem spec understood by
        `binary_distillation_workflow.assess_binary_distillation_problem`.

    Returns
    -------
    dict
        `{'calculation_performed': bool, 'workflow': <assessment dict>,
        'checks': {'feed_phase': <result dict>}}`. `checks` is empty when
        `calculation_performed` is False (the workflow was not yet ready).
        Structured so additional deterministic checks (relative_volatility,
        azeotrope, thermal_stability, condensability,
        critical_temperature_margin, ...) can be added alongside
        `feed_phase` later without changing this shape.
    """
    assessment = assess_binary_distillation_problem(spec)

    if assessment['status'] != 'ready_for_calculation':
        return {
            'calculation_performed': False,
            'workflow': assessment,
            'checks': {},
            'calculation_progress': {
                'completed_steps': [],
                'next_step': None,
                'next_step_available': False,
                'remaining_steps': [],
                'remaining_outputs': [],
                'blocked_reason': 'workflow_not_ready',
                'message': assessment['message'],
            },
        }

    try:
        feed = build_biosteam_feed(spec, assessment)
    except BiosteamFeedError as err:
        checks = {
            'feed_phase': {
                'check': 'feed_phase',
                'valid': False,
                'error': 'feed_build_failed',
                'message': str(err),
            },
        }
        return {
            'calculation_performed': False,
            'workflow': assessment,
            'checks': checks,
            'calculation_progress': build_calculation_progress(assessment=assessment, checks=checks),
        }

    phase_result = evaluate_feed_phase(
        feed,
        pressure_Pa=spec['pressure_Pa'],
        feed_temperature_K=spec.get('feed_temperature_K'),
        feed_quality=spec.get('feed_quality'),
        feed_enthalpy_kJ_per_hr=spec.get('feed_enthalpy_kJ_per_hr'),
    )
    checks = {'feed_phase': phase_result}

    # tools/binary-distillation-feed-vapor-liquid.md Steps 7-11 -- routing is
    # decided here, deterministically, from `phase_result['phase']` alone.
    # The LLM never sees this branch; it only ever explains whichever
    # structured result comes back.
    if phase_result.get('valid'):
        phase = phase_result['phase']

        if phase == 'liquid':
            checks['routing'] = _liquid_phase_routing_result()

        elif phase == 'vapor':
            screen_result = evaluate_vapor_feed_at_reference_temperature(
                feed,
                pressure_Pa=spec['pressure_Pa'],
                initial_temperature_K=phase_result['temperature_K'],
                reference_temperature_K=REFERENCE_TEMPERATURE_K,
            )
            checks['vapor_condensation_screen'] = screen_result
            if screen_result.get('valid'):
                checks['routing'] = {
                    'valid': True,
                    'check': 'routing',
                    'route': screen_result['route'],
                    'implemented': False,
                    'liquid_fraction': screen_result['liquid_fraction'],
                    'vapor_fraction': screen_result['vapor_fraction'],
                    'liquid_percent': screen_result['liquid_percent'],
                    'vapor_percent': screen_result['vapor_percent'],
                    'message': screen_result['message'],
                }

        elif phase == 'vapor_liquid':
            checks['routing'] = _two_phase_routing_result(phase_result)

    return {
        'calculation_performed': True,
        'workflow': assessment,
        'checks': checks,
        'calculation_progress': build_calculation_progress(assessment=assessment, checks=checks),
    }


if __name__ == '__main__':
    import json

    INCOMPLETE_SPEC = {'component_names': ['Butane', 'Acetaldehyde']}
    COMPLETE_SPEC = {
        'component_names': ['Butane', 'Acetaldehyde'],
        'component_flows': {'Butane': 50, 'Acetaldehyde': 50},
        'component_flow_units': 'kmol/hr',
        'pressure_Pa': 101325,
        'feed_temperature_K': 405,
        'reflux_condition': 'saturated_liquid',
        'Lr': 0.99, 'Hr': 0.99,
        'external_reflux_ratio_LD': 5.0,
        'use_optimum_feed_plate': True,
    }

    print('--- Incomplete spec ---')
    result = calculate_binary_distillation_problem(INCOMPLETE_SPEC)
    print(f"calculation_performed: {result['calculation_performed']}")
    print(f"workflow status: {result['workflow']['status']}")
    print()

    print('--- Complete spec ---')
    result = calculate_binary_distillation_problem(COMPLETE_SPEC)
    print(f"calculation_performed: {result['calculation_performed']}")
    print(json.dumps(result['checks']['feed_phase'], indent=2))
    print(json.dumps(result['calculation_progress'], indent=2))
