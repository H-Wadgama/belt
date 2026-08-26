"""
Single-point Wankat Case A/B/C/D binary-distillation design executor.

Unlike `optimizer.optimize_reflux_ratio` (which sweeps a range of internal
`k = R/Rmin` multipliers and picks the cheapest feasible one), this module
runs the deterministic engineering layer **once**, at the single reflux
condition the user actually specified per Wankat Table 3-2 -- it is a
direct-design calculation, not a cost search. See
`tools/binary-distillation-context.md` sections 2 and 4 for why these are
different problems, and why the external/actual reflux ratio (L0/D) must
not be treated as equivalent to the internal multiplier k.

This module assumes its caller (`separation_tool.py`) has already run
`problem_spec.validate_problem()` and confirmed the specification is
complete and unambiguous -- it does not re-derive Table 3-1/3-2
completeness itself, only executes the already-identified case. It also
assumes `feed` has already been built with its thermal condition (T,
vapor fraction, or enthalpy) set explicitly by the caller -- this module
never calls `feed.bubble_point_at_P()` or otherwise imposes a feed
condition on the caller's behalf.
"""
from separation_trial import run_separation, check_binary_feed

# Cases the current BioSTEAM shortcut (Fenske-Underwood-Gilliland)
# BinaryDistillation model can actually execute. Case C (a specified
# product flow rate) and Case D (a specified boilup ratio) are correctly
# *identified* by problem_spec.identify_case(), but the underlying shortcut
# column has no way to accept either as an input -- it only solves given
# (xD, xB) or (Lr, Hr) plus a reflux ratio. Rather than silently forcing
# those cases through the Case A/B machinery, they are rejected here with
# an explicit "recognized but not implemented" message.
IMPLEMENTED_CASES = ('A', 'B')


def _extract_minimum_reflux_LD(feed, LHK, P, is_divided, tol, spec_kwargs, trial_ks=(1.5, 2.0, 3.0)):
    """
    Run the shortcut column once (BioSTEAM computes minimum reflux via the
    Underwood equations independent of the k chosen) purely to read back
    `minimum_reflux_ratio_LD`. Tries a few trial k values in case the first
    one fails to converge.
    """
    for i, trial_k in enumerate(trial_ks):
        trial = run_separation(
            feed.copy(), LHK=LHK, reflux_ratio_k=trial_k, P=P,
            is_divided=is_divided, tol=tol, ID=f'_Rmin_trial{i}', **spec_kwargs,
        )
        Rmin = trial['operating_conditions']['minimum_reflux_ratio_LD']
        if trial['error'] is None and Rmin is not None:
            return Rmin, None
    return None, (
        f"Could not determine the minimum reflux ratio for this "
        f"specification (tried trial k values {list(trial_ks)}, all failed "
        f"to converge)."
    )


