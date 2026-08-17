# Global imports
import biosteam as bst


def _mass_flows_kg_hr(stream):
    """Component mass flow rates [kg/hr] for a stream, nonzero only."""
    return {
        ID: flow
        for ID, flow in zip(stream.chemicals.IDs, stream.mass)
        if flow > 1e-9
    }


def run_separation(
    feed,
    LHK,
    reflux_ratio_k,
    P=101325,
    spec='purity',
    target='top',
    y_top=0.99,
    x_bot=0.01,
    Lr=0.99,
    Hr=0.99,
    is_divided=True,
    tol=1e-3,
    ID='D1',
    **design_kwargs,
):
    """
    Build and simulate a single BinaryDistillation column for a
    user-defined separation target, and report whether it was actually met.

    This is a trial/scoping helper, not an optimizer: it runs the column
    exactly as specified and tells you what you got.

    Parameters
    ----------
    feed : bst.Stream
        Feed to the column (thermo must already be set on `bst.settings`).
    LHK : tuple[str, str]
        (light_key, heavy_key) component IDs.
    reflux_ratio_k : float
        `k` in BioSTEAM's shortcut (Fenske-Underwood-Gilliland) method --
        NOT an absolute reflux ratio. `k` is the ratio of the actual
        (absolute L/D) reflux ratio to the minimum reflux ratio, i.e.
        `k = actual_reflux_ratio_LD / minimum_reflux_ratio_LD`. You supply
        `k`; BioSTEAM computes the absolute L/D from it internally. Both
        the resulting absolute reflux ratio and the minimum reflux ratio
        it was computed from are reported back in
        `operating_conditions['actual_reflux_ratio_LD']` and
        `operating_conditions['minimum_reflux_ratio_LD']`, respectively.
    P : float
        Column pressure [Pa]. Default 101325 (1 atm).
    spec : {'purity', 'recovery'}
        Which kind of target to check feasibility against.
    target : {'top', 'bottom'}
        Which outlet carries the target you care about. 'top' checks the
        light key's purity/recovery in the distillate; 'bottom' checks the
        heavy key's purity/recovery in the bottoms. The other outlet is
        returned as `streams['waste']`.
    y_top, x_bot : float
        Required together when spec='purity'. Light-key molar fraction
        (on a light-key/heavy-key basis) targeted in the distillate
        (y_top) and bottoms (x_bot) -- this is what the shortcut method
        actually solves for. Both are needed to fully specify the column
        even though only one end is checked against `target`.
    Lr, Hr : float
        Required together when spec='recovery'. Fractional recovery of the
        light key to the distillate (Lr) and the heavy key to the bottoms
        (Hr). Both are needed to fully specify the column.
    is_divided : bool
        Passed to BinaryDistillation (divided vs. non-divided column).
    tol : float
        Absolute tolerance used when checking achieved vs. target.
    ID : str
        Unit ID for the column. Also used to name the two outlet streams
        (`f'{ID}_distillate'`, `f'{ID}_bottoms'`) so that repeated calls
        with different IDs (e.g. in a parameter sweep) don't collide in
        BioSTEAM's flowsheet registry.
    **design_kwargs
        Any other BinaryDistillation keyword arguments (e.g.
        `vessel_material`, `tray_type`, `stage_efficiency`), passed
        through unchanged.

    Returns
    -------
    results : dict with keys:
        'feasible'   : bool -- simulation converged AND the target spec
                       (purity or recovery, whichever `spec` selects) was
                       met within `tol`.
        'error'      : str or None -- exception message if the column
                       failed to build/simulate (e.g. spec unreachable in
                       <100 stages).
        'purity'     : {'target', 'achieved', 'met'} -- 'achieved' is the
                       overall molar fraction of the target key actually
                       present in the product stream (all components
                       included), which can legitimately read lower than
                       the LHK-basis `target` if non-key components end up
                       in that stream. 'target'/'met' are only populated
                       when spec='purity'.
        'recovery'   : {'target', 'achieved', 'met'} -- 'achieved' is
                       moles of target key in the product / moles of
                       target key in the feed. 'target'/'met' are only
                       populated when spec='recovery'.
        'capex_usd'  : float -- column installed cost.
        'utilities'  : {'heating_duty_kJ_per_hr', 'heating_cost_USD_per_hr',
                       'cooling_duty_kJ_per_hr', 'cooling_cost_USD_per_hr'}.
        'streams'    : {'feed', 'product', 'waste'}, each a dict of
                       {'stream': <bst.Stream>, 'flow_kg_per_hr': {component:
                       kg/hr, ...}, 'total_kg_per_hr': float}. 'product' and
                       'waste' are None if simulation failed.
        'operating_conditions' : {'pressure_Pa', 'reflux_ratio_k',
                       'actual_reflux_ratio_LD', 'minimum_reflux_ratio_LD',
                       'theoretical_stages', 'feed_stage'} -- 'reflux_ratio_k'
                       echoes back the *input* multiplier k; the other two
                       are the *absolute* (L/D) reflux ratios BioSTEAM
                       computed from it. Do not confuse the two: k is not
                       an L/D value.
        'unit'       : the simulated BinaryDistillation instance, or None
                       if construction/simulation failed.
    """
    if spec not in ('purity', 'recovery'):
        raise ValueError("spec must be 'purity' or 'recovery'")
    if target not in ('top', 'bottom'):
        raise ValueError("target must be 'top' or 'bottom'")

    light_key, heavy_key = LHK

    results = {
        'feasible': False,
        'error': None,
        'purity': {'target': None, 'achieved': None, 'met': None},
        'recovery': {'target': None, 'achieved': None, 'met': None},
        'capex_usd': None,
        'utilities': {
            'heating_duty_kJ_per_hr': None,
            'heating_cost_USD_per_hr': None,
            'cooling_duty_kJ_per_hr': None,
            'cooling_cost_USD_per_hr': None,
        },
        'streams': {
            'feed': {
                'stream': feed,
                'flow_kg_per_hr': _mass_flows_kg_hr(feed),
                'total_kg_per_hr': feed.F_mass,
            },
            'product': None,
            'waste': None,
        },
        'operating_conditions': {
            'pressure_Pa': P,
            'reflux_ratio_k': reflux_ratio_k,      # BioSTEAM input multiplier, NOT an L/D value
            'actual_reflux_ratio_LD': None,        # absolute L/D BioSTEAM computed from k
            'minimum_reflux_ratio_LD': None,       # absolute L/D minimum reflux
            'theoretical_stages': None,
            'feed_stage': None,
        },
        'unit': None,
    }

    if spec == 'purity':
        results['purity']['target'] = y_top if target == 'top' else 1 - x_bot
    else:
        results['recovery']['target'] = Lr if target == 'top' else Hr

    column_kwargs = dict(
        ID=ID, ins=feed, outs=(f'{ID}_distillate', f'{ID}_bottoms'),
        LHK=LHK, k=reflux_ratio_k, P=P, is_divided=is_divided,
        **design_kwargs,
    )
    if spec == 'purity':
        column_kwargs.update(y_top=y_top, x_bot=x_bot)
    else:
        column_kwargs.update(Lr=Lr, Hr=Hr)

    try:
        D1 = bst.units.BinaryDistillation(**column_kwargs)
        D1.simulate()
    except Exception as e:
        results['error'] = f'{type(e).__name__}: {e}'
        return results

    results['unit'] = D1
    distillate, bottoms = D1.outs
    product, waste = (distillate, bottoms) if target == 'top' else (bottoms, distillate)
    results['streams']['product'] = {
        'stream': product,
        'flow_kg_per_hr': _mass_flows_kg_hr(product),
        'total_kg_per_hr': product.F_mass,
    }
    results['streams']['waste'] = {
        'stream': waste,
        'flow_kg_per_hr': _mass_flows_kg_hr(waste),
        'total_kg_per_hr': waste.F_mass,
    }

    target_key = light_key if target == 'top' else heavy_key

    achieved_purity = product.get_molar_fraction(target_key)
    results['purity']['achieved'] = achieved_purity
    if spec == 'purity':
        results['purity']['met'] = achieved_purity >= results['purity']['target'] - tol

    feed_key_mol = feed.imol[target_key]
    achieved_recovery = (product.imol[target_key] / feed_key_mol) if feed_key_mol else None
    results['recovery']['achieved'] = achieved_recovery
    if spec == 'recovery':
        results['recovery']['met'] = (
            achieved_recovery is not None
            and achieved_recovery >= results['recovery']['target'] - tol
        )

    results['capex_usd'] = D1.installed_cost

    heating_duty = heating_cost = cooling_duty = cooling_cost = 0.0
    for hu in D1.heat_utilities:
        if hu.duty > 0:
            heating_duty += hu.duty
            heating_cost += hu.cost
        elif hu.duty < 0:
            cooling_duty += hu.duty
            cooling_cost += hu.cost
    results['utilities'] = {
        'heating_duty_kJ_per_hr': heating_duty,
        'heating_cost_USD_per_hr': heating_cost,
        'cooling_duty_kJ_per_hr': cooling_duty,
        'cooling_cost_USD_per_hr': cooling_cost,
    }

    dr = D1.design_results
    results['operating_conditions'].update(
        actual_reflux_ratio_LD=dr.get('Reflux'),
        minimum_reflux_ratio_LD=dr.get('Minimum reflux'),
        theoretical_stages=dr.get('Theoretical stages'),
        feed_stage=dr.get('Theoretical feed stage'),
    )

    results['feasible'] = (
        (results['purity']['met'] if spec == 'purity' else results['recovery']['met'])
        is True
    )

    return results


