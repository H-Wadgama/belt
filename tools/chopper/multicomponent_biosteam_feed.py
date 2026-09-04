"""
Deterministic BioSTEAM feed adapter for multicomponent distillation.

See tools/multicomponent-distillation-feed-phase-plan.md "Canonical
Molar-Flow Conversion". This is the ONLY place in the multicomponent
intake pipeline that performs molecular-weight-aware conversion --
`multicomponent_feed_state.py` deliberately never does, since it has no
BioSTEAM access and cross-basis conversion (e.g. a mass composition against
a molar total flow) requires molecular weights.

Converts an already-`ready` `multicomponent_feed_state.assess_feed_state()`
state into one canonical mapping, `component_molar_flows_kmol_per_hr`, and
builds the `bst.Stream` ONLY from that mapping -- never from the raw
user-entered quantities directly, and never from a value not already
present in `state`. Pressure is converted to Pa here via
`multicomponent_units.pressure_to_Pa`, since the canonical feed state
stores pressure in whatever unit the user gave, not in Pa.

No LLM calls -- this module must never import `ollama` or `openai`.
"""
import biosteam as bst

from multicomponent_units import (
    is_mass_flow_unit,
    is_molar_flow_unit,
    normalize_flow_unit,
    pressure_to_Pa,
)

MIN_COMPONENTS = 3


class MulticomponentBiosteamFeedError(ValueError):
    """Raised when a feed state cannot be converted into a BioSTEAM feed
    (not ready, too few components, or missing a value the calculation
    layer requires)."""


def _canonical_molar_flows_kmol_per_hr(state, chemicals):
    """
    Molecular-weight-aware conversion of `state`'s raw quantity facts into
    one canonical `{component_name: kmol/hr}` mapping. Implements
    tools/multicomponent-distillation-feed-phase-plan.md "Canonical
    Molar-Flow Conversion" steps 1-4.

    Prefers Mode A (direct per-component flows) when every named component
    already has one; otherwise requires Mode B (total flow + full
    composition on a known basis) and derives per-component molar flows
    from it, converting mass fractions to mole fractions with molecular
    weights whenever the composition basis disagrees with (or the total
    flow is expressed in) a mass unit.
    """
    names = state['component_names']

    def MW(name):
        return chemicals[name].MW

    flows = state.get('component_flows') or {}
    flow_units = normalize_flow_unit(state.get('component_flow_units')) or state.get('component_flow_units')
    if flow_units and all(n in flows for n in names):
        result = {}
        for n in names:
            v = flows[n]
            if flow_units == 'kmol/hr':
                result[n] = v
            elif flow_units == 'mol/hr':
                result[n] = v / 1000.0
            elif is_mass_flow_unit(flow_units):
                result[n] = v / MW(n)
            else:
                raise MulticomponentBiosteamFeedError(
                    f'Unsupported component_flow_units: {flow_units!r}.'
                )
        return result

    total_flow = state.get('total_flow')
    total_flow_units = normalize_flow_unit(state.get('total_flow_units')) or state.get('total_flow_units')
    composition = state.get('composition') or {}
    composition_basis = state.get('composition_basis')

    if (total_flow is not None and total_flow_units and composition_basis
            and all(n in composition for n in names)):
        if composition_basis == 'mole':
            mole_fractions = dict(composition)
        elif composition_basis == 'mass':
            denom = sum(composition[n] / MW(n) for n in names)
            if denom <= 0:
                raise MulticomponentBiosteamFeedError(
                    'Mass composition fractions and molecular weights produce a '
                    'non-positive normalization; cannot convert to mole fractions.'
                )
            mole_fractions = {n: (composition[n] / MW(n)) / denom for n in names}
        else:
            raise MulticomponentBiosteamFeedError(
                f'Unsupported composition_basis: {composition_basis!r}.'
            )

        if total_flow_units == 'kmol/hr':
            total_kmol_hr = total_flow
        elif total_flow_units == 'mol/hr':
            total_kmol_hr = total_flow / 1000.0
        elif is_mass_flow_unit(total_flow_units):
            mixture_MW = sum(mole_fractions[n] * MW(n) for n in names)
            total_kmol_hr = total_flow / mixture_MW
        else:
            raise MulticomponentBiosteamFeedError(
                f'Unsupported total_flow_units: {total_flow_units!r}.'
            )

        return {n: total_kmol_hr * mole_fractions[n] for n in names}

    raise MulticomponentBiosteamFeedError(
        'Feed state does not have a complete quantity specification -- need '
        'either a flow for every component in one shared unit, or a total '
        'flow with its units, a composition basis, and a fraction for every '
        'component.'
    )


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
        If `state` has fewer than MIN_COMPONENTS components, the quantity
        specification is incomplete, or pressure/its units are missing.
    """
    component_names = list(state.get('component_names') or [])
    if len(component_names) < MIN_COMPONENTS:
        raise MulticomponentBiosteamFeedError(
            f'build_multicomponent_biosteam_feed requires at least '
            f'{MIN_COMPONENTS} components; got {len(component_names)}: '
            f'{component_names}.'
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
    chemicals = bst.settings.chemicals

    component_molar_flows_kmol_per_hr = _canonical_molar_flows_kmol_per_hr(state, chemicals)

    feed = bst.Stream(
        stream_id, units='kmol/hr', P=pressure_Pa, **component_molar_flows_kmol_per_hr,
    )
    return feed, pressure_Pa


if __name__ == '__main__':
    state = {
        'component_names': ['Water', 'Methanol', 'Ethanol'],
        'total_flow': 100, 'total_flow_units': 'kmol/hr',
        'composition': {'Water': 0.20, 'Methanol': 0.20, 'Ethanol': 0.60},
        'composition_basis': 'mass',
        'pressure': 1.0, 'pressure_units': 'atm',
    }
    feed, pressure_Pa = build_multicomponent_biosteam_feed(state)
    feed.show()
    print('pressure_Pa:', pressure_Pa)
