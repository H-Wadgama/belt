"""
Binary-distillation workflow checker -- see `tools/binary-distillation-workflow.md`.

This module implements the workflow-only refactor described in that
document: a deterministic, LLM-free checker that recognizes whether a
requested separation is genuinely binary, collects the mandatory binary-
distillation inputs, identifies which Wankat design case (A-D) the supplied
specifications correspond to, and reports what a designer WOULD calculate
once the problem is fully specified -- without ever running a BioSTEAM
calculation itself.

It contains no BioSTEAM calls and no LLM calls, same as `problem_spec.py`
(which it wraps and reuses for the Table 3-1/Table 3-2 field-presence
logic). The one function this module exposes,
`assess_binary_distillation_problem()`, is meant to be the terminal
engineering tool for this development phase -- see
`binary_distillation_workflow_agent.py` for the isolated tool-calling agent
that exposes only this function to an LLM (Option C,
tools/binary-distillation-workflow.md section 18).

    Wankat, Phillip C. _Separation Process Engineering: Includes Mass
    Transfer Analysis_. Pearson, 2022.
        Table 3-1 -- Usual specified variables for binary distillation
        Table 3-2 -- Specifications and calculated variables for binary
                      distillation design problems
"""
from feed_state import (
    apply_user_update,
    assess_feed_state,
    empty_feed_state,
)
from problem_spec import (
    CASE_FIELD_SUMMARY,
    FULL_CITATION,
    SUPPORTED_REFLUX_CONDITIONS,
    TABLE_3_1_PROVENANCE,
    TABLE_3_2_PROVENANCE,
    check_essential_inputs,
    identify_case,
)

PROVENANCE = {
    'source': FULL_CITATION,
    'essential_inputs': TABLE_3_1_PROVENANCE,
    'design_cases': TABLE_3_2_PROVENANCE,
}

# What a designer would calculate once each case is fully specified --
# tools/binary-distillation-workflow.md section 8. Case C's calculated set
# depends on WHICH product flow/composition was given (the other one is
# calculated), so it is built dynamically in `_would_calculate` below rather
# than listed statically here.
_WOULD_CALCULATE_ABD = ['D', 'B', 'QR', 'Qc', 'N', 'Nfeed (optimum feed stage)', 'column diameter']
WOULD_CALCULATE_BY_CASE = {
    'A': list(_WOULD_CALCULATE_ABD),
    'B': ['xD', 'xB', *_WOULD_CALCULATE_ABD],
    'D': list(_WOULD_CALCULATE_ABD),
}

# Case A-D fields that identify which case is being specified -- used only
# to distinguish "nothing case-specific stated yet" (explain the four
# options) from "some case-specific field given, but that candidate is
# still incomplete" (ask only for what's missing). optimum-feed-plate use
# is deliberately excluded: it is common to all four cases and carries zero
# case-identification signal (section 9 of the workflow doc).
_CASE_SIGNAL_FIELDS = (
    'xD', 'xB', 'Lr', 'Hr', 'distillate_flow', 'bottoms_flow', 'boilup_ratio_VB',
)

# tools/binary-distillation-pending-truth.md -- deterministic pending-request
# generation. `pending_request` is never stored as separate mutable state; it
# is recomputed fresh on every call from whatever `spec` currently holds, so
# it is automatically correct/absent whenever the accumulated problem changes
# or is reset (section 10) with no extra invalidation logic needed. Fields
# whose missing-ness is inherently a choice between two things (e.g. "xD or
# xB", "external_reflux_ratio_LD (or reflux_ratio_multiplier_k)") are never
# turned into a pending_request -- per section 8, don't guess which of two
# equally unresolved fields a short reply is meant to answer.
_PLAIN_CASE_FIELDS = {'xD', 'xB', 'Lr', 'Hr', 'distillate_flow', 'bottoms_flow', 'boilup_ratio_VB'}

