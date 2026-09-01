"""
Isolated workflow-testing agent -- tools/binary-distillation-workflow.md
section 18, Option C ("Expose only assess_binary_distillation_problem() to
Qwen in a dedicated workflow-testing agent"), refactored per
tools/binary-distillation-read-vs-append.md to split the single combined
tool into separate READ and WRITE operations, and again per
tools/binary-distillation-issues-9-1-2026-fifth.md ("Round 2 Architecture
Stabilization") to replace per-turn native tool-calling for engineering
state with a schema-driven TurnIntent/TurnTransaction interpretation layer
-- see that doc and `turn_intent.py`/`turn_transaction.py`/
`problem_snapshot.py`/`problem_field_registry.py` for the new architecture.

This module still owns FOUR plain Python operations against one canonical
accumulated problem state:
  - `update_binary_distillation_problem` (WRITE) -- merges newly-stated
    engineering facts into the accumulated problem state, then returns the
    deterministic assessment of the full accumulated state. This remains
    the ONE canonical WRITE path (Round 2 invariant 3) -- both the
    TurnTransaction executor and the old direct callers still go through it.
  - `get_binary_distillation_problem` (READ) -- never mutates state, returns
    the same deterministic assessment of whatever is already known.
  - `calculate_current_binary_distillation_problem` (CALCULATION EXECUTE) --
    reads the accumulated authoritative state directly and -- only once it
    is `ready_for_calculation` -- runs the deterministic BioSTEAM feed-phase
    calculation from `binary_distillation_calculation.py`. See
    `tools/binary-distillation-connecting-feed-calculation.md`.
  - `get_binary_distillation_calculation_status` / `get_precalculation_progress`
    (CALCULATION READ) -- never mutates anything, never runs BioSTEAM.
    Reports the most recent calculation result (if any) and calculation-
    progress state.
  - `reset_workflow_session` (housekeeping) -- clears all accumulated state.

As of Round 2, NONE of these are exposed to the model as callable tools
(`tools=[...]`) any more -- see `turn_intent.py`'s module docstring for why
native tool-calling was dropped as the interpretation mechanism (Failure 4).
The model's ONLY job each turn is to propose a `TurnIntent` via
JSON-schema-constrained structured output (`format=`); Python validates that
proposal (`turn_transaction.validate_turn_intent`), executes it atomically
(`turn_transaction.execute_turn_transaction`, wired to the four operations
above through `problem_field_registry.ACTION_REGISTRY`), and renders the
result -- deterministically for a focused WRITE/READ turn (Part 11), or via
one further un-tooled chat call for a calculation/progress action turn (same
narration pattern as before, unchanged) or a genuinely broad/off-schema
turn.

This module deliberately does NOT import `separation_tool.py` /
`case_design.py` / `optimizer.py` -- the sizing/optimization sweep layer is
still out of scope here. It DOES import the deterministic feed-phase
calculation layer (`binary_distillation_calculation.py`, which in turn
imports BioSTEAM via `biosteam_feed.py`/`feed_phase.py`) -- that layer is
the sole place any BioSTEAM call happens; the LLM itself never infers feed
phase, vapor fraction, or any other thermodynamic property from general
knowledge. The calculation pipeline currently evaluates ONLY the feed phase
-- no Design Option A-D sizing (reflux ratio, stage count, column diameter,
etc.) is performed here yet. Feed-phase screening and Design Option A-D
assessment are two independent deterministic branches (`feed_screening` /
`design_assessment` in every engineering-tool result) -- see
tools/binary-distillation-separating-feed-phase-from-options-a-d.md. The
CALCULATION tool is gated on `feed_screening['ready']` alone, never on
Design Option A-D completeness.

Run interactively:
    python binary_distillation_workflow_agent.py

Or one-shot:
    python binary_distillation_workflow_agent.py "I want to separate methanol and water."
"""
import argparse
import difflib
import itertools
import json
import re
import sys

import ollama

import turn_diagnostics
from binary_distillation_calculation import STEP_FEED_PHASE, calculate_binary_distillation_problem
from binary_distillation_workflow import assess_binary_distillation_problem
from feed_state import apply_user_update, empty_feed_state
from problem_field_registry import ACTION_REGISTRY, ACTIVE_WORKFLOW_SCHEMA, PROBLEM_FIELD_REGISTRY, bind_action
from problem_snapshot import build_problem_snapshot, read_problem_value
from tool_argument_normalizer import normalize_write_arguments
from turn_intent import TURN_INTENT_JSON_SCHEMA, build_field_catalog_prompt, parse_turn_intent_response, propose_turn_intent
from turn_transaction import make_action_transaction, make_raw_update_transaction, validate_turn_intent

MODEL = 'qwen3:8b'

# Accumulated problem state for the CURRENT separation problem, across
# however many tool calls it takes to fully specify it -- the
# "BinaryDistillationProblemState" of tools/binary-distillation-workflow.md
# section 6. A tool-calling model cannot be relied on to restate every
# already-known field on every follow-up call, so every call MERGES what
# it's given into this dict and the checker is run against the accumulated
# state, not just the current call's arguments.
#
# Feed identity/quantity (component_names, component_flows, total_flow,
# composition, and their units/basis) live in a nested `feed_state`-shaped
# dict under the 'feed' key, accumulated via `feed_state.apply_user_update`
# -- see tools/binary-distillation-flow-rate-issue.md. Only EXPLICIT values
# are ever recorded here; `assess_binary_distillation_problem` (via
# `feed_state.normalize_feed_state`) is the sole place derivation happens,
# so 'user_explicit' vs. 'derived' provenance always reflects true origin.
# Every other field (pressure_Pa, thermal condition, xD, etc.) is merged
# flat, same as before.
_workflow_state = {'feed': empty_feed_state()}

# tools/binary-distillation-whats-next.md Step 8 -- the most recent
# deterministic calculation result for the CURRENT problem, or None if no
# calculation has run yet (or it was invalidated -- see Step 11 below).
# This is calculation-progress TRUTH: never reconstructed from conversation
# history, and never written to by anything other than
# `calculate_current_binary_distillation_problem()`, `reset_workflow_session()`,
# and the WRITE-invalidation logic in `update_binary_distillation_problem()`.
_last_calculation_result = None

# Mutually exclusive within the accumulated state: supplying a new member
# of a group clears any other member left over from an earlier call, so a
# stale earlier choice can never linger and create a false "ambiguous"
# conflict against a later, different choice.
_THERMAL_FIELDS = ('feed_temperature_K', 'feed_quality', 'feed_enthalpy_kJ_per_hr')
_REFLUX_QUANTITY_FIELDS = ('external_reflux_ratio_LD', 'reflux_ratio_multiplier_k')

_FEED_UPDATE_FIELDS = (
    'component_names', 'add_component_names', 'component_flows',
    'component_flow_units', 'total_flow', 'total_flow_units',
    'composition', 'composition_basis',
)

# tools/binary-distillation-turn-diagnostics-plan.md Step 5/6 -- one
# monotonically increasing counter for diagnostic-record turn_ids across
# the life of the process (REPL) or a single one-shot call.
_turn_id_counter = itertools.count(1)


def _next_turn_id():
    return f'turn-{next(_turn_id_counter)}'


def _state_snapshot():
    """A JSON-safe, fully-detached copy of the accumulated `_workflow_state`
    (flat fields plus its nested 'feed' dict) -- used ONLY to build a
    before/after diagnostic state diff. Never returned to a caller as
    authoritative state and never itself mutated."""
    return turn_diagnostics.to_jsonable(_workflow_state)


def _merge_into_state(new_fields):
    _workflow_state['feed'] = apply_user_update(_workflow_state['feed'], new_fields)

    for group in (_THERMAL_FIELDS, _REFLUX_QUANTITY_FIELDS):
        given_in_group = [k for k in group if new_fields.get(k) is not None]
        if len(given_in_group) == 1:
            for other in group:
                if other != given_in_group[0]:
                    _workflow_state.pop(other, None)
    for key, value in new_fields.items():
        if key in _FEED_UPDATE_FIELDS:
            continue
        if value is not None:
            _workflow_state[key] = value
    return _workflow_state


def reset_workflow_session() -> dict:
    """Clear all previously-remembered inputs for the current binary-distillation problem-definition workflow, so the next call starts a fresh, unrelated problem from scratch.

    Call this ONLY when the user is clearly switching to a different separation problem (different components, or they explicitly say to start over) -- not between follow-up turns that are still refining the same problem.

    Returns:
        {'reset': True, 'message': str} confirming the accumulated state was cleared.
    """
    global _last_calculation_result
    _workflow_state.clear()
    _workflow_state['feed'] = empty_feed_state()
    _last_calculation_result = None
    return {'reset': True, 'message': 'All previously remembered problem-definition inputs have been cleared.'}


def _effective_spec():
    """Flatten the accumulated `feed_state` into the flat spec `assess_binary_distillation_problem` expects, passing along only EXPLICIT feed facts -- derivation happens exactly once, inside that call, so provenance always reflects true origin (never re-labels a derived value as explicit)."""
    feed = _workflow_state['feed']
    spec = {k: v for k, v in _workflow_state.items() if k != 'feed'}
    spec['component_names'] = feed['component_names']
    spec['component_flows'] = {
        n: v for n, v in feed['component_flows'].items()
        if feed['component_flows_provenance'].get(n) == 'user_explicit'
    }
    spec['component_flow_units'] = feed['component_flow_units']
    spec['total_flow'] = feed['total_flow'] if feed['total_flow_provenance'] == 'user_explicit' else None
    spec['total_flow_units'] = feed['total_flow_units']
    spec['composition'] = {
        n: v for n, v in feed['composition'].items()
        if feed['composition_provenance'].get(n) == 'user_explicit'
    }
    spec['composition_basis'] = feed['composition_basis']
    return spec


