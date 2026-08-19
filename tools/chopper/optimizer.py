import biosteam as bst

from sweep_separation import sweep_reflux_ratio
from sep_economic_analysis import annualize_sweep, DEFAULT_OPERATING_DAYS
from best_design import find_best_design


def validate_key_selection(feed, LHK):
    """
    Check whether a light_key/heavy_key pair is valid for the shortcut
    (Fenske-Underwood-Gilliland) BinaryDistillation workflow used
    throughout this package.

    The shortcut method assumes light_key and heavy_key are adjacent in
    relative volatility -- every other feed component is expected to fall
    cleanly on one side of the split. If some other feed component's
    normal boiling point lies between light_key's and heavy_key's, that
    component is a "distributed" component the shortcut method has no way
    to pin down, and any resulting (in)feasibility may have nothing to do
    with reflux ratio.

    This function only checks and reports -- it never changes `LHK` or
    picks keys on the caller's behalf.

    Parameters
    ----------
    feed : bst.Stream
        Feed stream (thermo already set). Only components with nonzero
        flow in `feed` are checked against the keys.
    LHK : tuple[str, str]
        (light_key, heavy_key) component IDs.

    Returns
    -------
    dict with keys:
        'valid'   : bool -- True if no other feed component's boiling
                    point falls strictly between light_key's and
                    heavy_key's.
        'warning' : str or None -- human-readable warning if not valid,
                    else None.
        'light_key', 'heavy_key' : str -- echoed back from LHK.
        'light_key_Tb_K', 'heavy_key_Tb_K' : float -- normal boiling
                    points (K) used for the comparison.
        'distributed_components' : list[dict] -- one
                    {'component', 'Tb_K'} entry per feed component whose
                    boiling point falls between the two keys'.
    """
    light_key, heavy_key = LHK
    chemicals = feed.chemicals

    Tb_lk = chemicals[light_key].Tb
    Tb_hk = chemicals[heavy_key].Tb
    lo, hi = sorted((Tb_lk, Tb_hk))

    distributed = []
    for ID in feed.chemicals.IDs:
        if ID in (light_key, heavy_key):
            continue
        if feed.imol[ID] <= 0:
            continue
        Tb = chemicals[ID].Tb
        if Tb is not None and lo < Tb < hi:
            distributed.append({'component': ID, 'Tb_K': Tb})

    valid = len(distributed) == 0
    warning = None
    if not valid:
        names = ', '.join(f"{d['component']} (Tb={d['Tb_K']:.1f} K)" for d in distributed)
        warning = (
            f"Key selection may be ambiguous/invalid for the shortcut method: "
            f"light_key={light_key} (Tb={Tb_lk:.1f} K) and heavy_key={heavy_key} "
            f"(Tb={Tb_hk:.1f} K) are not adjacent in volatility -- the following "
            f"feed component(s) boil in between and are 'distributed' "
            f"components the shortcut method cannot resolve: {names}. Consider "
            f"choosing light_key/heavy_key that are adjacent in volatility, or "
            f"treat this design/feasibility result with caution."
        )

    return {
        'valid': valid,
        'warning': warning,
        'light_key': light_key,
        'heavy_key': heavy_key,
        'light_key_Tb_K': Tb_lk,
        'heavy_key_Tb_K': Tb_hk,
        'distributed_components': distributed,
    }


