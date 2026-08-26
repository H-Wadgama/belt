"""
Deterministic input-specification checker for binary distillation problems.

This module implements the structured input-check procedure described in
`tools/binary-distillation-context.md` (Steps 1-5), which is itself based
on:

    Wankat, Phillip C. _Separation Process Engineering: Includes Mass
    Transfer Analysis_. Pearson, 2022.
        Table 3-1 -- Usual specified variables for binary distillation
        Table 3-2 -- Specifications and calculated variables for binary
                      distillation design problems

It contains no BioSTEAM calls and no LLM calls -- it is pure field-presence
logic over a plain dict of user-supplied values, so that:

  * whether Table 3-1's essential inputs are all known, and
  * which Table 3-2 design case (A-D) the remaining specifications match

are both determined **deterministically by this code**, not inferred by an
LLM. Callers (e.g. `separation_tool.py`) are expected to run
`validate_problem()` before building any feed stream or BioSTEAM unit, and
to refuse to proceed -- surfacing `missing_essential_inputs`,
`case_candidates` / `missing_case_inputs_by_candidate`, and `ambiguous` /
`ambiguous_reason` back to the caller -- rather than silently completing an
underspecified problem.
"""

TABLE_3_1_PROVENANCE = (
    "Wankat, P.C. (2022), Separation Process Engineering, Table 3-1 -- "
    "Usual specified variables for binary distillation"
)
TABLE_3_2_PROVENANCE = (
    "Wankat, P.C. (2022), Separation Process Engineering, Table 3-2 -- "
    "Specifications and calculated variables for binary distillation "
    "design problems"
)
FULL_CITATION = (
    "Wankat, Phillip C. Separation Process Engineering: Includes Mass "
    "Transfer Analysis. Pearson, 2022."
)

# The only reflux thermal condition BioSTEAM's shortcut BinaryDistillation
# model actually implements today. Wankat notes saturated-liquid reflux is
# "usual", but per the context doc this must be an explicitly stated
# condition, not an invisible default -- callers must pass this value
# themselves rather than have it assumed for them.
SUPPORTED_REFLUX_CONDITIONS = {'saturated_liquid'}

# Table 3-1 feed thermal condition fields -- exactly one is required.
FEED_THERMAL_FIELDS = ('feed_temperature_K', 'feed_quality', 'feed_enthalpy_kJ_per_hr')

CASE_FIELD_SUMMARY = {
    'A': "xD + xB + external reflux ratio (L0/D) + optimum feed plate",
    'B': "fractional recoveries (Lr, Hr) + external reflux ratio (L0/D) + optimum feed plate",
    'C': "one product flow (distillate_flow or bottoms_flow) + one composition (xD or xB) "
         "+ external reflux ratio (L0/D) + optimum feed plate",
    'D': "xD + xB + boilup ratio (V/B) + optimum feed plate",
}


def check_essential_inputs(spec):
    """
    Step 1 of the context doc's procedure: check the Table 3-1 "usual
    specified variables" are all present in `spec`.

    Parameters
    ----------
    spec : dict
        Raw user-supplied fields. Recognized keys checked here:
        'pressure_Pa', 'components' (dict of component -> flow, standing in
        for feed flow rate + feed composition), 'feed_temperature_K',
        'feed_quality', 'feed_enthalpy_kJ_per_hr' (exactly one of these
        three is the feed thermal condition), and 'reflux_condition'.

    Returns
    -------
    dict with keys:
        'missing'                : list[str] -- human-readable names of
                                    essential inputs that are absent.
        'given_thermal_fields'   : list[str] -- which of the three feed
                                    thermal-condition fields were supplied.
        'ambiguous_thermal'      : bool -- True if more than one feed
                                    thermal-condition field was supplied
                                    (over-specified, not just under).
        'invalid_reflux_condition' : bool -- True if `reflux_condition`
                                    was supplied but isn't one of
                                    SUPPORTED_REFLUX_CONDITIONS.
    """
    missing = []

    if spec.get('pressure_Pa') is None:
        missing.append('pressure_Pa (column pressure)')

    components = spec.get('components')
    valid_components = (
        isinstance(components, dict)
        and sum(1 for v in components.values() if v and v > 0) >= 2
    )
    if not valid_components:
        missing.append(
            'components (feed flow rate + feed composition -- at least 2 '
            'nonzero-flow components)'
        )

    given_thermal = [f for f in FEED_THERMAL_FIELDS if spec.get(f) is not None]
    ambiguous_thermal = False
    if len(given_thermal) == 0:
        missing.append(
            'feed thermal condition (exactly one of feed_temperature_K, '
            'feed_quality, or feed_enthalpy_kJ_per_hr -- this must be '
            'stated explicitly and is never assumed, e.g. never defaulted '
            'to bubble point)'
        )
    elif len(given_thermal) > 1:
        ambiguous_thermal = True

    reflux_condition = spec.get('reflux_condition')
    invalid_reflux_condition = False
    if reflux_condition is None:
        missing.append(
            "reflux_condition (state explicitly, e.g. 'saturated_liquid' -- "
            "Wankat notes this is the usual condition, but it must be an "
            "identified/stated condition, never a silent default)"
        )
    elif reflux_condition not in SUPPORTED_REFLUX_CONDITIONS:
        invalid_reflux_condition = True

    return {
        'missing': missing,
        'given_thermal_fields': given_thermal,
        'ambiguous_thermal': ambiguous_thermal,
        'invalid_reflux_condition': invalid_reflux_condition,
    }