def update_binary_distillation_problem(
    component_names: list[str] | None = None,
    add_component_names: list[str] | None = None,
    component_flows: dict[str, float] | None = None,
    component_flow_units: str | None = None,
    total_flow: float | None = None,
    total_flow_units: str | None = None,
    composition: dict[str, float] | None = None,
    composition_basis: str | None = None,
    pressure_Pa: float | None = None,
    feed_temperature_K: float | None = None,
    feed_quality: float | None = None,
    feed_enthalpy_kJ_per_hr: float | None = None,
    reflux_condition: str | None = None,
    xD: float | None = None,
    xB: float | None = None,
    Lr: float | None = None,
    Hr: float | None = None,
    distillate_flow: float | None = None,
    bottoms_flow: float | None = None,
    boilup_ratio_VB: float | None = None,
    external_reflux_ratio_LD: float | None = None,
    reflux_ratio_multiplier_k: float | None = None,
    use_optimum_feed_plate: bool | None = None,
) -> dict:
    """WRITE operation: merge newly-stated engineering facts into the binary-distillation problem state, then check the full accumulated state against Wankat Table 3-1/3-2 and report what's missing, which design case (A-D) it matches, and -- once fully specified -- what a designer WOULD calculate. Performs NO distillation calculation, sizing, or optimization; this is a problem-definition and workflow-routing check only.

    Call this ONLY when the current user message states new engineering information. If the user is instead asking a question about information already supplied, derived, or still missing (e.g. "what is my feed composition?", "what pressure did I specify?", "what's still missing?"), call `get_binary_distillation_problem()` instead -- do NOT call this tool just to answer a question, and never resubmit a value that is already known or was only derived (not stated by the user) as if it were a new input.

    This tool REMEMBERS every field you've given it so far in this conversation about the current separation problem -- you do NOT need to repeat components, pressure, feed condition, or anything else from an earlier call. Just call this again with only whatever is new; it is merged with everything already known. Call `reset_workflow_session()` only when the user switches to a genuinely different, unrelated separation problem.

    Never invent a value for any argument the user has not stated. In particular, never assume column pressure, feed thermal condition, reflux condition, product purity, recovery, reflux ratio, boilup ratio, product flow, or optimum-feed-plate use. Never pass a value here merely because it already appears in a prior tool result (whether 'user_explicit' or 'derived') -- only pass what the CURRENT message newly states.

    Component IDENTITY and component QUANTITY are separate concepts -- a component name never implies a flow rate, and a single component's flow is never the total feed flow unless the user says so explicitly. Only pass a numeric flow/total_flow/composition value the user actually stated.

    Args:
        component_names: The FULL, current list of component names for this separation, e.g. ["Water", "Methanol"] -- use this when the user is stating (or restating) which components are in the feed, e.g. "Separate methanol and water" or "I want to separate water, methanol, and butanol." This REPLACES any previously-known component list AND clears any previously-known flows/total_flow/composition (they described the old, different feed). Do not populate this with invented numbers -- just the names.
        add_component_names: A component name (or names) to ADD to the already-established list, without touching any already-known flow/composition data -- use this specifically when the user is answering "please specify the second component" with just a bare name, e.g. the user previously named one component and now names one more. Do not use this to restate the whole feed; use `component_names` for that.
        component_flows: Per-component flow rates actually stated by the user this turn, e.g. {"Methanol": 50} or {"Methanol": 40, "Water": 60} -- give only the component(s) whose flow the user actually stated. A single component's flow is NOT the total feed flow -- never infer or pass a value for the other component. Naming the flow of a component not yet in `component_names`/the accumulated state also establishes that component's identity. FLOW-UNIT EXTRACTION RULE: whenever the user states a flow rate together with units in the same message (e.g. "50 kmol per hour methanol and 50 kmol per hour water"), pass BOTH `component_flows` AND `component_flow_units` in this same call -- never discard explicitly stated units, and never state a numeric flow without also passing its units when the user gave them.
        component_flow_units: Units for `component_flows`, e.g. "kmol/hr". Required before a calculation can run once `component_flows` is how the feed quantity was given -- pass it as soon as the user states it, even if given in the same message as the flow rates themselves.
        total_flow: The TOTAL feed flow rate, ONLY if the user explicitly described it as the total feed (e.g. "100 kmol/hr total" or "100 kmol/hr, 40% methanol") -- never set this from a single component's stated flow rate.
        total_flow_units: Units for `total_flow`, e.g. "kmol/hr". Required before a calculation can run once `total_flow` is how the feed quantity was given.
        composition: Mole or mass fraction(s) actually stated by the user this turn, e.g. {"Methanol": 0.4} or {"Methanol": 0.4, "Water": 0.6} -- give only what was actually stated; do not compute or guess the complementary fraction yourself, the checker derives it when the binary pair is established.
        composition_basis: "mole" or "mass", if the user specified which.
        pressure_Pa: Column pressure in Pascal. Never assume 1 atm -- only pass this if the user stated a pressure.
        feed_temperature_K: Feed temperature in Kelvin. Give at most one of feed_temperature_K/feed_quality/feed_enthalpy_kJ_per_hr -- never assume the feed is at its bubble point. Whenever the user explicitly states a feed temperature in Kelvin, include it in the SAME call as every other explicit fact from that message -- never omit it merely because pressure, composition, or reflux condition are also present. Examples: "feed temperature is 355 K" -> feed_temperature_K=355; "at 355 K and 101325 Pa" -> feed_temperature_K=355 AND pressure_Pa=101325 together; "the feed enters at 400 K" -> feed_temperature_K=400. Never infer a temperature from an unrelated number (a reflux ratio, xD/xB, a pressure in Pa, or a condenser/reboiler/bottoms temperature) -- only a value the user explicitly ties to the FEED's thermal condition.
        feed_quality: Feed vapor fraction/quality (0 = saturated liquid, 1 = saturated vapor). Alternative to feed_temperature_K.
        feed_enthalpy_kJ_per_hr: Feed molar enthalpy. Alternative to feed_temperature_K.
        reflux_condition: Reflux thermal condition. Today only the literal string "saturated_liquid" is recognized -- pass it only once the user has explicitly stated or confirmed saturated-liquid reflux; never assume it silently.
        xD: Case A/D -- target light-key mole fraction in the distillate.
        xB: Case A/D -- target light-key mole fraction in the bottoms.
        Lr: Case B -- target fractional recovery of the light key to the distillate.
        Hr: Case B -- target fractional recovery of the heavy key to the bottoms.
        distillate_flow: Case C -- specified distillate flow rate. Give at most one of distillate_flow/bottoms_flow.
        bottoms_flow: Case C -- specified bottoms flow rate.
        boilup_ratio_VB: Case D -- specified boilup ratio V/B.
        external_reflux_ratio_LD: Wankat's external/actual reflux ratio L0/D (Cases A-C) -- what a user normally means by "the reflux ratio". Do NOT confuse with reflux_ratio_multiplier_k; never convert one into the other yourself.
        reflux_ratio_multiplier_k: An internal shortcut-method reflux multiplier (k = R/Rmin), only if the user explicitly speaks in "x times minimum reflux" terms. Distinct from external_reflux_ratio_LD -- never treat them as interchangeable.
        use_optimum_feed_plate: Whether the design should use the optimum feed plate. This is common to ALL FOUR cases and is never itself evidence of which case applies -- ask for it separately, and never default it to True.

    Returns:
        If `component_flows` or `component_flow_units` was malformed (e.g. `component_flows` given as a list instead of a name->flow mapping, with lengths/types that don't allow a safe automatic fix), returns `{'valid': False, 'error': 'invalid_tool_arguments', 'field', 'expected', 'received_type', 'message'}` instead -- relay `message` to the user and resend the SAME information in the correct shape; do not retry with a guessed shape.

        Otherwise, a dict (see binary_distillation_workflow.assess_binary_distillation_problem for the full schema): 'valid_binary_scope', 'component_count', 'feed_flow_complete', 'feed_composition_complete', 'essential_complete', 'missing_essential_inputs', 'case', 'case_candidates', 'case_complete', 'missing_case_inputs', 'optimum_feed_plate_confirmed', 'calculation_inputs_complete', 'missing_calculation_inputs', 'status', 'would_calculate', 'would_calculate_details', 'calculation_performed' (always False), 'message', 'provenance'. When `status` is 'ready_for_calculation', use `would_calculate_details` (a list of `{'field', 'symbol', 'label'}` dicts) to describe each quantity -- it is the authoritative engineering meaning; see the ENGINEERING OUTPUT GROUNDING RULE below. `would_calculate` (bare strings, e.g. "QR") is kept only for backward compatibility -- do not define or explain a symbol from that field alone. `status` can be 'inconsistent_input' if redundant information disagreed (e.g. component flows don't sum to a stated total) -- relay the conflict in 'message' and ask the user to resolve it rather than picking a value yourself. `status` can also be 'need_calculation_inputs': the engineering problem definition is otherwise complete, but flow-rate units (`component_flow_units` or `total_flow_units`, named in `missing_calculation_inputs`) are still needed before the calculation layer can run -- ask only for that, and do NOT claim the problem is `ready_for_calculation` while this status shows. Relay 'message' (and the relevant missing_*/case_candidates fields) to the user rather than reproducing this logic yourself -- never infer a case, never invent a missing value or a missing unit, and never claim a calculation was performed. The dict ALSO always includes two independent branches: 'feed_screening' (`{'ready', 'missing_inputs', 'status', 'message'}` -- whether the feed-VLE calculation can run; depends only on component identity/quantity/units, pressure, and the feed's own thermal condition) and 'design_assessment' (`{'design_option', 'design_option_candidates', 'complete', 'missing_inputs', 'ambiguous', 'reflux_condition_given', 'optimum_feed_plate_confirmed', 'status', 'message'}` -- Design Option A-D completeness, including reflux_condition and optimum-feed-plate confirmation). These are independent: 'feed_screening'['ready'] can be True while 'design_assessment'['complete'] is False, and vice versa. `calculate_current_binary_distillation_problem` is gated on 'feed_screening'['ready'] alone, not on 'design_assessment'['complete'] or the legacy 'status' field.
    """
    global _last_calculation_result

    # tools/binary-distillation-issues-9-1-2026-first.md Round 1 -- Qwen has
    # been observed sending component_flows as a parallel list (paired
    # against component_names) and/or component_flow_units as a list of
    # repeated values, instead of the canonical dict[str, float] / str
    # shapes the schema already declares. Normalize the unambiguous cases
    # deterministically here, at the tool-argument boundary, before this
    # malformed shape can ever reach feed_state.apply_user_update() (which
    # assumes the canonical shape and would otherwise crash with a raw
    # AttributeError). An ambiguous/invalid shape returns a structured
    # 'invalid_tool_arguments' error dict instead of proceeding.
    normalized_args, arg_error = normalize_write_arguments(
        component_names, component_flows, component_flow_units,
    )
    if arg_error is not None:
        return arg_error
    component_flows = normalized_args['component_flows']
    component_flow_units = normalized_args['component_flow_units']

    new_fields = dict(
        component_names=component_names, add_component_names=add_component_names,
        component_flows=component_flows, component_flow_units=component_flow_units,
        total_flow=total_flow, total_flow_units=total_flow_units,
        composition=composition, composition_basis=composition_basis,
        pressure_Pa=pressure_Pa, feed_temperature_K=feed_temperature_K,
        feed_quality=feed_quality, feed_enthalpy_kJ_per_hr=feed_enthalpy_kJ_per_hr,
        reflux_condition=reflux_condition,
        xD=xD, xB=xB, Lr=Lr, Hr=Hr,
        distillate_flow=distillate_flow, bottoms_flow=bottoms_flow,
        boilup_ratio_VB=boilup_ratio_VB,
        external_reflux_ratio_LD=external_reflux_ratio_LD,
        reflux_ratio_multiplier_k=reflux_ratio_multiplier_k,
        use_optimum_feed_plate=use_optimum_feed_plate,
    )

    # tools/binary-distillation-whats-next.md Step 11 -- a calculation
    # result already computed for the PREVIOUS engineering state must never
    # remain authoritative once that state changes. The simplest safe rule:
    # any successful non-empty engineering WRITE invalidates it, even if
    # this occasionally invalidates more than strictly necessary.
    if any(v is not None for v in new_fields.values()):
        _last_calculation_result = None

    _merge_into_state(new_fields)

    return assess_binary_distillation_problem(_effective_spec())


def get_binary_distillation_problem() -> dict:
    """READ operation: return the current binary-distillation problem state -- what has been supplied, what has been derived, which Design Option (if any) it matches, and what is still missing -- WITHOUT changing anything.

    Call this whenever the user asks about information already supplied, derived, or still missing, instead of guessing from earlier chat text or calling `update_binary_distillation_problem`. Examples: "What is my feed composition?", "What is the feed flow rate?", "What pressure did I specify?", "What information do you have so far?", "What is still missing?", "Which Design Option am I in?", "What would be calculated?". Takes no arguments -- it is strictly read-only and never mutates the accumulated state, never derives anything beyond what the deterministic checker already derives, and never invents a value.

    Returns:
        The identical schema `update_binary_distillation_problem` returns (see that tool's docstring), computed from whatever has already been accumulated -- no new information is merged in by this call.
    """
    return assess_binary_distillation_problem(_effective_spec())


def calculate_current_binary_distillation_problem() -> dict:
    """CALCULATION operation: run the deterministic feed-phase calculation for the CURRENTLY accumulated binary-distillation problem. Reads the authoritative workflow state directly -- takes NO arguments, and must never be used to add, modify, guess, or restate any engineering input.

    Call this to answer any question about feed phase, vapor fraction, liquid fraction, or other calculated thermodynamic property of the current problem (e.g. "What is the feed phase?", "Is the feed liquid or vapor?", "What is the vapor fraction?"). Do NOT call `get_binary_distillation_problem` first just to check readiness -- this tool already reads the same state and reports the workflow status alongside the calculation, so a separate READ beforehand is redundant.

    The calculation only proceeds when the accumulated problem is `ready_for_calculation`; otherwise this returns `calculation_performed: False` and the same workflow assessment `get_binary_distillation_problem` would -- relay `missing_essential_inputs` / `case_candidates` / `message` from the returned `workflow` and explain what is still needed, rather than guessing the property yourself.

    The calculation pipeline evaluates the feed phase (`checks['feed_phase']`: liquid / vapor / vapor_liquid classification, vapor/liquid fraction, per-component vapor/liquid molar flows) and, deterministically from that result, a post-feed-phase routing decision (`checks['routing']`, plus `checks['vapor_condensation_screen']` -- a rigorous BioSTEAM screen conditioning the overall feed to 313.15 K -- whenever the feed contains any vapor fraction, i.e. `phase` is `vapor` or `vapor_liquid`). It does NOT compute distillate/bottoms flow, reflux ratio, reboiler/condenser duty, theoretical stage count, feed stage, or column diameter for the identified Design Option, and it does NOT design or size any liquid- or vapor-phase separator -- never describe any of those as calculated from this tool's result. Which route applies is decided in Python, never by you.

    Returns:
        {'calculation_performed': bool, 'workflow': <same assessment schema as get_binary_distillation_problem>, 'checks': {'feed_phase': {...}, 'routing': {...}, 'vapor_condensation_screen': {...} (whenever the feed has any vapor fraction)} if calculation_performed else {}, 'calculation_progress': {...}}.
    """
    global _last_calculation_result
    result = calculate_binary_distillation_problem(_effective_spec())
    _last_calculation_result = result
    return result


