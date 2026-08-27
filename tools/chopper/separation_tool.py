"""
The single tool exposed to the LLM: `optimize_separation`.

Wraps `optimizer.optimize_reflux_ratio` behind a JSON-in/JSON-out function
so an Ollama tool-calling model (e.g. qwen3:8b) can build a feed stream
from plain component/flow numbers, run the reflux-ratio sweep, and get
back a plain dict it can summarize in natural language.

`optimize_separation`'s type hints and docstring are read directly by
`ollama`'s `convert_function_to_tool` (triggered by passing the function
itself in `tools=[...]`) to build the JSON schema the model sees -- so
keep the signature and the per-argument docstring lines accurate; they
are the model's only view of what this tool does.
"""
import biosteam as bst

from optimizer import optimize_reflux_ratio
from problem_spec import check_essential_inputs, validate_problem, TABLE_3_1_PROVENANCE
from case_design import design_binary_distillation, IMPLEMENTED_CASES

DEFAULT_REFLUX_RATIOS_K = [1.2, 1.5, 1.75, 2.0, 2.5, 3.0, 3.5]

_call_count = 0

# Accumulated spec fields for the CURRENT separation problem, across
# however many tool calls it takes to fully specify it. This exists because
# an LLM tool-calling loop cannot be relied on to restate every
# already-known field on every follow-up call (small local models in
# particular tend to forward only the newest piece of information) -- so
# instead of requiring the caller to resend the whole spec each time, every
# call here MERGES whatever it was given into this dict, and completeness
# is judged against the accumulated state, not just the current call's
# arguments. Call `reset_separation_session()` to clear it when starting a
# genuinely different separation problem in the same process.
_spec_state = {}

# These two groups are each mutually exclusive within the accumulated
# state: supplying a new member of a group clears any other member
# previously stored, so an earlier turn's choice can never linger and
# create a false "ambiguous" conflict against a later, different choice
# (see problem_spec.identify_case's conflict checks).
_THERMAL_FIELDS = ('feed_temperature_K', 'feed_quality', 'feed_enthalpy_kJ_per_hr')
_REFLUX_QUANTITY_FIELDS = ('external_reflux_ratio_LD', 'reflux_ratio_multiplier_k')

# Fields that identify WHICH separation problem this is, as opposed to a
# parameter of it. A tool-calling model resending one of these with a
# different value is far more likely to be a hallucinated/drifted argument
# than a deliberate feed change -- see the incident this guards against:
# an 8B local model, asked only for pressure and feed temperature, resent
# `components` with fabricated flow rates on the same problem, and the old
# unconditional-overwrite merge silently accepted it. Changing one of these
# now requires reset_separation_session() first.
_STABLE_FIELDS = ('components', 'light_key', 'heavy_key')


class ConflictingResend(Exception):
    """Raised when a stable field is resent with a value that conflicts with what's already accumulated for this problem."""

    def __init__(self, field, previous_value, attempted_value):
        self.field = field
        self.previous_value = previous_value
        self.attempted_value = attempted_value
        super().__init__(
            f'{field} already set to {previous_value!r} for this separation '
            f'problem; got conflicting value {attempted_value!r}.'
        )


def _jsonify(value):
    """Recursively convert numpy/pandas scalars to plain JSON-safe types."""
    if isinstance(value, dict):
        return {k: _jsonify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonify(v) for v in value]
    if hasattr(value, 'item'):  # numpy scalar (e.g. np.float64, np.bool_)
        return value.item()
    return value


def _next_flowsheet():
    global _call_count
    _call_count += 1
    bst.main_flowsheet.set_flowsheet(f'sep_agent_{_call_count}')