def identify_case(spec):
    """
    Step 2-3 of the context doc's procedure: deterministically match the
    Table 3-2 design-specification fields in `spec` against Cases A-D.

    This never asks an LLM to infer the case -- it is pure presence/absence
    logic over the following keys (all optional on input; `None`/absent
    means "not given"):

        xD, xB                         -- Case A/D compositions
        Lr, Hr                         -- Case B recoveries
        distillate_flow, bottoms_flow  -- Case C product flow (exactly one)
        boilup_ratio_VB                -- Case D boilup ratio
        external_reflux_ratio_LD       -- Wankat's L0/D (Cases A-C)
        reflux_ratio_multiplier_k      -- internal BioSTEAM shortcut-method
                                           parameter k = R/Rmin. This is
                                           NOT the same quantity as
                                           external_reflux_ratio_LD (see
                                           tools/binary-distillation-context.md
                                           section 4) and is treated as a
                                           distinct field throughout.

    Returns
    -------
    dict with keys:
        'case'                : 'A'|'B'|'C'|'D'|None -- the single fully
                                 satisfied case, or None if zero or more
                                 than one case is fully satisfied.
        'ambiguous'            : bool -- True if the given fields directly
                                 conflict (e.g. both external_reflux_ratio_LD
                                 and reflux_ratio_multiplier_k given; both
                                 recoveries and compositions given).
        'ambiguous_reason'     : str or None.
        'candidates'           : list[str] -- case letters still consistent
                                 with the fields given so far (used when
                                 `case` is None and not ambiguous, i.e. the
                                 spec is merely incomplete).
        'missing_by_candidate' : dict[str, list[str]] -- for each candidate
                                 case, which of its fields are still absent.
    """
    have = {
        key: spec.get(key) is not None
        for key in (
            'xD', 'xB', 'Lr', 'Hr', 'distillate_flow', 'bottoms_flow',
            'boilup_ratio_VB', 'external_reflux_ratio_LD',
            'reflux_ratio_multiplier_k',
        )
    }

    reflux_given = int(have['external_reflux_ratio_LD']) + int(have['reflux_ratio_multiplier_k'])
    flow_given = int(have['distillate_flow']) + int(have['bottoms_flow'])
    comp_given = int(have['xD']) + int(have['xB'])
    recovery_given = int(have['Lr']) + int(have['Hr'])

    conflicts = []
    if reflux_given == 2:
        conflicts.append(
            "both external_reflux_ratio_LD and reflux_ratio_multiplier_k were "
            "given, but these are different quantities -- L0/D is Wankat's "
            "external/actual reflux ratio (Table 3-2), while k = R/Rmin is "
            "an internal BioSTEAM shortcut-method parameter. Supply exactly "
            "one."
        )
    if flow_given == 2:
        conflicts.append(
            "both distillate_flow and bottoms_flow were given -- Case C "
            "(Wankat Table 3-2) specifies exactly one product flow rate, "
            "with the other calculated."
        )
    if have['boilup_ratio_VB'] and reflux_given > 0:
        conflicts.append(
            "boilup_ratio_VB (Case D) was given together with an external "
            "reflux ratio / k (Cases A-C) -- these belong to different, "
            "mutually exclusive design cases."
        )
    if recovery_given > 0 and comp_given > 0:
        conflicts.append(
            "fractional recoveries (Case B) were given together with "
            "distillate/bottoms compositions (Cases A/C/D) -- pick one "
            "specification basis."
        )
    if recovery_given > 0 and flow_given > 0:
        conflicts.append(
            "fractional recoveries (Case B) were given together with a "
            "product flow rate (Case C) -- pick one specification basis."
        )
    if recovery_given > 0 and have['boilup_ratio_VB']:
        conflicts.append(
            "fractional recoveries (Case B) were given together with "
            "boilup_ratio_VB (Case D) -- pick one specification basis."
        )

    if conflicts:
        return {
            'case': None,
            'ambiguous': True,
            'ambiguous_reason': ' '.join(conflicts),
            'candidates': [],
            'missing_by_candidate': {},
        }

    candidates = {}

    # Case A -- xD, xB, external reflux ratio (or its internal k substitute)
    if comp_given <= 2 and recovery_given == 0 and flow_given == 0 and not have['boilup_ratio_VB']:
        missing = []
        if not have['xD']:
            missing.append('xD')
        if not have['xB']:
            missing.append('xB')
        if reflux_given == 0:
            missing.append('external_reflux_ratio_LD (or reflux_ratio_multiplier_k)')
        candidates['A'] = missing

    # Case B -- fractional recoveries, external reflux ratio (or k)
    if recovery_given <= 2 and comp_given == 0 and flow_given == 0 and not have['boilup_ratio_VB']:
        missing = []
        if not have['Lr']:
            missing.append('Lr')
        if not have['Hr']:
            missing.append('Hr')
        if reflux_given == 0:
            missing.append('external_reflux_ratio_LD (or reflux_ratio_multiplier_k)')
        candidates['B'] = missing

    # Case C -- one product flow, one composition, external reflux ratio (or k)
    if comp_given <= 1 and flow_given <= 1 and recovery_given == 0 and not have['boilup_ratio_VB']:
        missing = []
        if comp_given == 0:
            missing.append('xD or xB')
        if flow_given == 0:
            missing.append('distillate_flow or bottoms_flow')
        if reflux_given == 0:
            missing.append('external_reflux_ratio_LD (or reflux_ratio_multiplier_k)')
        candidates['C'] = missing

    # Case D -- xD, xB, boilup ratio (no reflux ratio at all)
    if comp_given <= 2 and recovery_given == 0 and flow_given == 0 and reflux_given == 0:
        missing = []
        if not have['xD']:
            missing.append('xD')
        if not have['xB']:
            missing.append('xB')
        if not have['boilup_ratio_VB']:
            missing.append('boilup_ratio_VB')
        candidates['D'] = missing

    complete = [c for c, missing in candidates.items() if not missing]

    if len(complete) == 1:
        return {
            'case': complete[0],
            'ambiguous': False,
            'ambiguous_reason': None,
            'candidates': [complete[0]],
            'missing_by_candidate': {},
        }

    if len(complete) > 1:
        # Should not happen given the conflict checks above, but never
        # silently pick one on the caller's behalf if it does.
        return {
            'case': None,
            'ambiguous': True,
            'ambiguous_reason': (
                f"the given fields fully satisfy more than one design case "
                f"at once ({', '.join(complete)}) -- this should not be "
                f"possible and indicates conflicting specifications."
            ),
            'candidates': complete,
            'missing_by_candidate': {},
        }

    return {
        'case': None,
        'ambiguous': False,
        'ambiguous_reason': None,
        'candidates': sorted(candidates),
        'missing_by_candidate': candidates,
    }