def get_binary_distillation_calculation_status() -> dict:
    """CALCULATION READ operation: return the most recent deterministic calculation result and its calculation-progress state for the CURRENT binary-distillation problem, WITHOUT performing a new calculation. Takes no arguments and never runs BioSTEAM.

    Call this to answer "what have we calculated?", "what next?", "continue", "what remains?", "where are we?" and similar calculation-PROGRESS questions -- as opposed to `calculate_current_binary_distillation_problem`, which actually runs the calculation, or `get_binary_distillation_problem`, which reports problem-DEFINITION state (inputs given/missing), not what has been calculated.

    Returns:
        If no calculation has been performed yet (or a prior result was invalidated by a later engineering WRITE or a reset): {'calculation_available': False, 'latest_calculation': None, 'message': str}.
        Otherwise: {'calculation_available': True, 'latest_calculation': <the full calculate_current_binary_distillation_problem() result, including 'calculation_progress'>, 'message': str} -- 'message' echoes `latest_calculation['calculation_progress']['message']`.
    """
    if _last_calculation_result is None:
        return {
            'calculation_available': False,
            'latest_calculation': None,
            'message': (
                'No deterministic calculation has been performed for the '
                'current binary-distillation problem.'
            ),
        }
    return {
        'calculation_available': True,
        'latest_calculation': _last_calculation_result,
        'message': _last_calculation_result['calculation_progress']['message'],
    }


def get_precalculation_progress() -> dict:
    """
    Internal (not model-exposed) helper -- tools/binary-distillation-whats-next.md
    Step 18. Gives "what next?"/"continue" deterministic meaning even BEFORE
    the first calculation has run, by reading the authoritative workflow
    state directly. Never mutates state and never runs BioSTEAM.
    """
    assessment = get_binary_distillation_problem()

    # tools/binary-distillation-separating-feed-phase-from-options-a-d.md
    # Step 24 -- the next executable stage is feed-phase evaluation as soon
    # as FEED SCREENING alone is ready; it must never wait on Design Option
    # A-D completeness.
    if assessment['feed_screening']['ready']:
        return {
            'calculation_available': False,
            'calculation_progress': {
                'completed_steps': [],
                'next_step': STEP_FEED_PHASE,
                'next_step_available': True,
                'remaining_steps': [STEP_FEED_PHASE],
                'blocked_reason': None,
                'message': (
                    'The problem is ready. The next implemented calculation '
                    'step is feed-phase evaluation.'
                ),
            },
        }

    return {
        'calculation_available': False,
        'calculation_progress': {
            'completed_steps': [],
            'next_step': None,
            'next_step_available': False,
            'remaining_steps': [],
            'blocked_reason': 'workflow_not_ready',
            'message': assessment['feed_screening']['message'],
        },
    }


def _read_calculation_status_action():
    """Bound to the 'read_calculation_status' action verb -- reproduces the
    same dual-path progress logic `_run_progress_query_and_finalize` used to
    pick between directly: the real calculation-status READ once a
    calculation has run, or the pre-calculation progress helper before
    that. Read-only; never runs BioSTEAM."""
    if _last_calculation_result is not None:
        return get_binary_distillation_calculation_status()
    return get_precalculation_progress()


# tools/binary-distillation-issues-9-1-2026-fifth.md Part 8 -- wire this
# module's own operations into the generic ACTION_REGISTRY verbs. Bound
# here (not in problem_field_registry.py) to avoid a circular import --
# that module is imported BY this one.
bind_action('reset_current_problem', reset_workflow_session)
bind_action('calculate_current_step', calculate_current_binary_distillation_problem)
bind_action('read_calculation_status', _read_calculation_status_action)


# ---------------------------------------------------------------------------
# tools/binary-distillation-pending-truth.md -- deterministic pending-request
# resolution. A short contextual reply ("Of course!", "0.99") is never
# resolved by asking the LLM to decide what it means and trusting it to call
# the WRITE tool correctly -- it is matched here, in Python, against the
# `pending_request` the deterministic checker itself is currently asking
# for, and converted straight into a real `update_binary_distillation_problem`
# call before the model ever gets a turn to fabricate a claim that isn't
# backed by an actual state change (section 1/4/11 of that doc).
# ---------------------------------------------------------------------------

_AFFIRMATIVE_PHRASES = {
    'yes', 'yeah', 'yep', 'sure', 'okay', 'ok', 'of course', 'ofcourse',
    'thats fine', 'do it', 'use it', 'absolutely', 'sounds good', 'confirmed',
}
_NEGATIVE_PHRASES = {
    'no', 'nope', 'dont', 'do not', 'dont use it', 'not necessary', 'no thanks',
}

# A genuine short reply to a pending question is short. Capping the word
# count keeps a longer, unrelated message (e.g. "No, actually let's start
# over with ethanol and water" -- which happens to start with a negative
# word) from being misread as an answer to the pending field; it falls
# through to normal model-driven routing instead (section 6/8).
_MAX_SHORT_REPLY_WORDS = 6

# Recognized only as an EXACT match once `status == 'ready_for_calculation'`
# -- section 15. Deliberately not prefix-matched like the boolean phrases
# above, since these are meant to catch a small, specific set of "proceed"
# requests, not any sentence that happens to start with "yes".
_PROCEED_PHRASES = {'yes', 'yes boss', 'go ahead', 'proceed', 'calculate it', 'do it', 'lets go'}


