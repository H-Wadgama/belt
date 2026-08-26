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


def design_separation_case(
    components: dict[str, float],
    light_key: str,
    heavy_key: str,
    pressure_Pa: float,
    reflux_condition: str,
    units: str = 'kmol/hr',
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
    target: str = 'top',
) -> dict:
    """Run a single, deterministic Wankat-Table-3-2 binary distillation design (Case A-D), NOT a cost search.

    This tool never guesses or defaults a missing input. It first checks the essential Table 3-1 variables (column pressure, feed flow/composition, feed thermal condition, reflux condition) and identifies which Table 3-2 design case (A, B, C, or D) your other arguments match -- deterministically, by which fields are present, not by asking a model to infer it. If anything required is missing, or if the fields you gave are ambiguous/contradictory, this returns a report explaining exactly what is missing or conflicting instead of running any calculation. Only call this with a specific value for every field the user has actually told you; never invent xD, xB, a reflux ratio, or a feed condition yourself -- ask the user instead.

    This tool currently only supports strictly binary feeds: `components` must have exactly 2 entries with nonzero flow.

    IMPORTANT -- external_reflux_ratio_LD vs reflux_ratio_multiplier_k are NOT the same quantity. external_reflux_ratio_LD is Wankat's actual/external reflux ratio L0/D (what a user normally means by "reflux ratio"). reflux_ratio_multiplier_k is an internal parameter (k = actual reflux ratio / minimum reflux ratio) specific to this tool's underlying shortcut method. Only pass reflux_ratio_multiplier_k if the user explicitly speaks in terms of "x times minimum reflux" -- otherwise, if the user gives a reflux ratio, pass it as external_reflux_ratio_LD. Never pass the same number to both, and never invent one from the other yourself; this tool converts external_reflux_ratio_LD to the internal k by measuring the column's actual minimum reflux.

    Args:
        components: Feed component flow rates -- exactly 2 nonzero entries, e.g. {"Water": 80, "Methanol": 100}. Keys must be valid BioSTEAM/chemicals-package chemical names.
        light_key: Component name of the light key (concentrates in the distillate/top product).
        heavy_key: Component name of the heavy key (concentrates in the bottoms/bottom product).
        pressure_Pa: Column operating pressure in Pascal. Required -- do not default this; ask the user if not given (1 atm = 101325 Pa is a common but not universal choice).
        reflux_condition: Thermal condition of the reflux returned to the column. Must be the literal string "saturated_liquid" -- the only condition the underlying engineering layer implements today. Wankat notes saturated-liquid reflux is the usual case, but it must be stated explicitly here rather than assumed silently -- ask the user to confirm rather than filling this in yourself if they haven't mentioned it.
        units: Flow rate units for `components`. Either "kmol/hr" or "kg/hr".
        feed_temperature_K: Feed temperature in Kelvin. Give exactly one of feed_temperature_K, feed_quality, or feed_enthalpy_kJ_per_hr -- never assume the feed is at its bubble point or any other condition if the user hasn't stated one; ask them instead.
        feed_quality: Feed vapor fraction (0 = saturated liquid, 1 = saturated vapor, in between = flashing feed). Alternative to feed_temperature_K.
        feed_enthalpy_kJ_per_hr: Feed molar enthalpy in kJ/hr (BioSTEAM's internal enthalpy basis). Alternative to feed_temperature_K.
        xD: Case A/D -- target light-key mole fraction in the distillate.
        xB: Case A/D -- target light-key mole fraction in the bottoms.
        Lr: Case B -- target fractional recovery (0-1) of the light key to the distillate.
        Hr: Case B -- target fractional recovery (0-1) of the heavy key to the bottoms.
        distillate_flow: Case C -- specified distillate flow rate (same units as `units`). Give at most one of distillate_flow/bottoms_flow.
        bottoms_flow: Case C -- specified bottoms flow rate (same units as `units`).
        boilup_ratio_VB: Case D -- specified boilup ratio V/B (used together with xD and xB, instead of a reflux ratio).
        external_reflux_ratio_LD: Wankat's external/actual reflux ratio L0/D (Cases A-C). See the IMPORTANT note above -- do not confuse with reflux_ratio_multiplier_k.
        reflux_ratio_multiplier_k: Internal shortcut-method parameter k = actual reflux ratio / minimum reflux ratio (Cases A-C, alternative to external_reflux_ratio_LD). See the IMPORTANT note above.
        target: Which outlet to report as the 'product' stream: "top" (distillate) or "bottom" (bottoms). Does not change which case applies.

    Returns:
        A dict. If the specification is incomplete or ambiguous: {'valid': False, 'case': None or a guess, 'missing_essential_inputs': [...], 'case_candidates': [...], 'missing_case_inputs_by_candidate': {...}, 'ambiguous': bool, 'ambiguous_reason': str or null, 'message': a human-readable explanation of exactly what is missing/conflicting, 'provenance': Wankat Table 3-1/3-2 citation}. Relay 'message' (or the missing/ambiguous fields) to the user and ask for the missing information rather than retrying with invented values. If the specification is complete: {'valid': True, 'case': 'A'|'B'|'C'|'D', 'implemented': bool, 'message': str, 'reflux': {'external_reflux_ratio_LD', 'reflux_ratio_multiplier_k', 'minimum_reflux_ratio_LD', 'basis'}, 'design_result': full column design/cost/stream data, or null if Case C/D (recognized but not implemented by the current engineering layer -- tell the user this rather than approximating), 'provenance': ...}.
    """
    spec = dict(
        pressure_Pa=pressure_Pa, components=components,
        feed_temperature_K=feed_temperature_K, feed_quality=feed_quality,
        feed_enthalpy_kJ_per_hr=feed_enthalpy_kJ_per_hr,
        reflux_condition=reflux_condition,
        xD=xD, xB=xB, Lr=Lr, Hr=Hr,
        distillate_flow=distillate_flow, bottoms_flow=bottoms_flow,
        boilup_ratio_VB=boilup_ratio_VB,
        external_reflux_ratio_LD=external_reflux_ratio_LD,
        reflux_ratio_multiplier_k=reflux_ratio_multiplier_k,
    )
    report = validate_problem(spec)
    if not report['valid']:
        return _jsonify(report)

    _next_flowsheet()
    try:
        feed = _build_feed(
            components, units, light_key, heavy_key, pressure_Pa,
            feed_temperature_K, feed_quality, feed_enthalpy_kJ_per_hr,
        )
    except Exception as e:
        return _jsonify({**report, 'valid': False, 'error': f'{type(e).__name__}: {e}'})

    if report['case'] not in IMPLEMENTED_CASES:
        design = design_binary_distillation(feed, LHK=(light_key, heavy_key), case=report['case'])
        return _jsonify({**report, **design})

    design = design_binary_distillation(
        feed, LHK=(light_key, heavy_key), case=report['case'], P=pressure_Pa,
        xD=xD, xB=xB, Lr=Lr, Hr=Hr,
        external_reflux_ratio_LD=external_reflux_ratio_LD,
        reflux_ratio_multiplier_k=reflux_ratio_multiplier_k,
        target=target,
    )
    return _jsonify({**report, **design})