_CASE_FIELD_META = {
    'xD': {'prompt': 'What is the target distillate light-key mole fraction, xD?',
           'constraints': {'min': 0, 'max': 1}},
    'xB': {'prompt': 'What is the target bottoms light-key mole fraction, xB?',
           'constraints': {'min': 0, 'max': 1}},
    'Lr': {'prompt': 'What is the target fractional recovery of the light key to the distillate, Lr?',
           'constraints': {'min': 0, 'max': 1}},
    'Hr': {'prompt': 'What is the target fractional recovery of the heavy key to the bottoms, Hr?',
           'constraints': {'min': 0, 'max': 1}},
    'distillate_flow': {'prompt': 'What is the specified distillate flow rate?'},
    'bottoms_flow': {'prompt': 'What is the specified bottoms flow rate?'},
    'boilup_ratio_VB': {'prompt': 'What is the specified boilup ratio, V/B?'},
}

_ESSENTIAL_FIELD_META = {
    'pressure_Pa': {'prompt': 'What is the column pressure, in Pa?'},
    'reflux_condition': {
        'prompt': "Please confirm the reflux thermal condition (currently only 'saturated_liquid' is supported).",
        'allowed_values': ['saturated_liquid'],
    },
}


def _case_pending_request(case_candidates, missing_by_candidate):
    """
    Build a pending_request for the case-input stage (section 7/8/18),
    but ONLY when exactly one case candidate remains and every field it
    still needs is a plain, unambiguous field -- never when multiple
    candidates remain (which field applies depends on which case the user
    ultimately picks) or when a remaining item is an "X or Y" choice.
    """
    if len(case_candidates) != 1:
        return None
    missing = missing_by_candidate.get(case_candidates[0], [])
    if not missing or any(m not in _PLAIN_CASE_FIELDS for m in missing):
        return None
    if len(missing) == 1:
        field = missing[0]
        request = {'field': field, 'request_type': 'float', 'prompt': _CASE_FIELD_META[field]['prompt']}
        if 'constraints' in _CASE_FIELD_META[field]:
            request['constraints'] = _CASE_FIELD_META[field]['constraints']
        return request
    return {
        'fields': list(missing),
        'request_type': 'ordered_float_group',
        'prompt': 'Please provide ' + ', then '.join(missing) + '.',
    }


def _essential_pending_request(other_missing, feed_incomplete, ambiguous_thermal, invalid_reflux_condition):
    """
    Build a pending_request for a single missing Table 3-1 essential.
    Feed quantity is multi-field and is left to the existing conversational
    follow-up rather than guessed at here. The feed thermal condition is a
    three-way choice (feed_temperature_K/feed_quality/feed_enthalpy_kJ_per_hr)
    -- this function still does not guess WHICH of the three a bare short
    reply answers, so it never generates a 'boolean_confirmation'-style
    pending_request for it. It DOES report the field as
    `request_type: 'temperature_K'` (tools/binary-distillation-temperature-issue.md
    Step 5) -- the resolver for that type only ever resolves an unambiguous,
    explicitly Kelvin-suffixed reply (e.g. '355 K'), never a bare number,
    so a reply naming feed_quality or feed_enthalpy instead is still left
    to normal model-driven routing rather than being forced through.
    """
    if feed_incomplete or ambiguous_thermal or invalid_reflux_condition or len(other_missing) != 1:
        return None
    missing_item = other_missing[0]
    if missing_item.startswith('pressure_Pa'):
        return {'field': 'pressure_Pa', 'request_type': 'float', 'prompt': _ESSENTIAL_FIELD_META['pressure_Pa']['prompt']}
    if missing_item.startswith('reflux_condition'):
        meta = _ESSENTIAL_FIELD_META['reflux_condition']
        return {'field': 'reflux_condition', 'request_type': 'string_choice', 'prompt': meta['prompt'], 'allowed_values': meta['allowed_values']}
    if missing_item.startswith('feed thermal condition'):
        return {
            'field': 'feed_temperature_K',
            'request_type': 'temperature_K',
            'prompt': (
                'What is the feed thermal condition? If you know the feed '
                'temperature, give it in Kelvin (e.g. "355 K") -- otherwise '
                'state the feed quality (0-1) or feed enthalpy instead.'
            ),
        }
    return None


