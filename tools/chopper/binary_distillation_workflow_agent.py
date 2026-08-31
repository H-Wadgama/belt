"""
Isolated workflow-testing agent -- tools/binary-distillation-workflow.md
section 18, Option C ("Expose only assess_binary_distillation_problem() to
Qwen in a dedicated workflow-testing agent"), refactored per
tools/binary-distillation-read-vs-append.md to split the single combined
tool into separate READ and WRITE operations.

This agent exposes FIVE tools to the model:
  - `update_binary_distillation_problem` (WRITE) -- merges newly-stated
    engineering facts into the accumulated problem state, then returns the
    deterministic assessment of the full accumulated state. Call this only
    when the current user message provides new engineering information.
  - `get_binary_distillation_problem` (READ) -- takes no engineering
    arguments, never mutates state, and just returns the same deterministic
    assessment of whatever is already known. Call this when the user asks
    about information already supplied, derived, or still missing -- never
    resubmit an existing or derived value through the WRITE tool merely to
    answer a question about it.
  - `calculate_current_binary_distillation_problem` (CALCULATION EXECUTE) --
    takes no arguments, reads the accumulated authoritative state directly,
    and -- only once it is `ready_for_calculation` -- runs the deterministic
    BioSTEAM feed-phase calculation from `binary_distillation_calculation.py`.
    See `tools/binary-distillation-connecting-feed-calculation.md`.
  - `get_binary_distillation_calculation_status` (CALCULATION READ) -- takes
    no arguments, never mutates anything, and never runs BioSTEAM. Reports
    the most recent calculation result (if any) and its calculation-progress
    state -- what has been completed, what is next, and what remains. See
    `tools/binary-distillation-whats-next.md`.
  - `reset_workflow_session` (housekeeping) -- clears all accumulated state,
    including the most recent calculation result.

Both engineering (READ/WRITE) tools wrap the same underlying deterministic
checker, `binary_distillation_workflow.assess_binary_distillation_problem()`.
This module deliberately does NOT import `separation_tool.py` /
`case_design.py` / `optimizer.py` -- the sizing/optimization sweep layer is
still out of scope here. It DOES import the deterministic feed-phase
calculation layer (`binary_distillation_calculation.py`, which in turn
imports BioSTEAM via `biosteam_feed.py`/`feed_phase.py`) for the CALCULATION
tool above -- that layer is the sole place any BioSTEAM call happens; the
LLM itself never infers feed phase, vapor fraction, or any other
thermodynamic property from general knowledge. The calculation pipeline
currently evaluates ONLY the feed phase -- no Wankat Case A-D sizing
(reflux ratio, stage count, column diameter, etc.) is performed here yet.

Run interactively:
    python binary_distillation_workflow_agent.py

Or one-shot:
    python binary_distillation_workflow_agent.py "I want to separate methanol and water."
"""
import json
import pprint
import re
import sys

import ollama