def optimize_separation(
    components: dict[str, float],
    light_key: str,
    heavy_key: str,
    pressure_Pa: float,
    reflux_condition: str,
    units: str = 'kmol/hr',
    feed_temperature_K: float | None = None,
    feed_quality: float | None = None,
    feed_enthalpy_kJ_per_hr: float | None = None,
    spec: str = 'purity',
    target: str = 'top',
    purity_target: float | None = None,
    recovery_target: float | None = None,
    reflux_ratios_k: list[float] | None = None,
) -> dict:
    """Size and cost a binary distillation column, sweeping an INTERNAL reflux-ratio multiplier to find the cheapest design that hits a purity or recovery target.

    This is a cost-optimization search, not a direct Wankat-Table-3-2 design -- it is only useful when the user wants "cheapest design that hits a target" rather than "solve the column at this specific reflux ratio". If the user has already specified a real external reflux ratio (what they'd call "the reflux ratio", e.g. "run it at L/D=3"), use `design_separation_case` instead -- do not convert their stated reflux ratio into a `reflux_ratios_k` sweep endpoint yourself.

    This tool currently only supports strictly binary feeds: `components` must have exactly 2 entries with nonzero flow. A 3+ component feed raises an error -- ternary/multicomponent feed support is planned for later but not implemented yet.

    Args:
        components: Feed component flow rates -- exactly 2 nonzero entries, e.g. {"Water": 80, "Methanol": 100}. Keys must be valid BioSTEAM/chemicals-package chemical names (e.g. "Water", "Methanol", "Ethanol", "Glycerol", "Ethylene").
        light_key: Component name of the light key -- the component that should concentrate in the distillate (top) product.
        heavy_key: Component name of the heavy key -- the component that should concentrate in the bottoms (bottom) product.
        pressure_Pa: Column operating pressure in Pascal. Required -- do not default this; ask the user if not given.
        reflux_condition: Thermal condition of the reflux returned to the column. Must be the literal string "saturated_liquid" -- the only condition implemented today. State this explicitly rather than assuming it; confirm with the user if they haven't mentioned it.
        units: Flow rate units for the `components` values. Either "kmol/hr" or "kg/hr".
        feed_temperature_K: Feed temperature in Kelvin. Give exactly one of feed_temperature_K, feed_quality, or feed_enthalpy_kJ_per_hr -- never assume the feed is at its bubble point or any other condition if the user hasn't stated one; ask them instead.
        feed_quality: Feed vapor fraction (0 = saturated liquid, 1 = saturated vapor). Alternative to feed_temperature_K.
        feed_enthalpy_kJ_per_hr: Feed molar enthalpy in kJ/hr. Alternative to feed_temperature_K.
        spec: Which kind of target to hit: "purity" (product concentration) or "recovery" (fraction of feed component recovered).
        target: Which outlet is the product of interest: "top" (distillate) or "bottom" (bottoms).
        purity_target: Required if spec is "purity". Target mole fraction (0-1) of the target key in the product stream, e.g. 0.99 for 99% pure.
        recovery_target: Required if spec is "recovery". Target fractional recovery (0-1) of the target key to the product stream, e.g. 0.99 for 99% recovery.
        reflux_ratios_k: List of INTERNAL reflux ratio multipliers (k = actual reflux ratio / minimum reflux ratio -- NOT the external/actual reflux ratio itself) to sweep, e.g. [1.5, 2.0, 2.5]. If omitted, a default sweep from 1.2x to 3.5x minimum reflux is used.

    Returns:
        A dict with the cheapest feasible design (or a message explaining why none was feasible), including capital cost, utility cost, achieved purity/recovery, and reflux ratio (both the internal k used and the resulting actual/minimum reflux ratios in L/D terms). Also includes 'key_selection', a validity check on light_key/heavy_key: if 'key_selection.warning' is not null, another feed component boils between the two keys and is a 'distributed' component the shortcut method can't resolve -- ALWAYS check this before attributing an infeasible result to reflux ratio or purity/recovery target. If essential Table 3-1 inputs (pressure, feed thermal condition, reflux condition) are missing, returns {'valid': False, 'missing_essential_inputs': [...], 'message': ..., 'provenance': ...} instead of running anything.
    """
    essential = check_essential_inputs(dict(
        pressure_Pa=pressure_Pa, components=components,
        feed_temperature_K=feed_temperature_K, feed_quality=feed_quality,
        feed_enthalpy_kJ_per_hr=feed_enthalpy_kJ_per_hr,
        reflux_condition=reflux_condition,
    ))
    if essential['missing'] or essential['ambiguous_thermal'] or essential['invalid_reflux_condition']:
        return _jsonify({
            'valid': False,
            'missing_essential_inputs': essential['missing'],
            'ambiguous_thermal': essential['ambiguous_thermal'],
            'invalid_reflux_condition': essential['invalid_reflux_condition'],
            'message': (
                'Missing or ambiguous essential inputs (Table 3-1): '
                + '; '.join(essential['missing'])
            ) if essential['missing'] else (
                'Feed thermal condition or reflux condition is ambiguous/unsupported -- see missing_essential_inputs fields.'
            ),
            'provenance': {'essential_inputs': TABLE_3_1_PROVENANCE},
        })

    _next_flowsheet()
    feed = _build_feed(
        components, units, light_key, heavy_key, pressure_Pa,
        feed_temperature_K, feed_quality, feed_enthalpy_kJ_per_hr,
    )

    result = optimize_reflux_ratio(
        feed=feed,
        LHK=(light_key, heavy_key),
        reflux_ratios_k=reflux_ratios_k or DEFAULT_REFLUX_RATIOS_K,
        P=pressure_Pa,
        spec=spec,
        target=target,
        purity_target=purity_target,
        recovery_target=recovery_target,
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


TOOLS = [design_separation_case, optimize_separation]
TOOL_FUNCTIONS = {
    'design_separation_case': design_separation_case,
    'optimize_separation': optimize_separation,
}