_OPTIMUM_FEED_PLATE_PENDING_REQUEST = {
    'field': 'use_optimum_feed_plate',
    'request_type': 'boolean_confirmation',
    'prompt': 'Should the design use the optimum feed plate?',
    'allowed_values': [True, False],
}

# tools/binary-distillation-flow-units.md -- calculation-specific inputs.
# These are requirements of the downstream BioSTEAM feed adapter
# (`biosteam_feed.build_biosteam_feed`), NOT new Wankat Table 3-1
# essentials -- checked in a separate layer, after `essential_complete`,
# so the two concepts stay conceptually distinct (Step 1).
_CALCULATION_INPUT_FIELD_META = {
    'component_flow_units': {'prompt': 'What units are the component flow rates in?'},
    'total_flow_units': {'prompt': 'What units is the total feed flow rate in?'},
}

_CALCULATION_INPUT_MESSAGES = {
    'component_flow_units': (
        'The binary-distillation problem definition is complete, but '
        'component flow-rate units are required before the BioSTEAM '
        'calculation can run.'
    ),
    'total_flow_units': (
        'The binary-distillation problem definition is complete, but the '
        'total feed flow-rate units are required before the BioSTEAM '
        'calculation can run.'
    ),
}


def check_calculation_inputs(feed_state):
    """
    tools/binary-distillation-flow-units.md Step 2. Deterministically
    checks whether the normalized `feed_state` (as returned by
    `feed_state.assess_feed_state`) carries the flow-rate units the
    downstream calculation adapter (`biosteam_feed.build_biosteam_feed`)
    actually needs to construct a `bst.Stream` -- `component_flow_units`
    if `component_flows`.

    Because `feed_state.normalize_feed_state` derives `component_flows`
    for BOTH representations once the feed is complete (per-component
    flows given directly, or total_flow + composition given instead), a
    plain presence check on `component_flows` can't tell which
    representation the user actually supplied. This checks PROVENANCE
    instead: whichever of `component_flows`/`total_flow` carries
    'user_explicit' entries is the representation actually used, and
    that is the one whose units field is required. `build_biosteam_feed`
    itself only ever needs ONE of `component_flow_units`/`total_flow_units`
    to be present (it accepts either), so this only ever reports at most
    one missing field.

    Never defaults a unit, never reads one from conversation history --
    only what's already present in `feed_state` counts.

    Returns
    -------
    dict with keys 'complete' (bool) and 'missing' (list[str], at most
    one entry: 'component_flow_units' or 'total_flow_units').
    """
    missing = []
    has_units = bool(feed_state.get('component_flow_units')) or bool(feed_state.get('total_flow_units'))
    if not has_units:
        used_component_flows = any(
            prov == 'user_explicit'
            for prov in (feed_state.get('component_flows_provenance') or {}).values()
        )
        used_total_flow_only = (
            feed_state.get('total_flow_provenance') == 'user_explicit' and not used_component_flows
        )
        missing.append('total_flow_units' if used_total_flow_only else 'component_flow_units')
    return {'complete': not missing, 'missing': missing}


def _calculation_pending_request(missing_calculation_inputs):
    """
    Step 4: a deterministic pending_request for a missing calculation
    input, ONLY when exactly one is missing -- `check_calculation_inputs`
    never reports more than one, so this is really just a lookup, but the
    length guard is kept for the same reason as `_case_pending_request`:
    never guess between two genuinely ambiguous fields.
    """
    if len(missing_calculation_inputs) != 1:
        return None
    field = missing_calculation_inputs[0]
    meta = _CALCULATION_INPUT_FIELD_META.get(field)
    if meta is None:
        return None
    return {'field': field, 'request_type': 'flow_units', 'prompt': meta['prompt']}