from binary_distillation_calculation import STEP_FEED_PHASE, calculate_binary_distillation_problem
from binary_distillation_workflow import assess_binary_distillation_problem
from feed_state import apply_user_update, empty_feed_state

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
        feed_temperature_K: Feed temperature in Kelvin. Give at most one of feed_temperature_K/feed_quality/feed_enthalpy_kJ_per_hr -- never assume the feed is at its bubble point.
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
        A dict (see binary_distillation_workflow.assess_binary_distillation_problem for the full schema): 'valid_binary_scope', 'component_count', 'feed_flow_complete', 'feed_composition_complete', 'essential_complete', 'missing_essential_inputs', 'case', 'case_candidates', 'case_complete', 'missing_case_inputs', 'optimum_feed_plate_confirmed', 'calculation_inputs_complete', 'missing_calculation_inputs', 'status', 'would_calculate', 'calculation_performed' (always False), 'message', 'provenance'. `status` can be 'inconsistent_input' if redundant information disagreed (e.g. component flows don't sum to a stated total) -- relay the conflict in 'message' and ask the user to resolve it rather than picking a value yourself. `status` can also be 'need_calculation_inputs': the engineering problem definition is otherwise complete, but flow-rate units (`component_flow_units` or `total_flow_units`, named in `missing_calculation_inputs`) are still needed before the calculation layer can run -- ask only for that, and do NOT claim the problem is `ready_for_calculation` while this status shows. Relay 'message' (and the relevant missing_*/case_candidates fields) to the user rather than reproducing this logic yourself -- never infer a case, never invent a missing value or a missing unit, and never claim a calculation was performed.
    """
    global _last_calculation_result

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
    """READ operation: return the current binary-distillation problem state -- what has been supplied, what has been derived, which Wankat case (if any) it matches, and what is still missing -- WITHOUT changing anything.

    Call this whenever the user asks about information already supplied, derived, or still missing, instead of guessing from earlier chat text or calling `update_binary_distillation_problem`. Examples: "What is my feed composition?", "What is the feed flow rate?", "What pressure did I specify?", "What information do you have so far?", "What is still missing?", "Which Wankat case am I in?", "What would be calculated?". Takes no arguments -- it is strictly read-only and never mutates the accumulated state, never derives anything beyond what the deterministic checker already derives, and never invents a value.

    Returns:
        The identical schema `update_binary_distillation_problem` returns (see that tool's docstring), computed from whatever has already been accumulated -- no new information is merged in by this call.
    """
    return assess_binary_distillation_problem(_effective_spec())


def calculate_current_binary_distillation_problem() -> dict:
    """CALCULATION operation: run the deterministic feed-phase calculation for the CURRENTLY accumulated binary-distillation problem. Reads the authoritative workflow state directly -- takes NO arguments, and must never be used to add, modify, guess, or restate any engineering input.

    Call this to answer any question about feed phase, vapor fraction, liquid fraction, or other calculated thermodynamic property of the current problem (e.g. "What is the feed phase?", "Is the feed liquid or vapor?", "What is the vapor fraction?"). Do NOT call `get_binary_distillation_problem` first just to check readiness -- this tool already reads the same state and reports the workflow status alongside the calculation, so a separate READ beforehand is redundant.

    The calculation only proceeds when the accumulated problem is `ready_for_calculation`; otherwise this returns `calculation_performed: False` and the same workflow assessment `get_binary_distillation_problem` would -- relay `missing_essential_inputs` / `case_candidates` / `message` from the returned `workflow` and explain what is still needed, rather than guessing the property yourself.

    The calculation pipeline evaluates the feed phase (`checks['feed_phase']`: liquid / vapor / vapor_liquid classification, vapor/liquid fraction, per-component vapor/liquid molar flows) and, deterministically from that result, a post-feed-phase routing decision (`checks['routing']`, plus `checks['vapor_condensation_screen']` for a vapor feed -- a rigorous BioSTEAM screen at 313.15 K). It does NOT compute distillate/bottoms flow, reflux ratio, reboiler/condenser duty, theoretical stage count, feed stage, or column diameter for the identified Wankat case, and it does NOT design or size any liquid- or vapor-phase separator -- never describe any of those as calculated from this tool's result. Which route applies is decided in Python, never by you.

    Returns:
        {'calculation_performed': bool, 'workflow': <same assessment schema as get_binary_distillation_problem>, 'checks': {'feed_phase': {...}, 'routing': {...}, 'vapor_condensation_screen': {...} (vapor feeds only)} if calculation_performed else {}, 'calculation_progress': {...}}.
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

    if assessment['status'] == 'ready_for_calculation':
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
            'message': assessment['message'],
        },
    }


TOOLS = [
    update_binary_distillation_problem,
    get_binary_distillation_problem,
    calculate_current_binary_distillation_problem,
    get_binary_distillation_calculation_status,
    reset_workflow_session,
]
TOOL_FUNCTIONS = {
    'update_binary_distillation_problem': update_binary_distillation_problem,
    'get_binary_distillation_problem': get_binary_distillation_problem,
    'calculate_current_binary_distillation_problem': calculate_current_binary_distillation_problem,
    'get_binary_distillation_calculation_status': get_binary_distillation_calculation_status,
    'reset_workflow_session': reset_workflow_session,
}


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
    normalized = normalize_short_reply(user_text)
    if not normalized or len(normalized.split()) > _MAX_SHORT_REPLY_WORDS:
        return None

    request_type = pending_request.get('request_type')

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

