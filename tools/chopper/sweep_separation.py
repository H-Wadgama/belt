import biosteam as bst
import pandas as pd

from separation_trial import run_separation


def sweep_reflux_ratio(
    feed,
    LHK,
    reflux_ratios_k,
    P=101325,
    spec='purity',
    target='top',
    y_top=0.99,
    x_bot=0.01,
    Lr=0.99,
    Hr=0.99,
    is_divided=True,
    tol=1e-3,
    lifetime_years=20,
    csv_path=None,
    **design_kwargs,
):
    """
    Run `run_separation` once per reflux ratio in `reflux_ratios` and
    collect the results into a single pandas DataFrame (one row per run).

    Every run gets its own copy of `feed` and its own unit ID (derived from
    the run's position in `reflux_ratios`), so repeated/looped calls don't
    collide in BioSTEAM's flowsheet registry the way reusing one `feed`
    stream and a fixed `ID='D1'` across iterations would.

    Parameters
    ----------
    feed : bst.Stream
        Feed to copy for each column in the sweep (thermo must already be
        set on `bst.settings`). The original `feed` is left untouched.
        Must have exactly 2 nonzero-flow components -- see
        `separation_trial.check_binary_feed`.
    LHK : tuple[str, str]
        (light_key, heavy_key) component IDs.
    reflux_ratios_k : Sequence[float]
        The `k` values to sweep over -- each is BioSTEAM's shortcut
        multiplier over the minimum reflux ratio, NOT an absolute L/D
        value (see `run_separation`'s `reflux_ratio_k` for the full
        explanation). One column is built and simulated per value.
    P, spec, target, y_top, x_bot, Lr, Hr, is_divided, tol, lifetime_years
        Passed straight through to `run_separation` for every reflux ratio
        in the sweep -- see `separation_trial.run_separation` for details.
        (Only `reflux_ratio_k` and the per-run `feed`/`ID` vary across
        rows; everything else is held fixed for now. Sweeping separation
        specs as well is a future extension, not handled here.)
    csv_path : str or None
        If given, the resulting DataFrame is written to this path via
        `DataFrame.to_csv(csv_path, index=False)`.
    **design_kwargs
        Any other `BinaryDistillation` keyword arguments, passed through
        to `run_separation` for every run.

    Returns
    -------
    df : pandas.DataFrame
        One row per reflux ratio, with columns: `reflux_ratio_k` (the
        *input* multiplier over minimum reflux -- NOT an absolute L/D
        value), `actual_reflux_ratio_LD` (the absolute L/D BioSTEAM
        computed from `reflux_ratio_k`), `minimum_reflux_ratio_LD` (the
        absolute L/D minimum reflux that `reflux_ratio_k` is relative to),
        `theoretical_stages`, `purity`, `purity_target`, `recovery`,
        `recovery_target`, `feasible`, `CAPEX_USD`, `lifetime_years`,
        `heating_cost_USD_hr`, `cooling_cost_USD_hr`, `error`.
        `purity_target`/`recovery_target` are `None` for whichever of the
        two `spec` doesn't apply. `CAPEX_USD` and `lifetime_years` are the
        two inputs `sep_economic_analysis.annualize_sweep` needs to turn
        this table into annualized $/yr figures.
    """
    table = []
    for i, k in enumerate(reflux_ratios_k):
        run_feed = feed.copy(f'{feed.ID}_sweep{i}')
        result = run_separation(
            feed=run_feed,
            LHK=LHK,
            reflux_ratio_k=k,
            P=P,
            spec=spec,
            target=target,
            y_top=y_top,
            x_bot=x_bot,
            Lr=Lr,
            Hr=Hr,
            is_divided=is_divided,
            tol=tol,
            ID=f'D_sweep{i}',
            lifetime_years=lifetime_years,
            **design_kwargs,
        )
        table.append({
            'reflux_ratio_k': result['operating_conditions']['reflux_ratio_k'],
            'actual_reflux_ratio_LD': result['operating_conditions']['actual_reflux_ratio_LD'],
            'minimum_reflux_ratio_LD': result['operating_conditions']['minimum_reflux_ratio_LD'],
            'theoretical_stages': result['operating_conditions']['theoretical_stages'],
            'purity': result['purity']['achieved'],
            'purity_target': result['purity']['target'],
            'recovery': result['recovery']['achieved'],
            'recovery_target': result['recovery']['target'],
            'feasible': result['feasible'],
            'CAPEX_USD': result['capex_usd'],
            'lifetime_years': result['lifetime_years'],
            'heating_cost_USD_hr': result['utilities']['heating_cost_USD_per_hr'],
            'cooling_cost_USD_hr': result['utilities']['cooling_cost_USD_per_hr'],
            'error': result['error'],
        })

    df = pd.DataFrame(table)

    if csv_path is not None:
        df.to_csv(csv_path, index=False)

    return df


if __name__ == '__main__':
    # Binary feed only -- run_separation rejects 3+ nonzero-flow components
    # (see separation_trial.check_binary_feed).
    bst.settings.set_thermo(['Water', 'Methanol'], cache=True)

    feed = bst.Stream('feed', flow=(80, 100), units='kmol/hr')
    feed.T = feed.bubble_point_at_P().T

    # These are k multipliers over minimum reflux, not absolute L/D values.
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
        csv_path='reflux_ratio_sweep.csv',
    )

    print(df)