def check_binary_scope(component_names):
    """
    Section 2 of tools/binary-distillation-workflow.md -- the first gate.
    Updated per tools/binary-distillation-flow-rate-issue.md: scope is
    determined by component IDENTITY alone, never by whether a flow rate
    is known for each -- naming two components is enough to be "in scope"
    even before either one's flow rate has been given.

    Counts distinct names in `component_names` (a list, or None/empty if
    not given yet) and reports exactly one of: need a first component,
    need a second component, reject as unsupported multicomponent, or
    proceed. Never silently drops components to force a feed into scope.

    Returns
    -------
    dict with keys 'valid_binary_scope', 'component_count', 'components'
    (the component names given, in order), 'status', 'message'.
    'status'/'message' are None when `valid_binary_scope` is True.
    """
    present = list(component_names or [])

    n = len(present)
    if n == 0:
        return {
            'valid_binary_scope': False, 'component_count': 0, 'components': present,
            'status': 'need_components',
            'message': 'Please specify the two components you want to separate.',
        }
    if n == 1:
        return {
            'valid_binary_scope': False, 'component_count': 1, 'components': present,
            'status': 'need_components',
            'message': (
                f"Binary distillation requires two components. You have "
                f"specified {present[0]}. Please specify the second component."
            ),
        }
    if n > 2:
        return {
            'valid_binary_scope': False, 'component_count': n, 'components': present,
            'status': 'unsupported_multicomponent',
            'message': (
                f"The current system supports binary distillation only. You "
                f"specified {', '.join(present)}. Please define a separation "
                f"containing exactly two components."
            ),
        }
    return {
        'valid_binary_scope': True, 'component_count': 2, 'components': present,
        'status': None, 'message': None,
    }


def _no_case_signal_given(spec):
    """True if none of the case-distinguishing fields have been given at all -- distinguishes 'explain the four Case A-D options' from 'narrow down what this partial candidate still needs' (workflow doc section 16)."""
    return all(spec.get(f) is None for f in _CASE_SIGNAL_FIELDS)


def _would_calculate(case, spec):
    """What a designer would calculate for a fully-specified `case`, given `spec` (section 8; Case C depends on which of D/B and xD/xB was actually supplied)."""
    if case != 'C':
        return list(WOULD_CALCULATE_BY_CASE[case])
    calc = []
    calc.append('B (bottoms flow)' if spec.get('distillate_flow') is not None else 'D (distillate flow)')
    calc.append('xB' if spec.get('xD') is not None else 'xD')
    calc += ['QR', 'Qc', 'N', 'Nfeed (optimum feed stage)', 'column diameter']
    return calc


def _base_report(scope, essential_complete=False, missing_essential_inputs=None,
                  case=None, case_candidates=None, case_complete=False,
                  missing_case_inputs=None, optimum_feed_plate_confirmed=None,
                  calculation_inputs_complete=False, missing_calculation_inputs=None,
                  status=None, would_calculate=None, message='', feed=None,
                  feed_flow_complete=False, feed_composition_complete=False,
                  pending_request=None):
    return {
        'valid_binary_scope': scope['valid_binary_scope'],
        'component_count': scope['component_count'],
        'components': scope['components'],
        'feed_flow_complete': feed_flow_complete,
        'feed_composition_complete': feed_composition_complete,
        'feed': feed,
        'essential_complete': essential_complete,
        'missing_essential_inputs': missing_essential_inputs or [],
        'case': case,
        'case_candidates': case_candidates or [],
        'case_complete': case_complete,
        'missing_case_inputs': missing_case_inputs or {},
        'optimum_feed_plate_confirmed': optimum_feed_plate_confirmed,
        # tools/binary-distillation-flow-units.md -- calculation-adapter
        # readiness, conceptually separate from Wankat `essential_complete`/
        # `case_complete` above. False/[] by default at every earlier
        # stage; only meaningful once essentials+case+optimum-feed-plate
        # are otherwise fully satisfied (see the bottom of
        # assess_binary_distillation_problem).
        'calculation_inputs_complete': calculation_inputs_complete,
        'missing_calculation_inputs': missing_calculation_inputs or [],
        'status': status,
        'would_calculate': would_calculate or [],
        'calculation_performed': False,
        'message': message,
        'provenance': PROVENANCE,
        # tools/binary-distillation-pending-truth.md -- deterministically
        # identifies the ONE specific field (or ordered field group) this
        # report is currently asking for, or None. Always recomputed fresh
        # from `spec` (never separately stored/mutated), so it is
        # automatically absent/correct after a reset or a problem change.
        'pending_request': pending_request,
    }