def _build_message(essential, case_info, valid):
    if valid:
        return f"Fully specified as Case {case_info['case']} ({TABLE_3_2_PROVENANCE})."

    parts = []
    if essential['missing']:
        parts.append(
            "Missing essential inputs (" + TABLE_3_1_PROVENANCE + "): "
            + '; '.join(essential['missing'])
        )
    if essential['ambiguous_thermal']:
        parts.append(
            "Ambiguous: more than one feed thermal condition was given "
            "(feed_temperature_K, feed_quality, feed_enthalpy_kJ_per_hr are "
            "mutually exclusive) -- supply exactly one."
        )
    if essential['invalid_reflux_condition']:
        parts.append(
            "reflux_condition given is not supported -- only "
            f"{sorted(SUPPORTED_REFLUX_CONDITIONS)} is implemented today."
        )

    if case_info['ambiguous']:
        parts.append(f"Ambiguous design specification: {case_info['ambiguous_reason']}")
    elif case_info['case'] is None:
        if case_info['candidates']:
            candidate_lines = '; '.join(
                f"Case {c} needs: {', '.join(case_info['missing_by_candidate'][c])}"
                for c in case_info['candidates']
            )
            parts.append(
                f"Design specification incomplete ({TABLE_3_2_PROVENANCE}). "
                f"Still-possible cases and what each still needs: {candidate_lines}."
            )
        else:
            parts.append(
                f"Design specification incomplete ({TABLE_3_2_PROVENANCE}). "
                f"Provide fields matching one of: "
                + '; '.join(f"Case {c} = {desc}" for c, desc in CASE_FIELD_SUMMARY.items())
                + '.'
            )

    return ' '.join(parts)