def _merge_into_state(new_fields):
    """Merge only the non-None fields in `new_fields` into `_spec_state`, clearing stale mutually-exclusive fields left over from an EARLIER call. Returns the updated `_spec_state`.

    Deliberately does NOT clear a group member when more than one member of
    that group is given in THIS SAME call -- that's a real conflict (e.g.
    both external_reflux_ratio_LD and reflux_ratio_multiplier_k given at
    once), and problem_spec.identify_case() needs to see both values
    together to detect and report it, rather than having this function
    silently resolve it by keeping only the last one processed.

    Raises ConflictingResend if a _STABLE_FIELD (components/light_key/
    heavy_key) is resent with a value that differs from what's already
    accumulated -- these identify the problem itself, so a change here
    must go through reset_separation_session(), not a silent overwrite.
    """
    for field in _STABLE_FIELDS:
        new_value = new_fields.get(field)
        if new_value is not None and field in _spec_state and _spec_state[field] != new_value:
            raise ConflictingResend(field, _spec_state[field], new_value)

    for group in (_THERMAL_FIELDS, _REFLUX_QUANTITY_FIELDS):
        given_in_group = [k for k in group if new_fields.get(k) is not None]
        if len(given_in_group) == 1:
            for other in group:
                if other != given_in_group[0]:
                    _spec_state.pop(other, None)

    for key, value in new_fields.items():
        if value is not None:
            _spec_state[key] = value
    return _spec_state


def reset_separation_session() -> dict:
    """Clear all previously-remembered separation inputs, so a new call starts a fresh, unrelated separation problem from scratch.

    Call this ONLY when the user is clearly switching to a different separation problem (different components, or they explicitly say to start over) -- not between follow-up turns that are still refining the same problem. Ordinary follow-ups (e.g. supplying a temperature you asked for, or changing a target) should NOT call this; just call design_separation_case/optimize_separation again with the new information, and everything given earlier in this problem stays remembered automatically.

    Returns:
        {'reset': True, 'message': str} confirming the accumulated inputs were cleared.
    """
    _spec_state.clear()
    return {'reset': True, 'message': 'All previously remembered separation inputs have been cleared.'}


def _build_feed(components, units, light_key, heavy_key, pressure_Pa,
                 feed_temperature_K, feed_quality, feed_enthalpy_kJ_per_hr):
    """
    Build the feed stream and set its thermal condition from EXACTLY the
    field the caller supplied. Never falls back to bubble point or any
    other implicit default -- see tools/binary-distillation-context.md
    section 1 ("feed thermal condition ... rather than silently assuming
    that the feed is at its bubble point").
    """
    chem_ids = sorted(set(components) | {light_key, heavy_key})
    bst.settings.set_thermo(chem_ids, cache=True)

    feed = bst.Stream('agent_feed', units=units, **components)
    if feed_temperature_K is not None:
        feed.vle(T=feed_temperature_K, P=pressure_Pa)
    elif feed_quality is not None:
        feed.vle(P=pressure_Pa, V=feed_quality)
    else:
        feed.vle(P=pressure_Pa, H=feed_enthalpy_kJ_per_hr)
    return feed


def _conflicting_resend_report(e: ConflictingResend) -> dict:
    """Build the tool-result dict returned when a ConflictingResend is caught -- valid=False, and the fix is reset_separation_session(), never a retry with a guessed value."""
    return {
        'valid': False,
        'error': 'conflicting_resend',
        'field': e.field,
        'previous_value': e.previous_value,
        'attempted_value': e.attempted_value,
        'message': (
            f"{e.field} was already set to {e.previous_value!r} earlier in this "
            f"separation problem; this call tried to change it to "
            f"{e.attempted_value!r}. {e.field} identifies which problem this is "
            f"and cannot be changed mid-problem -- if the feed/keys genuinely "
            f"changed, call reset_separation_session() first and restate the "
            f"full problem. If this was not an intentional change, resend the "
            f"call with {e.field} omitted (or with its original value)."
        ),
    }


def _missing_keys_check(state):
    """Light/heavy key aren't Wankat Table 3-1/3-2 variables, but the BioSTEAM layer needs to know which feed component is which -- check for them the same way essential inputs are checked."""
    return [k for k in ('light_key', 'heavy_key') if state.get(k) is None]