def _feed_quantity_message(feed):
    """
    Human-readable explanation of what's known and what's still missing
    about the feed's flow rate/composition -- issue doc section 9:
    distinguishes "nothing given" from "something given, but insufficient",
    and never implies a partial quantity (e.g. one component's flow) has
    been treated as the total feed flow.
    """
    explicit_flows = {
        n: v for n, v in feed['component_flows'].items()
        if feed['component_flows_provenance'].get(n) == 'user_explicit'
    }
    explicit_comp = {
        n: v for n, v in feed['composition'].items()
        if feed['composition_provenance'].get(n) == 'user_explicit'
    }

    if not explicit_flows and not explicit_comp and feed['total_flow'] is None:
        return (
            'The binary feed flow rate and composition have not been given '
            'yet.'
        )

    known_parts = []
    if explicit_flows:
        units = f" {feed['component_flow_units']}" if feed['component_flow_units'] else ''
        known_parts.append(', '.join(f"{n} = {v:g}{units}" for n, v in explicit_flows.items()))
    if feed['total_flow_provenance'] == 'user_explicit':
        units = f" {feed['total_flow_units']}" if feed['total_flow_units'] else ''
        known_parts.append(f"total feed flow = {feed['total_flow']:g}{units}")
    if explicit_comp:
        known_parts.append(', '.join(f"{n} = {v:g} mole fraction" for n, v in explicit_comp.items()))

    return (
        f"I know {'; '.join(known_parts)}, but the overall binary feed is "
        f"not yet fully defined. I still need enough information to "
        f"determine the total feed flow and composition -- for example, "
        f"the other component's flow rate, or the total feed flow together "
        f"with sufficient composition information."
    )


