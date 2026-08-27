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
from feed_phase import evaluate_feed_phase


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
        }

    try:
        feed = build_biosteam_feed(spec, assessment)
    except BiosteamFeedError as err:
        return {
            'calculation_performed': False,
            'workflow': assessment,
            'checks': {
                'feed_phase': {
                    'check': 'feed_phase',
                    'valid': False,
                    'error': 'feed_build_failed',
                    'message': str(err),
                },
            },
        }

    phase_result = evaluate_feed_phase(
        feed,
        pressure_Pa=spec['pressure_Pa'],
        feed_temperature_K=spec.get('feed_temperature_K'),
        feed_quality=spec.get('feed_quality'),
        feed_enthalpy_kJ_per_hr=spec.get('feed_enthalpy_kJ_per_hr'),
    )

    return {
        'calculation_performed': True,
        'workflow': assessment,
        'checks': {
            'feed_phase': phase_result,
        },
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