def optimize_reflux_ratio(
    feed,
    LHK,
    reflux_ratios_k,
    P=101325,
    spec='purity',
    target='top',
    purity_target=None,
    recovery_target=None,
    y_top=None,
    x_bot=None,
    Lr=None,
    Hr=None,
    is_divided=True,
    tol=1e-3,
    lifetime_years=20,
    operating_days=DEFAULT_OPERATING_DAYS,
    cost_col='total_annual_cost_usd_per_yr',
    csv_path=None,
    **design_kwargs,
):
    """
    High-level, one-call reflux-ratio optimizer.

    Wraps the full pipeline used throughout this package --
    `sweep_reflux_ratio()` -> `annualize_sweep()` -> `find_best_design()`
    -- behind a single function call. This is not a new optimization
    method: it is the same shortcut-column sweep as before, just so you
    don't have to wire the three steps together by hand every time.

    Parameters
    ----------
    feed : bst.Stream
        Feed to the column (thermo must already be set on `bst.settings`).
        A fresh copy is made per reflux ratio internally (see
        `sweep_reflux_ratio`); `feed` itself is never mutated.
    LHK : tuple[str, str]
        (light_key, heavy_key) component IDs.
    reflux_ratios_k : Sequence[float]
        The `k` values to sweep -- BioSTEAM's shortcut multiplier over
        minimum reflux, NOT absolute L/D values (see
        `separation_trial.run_separation` for the full explanation).
    P : float
        Column pressure [Pa]. Default 101325 (1 atm).
    spec : {'purity', 'recovery'}
        Which kind of target to check feasibility against.
    target : {'top', 'bottom'}
        Which outlet is the product of interest. 'top' checks the light
        key in the distillate; 'bottom' checks the heavy key in the
        bottoms.
    purity_target : float or None
        Convenience shorthand for spec='purity'. Sets a symmetric pair
        `y_top=purity_target`, `x_bot=1-purity_target` -- the same
        convention used everywhere else in this package (e.g.
        y_top=0.99/x_bot=0.01). Ignored if `y_top`/`x_bot` are given
        explicitly. Required (or `y_top`+`x_bot`) when spec='purity'.
    recovery_target : float or None
        Convenience shorthand for spec='recovery'. Sets a symmetric pair
        `Lr=recovery_target`, `Hr=recovery_target`. Ignored if `Lr`/`Hr`
        are given explicitly. Required (or `Lr`+`Hr`) when spec='recovery'.
    y_top, x_bot : float or None
        Explicit purity spec, passed straight through to
        `sweep_reflux_ratio` when given -- overrides `purity_target`.
        Both must be given together.
    Lr, Hr : float or None
        Explicit recovery spec, passed straight through to
        `sweep_reflux_ratio` when given -- overrides `recovery_target`.
        Both must be given together.
    is_divided : bool
        Passed to `BinaryDistillation` (divided vs. non-divided column).
    tol : float
        Absolute tolerance used when checking achieved vs. target.
    lifetime_years : float
        Column equipment lifetime in years, used to annualize CAPEX.
    operating_days : float
        Scheduled plant operating days/yr, used to annualize utility
        cost. Default 330 (0.9 operating factor) -- see
        `sep_economic_analysis.DEFAULT_OPERATING_DAYS`.
    cost_col : str
        Column in the annualized sweep to minimize over when picking the
        best design. Default `'total_annual_cost_usd_per_yr'`.
    csv_path : str or None
        If given, the raw (pre-annualized) sweep is written here via
        `sweep_reflux_ratio`'s own `csv_path` argument.
    **design_kwargs
        Any other `BinaryDistillation` keyword arguments (e.g.
        `vessel_material`, `tray_type`), passed through unchanged to
        every run in the sweep.

    Returns
    -------
    result : dict with keys:
        'best_design'   : dict or None -- the lowest-cost feasible row
                       (all annualized-sweep columns for that reflux
                       ratio), or None if nothing in the sweep was
                       feasible.
        'sweep_results' : list[dict] -- the complete annualized sweep,
                       one dict per reflux ratio (`econ_df.to_dict('records')`).
        'sweep_df'      : pandas.DataFrame -- the same complete sweep as a
                       DataFrame, for direct use with
                       `separation_plots.plot_reflux_sweep` or further
                       analysis.
        'n_feasible'    : int -- how many reflux ratios in the sweep were
                       feasible.
        'n_total'       : int -- how many reflux ratios were swept.
        'found'         : bool -- True if at least one feasible design
                       was found.
        'message'       : str -- human-readable summary from
                       `find_best_design`.
        'key_selection' : dict -- output of `validate_key_selection(feed,
                       LHK)`, run before the sweep. `LHK` is never changed
                       based on this check; `key_selection['warning']` is
                       non-None when another feed component's boiling
                       point falls between the light and heavy keys',
                       which can explain an unexpected infeasible result
                       independent of reflux ratio.
    """
    if spec not in ('purity', 'recovery'):
        raise ValueError("spec must be 'purity' or 'recovery'")

    key_selection = validate_key_selection(feed, LHK)

    if spec == 'purity':
        if y_top is None and x_bot is None:
            if purity_target is None:
                raise ValueError(
                    "spec='purity' requires either purity_target, or "
                    "both y_top and x_bot."
                )
            y_top = purity_target
            x_bot = 1 - purity_target
        elif y_top is None or x_bot is None:
            raise ValueError("Provide both y_top and x_bot together, or use purity_target instead.")
    else:
        if Lr is None and Hr is None:
            if recovery_target is None:
                raise ValueError(
                    "spec='recovery' requires either recovery_target, or "
                    "both Lr and Hr."
                )
            Lr = recovery_target
            Hr = recovery_target
        elif Lr is None or Hr is None:
            raise ValueError("Provide both Lr and Hr together, or use recovery_target instead.")

    # Unused ends of the shortcut spec pair still need a value to fully
    # define the column (see run_separation) -- default to the package
    # convention of 0.99/0.01 when the caller only cares about the other spec.
    df = sweep_reflux_ratio(
        feed=feed,
        LHK=LHK,
        reflux_ratios_k=reflux_ratios_k,
        P=P,
        spec=spec,
        target=target,
        y_top=y_top if y_top is not None else 0.99,
        x_bot=x_bot if x_bot is not None else 0.01,
        Lr=Lr if Lr is not None else 0.99,
        Hr=Hr if Hr is not None else 0.99,
        is_divided=is_divided,
        tol=tol,
        lifetime_years=lifetime_years,
        csv_path=csv_path,
        **design_kwargs,
    )

    econ_df = annualize_sweep(df, operating_days=operating_days)
    best = find_best_design(econ_df, cost_col=cost_col)

    return {
        'best_design': best['design'],
        'sweep_results': econ_df.to_dict('records'),
        'sweep_df': econ_df,
        'n_feasible': best['n_feasible'],
        'n_total': best['n_total'],
        'found': best['found'],
        'message': best['message'],
        'key_selection': key_selection,
    }


