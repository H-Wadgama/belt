import biosteam as bst
import pandas as pd

from separation_trial import run_separation

# 330 operating days/yr (0.9 operating factor) -- matches the lignin_saf
# TEA convention (e.g. ligsaf/settings/tea_params.py, cellulosic_tea.py).
DEFAULT_OPERATING_DAYS = 330


def annualize_capex(capex_usd, lifetime_years):
    """
    Straight-line annualized capital cost [$/yr] -- no interest/discount
    rate, just `capex_usd / lifetime_years`. `capex_usd` is expected to be
    an *installed* cost (see `separation_trial.run_separation`'s
    `capex_usd` output), not a bare equipment purchase cost.
    """
    if capex_usd is None or lifetime_years is None:
        return None
    return capex_usd / lifetime_years


def annualize_utilities(heating_cost_usd_hr, cooling_cost_usd_hr, operating_days=DEFAULT_OPERATING_DAYS):
    """
    Total column utility cost [$/yr] = (heating + cooling cost, $/hr) x
    (operating_days x 24 hr/day). Both hourly costs are expected to already
    be non-negative (as returned by `run_separation`'s `utilities` dict).
    """
    if heating_cost_usd_hr is None or cooling_cost_usd_hr is None:
        return None
    operating_hours = operating_days * 24
    return (heating_cost_usd_hr + cooling_cost_usd_hr) * operating_hours


def annualize_results(results, operating_days=DEFAULT_OPERATING_DAYS, lifetime_years=None):
    """
    Turn a single `run_separation(...)` results dict into annualized $/yr
    economics for that one column.

    Parameters
    ----------
    results : dict
        Output of `separation_trial.run_separation`.
    operating_days : float
        Scheduled plant operating days per year, used to convert the
        column's hourly utility costs into a $/yr figure (hours/yr =
        operating_days x 24). Default 330 (0.9 operating factor).
    lifetime_years : float or None
        Column equipment lifetime in years, used to annualize `capex_usd`.
        If None (default), falls back to `results['lifetime_years']` --
        the value `run_separation` was called with (itself defaulting to
        20 if not specified there).

    Returns
    -------
    econ : dict with keys:
        'lifetime_years'              : float -- lifetime actually used.
        'operating_days'              : float -- operating_days actually used.
        'annualized_capex_usd_per_yr' : float or None -- capex_usd / lifetime_years.
        'total_utility_cost_usd_per_yr' : float or None -- (heating + cooling
                       cost, $/hr) x operating hours/yr.
        'total_annual_cost_usd_per_yr' : float or None -- annualized capex +
                       total utility cost; the headline $/yr figure for
                       this simulation piece. None if the run failed
                       (`results['error']` is not None).
    """
    if lifetime_years is None:
        lifetime_years = results.get('lifetime_years')

    annualized_capex = annualize_capex(results['capex_usd'], lifetime_years)
    total_utility_cost = annualize_utilities(
        results['utilities']['heating_cost_USD_per_hr'],
        results['utilities']['cooling_cost_USD_per_hr'],
        operating_days=operating_days,
    )

    total_annual_cost = None
    if annualized_capex is not None and total_utility_cost is not None:
        total_annual_cost = annualized_capex + total_utility_cost

    return {
        'lifetime_years': lifetime_years,
        'operating_days': operating_days,
        'annualized_capex_usd_per_yr': annualized_capex,
        'total_utility_cost_usd_per_yr': total_utility_cost,
        'total_annual_cost_usd_per_yr': total_annual_cost,
    }


def annualize_sweep(df, operating_days=DEFAULT_OPERATING_DAYS):
    """
    Add annualized $/yr columns to a `sweep_separation.sweep_reflux_ratio`
    DataFrame (or any DataFrame with the same `CAPEX_USD`, `lifetime_years`,
    `heating_cost_USD_hr`, `cooling_cost_USD_hr` columns) -- one row's worth
    of economics per simulation piece (per reflux ratio).

    Parameters
    ----------
    df : pandas.DataFrame
        Output of `sweep_separation.sweep_reflux_ratio`.
    operating_days : float
        Scheduled plant operating days per year -- see `annualize_results`.

    Returns
    -------
    df : pandas.DataFrame
        A copy of `df` with three new columns: `annualized_capex_usd_per_yr`,
        `total_utility_cost_usd_per_yr`, `total_annual_cost_usd_per_yr`.
    """
    df = df.copy()
    operating_hours = operating_days * 24

    df['annualized_capex_usd_per_yr'] = df['CAPEX_USD'] / df['lifetime_years']
    df['total_utility_cost_usd_per_yr'] = (
        (df['heating_cost_USD_hr'] + df['cooling_cost_USD_hr']) * operating_hours
    )
    df['total_annual_cost_usd_per_yr'] = (
        df['annualized_capex_usd_per_yr'] + df['total_utility_cost_usd_per_yr']
    )
    return df


if __name__ == '__main__':
    bst.settings.set_thermo(['Water', 'Methanol', 'Glycerol'], cache=True)

    feed = bst.Stream('feed', flow=(80, 100, 25))
    feed.T = feed.bubble_point_at_P().T

    results = run_separation(
        feed, LHK=('Methanol', 'Water'), reflux_ratio_k=2, P=101325,
        spec='purity', target='top', y_top=0.99, x_bot=0.01,
        lifetime_years=20,
    )
    econ = annualize_results(results)

    print('--- Single-run economics ---')
    print(f"Installed CAPEX: ${results['capex_usd']:,.0f} "
          f"over {econ['lifetime_years']:.0f} yr lifetime")
    print(f"Annualized CAPEX: ${econ['annualized_capex_usd_per_yr']:,.0f}/yr")
    print(f"Total utility cost: ${econ['total_utility_cost_usd_per_yr']:,.0f}/yr "
          f"({econ['operating_days']:.0f} operating days/yr)")
    print(f"Total annual cost: ${econ['total_annual_cost_usd_per_yr']:,.0f}/yr")

    from sweep_separation import sweep_reflux_ratio

    reflux_ratios_k = [1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5]
    sweep_feed = bst.Stream('sweep_feed', flow=(80, 100, 25), units='kmol/hr')
    sweep_feed.T = sweep_feed.bubble_point_at_P().T

    df = sweep_reflux_ratio(
        feed=sweep_feed,
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

    print('\n--- Sweep economics ---')
    print(econ_df[['reflux_ratio_k', 'CAPEX_USD', 'annualized_capex_usd_per_yr',
                    'total_utility_cost_usd_per_yr', 'total_annual_cost_usd_per_yr']])