def design_binary_distillation(
    feed,
    LHK,
    case,
    P=101325,
    xD=None,
    xB=None,
    Lr=None,
    Hr=None,
    external_reflux_ratio_LD=None,
    reflux_ratio_multiplier_k=None,
    target='top',
    is_divided=True,
    tol=1e-3,
    ID='D1',
    lifetime_years=20,
    **design_kwargs,
):
    """
    Execute a single, already-identified Wankat Table 3-2 design case.

    Parameters
    ----------
    feed : bst.Stream
        Feed to the column, with thermal condition (T / vapor fraction /
        enthalpy) already set explicitly by the caller. Must have exactly
        2 nonzero-flow components (checked via
        `separation_trial.check_binary_feed`).
    LHK : tuple[str, str]
        (light_key, heavy_key).
    case : {'A', 'B', 'C', 'D'}
        The design case already identified by
        `problem_spec.identify_case()`. Only 'A' and 'B' are executable by
        the current engineering layer -- 'C' and 'D' return a
        `not_implemented` result rather than an approximate/forced answer.
    xD, xB : float
        Required for case 'A'. Target light-key mole fractions in the
        distillate and bottoms.
    Lr, Hr : float
        Required for case 'B'. Target fractional recovery of the light key
        to the distillate and the heavy key to the bottoms.
    external_reflux_ratio_LD : float or None
        Wankat's external/actual reflux ratio, L0/D. When given, this
        function first determines the column's minimum reflux ratio (Rmin)
        by an internal trial run, then computes and uses
        `k = external_reflux_ratio_LD / Rmin` for the real design run.
        Mutually exclusive with `reflux_ratio_multiplier_k` -- exactly one
        must be given (this is not re-validated here; the caller's
        `problem_spec.validate_problem()` call is what enforces that).
    reflux_ratio_multiplier_k : float or None
        The internal BioSTEAM shortcut-method multiplier k = R/Rmin, used
        directly with no Rmin back-solving. This is NOT the same quantity
        as `external_reflux_ratio_LD` -- see module docstring.
    target : {'top', 'bottom'}
        Passed through to `run_separation` -- which outlet is labeled the
        'product' stream in the result.
    is_divided, tol, ID, lifetime_years, **design_kwargs
        Passed through to `run_separation` unchanged.

    Returns
    -------
    result : dict with keys:
        'case'              : echoed back.
        'implemented'        : bool -- False for 'C'/'D' (see above); when
                                False, no simulation is attempted and only
                                'message' is populated besides this.
        'message'            : str.
        'reflux'             : dict -- present only when implemented:
                                {'external_reflux_ratio_LD',
                                 'reflux_ratio_multiplier_k',
                                 'minimum_reflux_ratio_LD', 'basis'}.
                                'basis' is either
                                'user_specified_external_LD' (converted to
                                k via a measured Rmin) or
                                'user_specified_internal_k' (k used as
                                given, no conversion).
        'design_result'      : dict -- the full `run_separation()` output
                                for the final design run, or None if not
                                implemented or if Rmin extraction/the final
                                run failed (see 'error').
        'error'              : str or None.
    """
    if case not in IMPLEMENTED_CASES:
        return {
            'case': case,
            'implemented': False,
            'message': (
                f"Case {case} was correctly identified (Wankat Table 3-2), "
                f"but the current deterministic engineering layer "
                f"(BioSTEAM's shortcut BinaryDistillation) does not accept "
                f"a direct product-flow-rate specification (Case C) or a "
                f"boilup-ratio specification (Case D) as an input -- this "
                f"is not implemented yet. Case A (xD & xB + external "
                f"reflux ratio) or Case B (recoveries + external reflux "
                f"ratio) are supported today."
            ),
            'reflux': None,
            'design_result': None,
            'error': None,
        }

    check_binary_feed(feed)

    if case == 'A':
        spec_kwargs = dict(spec='purity', target=target, y_top=xD, x_bot=xB)
    else:
        spec_kwargs = dict(spec='recovery', target=target, Lr=Lr, Hr=Hr)

    if external_reflux_ratio_LD is not None:
        Rmin, error = _extract_minimum_reflux_LD(
            feed, LHK, P, is_divided, tol, spec_kwargs,
        )
        if error is not None:
            return {
                'case': case, 'implemented': True, 'message': error,
                'reflux': None, 'design_result': None, 'error': error,
            }
        if external_reflux_ratio_LD <= Rmin:
            error = (
                f"Requested external_reflux_ratio_LD={external_reflux_ratio_LD:.4g} "
                f"is at or below the minimum reflux ratio "
                f"(Rmin={Rmin:.4g}) for this separation -- infeasible "
                f"(would require infinite stages)."
            )
            return {
                'case': case, 'implemented': True, 'message': error,
                'reflux': {
                    'external_reflux_ratio_LD': external_reflux_ratio_LD,
                    'reflux_ratio_multiplier_k': None,
                    'minimum_reflux_ratio_LD': Rmin,
                    'basis': 'user_specified_external_LD',
                },
                'design_result': None, 'error': error,
            }
        k_actual = external_reflux_ratio_LD / Rmin
        reflux_basis = 'user_specified_external_LD'
    else:
        k_actual = reflux_ratio_multiplier_k
        Rmin = None
        reflux_basis = 'user_specified_internal_k'

    design_result = run_separation(
        feed, LHK=LHK, reflux_ratio_k=k_actual, P=P,
        is_divided=is_divided, tol=tol, ID=ID, lifetime_years=lifetime_years,
        **spec_kwargs, **design_kwargs,
    )

    if Rmin is None:
        Rmin = design_result['operating_conditions']['minimum_reflux_ratio_LD']

    return {
        'case': case,
        'implemented': True,
        'message': (
            f"Case {case} design complete "
            f"({'feasible' if design_result['feasible'] else 'NOT feasible/converged'})."
        ),
        'reflux': {
            'external_reflux_ratio_LD': (
                external_reflux_ratio_LD if external_reflux_ratio_LD is not None
                else design_result['operating_conditions']['actual_reflux_ratio_LD']
            ),
            'reflux_ratio_multiplier_k': k_actual,
            'minimum_reflux_ratio_LD': Rmin,
            'basis': reflux_basis,
        },
        'design_result': design_result,
        'error': design_result['error'],
    }


if __name__ == '__main__':
    import biosteam as bst

    bst.settings.set_thermo(['Water', 'Methanol'], cache=True)
    feed = bst.Stream('feed', Water=80, Methanol=100, units='kmol/hr')
    feed.vle(T=350.0, P=101325)  # explicit feed thermal condition -- never bubble-point-defaulted

    print('--- Case A, external_reflux_ratio_LD given (converted to k via Rmin) ---')
    result = design_binary_distillation(
        feed, LHK=('Methanol', 'Water'), case='A', P=101325,
        xD=0.99, xB=0.01, external_reflux_ratio_LD=3.0,
    )
    print(result['message'])
    print('reflux:', result['reflux'])

    print('\n--- Case B, reflux_ratio_multiplier_k given directly (no Rmin conversion) ---')
    feed2 = bst.Stream('feed2', Water=80, Methanol=100, units='kmol/hr')
    feed2.vle(T=350.0, P=101325)
    result2 = design_binary_distillation(
        feed2, LHK=('Methanol', 'Water'), case='B', P=101325,
        Lr=0.99, Hr=0.99, reflux_ratio_multiplier_k=1.5, ID='D2',
    )
    print(result2['message'])
    print('reflux:', result2['reflux'])

    print('\n--- Case C, recognized but not implemented ---')
    result3 = design_binary_distillation(
        feed2, LHK=('Methanol', 'Water'), case='C', P=101325,
    )
    print(result3['message'])
