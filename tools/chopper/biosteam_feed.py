"""
Deterministic BioSTEAM feed adapter for binary distillation.

See `tools/binary-distillation-feed-phase-evaluation.md` Step 1. Converts
the authoritative, already-normalized workflow state (the output of
`binary_distillation_workflow.assess_binary_distillation_problem()`) into
one `bst.Stream`. This module never invents a component, flow, pressure,
or thermal state -- feed-state normalization (`feed_state.py`) has already
handled every mathematically forced derivation upstream; this module only
transcribes the result into BioSTEAM.

No LLM calls -- this module must never import `ollama` or `openai`.
"""
import biosteam as bst


class BiosteamFeedError(ValueError):
    """Raised when the authoritative workflow state cannot be converted
    into a BioSTEAM feed (not ready, wrong component count, or missing
    a value the calculation layer requires)."""


def build_biosteam_feed(spec, assessment, *, stream_id='feed'):
    """
    Build a `bst.Stream` from an already-`ready_for_calculation`
    workflow assessment.

    Parameters
    ----------
    spec : dict
        The same spec dict passed to `assess_binary_distillation_problem`
        -- used here only to read `pressure_Pa` (the normalized feed state
        in `assessment['feed']` does not carry pressure).
    assessment : dict
        Output of `binary_distillation_workflow.assess_binary_distillation_problem(spec)`.
        Must have `assessment['status'] == 'ready_for_calculation'`.
    stream_id : str, optional
        BioSTEAM unit/stream ID for the constructed feed.

    Returns
    -------
    bst.Stream

    Raises
    ------
    BiosteamFeedError
        If the assessment is not ready, the normalized feed does not have
        exactly 2 components, a component's flow is missing, no flow units
        are available, or `pressure_Pa` is missing from `spec`.
    """
    if assessment.get('status') != 'ready_for_calculation':
        raise BiosteamFeedError(
            "build_biosteam_feed requires assessment['status'] == "
            f"'ready_for_calculation'; got {assessment.get('status')!r}."
        )

    feed_state = assessment.get('feed') or {}
    component_names = list(feed_state.get('component_names') or [])
    if len(component_names) != 2:
        raise BiosteamFeedError(
            f"build_biosteam_feed requires exactly 2 components in the "
            f"normalized feed state; got {len(component_names)}: "
            f"{component_names}."
        )

    component_flows = feed_state.get('component_flows') or {}
    missing_flows = [n for n in component_names if n not in component_flows]
    if missing_flows:
        raise BiosteamFeedError(
            f"Normalized feed state is missing component flow(s) for "
            f"{missing_flows}; cannot build a BioSTEAM feed."
        )

    flow_units = feed_state.get('component_flow_units') or feed_state.get('total_flow_units')
    if flow_units is None:
        raise BiosteamFeedError(
            "Normalized feed state has neither component_flow_units nor "
            "total_flow_units; cannot build a BioSTEAM feed."
        )

    pressure_Pa = spec.get('pressure_Pa')
    if pressure_Pa is None:
        raise BiosteamFeedError(
            "spec['pressure_Pa'] is required to build a BioSTEAM feed."
        )

    bst.settings.set_thermo(component_names, cache=True)

    flows = {name: component_flows[name] for name in component_names}
    feed = bst.Stream(
        stream_id,
        units=flow_units,
        P=pressure_Pa,
        **flows,
    )
    return feed


if __name__ == '__main__':
    import json

    from binary_distillation_workflow import assess_binary_distillation_problem

    spec = {
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
    assessment = assess_binary_distillation_problem(spec)
    print('status:', assessment['status'])
    feed = build_biosteam_feed(spec, assessment)
    feed.show()
    print(json.dumps({ID: float(feed.imol[ID]) for ID in feed.chemicals.IDs}, indent=2))