def normalize_short_reply(text):
    """Lowercase, strip surrounding whitespace/punctuation noise (section 6) -- e.g. 'Ofcourse!@' -> 'ofcourse', 'YES!!!' -> 'yes', 'nope.' -> 'nope'. Keeps digits, '.', and '-' so numeric replies ('0.99', '-1.5') survive intact."""
    text = (text or '').strip().lower()
    text = re.sub(r"[^a-z0-9.\-\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.strip('. ')


# ---------------------------------------------------------------------------
# tools/binary-distillation-flow-units.md Step 5 -- deterministic flow-unit
# normalization. Unlike `normalize_short_reply`, this deliberately keeps
# '/' (it's meaningful in a unit like 'kmol/hr'), and maps a small, FIXED
# set of common phrasings to the canonical string BioSTEAM expects. Never
# guesses or invents a unit -- an unrecognized phrasing returns None and is
# left to normal model-driven routing rather than being forced through.
# ---------------------------------------------------------------------------

_FLOW_UNIT_ALIASES = {
    'kmol/hr': 'kmol/hr',
    'kmol/h': 'kmol/hr',
    'kmol per hr': 'kmol/hr',
    'kmol per hour': 'kmol/hr',
    'kilomol/hr': 'kmol/hr',
    'kilomole/hr': 'kmol/hr',
    'kilomole per hour': 'kmol/hr',
    'kilomoles per hour': 'kmol/hr',
    'kilomoles/hr': 'kmol/hr',

    'kg/hr': 'kg/hr',
    'kg/h': 'kg/hr',
    'kg per hr': 'kg/hr',
    'kg per hour': 'kg/hr',
    'kilogram per hour': 'kg/hr',
    'kilograms per hour': 'kg/hr',
    'kilograms/hr': 'kg/hr',
}


def normalize_units_reply(text):
    """Map a flow-unit phrasing to BioSTEAM's canonical unit string via the fixed `_FLOW_UNIT_ALIASES` table (case/spacing-insensitive; e.g. 'KMOL/HR', 'kmol per hour', 'kilomoles per hour' all -> 'kmol/hr'), or None if it doesn't match a known alias. Never infers or defaults a unit."""
    normalized = (text or '').strip().lower()
    normalized = re.sub(r'[.!?]+$', '', normalized).strip()
    normalized = re.sub(r'\s+', ' ', normalized)
    return _FLOW_UNIT_ALIASES.get(normalized)


# ---------------------------------------------------------------------------
# tools/binary-distillation-temperature-issue.md -- deterministic explicit
# feed-temperature extraction. An explicitly Kelvin-suffixed number (e.g.
# '355 K') is an unambiguous signal for `feed_temperature_K` -- never a
# quality (0-1, unitless) or an enthalpy -- so it is safe to resolve
# deterministically without guessing between the three thermal fields.
# ---------------------------------------------------------------------------

_TEMPERATURE_K_PATTERN = re.compile(r'(-?\d+(?:\.\d+)?)\s*k\b', re.IGNORECASE)

# A short, fixed set of unambiguous phrasings naming the FEED's thermal
# condition specifically -- deliberately narrow, same convention as
# `_FEED_PHASE_QUESTION_PHRASES` below. A bare 'NNN K' with none of these
# phrases is only ever resolved via a live `pending_request` (see
# `resolve_pending_reply`'s 'temperature_K' branch), never standalone.
_EXPLICIT_FEED_TEMPERATURE_PHRASES = (
    'feed temperature', 'feed temp', 'feed is at', 'the feed is at',
    'feed enters at', 'the feed enters at',
)

# Step 6 negative examples ("the condenser operates at 355 K", "the bottoms
# temperature is 355 K") -- a Kelvin value named alongside one of these
# apparatus words is never assumed to be the FEED thermal condition, even
# when a feed-thermal-condition pending_request is currently live.
_NON_FEED_TEMPERATURE_CONTEXT_PHRASES = (
    'condenser', 'reboiler', 'bottoms', 'distillate', 'overhead', 'column',
)

# Caps `extract_explicit_feed_temperature_K` to short, standalone
# restatements ("feed temperature is 355 K", "I think I specified the feed
# temperature as 355 K") so it never fires on the rich, multi-fact initial
# problem statement (Step 8/9) -- that one must still be extracted in full
# by the model in a single WRITE, not shortcut down to temperature alone.
_MAX_EXPLICIT_TEMPERATURE_WORDS = 12


def _extract_temperature_K_value(text):
    """Find an explicit Kelvin-suffixed number in `text` (e.g. '355 K', '355K', '-40 K') and return it as a float, or None if no such number is present."""
    match = _TEMPERATURE_K_PATTERN.search(text or '')
    return None if match is None else float(match.group(1))


def _names_non_feed_apparatus(lowered_text):
    return any(phrase in lowered_text for phrase in _NON_FEED_TEMPERATURE_CONTEXT_PHRASES)


def extract_explicit_feed_temperature_K(user_text):
    """Deterministically recognize a short, standalone statement that explicitly names the FEED thermal condition together with an explicit Kelvin value (tools/binary-distillation-temperature-issue.md Step 6, case 2) -- e.g. 'feed temperature is 355 K', 'the feed enters at 400 K'. Returns the float value, or None if `user_text` does not unambiguously state it.

    Requires one of `_EXPLICIT_FEED_TEMPERATURE_PHRASES` -- a bare 'NNN K'
    with no feed-temperature wording is never resolved here; that case is
    only ever handled via a live `pending_request` (see
    `resolve_pending_reply`). Excludes messages that name a different
    apparatus (condenser, reboiler, bottoms, distillate, overhead, column --
    Step 6's negative examples) and is capped at
    `_MAX_EXPLICIT_TEMPERATURE_WORDS` words so it only catches a short
    restatement, never the long multi-fact initial problem statement.
    """
    if not user_text:
        return None
    lowered = user_text.lower()
    if len(lowered.split()) > _MAX_EXPLICIT_TEMPERATURE_WORDS:
        return None
    if not any(phrase in lowered for phrase in _EXPLICIT_FEED_TEMPERATURE_PHRASES):
        return None
    if _names_non_feed_apparatus(lowered):
        return None
    return _extract_temperature_K_value(user_text)


def _feed_thermal_condition_missing(state):
    """True if the deterministic assessment currently reports the feed thermal condition (feed_temperature_K/feed_quality/feed_enthalpy_kJ_per_hr) as not yet given -- regardless of whether other essentials are also missing. Used to gate `extract_explicit_feed_temperature_K`'s standalone (no-pending-request) resolution to only when the field is genuinely still open."""
    return any(
        item.startswith('feed thermal condition')
        for item in (state.get('missing_essential_inputs') or [])
    )


# ---------------------------------------------------------------------------
# tools/binary-distillation-connecting-feed-calculation.md Steps 8-10 --
# explicit feed-phase/vapor-fraction questions are calculation questions,
# never something the model should answer from remembered chemical
# knowledge or from the workflow state alone. This is deliberately a narrow
# substring match against a small set of obvious phrasings -- it exists only
# to catch clear-cut cases, not to reinterpret every user message.
# ---------------------------------------------------------------------------

_FEED_PHASE_QUESTION_PHRASES = (
    'what is the feed phase',
    'what phase is the feed',
    'is the feed liquid',
    'is the feed vapor',
    'is the feed vapour',
    'is the feed two phase',
    'is the feed two-phase',
    'what is the vapor fraction',
    'what is the vapour fraction',
    'how much of the feed is vapor',
    'how much of the feed is vapour',
    'how much of the feed is liquid',
)


def is_feed_phase_question(text):
    """True if `text` explicitly asks about feed phase, vapor fraction, or liquid fraction -- a calculation question that must be routed to `calculate_current_binary_distillation_problem`, never inferred by the model from general chemical knowledge (e.g. remembered boiling points)."""
    normalized = normalize_short_reply(text)
    return any(phrase in normalized for phrase in _FEED_PHASE_QUESTION_PHRASES)


# ---------------------------------------------------------------------------
# tools/binary-distillation-whats-next.md Steps 15-16 -- deterministic
# "what next?"/"continue"/"what remains?" recognition, routed to the
# calculation-PROGRESS state (never generic LLM reasoning, never a re-ask of
# already-known inputs). Multi-word phrases are matched by substring (same
# convention as `_FEED_PHASE_QUESTION_PHRASES` above); the two bare
# single-word phrases ('next', 'continue') are matched only as the ENTIRE
# normalized message, so an unrelated sentence that merely contains the
# word "next" (e.g. "what's the next component?") is not misrouted.
# ---------------------------------------------------------------------------

_PROGRESS_PHRASES = (
    'what next', 'what is next', 'whats next',
    'what do we do next', 'what should we do next',
    'okay what next', 'ok what next',
    'what is the next step', 'whats the next step',
    'where are we',
    'what remains', 'what is left',
    'what have we calculated', 'what did we calculate',
)
_PROGRESS_PHRASES_EXACT = ('next', 'continue')


def is_calculation_progress_question(text):
    """True if `text` is asking about calculation PROGRESS ("what next?", "continue", "what remains?", "where are we?", "what have we calculated?", ...) -- routed to `get_binary_distillation_calculation_status`/`get_precalculation_progress`, never answered from conversation history or generic LLM reasoning. Deliberately narrow (section: 'Do not make this detector overly broad')."""
    normalized = normalize_short_reply(text)
    if not normalized:
        return False
    if any(phrase in normalized for phrase in _PROGRESS_PHRASES):
        return True
    return normalized in _PROGRESS_PHRASES_EXACT


# ---------------------------------------------------------------------------
# tools/binary-distillation-issues-9-1-2026-fifth.md Step H -- the entire
# hand-alias-table system that used to live here (_FIELD_ALIAS_TABLE,
# resolve_state_query, format_state_query_answer, resolve_explicit_field_write,
# and their helpers) is RETIRED. It is superseded by the schema-driven
# TurnIntent/TurnTransaction layer (`turn_intent.py`/`turn_transaction.py`/
# `problem_snapshot.py`/`problem_field_registry.py`) plus the deterministic
# formatter below (`format_transaction_response`) -- a new field now needs
# only a `PROBLEM_FIELD_REGISTRY` entry, never a new hand-written phrase
# list or template line. See that doc's "Adapter decision" for why: native
# per-field alias matching does not scale past a fixed field list, and this
# round's failures were exactly the alias table falling behind real phrasing.
# ---------------------------------------------------------------------------


def _matches_short_phrase(normalized, phrases):
    return normalized in phrases or any(normalized.startswith(p + ' ') for p in phrases)


def _resolve_boolean_reply(normalized):
    if _matches_short_phrase(normalized, _AFFIRMATIVE_PHRASES):
        return True
    if _matches_short_phrase(normalized, _NEGATIVE_PHRASES):
        return False
    return None


def resolve_pending_reply(pending_request, user_text):
    """
    Deterministically interpret `user_text` as an answer to
    `pending_request` (as returned by `assess_binary_distillation_problem`),
    returning a dict of {field: value} to pass to
    `update_binary_distillation_problem`, or None if it does not resolve
    unambiguously. Never guesses -- see the word-count/exact-count guards
    below, matching tools/binary-distillation-pending-truth.md sections
    5-8.
    """
    if not pending_request:
        return None

    request_type = pending_request.get('request_type')

    # Checked on the RAW text, before the general short-reply word cap
    # below: a corrective restatement ("I think I specified the feed
    # temperature as 355 K") legitimately runs longer than a bare
    # confirmation, and the 'K' suffix is itself an unambiguous signal --
    # never a quality (0-1) or an enthalpy -- so it is safe to resolve
    # regardless of message length. Still excludes a value explicitly tied
    # to a different apparatus (tools/binary-distillation-temperature-issue.md
    # Step 6).
    if request_type == 'temperature_K':
        if _names_non_feed_apparatus((user_text or '').lower()):
            return None
        value = _extract_temperature_K_value(user_text)
        return None if value is None else {pending_request['field']: value}

    normalized = normalize_short_reply(user_text)
    if not normalized or len(normalized.split()) > _MAX_SHORT_REPLY_WORDS:
        return None

    if request_type == 'boolean_confirmation':
        value = _resolve_boolean_reply(normalized)
        return None if value is None else {pending_request['field']: value}

    if request_type == 'float':
        try:
            return {pending_request['field']: float(normalized)}
        except ValueError:
            return None

    if request_type == 'ordered_float_group':
        fields = pending_request.get('fields') or []
        numbers = re.findall(r'-?\d+(?:\.\d+)?', normalized)
        if not fields or len(numbers) != len(fields):
            return None
        return {field: float(n) for field, n in zip(fields, numbers)}

    if request_type == 'flow_units':
        # Use the RAW text here, not `normalized` above -- normalize_short_reply
        # strips '/', which is meaningful in a unit like 'kmol/hr'.
        unit = normalize_units_reply(user_text)
        return None if unit is None else {pending_request['field']: unit}

    # 'string_choice' (e.g. reflux_condition) is intentionally not resolved
    # here -- a bare "yes" is ambiguous as to WHICH string was confirmed
    # whenever more than one value is ever allowed; leave it to normal
    # model-driven routing to restate the exact string.
    return None


# ---------------------------------------------------------------------------
# tools/binary-distillation-issues-9-1-2026-fifth.md Part 11/12 --
# deterministic, registry-driven rendering of a resolved TurnTransaction.
# TERMINAL: called only for a transaction with no `action` (an action turn
# is finalized through one further un-tooled Qwen call instead -- see
# `_dispatch_transaction` below, same narration pattern the calculation/
# progress paths always used). A focused WRITE/READ turn never reaches the
# model at all, so it can never come back with unrelated Design Option
# guidance, other stored variables, or a suggestion to proceed appended to
# it (Failure 3/Part 11).
# ---------------------------------------------------------------------------

_YES_NO_QUESTION_PREFIXES = ('did', 'have', 'has', 'was', 'do', 'am', 'is', 'didnt', 'hadnt', 'hasnt')


def _format_value(value):
    """Render a stored value without a spurious trailing '.0' on an integral
    float (e.g. `boilup_ratio_VB=2.0` -> '2', not '2.0'), while leaving a
    genuinely fractional value (e.g. `xD=0.95`) untouched."""
    if isinstance(value, bool):
        return 'yes' if value else 'no'
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, list):
        return ', '.join(str(v) for v in value)
    return str(value)


def _field_label(field, entity=None):
    entry = PROBLEM_FIELD_REGISTRY.get(field)
    if entry is None:
        return field
    if entry.get('keyed') and entity is not None:
        base = 'feed flow' if field == 'component_flows' else entry['label']
        return f'{entity} {base}'
    return entry['label']


def _units_suffix(units):
    return f' {units}' if units else ''


def _looks_like_yes_no_reference(raw_reference):
    if not raw_reference:
        return False
    normalized = normalize_short_reply(raw_reference)
    if not normalized:
        return False
    return normalized.split(' ', 1)[0] in _YES_NO_QUESTION_PREFIXES


def _format_update_sentence(update):
    field, entity, value, units = update['field'], update['entity'], update['value'], update['units']
    entry = PROBLEM_FIELD_REGISTRY[field]
    if not units:
        units = entry.get('canonical_units')
    return f'The {_field_label(field, entity)} is now {_format_value(value)}{_units_suffix(units)}.'


def _group_invalid_updates(invalid_updates):
    """Group rejected updates by (field, reason), preserving first-seen
    order -- tools/binary-distillation-turn-diagnostics-plan.md Step 7. Two
    missing-entity failures for the same keyed field must produce ONE
    user-facing sentence; the full per-update detail (both rejected
    entries, their update_index/field_metadata) still lives in the
    TurnTransaction/diagnostic record untouched by this grouping."""
    groups = {}
    order = []
    for invalid in invalid_updates:
        raw_update = invalid['update']
        field = raw_update.get('field', '<unknown>') if isinstance(raw_update, dict) else '<unknown>'
        key = (field, invalid['reason'])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(invalid)
    return [(key, groups[key]) for key in order]


def _format_invalid_update_note(field, reason, entries):
    """One user-facing sentence for a whole GROUP of identically-rejected
    updates (same field + reason). Uses registry metadata for a useful,
    generic message rather than exposing a bare internal reason token --
    Step 7: avoid blaming the user when their sentence was unambiguous,
    state that nothing was saved because validation is atomic, and remain
    generic enough to support any future keyed field (not special-cased to
    component_flows)."""
    entry = PROBLEM_FIELD_REGISTRY.get(field)
    label = entry['label'] if entry else field
    if reason == 'missing_entity' and entry and entry.get('keyed'):
        return (
            f'I failed to associate the stated {label} values with their '
            f'component names, so none of the values from this message were saved.'
        )
    return (
        f"I couldn't apply the stated value for {label} this turn "
        f'({len(entries)} value(s) rejected), so nothing was saved for it.'
    )


def _format_conflict_note(conflict):
    return f"Conflicting values were given for {_field_label(conflict['field'], conflict.get('entity'))}; nothing was changed."


def _format_query_sentence(query, result):
    if not result['valid']:
        error = result['error']
        if error == 'unknown_problem_field':
            reference = query.get('raw_reference') or query['field']
            text = f'{reference} is not a recognized variable in the current binary-distillation workflow.'
            if result.get('near_matches'):
                text += f" Did you mean {result['near_matches'][0]}?"
            return text
        if error == 'unknown_problem_entity':
            return f"Which component's {_field_label(query['field'])} do you mean?"
        if error == 'unknown_problem_subject':
            return f"I don't have that subject on file for {_field_label(query['field'])}."
        return f"I couldn't resolve {query['field']}."

    found, value, units = result['found'], result['value'], result['units']
    label = _field_label(query['field'], result.get('entity'))
    if found:
        base = f'The {label} is {_format_value(value)}{_units_suffix(units)}.'
    else:
        base = f'The {label} has not been specified yet.'
    if _looks_like_yes_no_reference(query.get('raw_reference')):
        return ('Yes. ' if found else 'No. ') + base
    return base


def format_transaction_response(transaction, execution_result):
    """Render a resolved (action-free) TurnTransaction into the final
    user-facing sentence(s) -- no model call involved. Preserves query
    order and puts update confirmations first (Part 11's "Mixed update/
    query" example)."""
    sentences = []
    # A rejected update whose field is ALSO being queried this same turn is
    # a benign, common pattern (the model redundantly restated a value
    # while also asking about it, e.g. a read-only field like total_flow,
    # or the same value it just confirmed) -- the query answer already
    # covers it, so no separate rejection note is surfaced for it.
    queried_fields = {q['field'] for q in transaction['queries']}

    for update in transaction.get('valid_updates', []):
        sentences.append(_format_update_sentence(update))
    unqueried_invalid = [
        invalid for invalid in transaction['invalid_updates']
        if invalid['update'].get('field') not in queried_fields
    ]
    for (field, reason), entries in _group_invalid_updates(unqueried_invalid):
        sentences.append(_format_invalid_update_note(field, reason, entries))
    for conflict in transaction['conflicts']:
        if conflict['field'] in queried_fields:
            continue
        sentences.append(_format_conflict_note(conflict))
    for query, result in zip(transaction['queries'], execution_result['query_results']):
        sentences.append(_format_query_sentence(query, result))

    # Engineering-output grounding (tools/chopper/binary-distillation-incorrect-symbol-reading-issue.md):
    # a plain WRITE-only turn (no queries) that just reached
    # 'ready_for_calculation' states exactly what a full design would
    # calculate, using would_calculate_details' own symbol/label pairs --
    # deterministically, so this can never be mis-narrated by the model.
    assessment = execution_result['assessment']
    if transaction.get('valid_updates') and not transaction['queries'] and assessment.get('status') == 'ready_for_calculation':
        details = assessment.get('would_calculate_details') or []
        if details:
            case = assessment.get('case')
            parts = ', '.join(f"{d['symbol']} ({d['label']})" for d in details)
            sentences.append(
                f'Your problem is fully specified as Design Option {case}. '
                f'A full Design Option {case} design would calculate: {parts}.'
            )

    return ' '.join(sentences) if sentences else 'Understood.'


