"""
Deterministic reference-temperature partial-condensation screen.

See `tools/binary-distillation-feed-vapor-liquid.md` Steps 2-8 and
`tools/binary-distillation-vapor-liquid-dead-end.md`. Once a feed has already
been classified by `feed_phase.evaluate_feed_phase` as containing a vapor
fraction -- entirely vapor, or already a vapor-liquid mixture -- this module
answers the next deterministic question: what is the overall feed's
equilibrium liquid/vapor split after conditioning it to a fixed reference
temperature (313.15 K / ~40 C, a common heat-exchanger utility-water
screening point)? BioSTEAM's `HXutility` with `rigorous=True` is the sole
source of the resulting vapor/liquid split -- this module never estimates or
infers that split itself, only reads it back out of the simulated outlet
stream and classifies it against a fixed threshold. The overall feed
(whatever its initial vapor/liquid split) is conditioned as a whole -- the
initial vapor portion is never carved out and conditioned on its own.

No LLM calls -- this module must never import `ollama` or `openai`.
"""
import biosteam as bst

REFERENCE_TEMPERATURE_K = 313.15
LIQUEFACTION_THRESHOLD = 0.50


def evaluate_vapor_feed_at_reference_temperature(
    feed,
    *,
    pressure_Pa,
    initial_temperature_K,
    reference_temperature_K=REFERENCE_TEMPERATURE_K,
):
    """
    Condition a copy of the overall `feed` -- already known (from
    `evaluate_feed_phase`) to be entirely vapor, or already a vapor-liquid
    mixture, at `initial_temperature_K`/`pressure_Pa` -- to
    `reference_temperature_K` via a rigorous BioSTEAM `HXutility` VLE flash,
    and deterministically route based on the resulting liquid fraction.

    Parameters
    ----------
    feed : bst.Stream
        The canonical 2-component feed (e.g. from
        `biosteam_feed.build_biosteam_feed`). Never mutated -- a copy is
        brought to its known equilibrium state at `initial_temperature_K`/
        `pressure_Pa` (whether that is entirely vapor or a vapor-liquid
        mixture) and passed through the exchanger as a whole; the initial
        vapor portion is never extracted and conditioned on its own.
    pressure_Pa : float
        Feed/column pressure, Pa. Held constant through the exchanger.
    initial_temperature_K : float
        The feed's actual temperature at its stated thermal condition (e.g.
        `evaluate_feed_phase(...)['temperature_K']`) -- used to set the
        exchanger inlet state and to determine cooling vs. heating.
    reference_temperature_K : float, optional
        Target temperature for the screen. Defaults to
        `REFERENCE_TEMPERATURE_K` (313.15 K).

    Returns
    -------
    dict
        On success: `{'valid': True, 'check': 'vapor_feed_reference_temperature',
        'target_temperature_K', 'initial_temperature_K', 'pressure_Pa',
        'operation', 'components', 'vapor_mol', 'liquid_mol',
        'liquid_fraction', 'vapor_fraction', 'liquid_percent',
        'vapor_percent', 'route', 'implemented': False, 'message'}`.
        On failure: `{'valid': False, 'check': 'vapor_feed_reference_temperature',
        'error', 'message'}`.
    """
    try:
        component_names = [
            ID for ID in feed.chemicals.IDs if feed.imol[ID] > 1e-9
        ]
        if len(component_names) != 2:
            return {
                'valid': False,
                'check': 'vapor_feed_reference_temperature',
                'error': 'unsupported_component_count',
                'message': (
                    f'evaluate_vapor_feed_at_reference_temperature requires '
                    f'exactly 2 nonzero-flow components; got '
                    f'{len(component_names)}: {component_names}.'
                ),
            }

        if initial_temperature_K > reference_temperature_K:
            operation = 'cooling'
        elif initial_temperature_K < reference_temperature_K:
            operation = 'heating'
        else:
            operation = 'none'

        # Never mutate the canonical feed -- copy first, then bring the copy
        # to its actual equilibrium state at the initial conditions (a
        # rigorous BioSTEAM VLE flash, not an assumption). For a feed already
        # known to be entirely vapor this reproduces that vapor state; for a
        # feed already known to be a vapor-liquid mixture this reproduces the
        # overall mixed-phase state -- either way the whole feed goes into
        # the exchanger, never only its vapor portion.
        feed_copy = feed.copy()
        feed_copy.vle(T=initial_temperature_K, P=pressure_Pa)

        heatex = bst.units.HXutility(ins=feed_copy, T=reference_temperature_K, rigorous=True)
        heatex.simulate()
        outlet = heatex.outs[0]

        vapor_mol = {ID: float(outlet.imol['g', ID]) for ID in component_names}
        liquid_mol = {ID: float(outlet.imol['l', ID]) for ID in component_names}
        vapor_mol_total = sum(vapor_mol.values())
        liquid_mol_total = sum(liquid_mol.values())
        total_mol = vapor_mol_total + liquid_mol_total

        if total_mol <= 0:
            return {
                'valid': False,
                'check': 'vapor_feed_reference_temperature',
                'error': 'zero_flow',
                'message': (
                    'Feed has zero total molar flow after the reference-'
                    'temperature screen; cannot compute a liquid/vapor split.'
                ),
            }

        liquid_fraction = liquid_mol_total / total_mol
        vapor_fraction = vapor_mol_total / total_mol

        if liquid_fraction >= LIQUEFACTION_THRESHOLD:
            route = 'liquid_and_vapor_separation_future'
            message = (
                f'{liquid_fraction * 100:.1f} mol% of the feed liquefies at '
                f'{reference_temperature_K:.2f} K ({operation} from '
                f'{initial_temperature_K:.2f} K); this is substantial partial '
                'condensation. That liquid fraction is intended to undergo a '
                'liquid-phase separation method -- not implemented yet. The '
                f'remaining {vapor_fraction * 100:.1f} mol% stays vapor and is '
                'intended to undergo a vapor-phase separation method -- also '
                'not implemented yet.'
            )
        else:
            route = 'vapor_separation_advisable'
            message = (
                f'{vapor_fraction * 100:.1f} mol% of the feed remains vapor at '
                f'{reference_temperature_K:.2f} K ({operation} from '
                f'{initial_temperature_K:.2f} K); only {liquid_fraction * 100:.1f} '
                'mol% liquefies. Since less than 50 mol% liquefies, a '
                'vapor-phase separation method is advisable. Vapor-phase '
                'separation calculations are not implemented yet.'
            )

        return {
            'valid': True,
            'check': 'vapor_feed_reference_temperature',
            'target_temperature_K': float(reference_temperature_K),
            'initial_temperature_K': float(initial_temperature_K),
            'pressure_Pa': float(pressure_Pa),
            'operation': operation,
            'components': component_names,
            'vapor_mol': vapor_mol,
            'liquid_mol': liquid_mol,
            'liquid_fraction': liquid_fraction,
            'vapor_fraction': vapor_fraction,
            'liquid_percent': liquid_fraction * 100.0,
            'vapor_percent': vapor_fraction * 100.0,
            'route': route,
            'implemented': False,
            'message': message,
        }
    except Exception as err:
        return {
            'valid': False,
            'check': 'vapor_feed_reference_temperature',
            'error': 'reference_temperature_flash_failed',
            'message': str(err),
        }


if __name__ == '__main__':
    import json

    bst.settings.set_thermo(['Butane', 'Water'], cache=True)
    feed = bst.Stream('feed', Butane=50, Water=50, units='kmol/hr', P=101325)

    result = evaluate_vapor_feed_at_reference_temperature(
        feed, pressure_Pa=101325, initial_temperature_K=405.0,
    )
    print(json.dumps(result, indent=2))