def validate_problem(spec):
    """
    Run the full Step 1-3 structured input check from
    `tools/binary-distillation-context.md` on `spec` and return a single
    report. Never raises -- callers should check `valid` before proceeding
    to build a feed stream or run any BioSTEAM calculation.

    Parameters
    ----------
    spec : dict
        See `check_essential_inputs` and `identify_case` for the full set
        of recognized keys.

    Returns
    -------
    dict with keys:
        'valid'                          : bool -- True only if all Table
                                            3-1 essentials are present, the
                                            feed thermal condition and
                                            reflux condition are each
                                            unambiguous, and exactly one
                                            Table 3-2 case is fully
                                            satisfied.
        'case'                           : 'A'|'B'|'C'|'D'|None.
        'case_candidates'                : list[str] -- cases still
                                            possible given what was
                                            supplied (only populated when
                                            incomplete, not ambiguous).
        'missing_essential_inputs'       : list[str].
        'missing_case_inputs_by_candidate' : dict[str, list[str]].
        'ambiguous'                      : bool.
        'ambiguous_reason'               : str or None.
        'message'                        : str -- human-readable summary,
                                            safe to surface directly to a
                                            user or LLM.
        'provenance'                     : dict -- Table 3-1/3-2 citation
                                            metadata, retained per
                                            tools/binary-distillation-context.md
                                            section 9.
    """
    essential = check_essential_inputs(spec)
    case_info = identify_case(spec)

    valid = (
        not essential['missing']
        and not essential['ambiguous_thermal']
        and not essential['invalid_reflux_condition']
        and case_info['case'] is not None
        and not case_info['ambiguous']
    )

    ambiguous = essential['ambiguous_thermal'] or case_info['ambiguous']
    ambiguous_reason = case_info['ambiguous_reason']
    if essential['ambiguous_thermal']:
        thermal_msg = "more than one feed thermal condition was supplied"
        ambiguous_reason = thermal_msg if not ambiguous_reason else f"{thermal_msg}; {ambiguous_reason}"

    message = _build_message(essential, case_info, valid)

    return {
        'valid': valid,
        'case': case_info['case'],
        'case_candidates': case_info['candidates'],
        'missing_essential_inputs': essential['missing'],
        'missing_case_inputs_by_candidate': case_info['missing_by_candidate'],
        'ambiguous': ambiguous,
        'ambiguous_reason': ambiguous_reason,
        'message': message,
        'provenance': {
            'essential_inputs': TABLE_3_1_PROVENANCE,
            'design_cases': TABLE_3_2_PROVENANCE,
            'citation': FULL_CITATION,
        },
    }


if __name__ == '__main__':
    print('--- Nothing given ---')
    print(validate_problem({})['message'])

    print('\n--- Case A, complete ---')
    print(validate_problem({
        'pressure_Pa': 101325, 'components': {'Methanol': 100, 'Water': 80},
        'feed_temperature_K': 350.0, 'reflux_condition': 'saturated_liquid',
        'xD': 0.99, 'xB': 0.01, 'external_reflux_ratio_LD': 3.0,
    })['message'])

    print('\n--- Case A, missing xB ---')
    print(validate_problem({
        'pressure_Pa': 101325, 'components': {'Methanol': 100, 'Water': 80},
        'feed_temperature_K': 350.0, 'reflux_condition': 'saturated_liquid',
        'xD': 0.99, 'external_reflux_ratio_LD': 3.0,
    })['message'])

    print('\n--- Ambiguous: both LD and k given ---')
    print(validate_problem({
        'pressure_Pa': 101325, 'components': {'Methanol': 100, 'Water': 80},
        'feed_temperature_K': 350.0, 'reflux_condition': 'saturated_liquid',
        'xD': 0.99, 'xB': 0.01, 'external_reflux_ratio_LD': 3.0,
        'reflux_ratio_multiplier_k': 2.0,
    })['message'])

    print('\n--- Missing feed thermal condition entirely ---')
    print(validate_problem({
        'pressure_Pa': 101325, 'components': {'Methanol': 100, 'Water': 80},
        'reflux_condition': 'saturated_liquid',
        'xD': 0.99, 'xB': 0.01, 'external_reflux_ratio_LD': 3.0,
    })['message'])