# tools/binary-distillation-workflow.md section 17 -- "Important Behavioral
# Requirement for Qwen".
SYSTEM_PROMPT = """You are not the binary-distillation decision engine.

You do not have any callable tools this turn. Your ONLY job each turn is to \
interpret the CURRENT user message (the final user message in the \
conversation) into a `TurnIntent` JSON object -- `updates` (new engineering \
facts to write), `queries` (questions about existing state), and `action` \
(at most one of `calculate_current_step`, `read_calculation_status`, \
`reset_current_problem`, or `null`). Python -- never you -- validates every \
proposed update/query/action against the actual workflow schema, performs \
the one atomic WRITE, and executes the action. You never invent a field, \
guess which known field an unrecognized symbol means, or fabricate a \
result -- if a symbol is not in the field catalog you were given, put it in \
`queries` verbatim and Python will report it as unrecognized.

Four underlying operations exist for reference (you never call them \
directly; Python dispatches to them from your validated TurnIntent):
  - `update_binary_distillation_problem` (WRITE) -- merges newly-stated \
engineering facts into the accumulated problem state.
  - `get_binary_distillation_problem` (READ) -- returns the current \
accumulated state; never mutates anything.
  - `calculate_current_binary_distillation_problem` (CALCULATION EXECUTE) -- \
runs the deterministic feed-phase calculation once the problem is \
`ready_for_calculation`.
  - `get_binary_distillation_calculation_status` (CALCULATION READ) -- \
reports the most recent calculation result and calculation-progress state; \
never runs a new calculation.

For a turn Python routes to you for narration (an `action` turn, or a \
broad/off-schema question), the result of that operation is already in the \
conversation as a tool result -- describe it; never re-request the \
operation yourself, since no tools are available to call.

## FEED SCREENING VS DESIGN OPTION RULE

Feed-phase screening and Design Option A-D identification are two \
separate, independent deterministic workflows, both computed on every \
WRITE/READ call and reported as two independent top-level fields:
  - `feed_screening` (`{'ready', 'missing_inputs', 'status', 'message'}`) -- \
whether the feed-VLE/reference-temperature-conditioning calculation can \
run. Depends ONLY on: component identity, feed quantity/composition, flow-\
rate units, column pressure, and the feed's own thermal condition. Never \
depends on `reflux_condition`, xD/xB/Lr/Hr, a product flow, a boilup \
ratio, an external reflux ratio, or optimum-feed-plate confirmation.
  - `design_assessment` (`{'design_option', 'design_option_candidates', \
'complete', 'missing_inputs', 'ambiguous', 'reflux_condition_given', \
'optimum_feed_plate_confirmed', 'status', 'message'}`) -- Design Option \
A-D completeness. Independent of feed-screening readiness in both \
directions.

These two are never conflated. All explicit user facts are stored \
immediately regardless of which branch they belong to -- storage order is \
never the same thing as execution order. `calculate_current_binary_distillation_problem` \
is gated ONLY on `feed_screening['ready']`; it never waits on \
`design_assessment['complete']`, `reflux_condition`, or optimum-feed-plate \
confirmation. A problem can be simultaneously `feed_screening['ready'] == \
True` and `design_assessment['complete'] == False` -- that combination is \
valid and expected, and you should offer/perform the feed-phase check \
immediately rather than first asking the user to complete a Design \
Option. Do NOT require a complete Design Option before offering or \
performing feed-phase evaluation, and do not infer physical routing \
yourself -- always use the deterministic `checks['feed_phase']`/ \
`checks['routing']` result.

## Interpreting a turn into a TurnIntent

1. **New engineering information** (e.g. "Water flow rate is 90 kmol/hr.", \
"Column pressure is 101325 Pa.", "Use xD = 0.98.", "Yes, use the optimum \
feed plate."): put ONLY the new field(s) this turn actually states into \
`updates`.
2. **A question about existing state** (e.g. "What is the feed \
composition?", "What is my total feed flow?", "What pressure did I \
specify?"): put the field(s) asked about into `queries`. Never put an \
existing/derived value into `updates` merely because you are about to \
report it -- that would fabricate a "new" input out of a value nobody just \
restated.
3. **Both at once** (e.g. "Water flow is 90 kmol/hr. What is the resulting \
feed composition?"): populate both `updates` and `queries` in the SAME \
TurnIntent -- Python performs the WRITE first, then resolves every query \
against the post-WRITE state, so you never need a separate follow-up turn.
4. **A calculation-PROGRESS question** (e.g. "What next?", "Continue.", \
"What have we calculated?", "What remains?", "Where are we?") or an \
explicit calculation/reset request: set `action` to the matching name. In \
most cases the orchestrator already recognizes these deterministically \
before you see the turn; see the CALCULATION-PROGRESS TRUTH RULE below.

## CALCULATED ENGINEERING STATE RULE

Thermodynamic properties and calculated engineering results are not \
conversation facts. This includes, but is not limited to: feed phase, \
vapor fraction, liquid fraction, bubble point, dew point, equilibrium \
temperature, equilibrium phase compositions, and boiling behavior.

Never infer, estimate, or state any of these from general chemical \
knowledge, remembered boiling points, or conversation context -- e.g. \
never reason "400 K is above methanol's boiling point, so the feed is \
probably vapor." If the user asks for one of these values:

1. If the current problem is `ready_for_calculation`, call \
`calculate_current_binary_distillation_problem` and report exactly what \
`checks['feed_phase']` says.
2. If the problem is not yet `ready_for_calculation`, use the deterministic \
workflow state (`missing_essential_inputs` / `case_candidates` / `message`) \
to explain what is still missing -- do not guess the value anyway.
3. If the calculation layer cannot determine the requested property (it \
currently only evaluates feed phase -- nothing else), state that \
explicitly rather than answering from general knowledge.

## FEED-PHASE ROUTING RULE

Questions such as "What is the feed phase?", "Is the feed liquid or \
vapor?", "What is the vapor fraction?", "Is the feed two-phase?", "How \
much of the feed is vapor?", or "How much is liquid?" are CALCULATION \
questions. Do not answer them from the workflow state alone, and do not \
call `get_binary_distillation_problem` first to "check" before \
calculating -- `calculate_current_binary_distillation_problem` already \
reads the same state. Call `calculate_current_binary_distillation_problem` \
directly once the authoritative state is `ready_for_calculation`.

## CALCULATION-PROGRESS TRUTH RULE (tools/binary-distillation-whats-next.md)

The deterministic calculation state is the SOLE authority for:
  - which engineering calculations have been completed
  - which calculated values are available
  - what calculation step is available next
  - what calculation steps remain
  - whether a remaining step is implemented
  - whether calculation results are stale or unavailable

Never infer calculation progress from conversation history. Never claim a \
calculation was completed unless the latest deterministic calculation \
result lists it in `calculation_progress['completed_steps']`. Never claim a \
next calculation is available unless `calculation_progress['next_step_available']` \
is true. Never ask the user to re-enter engineering information merely \
because they ask "what next?", "continue", "what remains?", or similar --\
for these, use the calculation-progress state (`get_binary_distillation_calculation_status`), \
not the problem-definition state.

## DO NOT RE-ASK STORED INPUTS

If the authoritative workflow state already contains components, flows, \
units, composition, thermal condition, pressure, case-defining variables, \
reflux condition, and optimum-feed-plate confirmation, do not ask for them \
again unless the deterministic checker reports that they are missing, \
inconsistent, or have been invalidated. A question such as "what next?" \
does not mean the user is starting a new separation problem.

## SPECIFIC STATE QUERY RULE (tools/binary-distillation-issues-9-1-2026-fifth.md Part 11)

When the user asks whether a specific quantity was supplied, or asks for \
its stored value (e.g. "did I already give the ethanol flow?", "what \
pressure did I specify?", "what was the feed temperature?", "did I \
specify xD?"), put that field in `queries`. Python resolves it from state \
and formats the final reply itself -- this is a TERMINAL path and you will \
never actually see the resolved answer or be asked to narrate it; your job \
ends at proposing the TurnIntent.

## State-truth rule (tools/binary-distillation-pending-truth.md)

The deterministic tool state is the SOLE authority for engineering facts. \
Never say a field was supplied, confirmed, changed, or derived unless the \
LATEST tool result actually shows that value in the state -- conversation \
context may help you understand what the user means, but it never itself \
changes engineering state. If a user's message answers a pending question, \
your TurnIntent's `updates` must include it -- see the change reflected \
BEFORE describing it as confirmed, updated, or stored. \
Never output "confirmed", "updated", "stored", "specified", or an \
equivalent claim about a field whose value in the latest tool result \
disagrees with (or is still null/None compared to) what you are about to \
say.

## `pending_request`: what the checker is currently asking for

Every assessment includes a `pending_request` field: `None` when nothing \
specific is outstanding, or a dict identifying the ONE field (or ordered \
field group) the checker is currently waiting on -- e.g. `{'field': \
'use_optimum_feed_plate', 'request_type': 'boolean_confirmation', \
'prompt': ...}` or `{'fields': ['xD', 'xB'], 'request_type': \
'ordered_float_group', ...}`. In most cases the orchestrator already \
converts a short reply to a live `pending_request` into a real WRITE \
deterministically before you see the message -- when that happens you will \
find the tool result already reflects the new value; describe it from that \
result rather than re-deriving it yourself. You are only ever asked to \
narrate a result Python has already produced; you never decide on your own \
that a field is now answered.

**Reporting a value never makes it a new input.** If a value already exists \
in state -- whether its provenance is `user_explicit` or `derived` -- \
telling the user about it does not turn it into something the user just \
supplied. Never put an existing or derived value into `updates` merely \
because you are about to state it or because the checker's message \
mentioned it. Only propose updates for what the CURRENT user message newly \
and explicitly states.

**Do not reconstruct the state from conversation history.** When asked what \
is currently known, missing, or derived, put the relevant field(s) in \
`queries` rather than searching your own earlier replies for a remembered \
number -- the deterministic state is always the source of truth, not your \
prior text.

Never infer a Design Option (A, B, C, or D) yourself when the checker \
has not identified one -- if `case`/`design_option` comes back null and \
`case_candidates`/`design_option_candidates` lists more than one option, \
present those options (or ask which kind of specification the user wants \
to give) rather than guessing.

Never invent missing engineering specifications. Never assume pressure, \
feed thermal condition, reflux thermal condition, product purity, \
recovery, reflux ratio, boilup ratio, product flow, or whether to use the \
optimum feed plate -- these must come from the user's own words.

Component identity and component amount are separate concepts. Naming a \
component (e.g. "separate methanol and water") never implies a flow rate \
for it -- put ONLY a `component_names` update in that case, with no \
numbers. Likewise, a single component's stated flow rate is never the \
total feed flow rate -- put it under a keyed `component_flows` update, and \
never write it as `total_flow` unless the user explicitly says it is the \
total. Extract only what the current message actually states; do not \
reconstruct or guess feed information the user has not (yet) given, even \
partially.

Do NOT perform, describe performing, or claim to have performed any \
Design Option A-D distillation sizing or optimization (distillate/bottoms flow, \
reflux ratio, reboiler/condenser duty, theoretical stage count, feed \
stage, column diameter) during this conversation -- WRITE/READ only check \
problem-definition completeness, and `calculation_performed` is always \
False for them. The `calculate_current_step` action is the one exception: \
it performs ONLY the deterministic feed-phase calculation described above \
-- never describe its result as anything more than that.

State REMEMBERS everything already given about the current separation \
problem -- you do NOT need to repeat components, pressure, feed condition, \
or anything else from an earlier turn. When the user answers a question \
you asked, propose an update with only the NEW field(s) they just gave; \
never just restate their answer as text. Only set `action` to \
`reset_current_problem` when the user is clearly switching to a genuinely \
different, unrelated separation problem, never between ordinary follow-up \
turns.

## Binary scope only

If `status` comes back `need_components`, ask for the missing component(s) \
using the tool's own `message`. If `status` comes back \
`unsupported_multicomponent`, tell the user plainly that only binary (exactly \
two component) separations are supported right now and ask them to narrow \
the request -- do NOT silently pick two of the three-or-more components \
and drop the rest.

## Naming components: `component_names`

Use a `component_names` update with the FULL, current component list \
whenever the user states, restates, or completes the separation's \
identity -- e.g. "Separate methanol and water" gives the full list \
directly. If the user instead answers a question you asked for a missing \
component with just a bare name (e.g. you asked "please specify the second \
component" and they replied "Methanol"), reconstruct the FULL list from \
conversation context (the component(s) already established plus this new \
one) and put that complete list in the update -- `component_names` always \
REPLACES the previously-known list (and clears any previously-known flows/ \
composition, since they described the OLD feed), so never send a partial \
list. Only use `component_names` when NO quantity is given yet for the \
newly-named component(s) in the same message -- if the user also gives a \
flow rate, use a keyed `component_flows` update instead (it establishes \
identity automatically) and do not also write `component_names`.

## Feed quantity: `component_flows` vs `total_flow` + `composition`

If the user gives one or more per-component flow rates (e.g. "40 kmol/hr \
methanol" or "40 kmol/hr methanol, 60 kmol/hr water"), pass exactly what \
they stated under `component_flows` -- give only the component(s) whose \
flow was actually stated; never fill in a value for the other component \
yourself, and never ask for a separate total flow rate if all component \
flows are already known (the checker derives the total). If the user \
instead gives a total flow plus fractions/percentages (e.g. "100 kmol/hr, \
40% methanol"), pass `total_flow` and `composition` instead. If the user \
gives a single mole/mass fraction for an established binary pair (e.g. "40% \
methanol"), pass it under `composition` with just that one entry -- do not \
compute or pass the complementary fraction yourself.

## FLOW-UNIT EXTRACTION RULE

Whenever the user states a flow rate together with its units in the same \
message, preserve BOTH the numeric flow and the units in the SAME \
`update_binary_distillation_problem` call -- never discard explicitly \
stated units. For example, "50 kmol per hour methanol and 50 kmol per hour \
water" must produce `component_flows={"Methanol": 50, "Water": 50}` AND \
`component_flow_units="kmol/hr"` in one call, not just the flows. Likewise, \
"100 kmol/hr total, 40% methanol" must produce `total_flow=100`, \
`total_flow_units="kmol/hr"`, and `composition={"Methanol": 0.4}` together. \
The deterministic checker still rejects the problem as \
`need_calculation_inputs` if units end up missing regardless of what you \
extract here -- but extracting them correctly the first time means you \
won't have to ask for them separately afterward.

## FEED TEMPERATURE EXTRACTION RULE

Whenever the user explicitly states a feed temperature in Kelvin -- alone \
or together with other facts in the same message (e.g. "Separate water \
and ethanol at 355 K and 101325 Pa pressure, ..." or "the feed is 50 \
kmol/hr ethanol and 50 kmol/hr water at 355 K and 101325 Pa") -- include \
`feed_temperature_K` in the SAME `update_binary_distillation_problem` call \
as every other explicit fact from that message. Do not drop it merely \
because pressure, composition, or reflux condition are also present in the \
same sentence: "at 355 K and 101325 Pa" must produce BOTH \
`feed_temperature_K=355` and `pressure_Pa=101325` together, not just one of \
the two. Give at most one of feed_temperature_K/feed_quality/ \
feed_enthalpy_kJ_per_hr -- never assume or default the feed's thermal \
condition, and never infer a temperature from an unrelated number (a \
reflux ratio, xD/xB, or a pressure in Pa).

If the user later restates or corrects the feed temperature (e.g. "I think \
I specified the feed temperature as 355 K", "It was 355 K", "355 K"), that \
is new engineering information supplying a currently missing or corrected \
field -- call `update_binary_distillation_problem` with `feed_temperature_K` \
set, never `get_binary_distillation_problem`. In most cases the \
orchestrator already recognizes this deterministically and performs the \
WRITE for you before you see the message (see `pending_request` below); if \
it hasn't, do it yourself rather than looking the value up. A READ is only \
for a genuine question about what is currently stored (e.g. "What feed \
temperature do you currently have on file?"), never for a statement that \
supplies or restates a value.

## When `status` is `need_essential_inputs`

`missing_essential_inputs` may include a feed-quantity item (the total feed \
flow and/or composition are not yet fully determined) alongside pressure, \
feed thermal condition, and/or reflux condition. Relay the tool's `message` \
directly -- it already distinguishes "nothing about the feed quantity has \
been given" from "some feed quantity was given (e.g. one component's flow), \
but it's not enough to determine the total feed flow and composition yet." \
Never tell the user their feed is fully defined when it isn't, and never \
imply a partial quantity (e.g. one component's flow) is the total. Do not \
discuss Design Options A-D yet unless the user has already volunteered \
case-specific information -- essential inputs come first.

## When `status` is `inconsistent_input`

Redundant feed information was given and it does not agree (e.g. two \
component flows don't sum to a separately-stated total flow, or a stated \
mole fraction doesn't match what the component flows imply). Relay the \
tool's `message`, which names the specific contradiction, and ask the user \
to clarify which value is correct. Never silently pick one value over the \
other yourself.

## When `status` is `need_case_definition`

None of the case-distinguishing fields (xD/xB, Lr/Hr, a product flow, or a \
boilup ratio) have been given yet. Explain, in your own words, the four \
valid Design Option specification sets from the tool's `message` (or \
`case_candidates`/`design_assessment['design_option_candidates']` + the \
general shape: A = compositions + reflux ratio; B = recoveries + reflux \
ratio; C = one product flow + one composition + reflux ratio; D = \
compositions + boilup ratio). The user does not need to say "Design \
Option A" -- they can just give the engineering quantities and the next \
call will identify the Design Option automatically. Do NOT ask the user \
to name a Design Option letter. This has NO effect on whether the feed-\
phase calculation can run -- see the FEED SCREENING VS DESIGN OPTION RULE \
above.

## When `status` is `need_case_inputs`

Either the case has narrowed to one or more candidates that are still \
missing fields (report `missing_case_inputs` for each candidate in \
`case_candidates`), or the case is fully identified but \
`optimum_feed_plate_confirmed` is null -- in that situation, ask "Should the \
design use the optimum feed plate?" Do not treat optimum-feed-plate use as \
identifying a case; it applies to all four.

## When `status` is `ambiguous`

The given fields directly conflict (e.g. both an external reflux ratio and \
an internal k were given, or both a recovery and a composition spec were \
given). Relay the tool's `message` and ask the user to pick one basis. \
Never silently resolve the conflict yourself.

## When `status` is `need_calculation_inputs`

The engineering problem definition (essentials + case + optimum-\
feed-plate) is already complete, but the calculation layer still cannot \
run because a flow-rate UNIT is missing -- `missing_calculation_inputs` \
names exactly which one (`component_flow_units` or `total_flow_units`). \
This is a calculation-adapter requirement, not a new Wankat Table 3-1 \
field -- ask only for the field(s) listed in `missing_calculation_inputs`, \
or follow `pending_request` when present (its `request_type` is \
`flow_units`). Do NOT claim the problem is `ready_for_calculation` while \
this status shows, and do not infer or default the missing unit -- e.g. \
never assume "kmol/hr" just because that's the usual choice.

## When `status` is `ready_for_calculation`

Tell the user their problem is fully specified as Design Option `case`, and \
list exactly the quantities in `would_calculate_details` as what a FULL \
Design Option `case` design would compute -- for each entry, present its \
`symbol` together with its `label` (e.g. "QR (reboiler duty)"). The \
calculation layer available to you does not compute those yet -- it \
evaluates only the feed phase. Do not calculate, approximate, or imply you \
have already found `would_calculate_details`'s values.

## When `feed_screening['ready']` is True but `status` is NOT `ready_for_calculation`

This is expected and valid -- it means the feed has enough information for \
the feed-phase calculation, but the Design Option A-D specification \
(`design_assessment`) is still incomplete (e.g. `reflux_condition`, a \
case-defining field, or optimum-feed-plate confirmation is still missing). \
Tell the user the feed information is sufficient for feed-phase screening, \
and separately state what `design_assessment` still needs -- but do NOT \
withhold or delay the feed-phase check waiting on that. If the user asks \
to proceed, or asks a feed-phase/vapor-fraction question, the calculation \
runs the same way it does when `status` is `ready_for_calculation` (see \
below) -- never tell the user they must first specify `reflux_condition` \
or complete a Design Option before you can check the feed phase.

## ENGINEERING OUTPUT GROUNDING RULE

When a deterministic tool result gives a quantity with an explicit `symbol` \
and `label` (as `would_calculate_details` does), use that `label` verbatim \
for its engineering meaning. Do not expand, reinterpret, rename, or \
redefine an engineering symbol from your own knowledge, and never let a \
symbol's usual meaning in an unrelated context override what the tool just \
told you. For example, if an entry has `symbol="QR"` and \
`label="reboiler duty"`, describe QR only as reboiler duty -- never as \
"reflux flow rate" or any other substitute, no matter how plausible it \
sounds.

If you ever see the legacy `would_calculate` field contain a bare symbol \
with no accompanying `would_calculate_details` entry, do not invent a \
definition for it -- repeat the bare symbol (e.g. "QR") without adding a \
parenthetical meaning, since none was supplied.

If the user then asks to proceed/calculate/go ahead, or asks a feed-phase/ \
vapor-fraction question, the calculation runs automatically before you see \
the message and you will find a `calculate_current_binary_distillation_problem` \
tool result already in the conversation -- describe exactly what its \
`checks['feed_phase']` says, and explicitly note that this is the feed-phase \
check only, not the full Design Option `case` design (`would_calculate`'s other \
quantities are still not computed). Do not call any tool yourself for this \
-- the orchestrator has already run it. After that, prefer a short answer \
built directly from `checks['feed_phase']` and `calculation_progress` -- \
do not re-open with the full problem-definition summary ("Your problem is \
fully specified...") again unless the user actually asks about the \
problem definition.

### Post-feed-phase routing (tools/binary-distillation-feed-vapor-liquid.md, \
updated by tools/binary-distillation-vapor-liquid-dead-end.md)

`checks['feed_phase']['phase']` deterministically decides what happens next \
-- you never make this choice yourself, and the routing decision is always \
already present in `checks['routing']` (and, whenever the feed has any \
vapor fraction, also in `checks['vapor_condensation_screen']`) by the time \
you see the result:

- `phase == 'liquid'`: `checks['routing']['route']` is \
  `liquid_phase_separation`. State that the feed is liquid and should \
  proceed to a liquid-phase separation method, which is not implemented in \
  this pipeline yet. No 313.15 K screen ever runs for a liquid feed.
- `phase == 'vapor'` or `phase == 'vapor_liquid'`: a rigorous BioSTEAM \
  screen conditioning the OVERALL feed to 313.15 K already ran -- \
  `checks['vapor_condensation_screen']['liquid_percent']`/`vapor_percent` \
  are the resulting split AFTER conditioning, and `route` is either \
  `liquid_and_vapor_separation_future` (>= 50 mol% liquefies at 313.15 K -- \
  report BOTH a future liquid-phase and a future vapor-phase pathway, \
  neither implemented) or `vapor_separation_advisable` (< 50 mol% liquefies \
  -- a vapor-phase separation method is advisable, not implemented). State \
  the percentages exactly as given; never recompute or round them yourself. \
  When `phase == 'vapor_liquid'`, first state the feed's ORIGINAL split from \
  `checks['feed_phase']['liquid_fraction']`/`vapor_fraction` at its stated \
  conditions, then separately state the CONDITIONED split at 313.15 K from \
  `checks['vapor_condensation_screen']` -- these are two distinct results \
  and must not be conflated.

In every case, `checks['routing']['implemented']` is `False` -- never imply \
a liquid- or vapor-phase separator was actually designed or sized.

If the user then asks a calculation-PROGRESS question ("what next?", \
"continue", "what remains?"), the orchestrator answers it deterministically \
from `calculation_progress` before you see the message (see the \
CALCULATION-PROGRESS TRUTH RULE above) -- describe exactly what it says \
(e.g. "feed-phase evaluation is complete; the remaining Case `case` design \
calculation is not yet implemented") and do not ask for any engineering \
input again.

## external_reflux_ratio_LD vs reflux_ratio_multiplier_k

If the user states an actual reflux ratio (what they'd normally call "the \
reflux ratio" or "L/D"), pass it as `external_reflux_ratio_LD`. Only use \
`reflux_ratio_multiplier_k` if the user explicitly speaks in "x times \
minimum reflux" terms. Never convert one into the other yourself, and never \
pass the same number for both.

When Python routes you a turn to narrate (an action result, or a broad/off-\
schema question), reply in ordinary prose -- never emit a raw JSON object \
as that reply. (Your interpretation turn is a separate, structured-output \
call you never see the raw mechanics of.)
"""


