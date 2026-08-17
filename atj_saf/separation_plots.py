import matplotlib.pyplot as plt


def _resolve_spec_columns(df, spec=None):
    """
    Figure out which spec ('purity' or 'recovery') a
    `sweep_separation.sweep_reflux_ratio` DataFrame was run with, and
    return the achieved/target column names that go with it.

    If `spec` is given explicitly, it is used as-is (and validated).
    Otherwise it's inferred from which of `purity_target` /
    `recovery_target` actually has values -- `sweep_reflux_ratio` only
    populates one of the two per run.
    """
    if spec is None:
        has_purity = df['purity_target'].notna().any()
        has_recovery = df['recovery_target'].notna().any()
        if has_purity and not has_recovery:
            spec = 'purity'
        elif has_recovery and not has_purity:
            spec = 'recovery'
        else:
            raise ValueError(
                "Could not infer spec from df (both or neither of "
                "'purity_target'/'recovery_target' are populated); pass "
                "spec='purity' or spec='recovery' explicitly."
            )
    if spec not in ('purity', 'recovery'):
        raise ValueError("spec must be 'purity' or 'recovery'")
    return spec, spec, f'{spec}_target'


def plot_purity_vs_reflux(
    df,
    spec=None,
    ylabel=None,
    title=None,
    ax=None,
    save_path=None,
    show=True,
):
    """
    Plot achieved separation performance (purity or recovery) against
    reflux ratio parameter k, with the target drawn as a reference line.

    Parameters
    ----------
    df : pandas.DataFrame
        Output of `sweep_separation.sweep_reflux_ratio` (or any DataFrame
        with the same `reflux_ratio_k`, `purity`, `purity_target`,
        `recovery`, `recovery_target` columns). `reflux_ratio_k` is the
        BioSTEAM shortcut multiplier over minimum reflux (x-axis here),
        not an absolute reflux ratio (L/D).
    spec : {'purity', 'recovery'} or None
        Which achieved/target column pair to plot. If None (default),
        it's inferred from whichever of `purity_target`/`recovery_target`
        is actually populated in `df`.
    ylabel : str or None
        Y-axis label. Defaults to `spec.capitalize()`.
    title : str or None
        Plot title. Defaults to `f'{spec.capitalize()} vs Reflux Ratio'`.
    ax : matplotlib.axes.Axes or None
        Axes to plot on. If None, a new figure/axes is created.
    save_path : str or None
        If given, the figure is saved here via `fig.savefig(save_path)`.
    show : bool
        Whether to call `plt.show()` after plotting.

    Returns
    -------
    ax : matplotlib.axes.Axes
    """
    spec, y_col, target_col = _resolve_spec_columns(df, spec)

    if ax is None:
        fig, ax = plt.subplots()
    else:
        fig = ax.figure

    ax.plot(df['reflux_ratio_k'], df[y_col], marker='o', label=spec.capitalize())

    target_values = df[target_col].dropna().unique()
    if len(target_values) == 1:
        ax.axhline(
            target_values[0], linestyle='--', color='gray',
            label=f'{spec.capitalize()} target',
        )
    elif len(target_values) > 1:
        ax.plot(
            df['reflux_ratio_k'], df[target_col], linestyle='--', color='gray',
            label=f'{spec.capitalize()} target',
        )

    # x-axis is k, BioSTEAM's shortcut multiplier over minimum reflux --
    # NOT the absolute reflux ratio (L/D); see df['actual_reflux_ratio_LD'].
    ax.set_xlabel('Reflux Ratio Parameter, k (multiplier over minimum reflux)')
    ax.set_ylabel(ylabel or spec.capitalize())
    ax.set_title(title or f'{spec.capitalize()} vs Reflux Ratio')
    ax.legend()

    if save_path is not None:
        fig.savefig(save_path, bbox_inches='tight')
    if show:
        plt.show()

    return ax


def plot_utility_cost_vs_reflux(
    df,
    title='Utility Cost vs Reflux Ratio',
    ax=None,
    save_path=None,
    show=True,
):
    """
    Plot reboiler heating cost and condenser cooling cost against reflux
    ratio parameter k.

    Parameters
    ----------
    df : pandas.DataFrame
        Output of `sweep_separation.sweep_reflux_ratio` (or any DataFrame
        with `reflux_ratio_k`, `heating_cost_USD_hr`, `cooling_cost_USD_hr`
        columns). `reflux_ratio_k` is the BioSTEAM shortcut multiplier
        over minimum reflux (x-axis here), not an absolute reflux ratio
        (L/D).
    title : str
        Plot title.
    ax : matplotlib.axes.Axes or None
        Axes to plot on. If None, a new figure/axes is created.
    save_path : str or None
        If given, the figure is saved here via `fig.savefig(save_path)`.
    show : bool
        Whether to call `plt.show()` after plotting.

    Returns
    -------
    ax : matplotlib.axes.Axes
    """
    if ax is None:
        fig, ax = plt.subplots()
    else:
        fig = ax.figure

    ax.plot(
        df['reflux_ratio_k'], df['heating_cost_USD_hr'], marker='o',
        label='Heating',
    )
    ax.plot(
        df['reflux_ratio_k'], df['cooling_cost_USD_hr'], marker='o',
        label='Cooling',
    )

    # x-axis is k, BioSTEAM's shortcut multiplier over minimum reflux --
    # NOT the absolute reflux ratio (L/D); see df['actual_reflux_ratio_LD'].
    ax.set_xlabel('Reflux Ratio Parameter, k (multiplier over minimum reflux)')
    ax.set_ylabel('Utility Cost ($/hr)')
    ax.set_title(title)
    ax.legend()

    if save_path is not None:
        fig.savefig(save_path, bbox_inches='tight')
    if show:
        plt.show()

    return ax


def plot_reflux_sweep(df, spec=None, save_dir=None, show=True):
    """
    Convenience wrapper: draws both the purity/recovery-vs-reflux plot and
    the utility-cost-vs-reflux plot for a `sweep_reflux_ratio` DataFrame.

    Parameters
    ----------
    df : pandas.DataFrame
        Output of `sweep_separation.sweep_reflux_ratio`.
    spec : {'purity', 'recovery'} or None
        Passed through to `plot_purity_vs_reflux`; inferred from `df` if
        None.
    save_dir : str or None
        If given, saves `{save_dir}/purity_vs_reflux.png` (or
        `recovery_vs_reflux.png`, depending on `spec`) and
        `{save_dir}/utility_cost_vs_reflux.png`.
    show : bool
        Whether to call `plt.show()` after each plot.

    Returns
    -------
    (ax_performance, ax_utility) : tuple[matplotlib.axes.Axes, matplotlib.axes.Axes]
    """
    resolved_spec, _, _ = _resolve_spec_columns(df, spec)

    performance_save_path = (
        f'{save_dir}/{resolved_spec}_vs_reflux.png' if save_dir else None
    )
    utility_save_path = (
        f'{save_dir}/utility_cost_vs_reflux.png' if save_dir else None
    )

    ax_performance = plot_purity_vs_reflux(
        df, spec=resolved_spec, save_path=performance_save_path, show=show,
    )
    ax_utility = plot_utility_cost_vs_reflux(
        df, save_path=utility_save_path, show=show,
    )

    return ax_performance, ax_utility


if __name__ == '__main__':
    import pandas as pd

    df = pd.read_csv('reflux_ratio_sweep.csv')
    plot_reflux_sweep(df)
