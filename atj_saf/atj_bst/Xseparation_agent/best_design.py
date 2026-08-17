import biosteam as bst
import pandas as pd

from sep_economic_analysis import annualize_sweep


def find_best_design(econ_df, cost_col='total_annual_cost_usd_per_yr'):
    """
    Pick the lowest-cost feasible design out of a reflux-ratio sweep.

    This is the answer to "given the sweep, what's the best design?" --
    it does not run any new simulations. It just filters an already
    -annualized sweep DataFrame (see `sep_economic_analysis.annualize_sweep`)
    down to rows that actually met their separation target, and returns
    whichever of those has the lowest total annualized cost.

    Parameters
    ----------
    econ_df : pandas.DataFrame
        Output of `sep_economic_analysis.annualize_sweep` (i.e. a
        `sweep_separation.sweep_reflux_ratio` DataFrame with the
        annualized cost columns added). Must have a boolean `feasible`
        column and a `cost_col` column.
    cost_col : str
        Column to minimize over among feasible rows. Default
        `'total_annual_cost_usd_per_yr'` -- annualized CAPEX + annualized
        utility cost, the headline figure `annualize_sweep` produces.

    Returns
    -------
    result : dict with keys:
        'found'      : bool -- True if at least one row was feasible.
        'design'     : dict or None -- the winning row (all of `econ_df`'s
                       columns for that reflux ratio) as a plain dict, or
                       None if no row was feasible.
        'message'    : str -- human-readable summary, either announcing
                       the winning design or explaining that nothing in
                       the sweep was feasible.
        'n_feasible' : int -- how many rows in `econ_df` were feasible.
        'n_total'    : int -- how many rows `econ_df` had in total.
    """
    for required_col in ('feasible', cost_col):
        if required_col not in econ_df.columns:
            raise ValueError(
                f"econ_df is missing required column {required_col!r}; "
                "pass the output of sep_economic_analysis.annualize_sweep."
            )

    feasible_df = econ_df[econ_df['feasible'] & econ_df[cost_col].notna()]

    if feasible_df.empty:
        return {
            'found': False,
            'design': None,
            'message': (
                'No feasible design found in the sweep -- every reflux '
                'ratio either failed to converge or missed its '
                'purity/recovery target.'
            ),
            'n_feasible': 0,
            'n_total': len(econ_df),
        }

    best_row = feasible_df.loc[feasible_df[cost_col].idxmin()]

    return {
        'found': True,
        'design': best_row.to_dict(),
        'message': (
            f"Best feasible design: reflux_ratio_k={best_row['reflux_ratio_k']:.3g} "
            f"(L/D={best_row['actual_reflux_ratio_LD']:.3g}) at "
            f"${best_row[cost_col]:,.0f}/yr total annualized cost "
            f"(CAPEX ${best_row['CAPEX_USD']:,.0f})."
        ),
        'n_feasible': len(feasible_df),
        'n_total': len(econ_df),
    }


if __name__ == '__main__':
    from sweep_separation import sweep_reflux_ratio

    bst.settings.set_thermo(['Water', 'Methanol', 'Glycerol'], cache=True)

    feed = bst.Stream('feed', flow=(80, 100, 25), units='kmol/hr')
    feed.T = feed.bubble_point_at_P().T

    reflux_ratios_k = [1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5]

    df = sweep_reflux_ratio(
        feed=feed,
        LHK=('Methanol', 'Water'),
        reflux_ratios_k=reflux_ratios_k,
        P=101325,
        spec='purity',
        target='top',
        y_top=0.99,
        x_bot=0.01,
        lifetime_years=20,
    )
    econ_df = annualize_sweep(df)

    best = find_best_design(econ_df)

    print('--- Sweep economics ---')
    print(econ_df[['reflux_ratio_k', 'feasible', 'CAPEX_USD',
                    'total_annual_cost_usd_per_yr']])

    print('\n--- Best feasible design ---')
    print(best['message'])
    if best['found']:
        print(pd.Series(best['design']))