# tools/binary-distillation-workflow.md section 17 -- "Important Behavioral
# Requirement for Qwen".
SYSTEM_PROMPT = """You are not the binary-distillation decision engine.

You have access to two engineering-state tools, two calculation tools, and \
one housekeeping tool:
  - `update_binary_distillation_problem` (WRITE) -- use ONLY when the \
current user message states NEW engineering information.
  - `get_binary_distillation_problem` (READ) -- use when the user asks a \
question about information already supplied, derived, stored, or still \
missing. Takes no arguments and never changes anything.
  - `calculate_current_binary_distillation_problem` (CALCULATION EXECUTE) -- \
use when the user asks for a calculated/derived thermodynamic result (feed \
phase, vapor fraction, liquid fraction, etc.) about the CURRENT problem. \
Takes no arguments -- it reads the accumulated state itself. Only runs the \
actual calculation once the problem is `ready_for_calculation`; otherwise \
it returns the same not-yet-ready assessment `get_binary_distillation_problem` \
would.
  - `get_binary_distillation_calculation_status` (CALCULATION READ) -- use \
when the user asks about calculation PROGRESS: "what have we calculated?", \
"what next?", "continue", "what remains?", "where are we?". Takes no \
arguments, never mutates anything, and never runs a new calculation -- it \
only reports the most recent calculation result (if any) and what is still \
unimplemented. In most cases the orchestrator already answers these \
questions deterministically before you see the message; see the \
CALCULATION-PROGRESS TRUTH RULE below.
  - `reset_workflow_session` (housekeeping) -- clears everything.

## Deciding which tool to call: classify every user turn

1. **New engineering information** (e.g. "Water flow rate is 90 kmol/hr.", \
"Column pressure is 101325 Pa.", "Use xD = 0.98.", "Yes, use the optimum \
feed plate."): call `update_binary_distillation_problem` with ONLY the new \
field(s) from this turn.
2. **A question about existing state** (e.g. "What is the feed \
composition?", "What is my total feed flow?", "What values have I given \
you?", "What is still missing?", "Which Wankat case does this match?", \
"What pressure did I specify?"): call `get_binary_distillation_problem` \
with no arguments. Do NOT call `update_binary_distillation_problem` for \
these, even if you copy the answer's numbers into the call -- that would \
fabricate a "new" input out of a value nobody just stated.
3. **Both at once** (e.g. "Water flow is 90 kmol/hr. What is the resulting \
feed composition?"): call `update_binary_distillation_problem` with just \
the new fact first, then answer the question directly from THAT call's \
returned state -- it already reflects the merge, so a follow-up \
`get_binary_distillation_problem` call is unnecessary.
4. **A calculation-PROGRESS question** (e.g. "What next?", "Continue.", \
"What have we calculated?", "What remains?", "Where are we?"): call \
`get_binary_distillation_calculation_status` with no arguments. This is \
NOT the same as category 2 -- it asks what has been CALCULATED, not what \
inputs have been supplied. The orchestrator usually answers this \
deterministically before you get a turn; see the CALCULATION-PROGRESS \
TRUTH RULE below.

Each user turn permits at most one operation from {WRITE, READ, \
CALCULATION EXECUTE, CALCULATION READ}. All four return a self-contained \
result. After any one of them runs, answer the user from that result; \
never request another state or calculation tool during the same turn -- \
the orchestrator will not run it anyway.

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

## State-truth rule (tools/binary-distillation-pending-truth.md)

The deterministic tool state is the SOLE authority for engineering facts. \
Never say a field was supplied, confirmed, changed, or derived unless the \
LATEST tool result actually shows that value in the state -- conversation \
context may help you understand what the user means, but it never itself \
changes engineering state. If a user's message answers a pending question, \
you must call `update_binary_distillation_problem` and see the change in \
its returned state BEFORE describing it as confirmed, updated, or stored. \
Never output "confirmed", "updated", "stored", "specified", or an \
equivalent claim about a field whose value in the latest tool result \
disagrees with (or is still null/None compared to) what you are about to \
say.

## `pending_request`: what the checker is currently asking for

Every tool result includes a `pending_request` field: `None` when nothing \
specific is outstanding, or a dict identifying the ONE field (or ordered \
field group) the checker is currently waiting on -- e.g. `{'field': \
'use_optimum_feed_plate', 'request_type': 'boolean_confirmation', \
'prompt': ...}` or `{'fields': ['xD', 'xB'], 'request_type': \
'ordered_float_group', ...}`. In most cases the orchestrator already \
converts a short reply to a live `pending_request` into a \
`update_binary_distillation_problem` call for you, deterministically, \
before you see the message -- when that happens you will find the tool \
result already reflects the new value; describe it from that result rather \
than re-deriving it yourself. If you ever do see a user message that \
plainly answers an active `pending_request` but no such WRITE has occurred \
yet, call `update_binary_distillation_problem` with exactly that field set \
before replying -- never describe the field as decided based on the user's \
words alone.

**Reporting a value never makes it a new input.** If a value already exists \
in state -- whether its provenance is `user_explicit` or `derived` -- \
telling the user about it does not turn it into something the user just \
supplied. Never pass an existing or derived value back through \
`update_binary_distillation_problem`'s arguments merely because you are \
about to state it or because the checker's message mentioned it. Only pass \
values the CURRENT user message newly and explicitly states.

**Do not reconstruct the state from conversation history.** When asked what \
is currently known, missing, or derived, call `get_binary_distillation_problem` \
rather than searching your own earlier replies for a remembered number -- \
the deterministic state is always the source of truth, not your prior text.

Never infer a Wankat design case (A, B, C, or D) yourself when the checker \
has not identified one -- if `case` comes back null and `case_candidates` \
lists more than one case, present those options (or ask which kind of \
specification the user wants to give) rather than guessing.

Never invent missing engineering specifications. Never assume pressure, \
feed thermal condition, reflux thermal condition, product purity, \
recovery, reflux ratio, boilup ratio, product flow, or whether to use the \
optimum feed plate -- these must come from the user's own words.

Component identity and component amount are separate concepts. Naming a \
component (e.g. "separate methanol and water") never implies a flow rate \
for it -- pass ONLY `component_names` in that case, with no numbers. \
Likewise, a single component's stated flow rate is never the total feed \
flow rate -- pass it under `component_flows`, and never pass it as \
`total_flow` unless the user explicitly says it is the total. Extract only \
what the current message actually states; do not reconstruct or guess \
feed information the user has not (yet) given, even partially.

Do NOT perform, describe performing, or claim to have performed any Wankat \
Case A-D distillation sizing or optimization (distillate/bottoms flow, \
reflux ratio, reboiler/condenser duty, theoretical stage count, feed \
stage, column diameter) during this conversation -- `update_binary_distillation_problem` \
and `get_binary_distillation_problem` only check problem-definition \
completeness, and their `calculation_performed` is always False. \
`calculate_current_binary_distillation_problem` is the one exception: it \
performs ONLY the deterministic feed-phase calculation described above -- \
never describe its result as anything more than that.

Both engineering tools REMEMBER everything already given about the current \
separation problem -- you do NOT need to repeat components, pressure, feed \
condition, or anything else from an earlier call. When the user answers a \
question you asked, call `update_binary_distillation_problem` again with \
only the NEW field(s) they just gave; never just restate their answer as \
text. Only call `reset_workflow_session` when the user is clearly switching \
to a genuinely different, unrelated separation problem, never between \
ordinary follow-up turns.

## Binary scope only

If `status` comes back `need_components`, ask for the missing component(s) \
using the tool's own `message`. If `status` comes back \
`unsupported_multicomponent`, tell the user plainly that only binary (exactly \
two component) separations are supported right now and ask them to narrow \
the request -- do NOT silently pick two of the three-or-more components \
and drop the rest.

## Naming components: `component_names` vs `add_component_names`

Use `component_names` (the FULL list) when the user states or restates the \
whole separation, e.g. "Separate methanol and water" or "I want to separate \
water" -- this replaces whatever component list (and any flows/composition) \
was known before, since it describes what the feed IS, not an addition to \
it. Use `add_component_names` instead when the user is answering a question \
you asked for a missing component with just a bare name (e.g. you asked \
"please specify the second component" and they replied "Methanol") -- this \
appends to the existing list without discarding any flow/composition data \
already known. When in doubt (a full new sentence describing the \
separation vs. a short answer to your own question), prefer `component_names` \
for the former and `add_component_names` for the latter.

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

## When `status` is `need_essential_inputs`

`missing_essential_inputs` may include a feed-quantity item (the total feed \
flow and/or composition are not yet fully determined) alongside pressure, \
feed thermal condition, and/or reflux condition. Relay the tool's `message` \
directly -- it already distinguishes "nothing about the feed quantity has \
been given" from "some feed quantity was given (e.g. one component's flow), \
but it's not enough to determine the total feed flow and composition yet." \
Never tell the user their feed is fully defined when it isn't, and never \
imply a partial quantity (e.g. one component's flow) is the total. Do not \
discuss Wankat cases A-D yet unless the user has already volunteered \
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
valid specification sets from the tool's `message` (or `case_candidates` + \
the general shape: A = compositions + reflux ratio; B = recoveries + \
reflux ratio; C = one product flow + one composition + reflux ratio; D = \
compositions + boilup ratio). The user does not need to say "Case A" -- \
they can just give the engineering quantities and the next call will \
identify the case automatically. Do NOT ask the user to name a case letter.

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

The engineering problem definition (Wankat essentials + case + optimum-\
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

Tell the user their problem is fully specified as Wankat Case `case`, and \
list exactly the quantities in `would_calculate` as what a FULL Case `case` \
design would compute. The calculation layer available to you does not \
compute those yet -- it evaluates only the feed phase. Do not calculate, \
approximate, or imply you have already found `would_calculate`'s values.

If the user then asks to proceed/calculate/go ahead, or asks a feed-phase/ \
vapor-fraction question, the calculation runs automatically before you see \
the message and you will find a `calculate_current_binary_distillation_problem` \
tool result already in the conversation -- describe exactly what its \
`checks['feed_phase']` says, and explicitly note that this is the feed-phase \
check only, not the full Case `case` design (`would_calculate`'s other \
quantities are still not computed). Do not call any tool yourself for this \
-- the orchestrator has already run it. After that, prefer a short answer \
built directly from `checks['feed_phase']` and `calculation_progress` -- \
do not re-open with the full problem-definition summary ("Your problem is \
fully specified...") again unless the user actually asks about the \
problem definition.

### Post-feed-phase routing (tools/binary-distillation-feed-vapor-liquid.md)

`checks['feed_phase']['phase']` deterministically decides what happens next \
-- you never make this choice yourself, and the routing decision is always \
already present in `checks['routing']` (and, for a vapor feed, also in \
`checks['vapor_condensation_screen']`) by the time you see the result:

- `phase == 'liquid'`: `checks['routing']['route']` is \
  `liquid_phase_separation`. State that the feed is liquid and should \
  proceed to a liquid-phase separation method, which is not implemented in \
  this pipeline yet. No 313.15 K screen ever runs for a liquid feed.
- `phase == 'vapor'`: a rigorous BioSTEAM screen at 313.15 K already ran -- \
  `checks['vapor_condensation_screen']['liquid_percent']`/`vapor_percent` \
  are the resulting split, and `route` is either \
  `liquid_and_vapor_separation_future` (>= 50 mol% liquefies -- report BOTH \
  a future liquid-phase and a future vapor-phase pathway, neither \
  implemented) or `vapor_separation_advisable` (< 50 mol% liquefies -- a \
  vapor-phase separation method is advisable, not implemented). State the \
  percentages exactly as given; never recompute or round them yourself.
- `phase == 'vapor_liquid'`: the feed was already two-phase at its stated \
  conditions (no 313.15 K screen runs). Report `checks['routing']`'s \
  `liquid_fraction`/`vapor_fraction` and state that routing an initially \
  two-phase feed is not implemented yet.

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

Never output a bare JSON object as your reply -- JSON only ever appears as \
tool-call arguments, never as chat text.
"""