if __name__ == '__main__':
    bst.settings.set_thermo(['Water', 'Methanol', 'Glycerol'], cache=True)

    feed = bst.Stream('feed', flow=(80, 100, 25))
    bp = feed.bubble_point_at_P()
    feed.T = bp.T  # Feed at bubble point T

    # Example 1: purity spec, checking distillate (top) methanol purity
    # reflux_ratio_k=2 means k=2, i.e. actual L/D = 2x the minimum reflux --
    # NOT an absolute L/D of 2.
    purity_results = run_separation(
        feed, LHK=('Methanol', 'Water'), reflux_ratio_k=2, P=101325,
        spec='purity', target='top', y_top=0.99, x_bot=0.01,
    )
    print('--- Purity-spec run ---')
    print(f"Feasible: {purity_results['feasible']}")
    print(f"Purity target: {purity_results['purity']['target']:.4f}  "
          f"achieved: {purity_results['purity']['achieved']:.4f}")
    print(f"CAPEX: ${purity_results['capex_usd']:,.0f}")
    print(f"Heating cost: ${purity_results['utilities']['heating_cost_USD_per_hr']:.2f}/hr")
    print(f"Cooling cost: ${purity_results['utilities']['cooling_cost_USD_per_hr']:.2f}/hr")
    print(f"Operating conditions: {purity_results['operating_conditions']}")
    print(f"Feed flow (kg/hr): {purity_results['streams']['feed']['flow_kg_per_hr']}")
    print(f"Product flow (kg/hr): {purity_results['streams']['product']['flow_kg_per_hr']}")
    print(f"Waste flow (kg/hr): {purity_results['streams']['waste']['flow_kg_per_hr']}")
    purity_results['unit'].show(T='degC', P='atm', composition=True)

    # Example 2: recovery spec, checking heavy-key (water) recovery to bottoms
    feed2 = bst.Stream('feed2', flow=(80, 100, 25))
    feed2.T = feed2.bubble_point_at_P().T
    recovery_results = run_separation(
        feed2, LHK=('Methanol', 'Water'), reflux_ratio_k=1.5, P=101325,
        spec='recovery', target='bottom', Lr=0.99, Hr=0.99, ID='D2',
    )
    print('\n--- Recovery-spec run ---')
    print(f"Feasible: {recovery_results['feasible']}")
    print(f"Recovery target: {recovery_results['recovery']['target']:.4f}  "
          f"achieved: {recovery_results['recovery']['achieved']:.4f}")
    print(f"CAPEX: ${recovery_results['capex_usd']:,.0f}")