def assess_binary_distillation_problem(spec):
    """
    Deterministically assess a binary-distillation problem-definition
    request against Wankat Table 3-1/3-2, and report -- without ever
    performing a distillation calculation -- whether it's ready, what's
    still missing, and (once ready) what a designer would calculate.

    See `tools/binary-distillation-workflow.md` for the full specification
    this implements (sections 1-16), and section 15/19 in particular for
    this function's return schema and the acceptance tests it must satisfy.

    Parameters
    ----------
    spec : dict
        Accumulated problem state (see `binary_distillation_workflow_agent.py`
        for cross-turn accumulation). Feed identity/quantity is recognized
        via the separated fields `feed_state.apply_user_update` understands
        -- 'component_names', 'add_component_names', 'component_flows',
        'component_flow_units', 'total_flow', 'total_flow_units',
        'composition', 'composition_basis' (see `feed_state.py`; a
        component name never implies a flow, and a single component's flow
        is never treated as the total feed flow). Also recognized: every
        field `problem_spec.check_essential_inputs` and
        `problem_spec.identify_case` look at (pressure_Pa,
        feed_temperature_K/feed_quality/feed_enthalpy_kJ_per_hr,
        reflux_condition, xD, xB, Lr, Hr, distillate_flow, bottoms_flow,
        boilup_ratio_VB, external_reflux_ratio_LD,
        reflux_ratio_multiplier_k), plus `use_optimum_feed_plate` (bool or
        None).

    Returns
    -------
    dict -- see module docstring / section 15 of the workflow doc, plus
    'feed_flow_complete', 'feed_composition_complete', and 'feed' (the
    normalized feed state, including per-quantity provenance) from
    tools/binary-distillation-flow-rate-issue.md section 8/10, plus
    'pending_request' (dict or None) from
    tools/binary-distillation-pending-truth.md section 2/18 -- the single
    field (`{'field', 'request_type', 'prompt', ...}`) or ordered field
    group (`{'fields', 'request_type': 'ordered_float_group', 'prompt'}`)
    this report is currently asking for, or None when nothing is
    unambiguously pending, plus 'calculation_inputs_complete' and
    'missing_calculation_inputs' from
    tools/binary-distillation-flow-units.md -- a calculation-adapter
    readiness layer checked AFTER `essential_complete`/`case_complete`/
    `optimum_feed_plate_confirmed` are all True, conceptually separate
    from those Wankat Table 3-1/3-2 concepts. `status` is only ever
    'ready_for_calculation' once `calculation_inputs_complete` is also
    True; otherwise (missing `component_flow_units`/`total_flow_units`)
    `status` is 'need_calculation_inputs' instead, with
    `pending_request` naming the missing units field when exactly one is
    missing. Never raises. `calculation_performed` is always False.
    """
    feed = apply_user_update(empty_feed_state(), spec)
    scope = check_binary_scope(feed['component_names'])
    if not scope['valid_binary_scope']:
        return _base_report(scope, status=scope['status'], message=scope['message'], feed=feed)

    assessed = assess_feed_state(feed)
    feed = assessed['state']
    if assessed['conflicts']:
        return _base_report(
            scope, feed=feed,
            feed_flow_complete=assessed['feed_flow_complete'],
            feed_composition_complete=assessed['feed_composition_complete'],
            status='inconsistent_input',
            message='Inconsistent feed information given: ' + ' '.join(assessed['conflicts']),
        )

    essential_spec = dict(spec)
    essential_spec['components'] = assessed['components']
    essential = check_essential_inputs(essential_spec)
    other_missing = [m for m in essential['missing'] if not m.startswith('components')]
    feed_incomplete = not (assessed['feed_flow_complete'] and assessed['feed_composition_complete'])

    essential_complete = (
        not feed_incomplete
        and not other_missing
        and not essential['ambiguous_thermal']
        and not essential['invalid_reflux_condition']
    )
    if not essential_complete:
        missing_essential_inputs = list(other_missing)
        if feed_incomplete:
            missing_essential_inputs.insert(
                0, 'feed flow rate and composition (not yet fully determined)'
            )
        parts = []
        if feed_incomplete:
            parts.append(_feed_quantity_message(feed))
        if other_missing:
            parts.append('I also still need: ' + '; '.join(other_missing))
        if essential['ambiguous_thermal']:
            parts.append(
                'More than one feed thermal condition was given '
                '(feed_temperature_K, feed_quality, feed_enthalpy_kJ_per_hr '
                'are mutually exclusive) -- supply exactly one.'
            )
        if essential['invalid_reflux_condition']:
            parts.append(
                'reflux_condition given is not supported -- only '
                f'{sorted(SUPPORTED_REFLUX_CONDITIONS)} is implemented today.'
            )
        return _base_report(
            scope, missing_essential_inputs=missing_essential_inputs,
            optimum_feed_plate_confirmed=spec.get('use_optimum_feed_plate'),
            status='need_essential_inputs', message=' '.join(parts),
            feed=feed, feed_flow_complete=assessed['feed_flow_complete'],
            feed_composition_complete=assessed['feed_composition_complete'],
            pending_request=_essential_pending_request(
                other_missing, feed_incomplete,
                essential['ambiguous_thermal'], essential['invalid_reflux_condition'],
            ),
        )

    case_info = identify_case(spec)

    if case_info['ambiguous']:
        return _base_report(
            scope, essential_complete=True,
            case_candidates=case_info['candidates'],
            optimum_feed_plate_confirmed=spec.get('use_optimum_feed_plate'),
            status='ambiguous', message=case_info['ambiguous_reason'],
            feed=feed, feed_flow_complete=True, feed_composition_complete=True,
        )

    if case_info['case'] is None:
        candidates = case_info['candidates']
        pending_request = None
        if _no_case_signal_given(spec):
            message = (
                'This does not yet identify a Wankat design case. Provide '
                'fields matching one of: '
                + '; '.join(f'Case {c} = {d}' for c, d in CASE_FIELD_SUMMARY.items())
                + '.'
            )
            status = 'need_case_definition'
        else:
            message = 'Still-possible cases and what each still needs: ' + '; '.join(
                f"Case {c} needs: {', '.join(case_info['missing_by_candidate'][c])}"
                for c in candidates
            ) + '.'
            status = 'need_case_inputs'
            pending_request = _case_pending_request(candidates, case_info['missing_by_candidate'])
        return _base_report(
            scope, essential_complete=True, case_candidates=candidates,
            missing_case_inputs=case_info['missing_by_candidate'],
            optimum_feed_plate_confirmed=spec.get('use_optimum_feed_plate'),
            status=status, message=message,
            feed=feed, feed_flow_complete=True, feed_composition_complete=True,
            pending_request=pending_request,
        )

    case = case_info['case']
    ofp = spec.get('use_optimum_feed_plate')
    if ofp is None:
        return _base_report(
            scope, essential_complete=True, case=case, case_candidates=[case],
            case_complete=True, optimum_feed_plate_confirmed=None,
            status='need_case_inputs',
            message='Should the design use the optimum feed plate?',
            feed=feed, feed_flow_complete=True, feed_composition_complete=True,
            pending_request=dict(_OPTIMUM_FEED_PLATE_PENDING_REQUEST),
        )

    calc_check = check_calculation_inputs(feed)
    if not calc_check['complete']:
        return _base_report(
            scope, essential_complete=True, case=case, case_candidates=[case],
            case_complete=True, optimum_feed_plate_confirmed=bool(ofp),
            calculation_inputs_complete=False,
            missing_calculation_inputs=calc_check['missing'],
            status='need_calculation_inputs',
            message=_CALCULATION_INPUT_MESSAGES[calc_check['missing'][0]],
            feed=feed, feed_flow_complete=True, feed_composition_complete=True,
            pending_request=_calculation_pending_request(calc_check['missing']),
        )

    would_calculate = _would_calculate(case, spec)
    return _base_report(
        scope, essential_complete=True, case=case, case_candidates=[case],
        case_complete=True, optimum_feed_plate_confirmed=bool(ofp),
        calculation_inputs_complete=True, missing_calculation_inputs=[],
        status='ready_for_calculation', would_calculate=would_calculate,
        message=(
            f"Your binary-distillation problem is fully specified as Wankat "
            f"Case {case}, and ready for the currently implemented "
            f"calculation layer. The available calculation can evaluate "
            f"feed phase. A full Case {case} design would also calculate: "
            f"{', '.join(would_calculate)} -- these are not yet implemented "
            f"in this pipeline."
        ),
        feed=feed, feed_flow_complete=True, feed_composition_complete=True,
    )