if __name__ == '__main__':
    bst.settings.set_thermo(['Water', 'Methanol', 'Glycerol'], cache=True)

    feed = bst.Stream('feed', flow=(80, 100, 25), units='kmol/hr')
    feed.T = feed.bubble_point_at_P().T

    result = optimize_reflux_ratio(
        feed=feed,
        LHK=('Methanol', 'Water'),
        reflux_ratios_k=[1.5, 1.75, 2.0, 2.25, 2.5],
        purity_target=0.99,
    )

    print(f"n_feasible: {result['n_feasible']}/{result['n_total']}")
    print(result['message'])
    print(f"key_selection: {result['key_selection']}")
    print('\nBest design:')
    for k, v in result['best_design'].items():
        print(f'  {k}: {v}')

    # Same feed, but LK/HK skip over Water -- Water is a distributed
    # component and validate_key_selection() should flag it.
    feed2 = bst.Stream('feed2', flow=(80, 100, 25), units='kmol/hr')
    feed2.T = feed2.bubble_point_at_P().T

    bad_key_result = optimize_reflux_ratio(
        feed=feed2,
        LHK=('Methanol', 'Glycerol'),
        reflux_ratios_k=[1.5, 1.75, 2.0, 2.25, 2.5],
        purity_target=0.99,
    )
    print('\n--- Ambiguous key selection demo (Methanol/Glycerol, skips Water) ---')
    print(f"n_feasible: {bad_key_result['n_feasible']}/{bad_key_result['n_total']}")
    print(f"key_selection warning: {bad_key_result['key_selection']['warning']}")