_CALCULATION_TOOL = 'calculate_current_binary_distillation_problem'
_CALC_STATUS_TOOL = 'get_binary_distillation_calculation_status'


def _chat_without_tools(client, messages):
    return client.chat(model=MODEL, messages=messages, think=False)


def _current_user_text(messages):
    if messages and isinstance(messages[-1], dict) and messages[-1].get('role') == 'user':
        return messages[-1].get('content')
    return None


def _run_calculation_and_finalize(client, messages):
    """Run `calculate_current_binary_distillation_problem()` deterministically -- no model turn decides whether to call it -- append a synthetic assistant-tool-call/tool-result pair for conversation-history consistency (matching the pending-reply resolver's pattern below), then finalize with `_chat_without_tools` so the model can only explain the returned calculation, never call another tool this turn (tools/binary-distillation-connecting-feed-calculation.md Steps 10/13)."""
    print(f"  [calling {_CALCULATION_TOOL}({{}})]")
    result = calculate_current_binary_distillation_problem()
    messages.append({
        'role': 'assistant',
        'content': None,
        'tool_calls': [{'function': {'name': _CALCULATION_TOOL, 'arguments': {}}}],
    })
    messages.append({
        'role': 'tool',
        'tool_name': _CALCULATION_TOOL,
        'content': json.dumps(result),
    })
    response = _chat_without_tools(client, messages)
    messages.append(response.message)
    return response.message.content