if __name__ == '__main__':
    import json

    def demo(title, spec):
        print(f'--- {title} ---')
        print(json.dumps(assess_binary_distillation_problem(spec), indent=2, default=str))
        print()

    ESSENTIALS = {
        'component_names': ['Methanol', 'Water'],
        'component_flows': {'Methanol': 40, 'Water': 60},
        'pressure_Pa': 101325, 'feed_temperature_K': 350.0,
        'reflux_condition': 'saturated_liquid',
    }

    demo('One component', {'component_names': ['Methanol']})
    demo('Three components', {'component_names': ['Methanol', 'Water', 'Glycerol']})
    demo('Component names only -- no invented flows', {'component_names': ['Methanol', 'Water']})
    demo('One component flow only -- not treated as total flow', {
        'component_names': ['Methanol', 'Water'],
        'component_flows': {'Methanol': 50}, 'component_flow_units': 'kmol/hr',
    })
    demo('Two components, no operating data', dict(
        component_names=['Methanol', 'Water'], component_flows={'Methanol': 40, 'Water': 60},
    ))
    demo('Inconsistent: component flows disagree with explicit total flow', dict(
        ESSENTIALS, component_flows={'Methanol': 40, 'Water': 60}, total_flow=120,
    ))
    demo('Optimum feed plate only (no case signal)', dict(ESSENTIALS))
    demo('Boilup ratio supplied -- routes to Case D', dict(ESSENTIALS, boilup_ratio_VB=2.0))
    demo('Complete Case D except component_flow_units -- need_calculation_inputs', dict(
        ESSENTIALS, xD=0.99, xB=0.01, boilup_ratio_VB=2.0, use_optimum_feed_plate=True,
    ))
    demo('Complete Case D', dict(
        ESSENTIALS, component_flow_units='kmol/hr',
        xD=0.99, xB=0.01, boilup_ratio_VB=2.0, use_optimum_feed_plate=True,
    ))
