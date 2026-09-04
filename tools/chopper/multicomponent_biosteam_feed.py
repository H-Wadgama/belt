"""
Deterministic BioSTEAM feed adapter for multicomponent distillation.

Mirrors `biosteam_feed.py`, generalized to any number (>=MIN_COMPONENTS)
of components. Converts an already-`ready`
`multicomponent_feed_state.assess_feed_state()` state into one
`bst.Stream` -- never invents a component, flow, or pressure; every value
transcribed here must already be present in `state`. Pressure is
converted to Pa here via `multicomponent_units.pressure_to_Pa`, since the
canonical feed state stores pressure in whatever unit the user gave, not
in Pa.

No LLM calls -- this module must never import `ollama` or `openai`.
"""
import biosteam as bst

from multicomponent_units import pressure_to_Pa

MIN_COMPONENTS = 3


class MulticomponentBiosteamFeedError(ValueError):
    """Raised when a feed state cannot be converted into a BioSTEAM feed
    (not ready, too few components, or missing a value the calculation
    layer requires)."""


def build_multicomponent_biosteam_feed(state, *, stream_id='multicomponent_feed'):
    """
    Build a `bst.Stream` from a normalized multicomponent feed state.

    Parameters
    ----------
    state : dict
        A `multicomponent_feed_state`-shaped dict, normally the `'state'`
        entry of an `assess_feed_state()` result whose `'ready']` is True.
    stream_id : str, optional
        BioSTEAM unit/stream ID for the constructed feed.

    Returns
    -------
    (bst.Stream, float)
        The constructed feed stream, and the feed pressure already
        converted to Pa (so callers don't need to re-derive it).

    Raises
    ------
    MulticomponentBiosteamFeedError
        If `state` has fewer than MIN_COMPONENTS components, a component
        is missing its flow, no flow units are available, or pressure/
        its units are missing.
    """
    component_names = list(state.get('component_names') or [])
    if len(component_names) < MIN_COMPONENTS:
        raise MulticomponentBiosteamFeedError(
            f'build_multicomponent_biosteam_feed requires at least '
            f'{MIN_COMPONENTS} components; got {len(component_names)}: '
            f'{component_names}.'
        )

    component_flows = state.get('component_flows') or {}
    missing_flows = [n for n in component_names if n not in component_flows]
    if missing_flows:
        raise MulticomponentBiosteamFeedError(
            f'Feed state is missing component flow(s) for {missing_flows}; '
            f'cannot build a BioSTEAM feed.'
        )

    flow_units = state.get('component_flow_units') or state.get('total_flow_units')
    if flow_units is None:
        raise MulticomponentBiosteamFeedError(
            'Feed state has neither component_flow_units nor '
            'total_flow_units; cannot build a BioSTEAM feed.'
        )

    pressure = state.get('pressure')
    pressure_units = state.get('pressure_units')
    if pressure is None or pressure_units is None:
        raise MulticomponentBiosteamFeedError(
            'Feed state is missing pressure or its units; cannot build a '
            'BioSTEAM feed.'
        )
    pressure_Pa = pressure_to_Pa(pressure, pressure_units)

    bst.settings.set_thermo(component_names, cache=True)

    flows = {name: component_flows[name] for name in component_names}
    feed = bst.Stream(stream_id, units=flow_units, P=pressure_Pa, **flows)
    return feed, pressure_Pa


if __name__ == '__main__':
    state = {
        'component_names': ['Water', 'Ethanol', 'Methanol'],
        'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30},
        'component_flow_units': 'kmol/hr',
        'total_flow_units': None,
        'pressure': 1.0,
        'pressure_units': 'atm',
    }
    feed, pressure_Pa = build_multicomponent_biosteam_feed(state)
    feed.show()
    print('pressure_Pa:', pressure_Pa)