def _run_tool_call(call):
    fn = TOOL_FUNCTIONS.get(call.function.name)
    if fn is None:
        return {'error': f'Unknown tool: {call.function.name}'}
    try:
        return fn(**call.function.arguments)
    except Exception as e:
        return {'error': f'{type(e).__name__}: {e}'}


# tools/binary-distillation-read-loop-fix-plan.md -- without a bounded
# per-turn policy, the model can keep re-selecting `get_binary_distillation_problem`
# (or any other tool) forever, since a READ result changes nothing about
# which tools are on offer next. The controller below, not the prompt,
# enforces termination: at most one engineering-state operation (READ or
# WRITE) per user turn, optionally preceded by one RESET, then a
# finalization call with no tools exposed so another tool call is
# impossible.
MAX_TOOL_CALLS_PER_TURN = 2

_ENGINEERING_TOOLS = ('update_binary_distillation_problem', 'get_binary_distillation_problem')
_CALCULATION_TOOL = 'calculate_current_binary_distillation_problem'
_CALC_STATUS_TOOL = 'get_binary_distillation_calculation_status'


def _fingerprint(call):
    return (call.function.name, json.dumps(call.function.arguments, sort_keys=True))


def _select_allowed_calls(tool_calls, reset_used, engineering_tool_used, fingerprints,
                           calculation_used=False, calc_status_used=False):
    """Pick which of this response's requested tool calls may actually run this round, per the per-turn policy: RESET first if not yet used, else at most one "primary operation" -- WRITE preferred over CALCULATION EXECUTE preferred over CALCULATION READ preferred over (state) READ -- skipping anything already run this turn (by fingerprint). tools/binary-distillation-connecting-feed-calculation.md Step 5 / tools/binary-distillation-whats-next.md Step 14: CALCULATION EXECUTE and CALCULATION READ are their own operation categories, but both still count toward the same one-primary-operation-per-turn budget as the engineering READ/WRITE pair, so a model cannot loop READ -> CALCULATION -> READ -> CALCULATION -> ... within one turn."""
    reset_call = None
    write_call = None
    read_call = None
    calculation_call = None
    calc_status_call = None
    for call in tool_calls:
        name = call.function.name
        if name == 'reset_workflow_session' and reset_call is None:
            reset_call = call
        elif name == 'update_binary_distillation_problem' and write_call is None:
            write_call = call
        elif name == 'get_binary_distillation_problem' and read_call is None:
            read_call = call
        elif name == _CALCULATION_TOOL and calculation_call is None:
            calculation_call = call
        elif name == _CALC_STATUS_TOOL and calc_status_call is None:
            calc_status_call = call

    primary_op_used = engineering_tool_used or calculation_used or calc_status_used

    if reset_call is not None and not reset_used:
        candidates = [reset_call]
    elif primary_op_used:
        candidates = []
    elif write_call is not None:
        candidates = [write_call]
    elif calculation_call is not None:
        candidates = [calculation_call]
    elif calc_status_call is not None:
        candidates = [calc_status_call]
    elif read_call is not None:
        candidates = [read_call]
    else:
        candidates = []

    return [call for call in candidates if _fingerprint(call) not in fingerprints]