def design_separation_case(
    components: dict[str, float] | None = None,
    light_key: str | None = None,
    heavy_key: str | None = None,
    pressure_Pa: float | None = None,
    reflux_condition: str | None = None,
    units: str | None = None,
    feed_temperature_K: float | None = None,
    feed_quality: float | None = None,
    feed_enthalpy_kJ_per_hr: float | None = None,
    xD: float | None = None,
    xB: float | None = None,
    Lr: float | None = None,
    Hr: float | None = None,
    distillate_flow: float | None = None,
    bottoms_flow: float | None = None,
    boilup_ratio_VB: float | None = None,
    external_reflux_ratio_LD: float | None = None,
    reflux_ratio_multiplier_k: float | None = None,
    target: str | None = None,
    purity_target: float | None = None,
    recovery_target: float | None = None,
    spec: str | None = None,
) -> dict:
    """Run a single, deterministic Wankat-Table-3-2 binary distillation design (Case A-D), NOT a cost search.

    Do NOT use this tool for a request that only gives a desired purity or recovery target and asks for a suitable/lowest-cost design (e.g. "95% methanol overhead", "99% recovery of methanol", "find the cheapest design meeting 95% purity") -- use `optimize_separation` for those. Use this tool only when the user has explicitly specified a fixed reflux quantity (external_reflux_ratio_LD or reflux_ratio_multiplier_k) or a Wankat Case A-D direct-design specification (xD/xB, Lr/Hr, a product flow, or a boilup ratio) -- i.e. one fixed column design, not a search. `purity_target`, `recovery_target`, and `spec` below exist only so a stray purity/recovery request can be caught and redirected deterministically; passing any of them always fails the call.

    This tool never guesses or defaults a missing input, and it REMEMBERS every field you've given it so far in this conversation about this separation problem -- you do NOT need to repeat components, pressure, feed condition, or anything else from an earlier call. Just call this again with only whatever is new (e.g. only `feed_temperature_K` after the user answers a question you asked); it is merged with everything already known. Call `reset_separation_session()` first if the user switches to a genuinely different, unrelated separation problem.

    It checks the essential Table 3-1 variables (column pressure, feed flow/composition, feed thermal condition, reflux condition) and identifies which Table 3-2 design case (A, B, C, or D) the accumulated fields match -- deterministically, by which fields are present, not by asking a model to infer it. There is NO default to Case A: if the user has given none of xD/xB, Lr/Hr, a product flow, or a boilup ratio yet, `case` is null and `case_candidates` lists every case still consistent (typically all four, A-D) along with what each one still needs -- ask the user which kind of specification they want to give (or just ask for whichever fields the user is most likely to have, e.g. a purity target), do not silently pick a case yourself. As soon as the user states something case-specific (e.g. a fractional recovery), the candidate set narrows automatically to match. If anything required is still missing, or the fields given are ambiguous/contradictory, this returns a report explaining exactly what, instead of running any calculation. Never invent xD, xB, a reflux ratio, or a feed condition yourself -- ask the user instead.

    This tool currently only supports strictly binary feeds: `components` must have exactly 2 entries with nonzero flow.

    IMPORTANT -- external_reflux_ratio_LD vs reflux_ratio_multiplier_k are NOT the same quantity. external_reflux_ratio_LD is Wankat's actual/external reflux ratio L0/D (what a user normally means by "reflux ratio"). reflux_ratio_multiplier_k is an internal parameter (k = actual reflux ratio / minimum reflux ratio) specific to this tool's underlying shortcut method. Only pass reflux_ratio_multiplier_k if the user explicitly speaks in terms of "x times minimum reflux" -- otherwise, if the user gives a reflux ratio, pass it as external_reflux_ratio_LD. Never pass the same number to both, and never invent one from the other yourself; this tool converts external_reflux_ratio_LD to the internal k by measuring the column's actual minimum reflux.

    Args:
        components: Feed component flow rates -- exactly 2 nonzero entries, e.g. {"Water": 80, "Methanol": 100}. Keys must be valid BioSTEAM/chemicals-package chemical names. Omit if already given in an earlier call this conversation -- resending it with a DIFFERENT value than what's already established is rejected (call reset_separation_session() first if the feed genuinely changed).
        light_key: Component name of the light key (concentrates in the distillate/top product). Omit if already given -- resending a different value than already established is rejected the same way as components.
        heavy_key: Component name of the heavy key (concentrates in the bottoms/bottom product). Omit if already given -- resending a different value than already established is rejected the same way as components.
        pressure_Pa: Column operating pressure in Pascal. Do not default this yourself; ask the user if never given (1 atm = 101325 Pa is a common but not universal choice). Omit if already given in an earlier call.
        reflux_condition: Thermal condition of the reflux returned to the column. Must be the literal string "saturated_liquid" -- the only condition the underlying engineering layer implements today. Wankat notes saturated-liquid reflux is the usual case, but it must be stated explicitly rather than assumed silently -- ask the user to confirm rather than filling this in yourself if they haven't mentioned it. Omit if already given.
        units: Flow rate units for `components`. Either "kmol/hr" or "kg/hr".
        feed_temperature_K: Feed temperature in Kelvin. Give exactly one of feed_temperature_K, feed_quality, or feed_enthalpy_kJ_per_hr -- never assume the feed is at its bubble point or any other condition if the user hasn't stated one; ask them instead. Omit if already given.
        feed_quality: Feed vapor fraction (0 = saturated liquid, 1 = saturated vapor, in between = flashing feed). Alternative to feed_temperature_K.
        feed_enthalpy_kJ_per_hr: Feed molar enthalpy in kJ/hr (BioSTEAM's internal enthalpy basis). Alternative to feed_temperature_K.
        xD: Case A/D -- target light-key mole fraction in the distillate.
        xB: Case A/D -- target light-key mole fraction in the bottoms.
        Lr: Case B -- target fractional recovery (0-1) of the light key to the distillate. Giving this (with Hr) switches the design to Case B automatically.
        Hr: Case B -- target fractional recovery (0-1) of the heavy key to the bottoms.
        distillate_flow: Case C -- specified distillate flow rate (same units as `units`). Give at most one of distillate_flow/bottoms_flow.
        bottoms_flow: Case C -- specified bottoms flow rate (same units as `units`).
        boilup_ratio_VB: Case D -- specified boilup ratio V/B (used together with xD and xB, instead of a reflux ratio).
        external_reflux_ratio_LD: Wankat's external/actual reflux ratio L0/D (Cases A-C). See the IMPORTANT note above -- do not confuse with reflux_ratio_multiplier_k.
        reflux_ratio_multiplier_k: Internal shortcut-method parameter k = actual reflux ratio / minimum reflux ratio (Cases A-C, alternative to external_reflux_ratio_LD). See the IMPORTANT note above.
        target: Which outlet to report as the 'product' stream: "top" (distillate) or "bottom" (bottoms). Does not change which case applies.
        purity_target: Do not pass this. It belongs to `optimize_separation`'s purity/recovery cost search, not a fixed-design case. Passing it here always returns {'valid': False, 'error': 'wrong_workflow'} directing you to call `optimize_separation` instead.
        recovery_target: Do not pass this -- same as purity_target above; belongs to `optimize_separation`.
        spec: Do not pass this -- same as purity_target above; belongs to `optimize_separation`.

    Returns:
        A dict. If purity_target/recovery_target/spec was passed: {'valid': False, 'error': 'wrong_workflow', 'recommended_tool': 'optimize_separation', 'message': str} -- call `optimize_separation` instead, forwarding whatever fields (including purity_target/recovery_target/spec) the user actually gave. If the specification is incomplete or ambiguous: {'valid': False, 'case': None, 'missing_essential_inputs': [...], 'case_candidates': [...], 'missing_case_inputs_by_candidate': {...}, 'ambiguous': bool, 'ambiguous_reason': str or null, 'message': a human-readable explanation of exactly what is missing/conflicting (listing every still-possible case and what each needs, when nothing case-specific has been given), 'provenance': Wankat Table 3-1/3-2 citation}. Relay 'message' (or the missing/ambiguous fields) to the user and ask for exactly that -- do not retry with invented values, and do not repeat fields already given; the next call only needs the new answer. If the specification is complete: {'valid': True, 'case': 'A'|'B'|'C'|'D', 'implemented': bool, 'message': str, 'reflux': {'external_reflux_ratio_LD', 'reflux_ratio_multiplier_k', 'minimum_reflux_ratio_LD', 'basis'}, 'design_result': full column design/cost/stream data, or null if Case C/D (recognized but not implemented by the current engineering layer -- tell the user this rather than approximating), 'provenance': ...}.
    """
    if purity_target is not None or recovery_target is not None or spec is not None:
        return _jsonify({
            'valid': False,
            'error': 'wrong_workflow',
            'recommended_tool': 'optimize_separation',
            'message': (
                'This request contains a purity/recovery target without a fixed '
                'reflux specification. Use optimize_separation rather than '
                'design_separation_case.'
            ),
        })

    try:
        state = _merge_into_state(dict(
            components=components, light_key=light_key, heavy_key=heavy_key,
            pressure_Pa=pressure_Pa, reflux_condition=reflux_condition, units=units,
            feed_temperature_K=feed_temperature_K, feed_quality=feed_quality,
            feed_enthalpy_kJ_per_hr=feed_enthalpy_kJ_per_hr,
            xD=xD, xB=xB, Lr=Lr, Hr=Hr,
            distillate_flow=distillate_flow, bottoms_flow=bottoms_flow,
            boilup_ratio_VB=boilup_ratio_VB,
            external_reflux_ratio_LD=external_reflux_ratio_LD,
            reflux_ratio_multiplier_k=reflux_ratio_multiplier_k,
            target=target,
        ))
    except ConflictingResend as e:
        return _jsonify(_conflicting_resend_report(e))

    report = validate_problem(state)
    missing_keys = _missing_keys_check(state)
    if missing_keys:
        report = dict(report, valid=False)
        report['missing_essential_inputs'] = [
            *report['missing_essential_inputs'],
            *(f'{k} (which feed component this is)' for k in missing_keys),
        ]
        report['message'] = (
            f"Missing {', '.join(missing_keys)} -- need to know which feed "
            f"component is the light key and which is the heavy key. "
        ) + report['message']

    if not report['valid']:
        return _jsonify(report)

    eff_units = state.get('units') or 'kmol/hr'
    eff_target = state.get('target') or 'top'

    _next_flowsheet()
    try:
        feed = _build_feed(
            state['components'], eff_units, state['light_key'], state['heavy_key'],
            state['pressure_Pa'], state.get('feed_temperature_K'),
            state.get('feed_quality'), state.get('feed_enthalpy_kJ_per_hr'),
        )
    except Exception as e:
        return _jsonify({**report, 'valid': False, 'error': f'{type(e).__name__}: {e}'})

    if report['case'] not in IMPLEMENTED_CASES:
        design = design_binary_distillation(
            feed, LHK=(state['light_key'], state['heavy_key']), case=report['case'],
        )
        return _jsonify({**report, **design})

    design = design_binary_distillation(
        feed, LHK=(state['light_key'], state['heavy_key']), case=report['case'],
        P=state['pressure_Pa'],
        xD=state.get('xD'), xB=state.get('xB'), Lr=state.get('Lr'), Hr=state.get('Hr'),
        external_reflux_ratio_LD=state.get('external_reflux_ratio_LD'),
        reflux_ratio_multiplier_k=state.get('reflux_ratio_multiplier_k'),
        target=eff_target,
    )
    return _jsonify({**report, **design})