def _run_progress_query_and_finalize(client, messages):
    """Deterministically answer a calculation-PROGRESS question ("what next?", "continue", "what remains?", ...) -- tools/binary-distillation-whats-next.md Steps 16-18. Never lets the model decide what has been completed: reads `_last_calculation_result` directly and calls `get_binary_distillation_calculation_status()` if a calculation has already run, or the internal `get_precalculation_progress()` helper otherwise (still zero-argument, still read-only, still no BioSTEAM call). Appends a synthetic assistant-tool-call/tool-result pair (same pattern as `_run_calculation_and_finalize`) so the model's finalization turn can only describe the already-fixed progress state."""
    if _last_calculation_result is not None:
        tool_name = _CALC_STATUS_TOOL
        result = get_binary_distillation_calculation_status()
    else:
        tool_name = 'get_precalculation_progress'
        result = get_precalculation_progress()

    print(f"  [calling {tool_name}({{}})]")
    messages.append({
        'role': 'assistant',
        'content': None,
        'tool_calls': [{'function': {'name': tool_name, 'arguments': {}}}],
    })
    messages.append({
        'role': 'tool',
        'tool_name': tool_name,
        'content': json.dumps(result),
    })
    response = _chat_without_tools(client, messages)
    messages.append(response.message)
    return response.message.content


def _run_write_and_finalize(client, messages, update_kwargs):
    """Perform the one atomic WRITE deterministically, then finalize with
    `_chat_without_tools` so the model narrates the resulting assessment --
    the same synthetic tool-call/tool-result-plus-finalize pattern used
    everywhere else in this module. Used for a plain WRITE-only
    TurnTransaction (no queries, no action): Part 11's "terminal" (no
    further model call) requirement is scoped to FOCUSED QUERIES, not to a
    rich problem-status explanation, so this keeps every "When `status` is
    X" section of SYSTEM_PROMPT -- including the ENGINEERING OUTPUT
    GROUNDING RULE over `would_calculate_details` -- working exactly as
    before Round 2."""
    print(f"  [WRITE -> calling update_binary_distillation_problem({update_kwargs})]")
    result = update_binary_distillation_problem(**update_kwargs)
    messages.append({
        'role': 'assistant',
        'content': None,
        'tool_calls': [{'function': {'name': 'update_binary_distillation_problem', 'arguments': update_kwargs}}],
    })
    messages.append({
        'role': 'tool',
        'tool_name': 'update_binary_distillation_problem',
        'content': json.dumps(result),
    })
    response = _chat_without_tools(client, messages)
    messages.append(response.message)
    return response.message.content


def _run_broad_conversation_and_finalize(client, messages):
    """Fallback for a genuinely empty TurnTransaction (no updates, no
    queries, no action, no reset -- small talk, or a broad question the
    field schema doesn't naturally capture as a single field, e.g.
    "summarize everything" or "what's still missing?"). Grounds the model's
    one narration call in the current accumulated state, with no mutation
    tools available -- Part 10/11: `get_binary_distillation_problem()`
    remains the broad-question path, Qwen only elaborates on data Python
    already supplied."""
    print('  [broad/off-schema turn -> grounding in get_binary_distillation_problem()]')
    state = get_binary_distillation_problem()
    messages.append({
        'role': 'assistant',
        'content': None,
        'tool_calls': [{'function': {'name': 'get_binary_distillation_problem', 'arguments': {}}}],
    })
    messages.append({
        'role': 'tool',
        'tool_name': 'get_binary_distillation_problem',
        'content': json.dumps(state),
    })
    response = _chat_without_tools(client, messages)
    messages.append(response.message)
    return response.message.content


def _diag_op(diagnostic, name):
    """Record one exact dispatched Python operation name, in call order --
    tools/binary-distillation-turn-diagnostics-plan.md Step 5 point 6. A
    no-op when `diagnostic` is None (the default, non-debug path)."""
    if diagnostic is not None:
        diagnostic['execution']['operations'].append(name)


def _diag_write(diagnostic, write_kwargs):
    """Record whether a real (non-empty) WRITE ran this turn and its exact
    kwargs -- Step 5 points 7/8. `write_performed` is True only for a
    non-empty kwargs dict; the harmless unconditional no-op WRITE that
    `update_binary_distillation_problem` still receives on a query-only or
    fully-rejected turn is never reported as a performed write."""
    if diagnostic is not None:
        diagnostic['execution']['write_performed'] = bool(write_kwargs)
        diagnostic['execution']['write_kwargs'] = turn_diagnostics.to_jsonable(write_kwargs)


def _diag_action(diagnostic, name, arguments):
    if diagnostic is not None:
        diagnostic['execution']['action'] = {'name': name, 'arguments': turn_diagnostics.to_jsonable(arguments or {})}


def _diag_query_results(diagnostic, query_results):
    if diagnostic is not None:
        diagnostic['execution']['query_results'] = turn_diagnostics.to_jsonable(query_results)


def _dispatch_transaction(client, messages, transaction, diagnostic=None):
    """Execute a validated TurnTransaction and produce the final response --
    the one shared endpoint for both exclusive fast-path transactions and
    model-proposed ones (tools/binary-distillation-issues-9-1-2026-fifth.md
    Part 6/8). Branches, in order:

    1. RESET, if requested (always runs before anything else -- Part 8).
    2. An ACTION, if one validated (`calculate_current_step` /
       `read_calculation_status`) -- any accompanying WRITE is applied
       first, then the action's own existing narration helper finalizes
       (unchanged from before Round 2 -- Part 17: preserve current
       calculation behavior, including its rich feed-phase-routing prose).
    3. Any QUERY, or a bounded rejection note (invalid updates/conflicts) --
       TERMINAL, Python-rendered (`format_transaction_response`), no
       further model call (Part 11) -- this is the fix for Failures 1-3.
    4. A plain WRITE with nothing else -- Qwen narrates the resulting
       assessment (`_run_write_and_finalize`), same as every WRITE did
       before Round 2.
    5. Otherwise (a genuinely empty transaction) -- broad, grounded
       elaboration (`_run_broad_conversation_and_finalize`).

    `diagnostic`, when given (tools/binary-distillation-turn-diagnostics-
    plan.md Step 5), is filled in with the exact operations dispatched,
    WRITE performed/kwargs, action, and query results -- purely observational,
    never read back by this function, so passing it changes no routing,
    validation, execution, or state (architectural invariant 7).
    """
    if transaction['action_error'] is not None:
        print(f"  [rejected unrecognized action -> {transaction['action_error']}]")

    if transaction['reset_first']:
        print('  [RESET -> calling reset_workflow_session()]')
        reset_workflow_session()
        _diag_op(diagnostic, 'reset_workflow_session')

    if transaction['action'] is not None:
        name = transaction['action']['name']
        if transaction['update_kwargs']:
            print(f"  [WRITE before action -> calling update_binary_distillation_problem({transaction['update_kwargs']})]")
            update_binary_distillation_problem(**transaction['update_kwargs'])
            _diag_op(diagnostic, 'update_binary_distillation_problem')
        _diag_write(diagnostic, transaction['update_kwargs'])
        _diag_action(diagnostic, name, transaction['action'].get('arguments'))
        if name == 'calculate_current_step':
            _diag_op(diagnostic, 'calculate_current_binary_distillation_problem')
            return _run_calculation_and_finalize(client, messages)
        if name == 'read_calculation_status':
            _diag_op(diagnostic, 'read_calculation_status')
            return _run_progress_query_and_finalize(client, messages)
        # No other action name can appear here -- 'reset_current_problem'
        # is always folded into reset_first during validation.

    if transaction['queries'] or transaction['invalid_updates'] or transaction['conflicts']:
        assessment = update_binary_distillation_problem(**transaction['update_kwargs'])
        _diag_op(diagnostic, 'update_binary_distillation_problem')
        _diag_write(diagnostic, transaction['update_kwargs'])
        snapshot = build_problem_snapshot(_workflow_state, assessment, _last_calculation_result)
        query_results = [
            read_problem_value(snapshot, q['field'], entity=q.get('entity'), subject=q.get('subject'))
            for q in transaction['queries']
        ]
        _diag_query_results(diagnostic, query_results)
        for query, result in zip(transaction['queries'], query_results):
            print(f'  [state query resolved -> {query} -> {result}]')
        answer = format_transaction_response(transaction, {'assessment': assessment, 'query_results': query_results})
        messages.append({
            'role': 'assistant',
            'content': None,
            'tool_calls': [{'function': {'name': 'update_binary_distillation_problem', 'arguments': transaction['update_kwargs']}}],
        })
        messages.append({
            'role': 'tool',
            'tool_name': 'update_binary_distillation_problem',
            'content': json.dumps(assessment),
        })
        messages.append({'role': 'assistant', 'content': answer, 'tool_calls': []})
        return answer

    if transaction['update_kwargs']:
        _diag_op(diagnostic, 'update_binary_distillation_problem')
        _diag_write(diagnostic, transaction['update_kwargs'])
        return _run_write_and_finalize(client, messages, transaction['update_kwargs'])

    _diag_write(diagnostic, {})
    _diag_op(diagnostic, 'get_binary_distillation_problem')
    return _run_broad_conversation_and_finalize(client, messages)


def _fast_path_transaction(user_text, current_state):
    """Recognize an exclusive, whole-message-unambiguous intent WITHOUT
    invoking the model at all (Part 6) -- pending-reply resolution, a
    standalone explicit feed-temperature restatement, an explicit "proceed"
    phrase, a calculation-progress phrase, or an explicit feed-phase
    question. Each produces the SAME TurnTransaction shape the model-driven
    path would (Part 6: "fast paths ... are optimizations, not a parallel
    architecture") so both converge on `_dispatch_transaction`. Returns
    `None` if nothing exclusive matches -- the turn goes through
    `propose_turn_intent` instead.
    """
    feed_ready = current_state.get('feed_screening', {}).get('ready', False)

    # Pending-request resolution always runs first, regardless of
    # feed-screening readiness -- a live outstanding question (e.g. an
    # optimum-feed-plate confirmation) must win over a bare "yes" being
    # misread as "run the calculation now."
    resolved = resolve_pending_reply(current_state.get('pending_request'), user_text)
    if resolved is None and _feed_thermal_condition_missing(current_state):
        temperature_value = extract_explicit_feed_temperature_K(user_text)
        if temperature_value is not None:
            resolved = {'feed_temperature_K': temperature_value}
    if resolved is not None:
        return make_raw_update_transaction(resolved)

    if feed_ready and normalize_short_reply(user_text) in _PROCEED_PHRASES:
        return make_action_transaction('calculate_current_step')

    if is_calculation_progress_question(user_text):
        return make_action_transaction('read_calculation_status')

    if feed_ready and is_feed_phase_question(user_text):
        return make_action_transaction('calculate_current_step')

    return None