def _chat_with_tools(client, messages):
    return client.chat(model=MODEL, messages=messages, tools=TOOLS, think=False)


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


def ask(client, messages):
    """Send `messages` to the model, resolving any tool calls under the bounded per-turn policy above, and return the final assistant message text.

    Before doing so, deterministic layers get first refusal at the current
    turn, in this order (tools/binary-distillation-pending-truth.md section
    4/17, tools/binary-distillation-connecting-feed-calculation.md Step 12,
    tools/binary-distillation-whats-next.md Step 16): it inspects the
    CURRENT authoritative state (never conversation history) and --
      1. if the user's message plainly resolves an outstanding
         `pending_request`, converts it directly into a real WRITE;
      2. else if `status == 'ready_for_calculation'` and the message is a
         "proceed" request, runs the (currently feed-phase-only)
         calculation layer and finalizes from its result;
      3. else if the message is a calculation-PROGRESS question
         (`is_calculation_progress_question` -- "what next?", "continue",
         "what remains?", ...), answers it deterministically from
         `get_binary_distillation_calculation_status()` (if a calculation
         has already run) or `get_precalculation_progress()` (if not) --
         never from conversation history or generic LLM reasoning, and
         never by re-asking for engineering inputs already on file;
      4. else if the message explicitly asks a feed-phase/vapor-fraction
         question (`is_feed_phase_question`) while `status ==
         'ready_for_calculation'`, likewise runs the calculation layer
         deterministically instead of letting the model decide whether to
         answer from remembered chemical knowledge.
    If none of these apply (including: a feed-phase question asked before
    the problem is `ready_for_calculation`, which must not trigger a
    BioSTEAM call), control falls through to normal model-driven tool
    selection below.
    """
    user_text = _current_user_text(messages)
    if user_text is not None:
        current_state = get_binary_distillation_problem()
        status = current_state.get('status')

        if status == 'ready_for_calculation':
            if normalize_short_reply(user_text) in _PROCEED_PHRASES:
                return _run_calculation_and_finalize(client, messages)
        else:
            resolved = resolve_pending_reply(current_state.get('pending_request'), user_text)
            if resolved is not None:
                print(f"  [pending-request resolved -> calling update_binary_distillation_problem({resolved})]")
                messages.append({
                    'role': 'assistant',
                    'content': None,
                    'tool_calls': [{'function': {'name': 'update_binary_distillation_problem', 'arguments': resolved}}],
                })
                result = update_binary_distillation_problem(**resolved)
                messages.append({
                    'role': 'tool',
                    'tool_name': 'update_binary_distillation_problem',
                    'content': json.dumps(result),
                })
                response = _chat_without_tools(client, messages)
                messages.append(response.message)
                return response.message.content

        if is_calculation_progress_question(user_text):
            return _run_progress_query_and_finalize(client, messages)

        if status == 'ready_for_calculation' and is_feed_phase_question(user_text):
            return _run_calculation_and_finalize(client, messages)

    response = _chat_with_tools(client, messages)
    messages.append(response.message)

    reset_used = False
    engineering_tool_used = False
    calculation_used = False
    calc_status_used = False
    fingerprints = set()
    calls_used = 0

    while response.message.tool_calls and calls_used < MAX_TOOL_CALLS_PER_TURN:
        selected_calls = _select_allowed_calls(
            response.message.tool_calls,
            reset_used=reset_used,
            engineering_tool_used=engineering_tool_used,
            fingerprints=fingerprints,
            calculation_used=calculation_used,
            calc_status_used=calc_status_used,
        )

        if not selected_calls:
            # Nothing left is allowed to run this turn -- finalize from
            # what we already have instead of looping.
            break

        for call in selected_calls:
            if calls_used >= MAX_TOOL_CALLS_PER_TURN:
                break
            fingerprints.add(_fingerprint(call))
            print(f"  [calling {call.function.name}({call.function.arguments})]")
            result = _run_tool_call(call)
            print("\n========== RAW TOOL RESULT ==========")
            pprint.pprint(result, width=100)
            print("=====================================\n")
            messages.append({
                'role': 'tool',
                'tool_name': call.function.name,
                'content': json.dumps(result),
            })
            calls_used += 1

            if call.function.name == 'reset_workflow_session':
                reset_used = True
            elif call.function.name in _ENGINEERING_TOOLS:
                engineering_tool_used = True
            elif call.function.name == _CALCULATION_TOOL:
                calculation_used = True
            elif call.function.name == _CALC_STATUS_TOOL:
                calc_status_used = True

        if engineering_tool_used or calculation_used or calc_status_used:
            # WRITE, READ, CALCULATION, and CALCULATION READ all return a
            # self-contained result -- force a prose answer instead of
            # offering another tool call.
            response = _chat_without_tools(client, messages)
        else:
            # Only RESET ran so far; allow one more tool-enabled round so
            # the model can submit the new problem via WRITE.
            response = _chat_with_tools(client, messages)
        messages.append(response.message)

    if response.message.tool_calls:
        # Hard-stop fallback: budget or policy exhausted but the model
        # still wants to call something -- force a prose answer.
        response = _chat_without_tools(client, messages)
        messages.append(response.message)

    return response.message.content


def run_repl():
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
        reply = ask(client, messages)
        print(f"\nAssistant: {reply}")


if __name__ == '__main__':
    if len(sys.argv) > 1:
        client = ollama.Client()
        messages = [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': ' '.join(sys.argv[1:])},
        ]
        print(ask(client, messages))
    else:
        run_repl()