def optimize_separation(
    components: dict[str, float] | None = None,
    light_key: str | None = None,
    heavy_key: str | None = None,
    pressure_Pa: float | None = None,
    reflux_condition: str | None = None,
    units: str | None = None,
    feed_temperature_K: float | None = None,
    feed_quality: float | None = None,
    feed_enthalpy_kJ_per_hr: float | None = None,
    spec: str | None = None,
    target: str | None = None,
    purity_target: float | None = None,
    recovery_target: float | None = None,
    reflux_ratios_k: list[float] | None = None,
) -> dict:
    """Size and cost a binary distillation column, sweeping an INTERNAL reflux-ratio multiplier to find the cheapest design that hits a purity or recovery target.

    This is the DEFAULT tool whenever the user states a desired product purity or recovery and does NOT also specify a fixed reflux ratio or Wankat Case A-D design condition -- e.g. "95% methanol overhead", "99% recovery of methanol", "find the cheapest design meeting 95% purity", "produce 95% methanol in the distillate". A purity/recovery target alone always routes here, never to `design_separation_case`.

    This is a cost-optimization search, not a direct Wankat-Table-3-2 design -- it is only useful when the user wants "cheapest design that hits a target" rather than "solve the column at this specific reflux ratio". If the user has already specified a real external reflux ratio (what they'd call "the reflux ratio", e.g. "run it at L/D=3"), use `design_separation_case` instead -- do not convert their stated reflux ratio into a `reflux_ratios_k` sweep endpoint yourself.

    This tool REMEMBERS every field you've given it so far in this conversation about this separation problem (shared with design_separation_case) -- you do NOT need to repeat components, pressure, feed condition, or anything else from an earlier call. Just call this again with only whatever is new; it is merged with everything already known. Call `reset_separation_session()` first if the user switches to a genuinely different, unrelated separation problem.

    This tool currently only supports strictly binary feeds: `components` must have exactly 2 entries with nonzero flow. A 3+ component feed raises an error -- ternary/multicomponent feed support is planned for later but not implemented yet.

    Args:
        components: Feed component flow rates -- exactly 2 nonzero entries, e.g. {"Water": 80, "Methanol": 100}. Keys must be valid BioSTEAM/chemicals-package chemical names (e.g. "Water", "Methanol", "Ethanol", "Glycerol", "Ethylene"). Omit if already given in an earlier call this conversation -- resending it with a DIFFERENT value than what's already established is rejected (call reset_separation_session() first if the feed genuinely changed).
        light_key: Component name of the light key -- the component that should concentrate in the distillate (top) product. Omit if already given -- resending a different value than already established is rejected the same way as components.
        heavy_key: Component name of the heavy key -- the component that should concentrate in the bottoms (bottom) product. Omit if already given -- resending a different value than already established is rejected the same way as components.
        pressure_Pa: Column operating pressure in Pascal. Do not default this yourself; ask the user if never given. Omit if already given.
        reflux_condition: Thermal condition of the reflux returned to the column. Must be the literal string "saturated_liquid" -- the only condition implemented today. State this explicitly rather than assuming it; confirm with the user if they haven't mentioned it. Omit if already given.
        units: Flow rate units for the `components` values. Either "kmol/hr" or "kg/hr".
        feed_temperature_K: Feed temperature in Kelvin. Give exactly one of feed_temperature_K, feed_quality, or feed_enthalpy_kJ_per_hr -- never assume the feed is at its bubble point or any other condition if the user hasn't stated one; ask them instead. Omit if already given.
        feed_quality: Feed vapor fraction (0 = saturated liquid, 1 = saturated vapor). Alternative to feed_temperature_K.
        feed_enthalpy_kJ_per_hr: Feed molar enthalpy in kJ/hr. Alternative to feed_temperature_K.
        spec: Which kind of target to hit: "purity" (product concentration) or "recovery" (fraction of feed component recovered). Defaults to "purity" if never given.
        target: Which outlet is the product of interest: "top" (distillate) or "bottom" (bottoms). Defaults to "top" if never given.
        purity_target: Required if spec is "purity". Target mole fraction (0-1) of the target key in the product stream, e.g. 0.99 for 99% pure.
        recovery_target: Required if spec is "recovery". Target fractional recovery (0-1) of the target key to the product stream, e.g. 0.99 for 99% recovery.
        reflux_ratios_k: List of INTERNAL reflux ratio multipliers (k = actual reflux ratio / minimum reflux ratio -- NOT the external/actual reflux ratio itself) to sweep, e.g. [1.5, 2.0, 2.5]. If omitted, a default sweep from 1.2x to 3.5x minimum reflux is used.

    Returns:
        A dict with the cheapest feasible design (or a message explaining why none was feasible), including capital cost, utility cost, achieved purity/recovery, and reflux ratio (both the internal k used and the resulting actual/minimum reflux ratios in L/D terms). Also includes 'key_selection', a validity check on light_key/heavy_key: if 'key_selection.warning' is not null, another feed component boils between the two keys and is a 'distributed' component the shortcut method can't resolve -- ALWAYS check this before attributing an infeasible result to reflux ratio or purity/recovery target. If essential Table 3-1 inputs (pressure, feed thermal condition, reflux condition, light/heavy key) are missing, returns {'valid': False, 'missing_essential_inputs': [...], 'message': ..., 'provenance': ...} instead of running anything -- relay that message and ask for exactly what's missing; the next call only needs the new answer, not a restated full spec.
    """
    try:
        state = _merge_into_state(dict(
            components=components, light_key=light_key, heavy_key=heavy_key,
            pressure_Pa=pressure_Pa, reflux_condition=reflux_condition, units=units,
            feed_temperature_K=feed_temperature_K, feed_quality=feed_quality,
            feed_enthalpy_kJ_per_hr=feed_enthalpy_kJ_per_hr,
            spec=spec, target=target, purity_target=purity_target,
            recovery_target=recovery_target,
        ))
    except ConflictingResend as e:
        return _jsonify(_conflicting_resend_report(e))

    essential = check_essential_inputs(state)
    missing_keys = _missing_keys_check(state)
    missing = [*essential['missing'], *(f'{k} (which feed component this is)' for k in missing_keys)]
    if missing or essential['ambiguous_thermal'] or essential['invalid_reflux_condition']:
        return _jsonify({
            'valid': False,
            'missing_essential_inputs': missing,
            'ambiguous_thermal': essential['ambiguous_thermal'],
            'invalid_reflux_condition': essential['invalid_reflux_condition'],
            'message': (
                'Missing or ambiguous essential inputs (Table 3-1): '
                + '; '.join(missing)
            ) if missing else (
                'Feed thermal condition or reflux condition is ambiguous/unsupported -- see missing_essential_inputs fields.'
            ),
            'provenance': {'essential_inputs': TABLE_3_1_PROVENANCE},
        })

    eff_units = state.get('units') or 'kmol/hr'
    eff_spec = state.get('spec') or 'purity'
    eff_target = state.get('target') or 'top'

    _next_flowsheet()
    feed = _build_feed(
        state['components'], eff_units, state['light_key'], state['heavy_key'],
        state['pressure_Pa'], state.get('feed_temperature_K'),
        state.get('feed_quality'), state.get('feed_enthalpy_kJ_per_hr'),
    )

    result = optimize_reflux_ratio(
        feed=feed,
        LHK=(state['light_key'], state['heavy_key']),
        reflux_ratios_k=reflux_ratios_k or DEFAULT_REFLUX_RATIOS_K,
        P=state['pressure_Pa'],
        spec=eff_spec,
        target=eff_target,
        purity_target=state.get('purity_target'),
        recovery_target=state.get('recovery_target'),
    )

    return _jsonify({
        'valid': True,
        'found': result['found'],
        'message': result['message'],
        'n_feasible': result['n_feasible'],
        'n_total': result['n_total'],
        'best_design': result['best_design'],
        'key_selection': result['key_selection'],
    })


TOOLS = [design_separation_case, optimize_separation, reset_separation_session]
TOOL_FUNCTIONS = {
    'design_separation_case': design_separation_case,
    'optimize_separation': optimize_separation,
    'reset_separation_session': reset_separation_session,
}