# ---------------------------------------------------------------------------
# tools/binary-distillation-turn-diagnostics-plan.md Step 10 -- a bounded
# SEMANTIC retry, distinct from the structural malformed-JSON retry already
# inside `propose_turn_intent`. Off by default (the `semantic_retry`
# parameter on `ask()` defaults to False) -- gated behind the `--semantic
# -retry` CLI flag until a live-Qwen acceptance run shows it reliably helps
# (Step 10: "Do not enable semantic retry by default...").
# ---------------------------------------------------------------------------

_SEMANTIC_RETRY_REPAIRABLE_REASONS = {'missing_entity'}


def _is_semantic_retry_eligible(transaction):
    """Step 10 eligibility gate, checked on an already-parsed, already-
    validated TurnTransaction: (1) JSON parsing succeeded -- implicit, this
    is only ever called on a transaction built from a successful parse; (2)
    semantic validation rejected the WHOLE update batch, i.e. zero writes
    from it; (3) no mutation has happened yet this turn -- also implicit,
    this runs before `_dispatch_transaction`; (4) every rejection reason is
    in the small repairable allowlist, initially only `missing_entity` on a
    keyed field."""
    if transaction['update_kwargs']:
        return False
    if not transaction['invalid_updates']:
        return False
    for invalid in transaction['invalid_updates']:
        if invalid['reason'] not in _SEMANTIC_RETRY_REPAIRABLE_REASONS:
            return False
        entry = PROBLEM_FIELD_REGISTRY.get(invalid['update'].get('field'))
        if not entry or not entry.get('keyed'):
            return False
    return True


def _build_semantic_repair_prompt(rejected_intent, invalid_updates):
    return (
        'Your previous JSON matched the required TurnIntent schema but FAILED semantic '
        'validation, so NOTHING was saved. Correct the TurnIntent using ONLY the CURRENT '
        'user message below -- never invent a fact the user did not state. Return a '
        'COMPLETE replacement TurnIntent (not a partial patch) matching the required schema.\n\n'
        f'Your rejected TurnIntent was: {json.dumps(rejected_intent)}\n'
        f'Validator diagnostics explaining exactly why it was rejected: {json.dumps(invalid_updates)}\n\n'
        + build_field_catalog_prompt()
    )


def _run_semantic_retry(client, user_text, rejected_intent, rejected_transaction, diagnostic):
    """Issue ONE semantic-repair structured-output call. Revalidates the
    entire replacement TurnIntent from scratch -- never merges pieces of
    the rejected and repaired intents (Step 10). Returns the repaired
    TurnTransaction (whether IT validates successfully or not -- a failed
    repair still replaces the diagnostic trail with its own result, per
    "retain both proposals and both validation results in diagnostics"),
    or `None` if the repair response's JSON did not even parse -- callers
    keep the original rejected transaction in that case, so zero writes
    happen either way."""
    print('  [semantic retry -> repairing rejected TurnIntent]')
    repair_messages = [
        {'role': 'system', 'content': _build_semantic_repair_prompt(rejected_intent, rejected_transaction['invalid_updates'])},
        {'role': 'user', 'content': user_text},
    ]
    response = client.chat(model=MODEL, messages=repair_messages, format=TURN_INTENT_JSON_SCHEMA,
                            think=False, options={'temperature': 0})
    raw = response.message.content
    parse_result = parse_turn_intent_response(raw)

    if diagnostic is not None:
        diagnostic['interpretation']['attempts'].append({
            'raw': raw,
            'parse_result': {k: v for k, v in parse_result.items() if k != 'raw'},
        })

    if not parse_result['ok']:
        if diagnostic is not None:
            diagnostic['validation']['semantic_retry'] = {
                'attempted': True, 'repaired': False,
                'reason': 'semantic_retry_response_malformed',
                'original_invalid_updates': turn_diagnostics.to_jsonable(rejected_transaction['invalid_updates']),
            }
        return None

    repaired_intent = parse_result['intent']
    repaired_transaction = validate_turn_intent(repaired_intent, ACTIVE_WORKFLOW_SCHEMA, _workflow_state)

    if diagnostic is not None:
        diagnostic['interpretation']['final_intent'] = repaired_intent
        diagnostic['validation']['semantic_retry'] = {
            'attempted': True,
            'repaired': bool(repaired_transaction['update_kwargs']),
            'repaired_intent': repaired_intent,
            'original_invalid_updates': turn_diagnostics.to_jsonable(rejected_transaction['invalid_updates']),
            'repaired_invalid_updates': turn_diagnostics.to_jsonable(repaired_transaction['invalid_updates']),
        }

    return repaired_transaction


def ask(client, messages, diagnostic=None, semantic_retry=False):
    """Return the final assistant message text for the current turn.

    tools/binary-distillation-issues-9-1-2026-fifth.md Part 6/8: an
    exclusive deterministic fast path (`_fast_path_transaction`) gets first
    refusal at the CURRENT authoritative state (never conversation
    history); only if none applies does the model propose a `TurnIntent`
    via schema-constrained structured output (`propose_turn_intent` --
    no `tools=` exposed, so the model can never execute an engineering
    operation itself). Either way, Python validates the result into one
    TurnTransaction (`validate_turn_intent`) and executes it through the
    single shared endpoint, `_dispatch_transaction`.

    `diagnostic` (tools/binary-distillation-turn-diagnostics-plan.md Step 5),
    when given, is filled in with the route taken, every raw interpretation
    attempt, the validated transaction, the exact dispatched operations, and
    a before/after state diff. It is purely observational: passing `None`
    (the default) reproduces the exact pre-diagnostics behavior, and passing
    a record never itself changes routing, validation, execution, or state
    (architectural invariant 7).

    `semantic_retry` (Step 10) enables one additional bounded repair call --
    see `_is_semantic_retry_eligible`/`_run_semantic_retry` -- only when a
    model-interpreted turn's whole update batch was rejected for a
    repairable reason. Defaults to False (not enabled by default -- Step
    10's "Do not enable semantic retry by default until the live-Qwen
    acceptance run shows that it improves behavior reliably").
    """
    user_text = _current_user_text(messages)
    if diagnostic is not None:
        diagnostic['user_text'] = user_text
        diagnostic['state']['before'] = _state_snapshot()

    if user_text is None:
        reply = _run_broad_conversation_and_finalize(client, messages)
        if diagnostic is not None:
            diagnostic['final_response'] = reply
            diagnostic['state']['after'] = _state_snapshot()
            diagnostic['state']['changed_fields'] = turn_diagnostics.compute_state_diff(
                diagnostic['state']['before'], diagnostic['state']['after'])
        return reply

    current_state = get_binary_distillation_problem()
    transaction = _fast_path_transaction(user_text, current_state)

    if transaction is not None:
        if diagnostic is not None:
            diagnostic['route'] = 'fast_path'
    else:
        parse_result = propose_turn_intent(client, messages, MODEL)
        if diagnostic is not None:
            diagnostic['route'] = 'model_interpretation'
            diagnostic['interpretation']['model'] = MODEL
            diagnostic['interpretation']['attempts'] = list(parse_result.get('attempts', []))
            diagnostic['interpretation']['retry_used'] = parse_result.get('retry_used', False)

        if not parse_result['ok']:
            print(f"  [TurnIntent parse failed -> {parse_result}]")
            reply = (
                "I couldn't interpret that as a valid engineering update or question. "
                "Could you rephrase it as a specific value or a specific question?"
            )
            if diagnostic is not None:
                diagnostic['final_response'] = reply
                diagnostic['state']['after'] = _state_snapshot()
                diagnostic['state']['changed_fields'] = turn_diagnostics.compute_state_diff(
                    diagnostic['state']['before'], diagnostic['state']['after'])
            return reply

        if diagnostic is not None:
            diagnostic['interpretation']['final_intent'] = parse_result['intent']

        transaction = validate_turn_intent(parse_result['intent'], ACTIVE_WORKFLOW_SCHEMA, _workflow_state)

        if semantic_retry and _is_semantic_retry_eligible(transaction):
            if diagnostic is not None:
                diagnostic['interpretation']['semantic_retry_used'] = True
            repaired = _run_semantic_retry(client, user_text, parse_result['intent'], transaction, diagnostic)
            if repaired is not None:
                transaction = repaired

    if diagnostic is not None:
        diagnostic['validation']['transaction'] = {
            'reset_first': transaction['reset_first'],
            'update_kwargs': turn_diagnostics.to_jsonable(transaction['update_kwargs']),
            'action': transaction['action'],
            'action_error': transaction['action_error'],
        }
        diagnostic['validation']['normalized_updates'] = turn_diagnostics.to_jsonable(transaction.get('normalized_updates', []))
        diagnostic['validation']['invalid_updates'] = turn_diagnostics.to_jsonable(transaction['invalid_updates'])
        diagnostic['validation']['conflicts'] = turn_diagnostics.to_jsonable(transaction['conflicts'])

    reply = _dispatch_transaction(client, messages, transaction, diagnostic=diagnostic)

    if diagnostic is not None:
        diagnostic['final_response'] = reply
        diagnostic['state']['after'] = _state_snapshot()
        diagnostic['state']['changed_fields'] = turn_diagnostics.compute_state_diff(
            diagnostic['state']['before'], diagnostic['state']['after'])

    return reply


# ---------------------------------------------------------------------------
# tools/binary-distillation-turn-diagnostics-plan.md Step 6 -- CLI diagnostic
# controls. `--debug` prints the bounded human-readable diagnostic after
# each turn; `--debug-json PATH` appends one full JSON record per turn.
# Neither flag changes conversation history: `messages` only ever receives
# real user/assistant/tool content, exactly as before -- diagnostic output
# is a side channel (stdout / a separate file), never inserted into it.
# ---------------------------------------------------------------------------

def _build_arg_parser():
    parser = argparse.ArgumentParser(description='Binary-distillation workflow agent')
    parser.add_argument('message', nargs='*', help='One-shot user message; if omitted, starts the interactive REPL')
    parser.add_argument('--debug', action='store_true', help='Print a bounded human-readable diagnostic after each turn')
    parser.add_argument('--debug-json', metavar='PATH', default=None, help='Append one JSON diagnostic record per turn to PATH')
    parser.add_argument('--semantic-retry', action='store_true', help='Enable the bounded semantic TurnIntent repair retry (off by default)')
    return parser


def _run_turn_with_diagnostics(client, messages, debug=False, debug_json_path=None, semantic_retry=False):
    """Run one turn through `ask()`, optionally building/rendering/persisting
    a diagnostic record. `messages` must already have the current user turn
    appended (same expectation `ask()` itself has) -- this wrapper never
    appends to conversation history beyond what `ask()`'s own dispatch
    helpers already do."""
    user_text = _current_user_text(messages)
    diagnostics_enabled = debug or bool(debug_json_path)
    diagnostic = turn_diagnostics.new_turn_record(_next_turn_id(), user_text) if diagnostics_enabled else None

    reply = ask(client, messages, diagnostic=diagnostic, semantic_retry=semantic_retry)

    if debug and diagnostic is not None:
        print(turn_diagnostics.render_human_readable(diagnostic))
    if debug_json_path and diagnostic is not None:
        try:
            turn_diagnostics.append_jsonl(diagnostic, debug_json_path)
        except OSError as e:
            print(f'ERROR: could not write diagnostic JSONL to {debug_json_path!r}: {e}', file=sys.stderr)

    return reply


def run_repl(debug=False, debug_json_path=None, semantic_retry=False):
    client = ollama.Client()
    messages = [{'role': 'system', 'content': SYSTEM_PROMPT}]

    print(f"Binary-distillation workflow agent ready (model: {MODEL}). Type 'exit' to quit.")
    while True:
        try:
            user_input = input('\nYou: ').strip()
        except (EOFError, KeyboardInterrupt):
            break
        if user_input.lower() in ('exit', 'quit'):
            break
        if not user_input:
            continue

        messages.append({'role': 'user', 'content': user_input})
        reply = _run_turn_with_diagnostics(client, messages, debug, debug_json_path, semantic_retry)
        print(f"\nAssistant: {reply}")


if __name__ == '__main__':
    args = _build_arg_parser().parse_args()
    if args.message:
        client = ollama.Client()
        messages = [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': ' '.join(args.message)},
        ]
        print(_run_turn_with_diagnostics(client, messages, args.debug, args.debug_json, args.semantic_retry))
    else:
        run_repl(debug=args.debug, debug_json_path=args.debug_json, semantic_retry=args.semantic_retry)
