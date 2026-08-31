# Objective

Add a deterministic **calculation-progress state layer** so the agent can answer questions like:

```text
what next?
continue
what have we calculated?
what remains?
where are we?
```

without falling back to generic LLM reasoning or asking the user to re-enter information that is already stored in authoritative workflow state.

The current architecture already has:

```text
Problem-definition truth
    → authoritative workflow state

Pending-question truth
    → deterministic pending_request

Calculation truth
    → deterministic BioSTEAM feed-phase result
```

The missing layer is:

```text
Calculation-progress truth
    → what has been completed
    → what is available next
    → what remains unimplemented
```

The desired architecture is:

```text
User
  ↓
binary_distillation_workflow_agent.py
  |
  +-- WRITE problem state
  +-- READ problem state
  +-- EXECUTE calculation
  +-- READ calculation progress
  +-- RESET
  |
  ↓
deterministic result
  ↓
LLM explains only what the state says
```

Do not solve `"what next?"` purely through prompt instructions. The next-step answer should come from deterministic calculation state.

The existing architecture already separates deterministic state and engineering calculations from LLM interpretation; preserve that separation.

# Step 1 — Define a calculation-progress schema

Modify:

```text
tools/chopper/binary_distillation_calculation.py
```

Extend the result from:

```python
{
    "calculation_performed": True,
    "workflow": assessment,
    "checks": {
        "feed_phase": phase_result,
    },
}
```

to include:

```python
"calculation_progress": {
    "completed_steps": [],
    "next_step": None,
    "next_step_available": False,
    "remaining_steps": [],
    "blocked_reason": None,
    "message": "",
}
```

The calculation result should become the authoritative source of calculation progress.

# Step 2 — Define stable calculation-step IDs

Do not use prose strings as the only internal representation.

Add constants such as:

```python
STEP_FEED_PHASE = "feed_phase"

STEP_CASE_A_DESIGN = "case_A_design"
STEP_CASE_B_DESIGN = "case_B_design"
STEP_CASE_C_DESIGN = "case_C_design"
STEP_CASE_D_DESIGN = "case_D_design"
```

For the current implementation, only:

```python
STEP_FEED_PHASE
```

is executable.

The Case A-D design steps can exist as recognized future steps even if not yet implemented.

# Step 3 — Add a deterministic progress builder

In:

```text
binary_distillation_calculation.py
```

implement:

```python
def build_calculation_progress(
    *,
    assessment,
    checks,
):
    ...
```

It must derive progress from deterministic results only.

Do not ask the LLM what has been completed.

For example:

```python
def build_calculation_progress(*, assessment, checks):
    completed_steps = []

    feed_phase = checks.get("feed_phase")

    if (
        isinstance(feed_phase, dict)
        and feed_phase.get("valid") is True
    ):
        completed_steps.append("feed_phase")

    case = assessment.get("case")

    remaining_steps = []
    next_step = None
    next_step_available = False
    blocked_reason = None

    if case == "A":
        remaining_steps.append("case_A_design")

    elif case == "B":
        remaining_steps.append("case_B_design")

    elif case == "C":
        remaining_steps.append("case_C_design")

    elif case == "D":
        remaining_steps.append("case_D_design")

    if remaining_steps:
        blocked_reason = "not_implemented"

    return {
        "completed_steps": completed_steps,
        "next_step": next_step,
        "next_step_available": next_step_available,
        "remaining_steps": remaining_steps,
        "blocked_reason": blocked_reason,
        "message": (
            "Feed-phase evaluation is complete. "
            f"The remaining {case or 'binary-distillation'} design "
            "calculation is not yet implemented."
        ),
    }
```

Adapt wording to the actual case.

# Step 4 — Return calculation progress from every calculation

Update:

```python
calculate_binary_distillation_problem(spec)
```

so the successful path becomes conceptually:

```python
checks = {
    "feed_phase": phase_result,
}

progress = build_calculation_progress(
    assessment=assessment,
    checks=checks,
)

return {
    "calculation_performed": True,
    "workflow": assessment,
    "checks": checks,
    "calculation_progress": progress,
}
```

# Step 5 — Also return progress when calculation cannot proceed

If the workflow is incomplete:

```python
assessment["status"] != "ready_for_calculation"
```

return:

```python
{
    "calculation_performed": False,
    "workflow": assessment,
    "checks": {},
    "calculation_progress": {
        "completed_steps": [],
        "next_step": None,
        "next_step_available": False,
        "remaining_steps": [],
        "blocked_reason": "workflow_not_ready",
        "message": assessment["message"],
    },
}
```

This keeps the result schema stable.

# Step 6 — Make the current Case D state explicit

For the exact current example:

```text
Case D
feed phase successfully calculated
full Case D design not implemented
```

the deterministic progress result should be approximately:

```python
{
    "completed_steps": [
        "feed_phase"
    ],

    "next_step": None,

    "next_step_available": False,

    "remaining_steps": [
        "case_D_design"
    ],

    "blocked_reason": "not_implemented",

    "message": (
        "Feed-phase evaluation is complete. "
        "The remaining Case D design calculation is not yet implemented."
    ),
}
```

Do not report the problem as needing new inputs.

# Step 7 — Optionally expose detailed remaining quantities

Because the workflow already knows what Case D would calculate, optionally add:

```python
"remaining_outputs": [
    "D",
    "B",
    "QR",
    "Qc",
    "N",
    "Nfeed",
    "column_diameter",
]
```

For example:

```python
"calculation_progress": {
    "completed_steps": ["feed_phase"],
    "next_step": None,
    "next_step_available": False,
    "remaining_steps": ["case_D_design"],
    "remaining_outputs": [
        "D",
        "B",
        "QR",
        "Qc",
        "N",
        "Nfeed",
        "column_diameter",
    ],
    "blocked_reason": "not_implemented",
}
```

Prefer deriving this from:

```python
assessment["would_calculate"]
```

instead of duplicating Case A-D output lists in multiple modules.

# Step 8 — Store the latest calculation result in the agent

Modify:

```text
tools/chopper/binary_distillation_workflow_agent.py
```

Add module-level state:

```python
_last_calculation_result = None
```

This stores only the most recent deterministic calculation result for the current workflow session.

Do not treat conversation history as calculation state.

# Step 9 — Update the calculation wrapper

Modify:

```python
calculate_current_binary_distillation_problem()
```

from conceptually:

```python
def calculate_current_binary_distillation_problem():
    spec = _effective_spec()
    return calculate_binary_distillation_problem(spec)
```

to:

```python
def calculate_current_binary_distillation_problem():
    global _last_calculation_result

    spec = _effective_spec()

    result = calculate_binary_distillation_problem(spec)

    _last_calculation_result = result

    return result
```

The stored result must be exactly the deterministic calculation output.

Do not let the LLM modify `_last_calculation_result`.

# Step 10 — Clear calculation state on reset

Modify:

```python
reset_workflow_session()
```

so it clears both:

```python
_workflow_state
```

and:

```python
_last_calculation_result
```

Conceptually:

```python
def reset_workflow_session():
    global _workflow_state
    global _last_calculation_result

    _workflow_state = {}
    _last_calculation_result = None

    return {
        "reset": True,
        "message": "Binary-distillation workflow session reset.",
    }
```

# Step 11 — Invalidate stale calculation state when engineering inputs change

This is important.

If a calculation has already run:

```python
_last_calculation_result != None
```

and the user then changes an engineering input such as:

```text
feed temperature
pressure
component flow
composition
xD
xB
boilup ratio
```

the old calculation result must not remain authoritative.

After a successful WRITE:

```python
update_binary_distillation_problem(...)
```

invalidate:

```python
_last_calculation_result = None
```

whenever the WRITE changes engineering state.

The simplest safe first implementation is:

```python
any successful non-empty engineering WRITE
→ invalidate latest calculation result
```

That may occasionally invalidate more than strictly necessary, but it prevents stale engineering results.

# Step 12 — Add a calculation READ tool

Add:

```python
def get_binary_distillation_calculation_status():
    """
    Return the latest authoritative calculation result and calculation
    progress without performing a new engineering calculation.

    This tool never mutates workflow state and never reruns BioSTEAM.
    """
```

Behavior when no calculation has run:

```python
{
    "calculation_available": False,
    "latest_calculation": None,
    "message": (
        "No deterministic calculation has been performed for the "
        "current binary-distillation problem."
    ),
}
```

Behavior after calculation:

```python
{
    "calculation_available": True,
    "latest_calculation": _last_calculation_result,
    "message": (
        _last_calculation_result[
            "calculation_progress"
        ]["message"]
    ),
}
```

# Step 13 — Register the calculation READ tool

Add:

```python
get_binary_distillation_calculation_status
```

to:

```python
TOOLS
```

and:

```python
TOOL_FUNCTIONS
```

The conceptual tool categories now become:

```text
STATE WRITE
update_binary_distillation_problem

STATE READ
get_binary_distillation_problem

CALCULATION EXECUTE
calculate_current_binary_distillation_problem

CALCULATION READ
get_binary_distillation_calculation_status

HOUSEKEEPING
reset_workflow_session
```

# Step 14 — Extend controller categories carefully

Update the per-turn controller so calculation READ is distinct from calculation EXECUTE.

Recommended precedence for model-selected calls:

```text
WRITE
>
CALCULATION EXECUTE
>
CALCULATION READ
>
STATE READ
```

However, preserve any existing deterministic pre-routing before model selection.

Still permit only one primary engineering operation per user turn.

After any selected primary operation, finalize with:

```python
_chat_without_tools(...)
```

# Step 15 — Add deterministic “what next?” recognition

Add:

```python
def is_calculation_progress_question(text: str) -> bool:
    ...
```

Use a narrow phrase set such as:

```python
_PROGRESS_PHRASES = (
    "what next",
    "what is next",
    "whats next",
    "what's next",
    "next",
    "continue",
    "what do we do next",
    "what should we do next",
    "okay what next",
    "ok what next",
    "what is the next step",
    "what's the next step",
    "where are we",
    "what remains",
    "what is left",
    "what have we calculated",
    "what did we calculate",
)
```

Normalize casing and punctuation before matching.

Do not make this detector overly broad.

# Step 16 — Deterministically route progress questions

Inside:

```python
ask()
```

after pending-reply resolution and before ordinary model tool selection:

```python
if is_calculation_progress_question(user_text):
    ...
```

If:

```python
_last_calculation_result is not None
```

call:

```python
get_binary_distillation_calculation_status()
```

directly.

Then finalize using:

```python
_chat_without_tools(...)
```

The model should only explain the deterministic progress result.

# Step 17 — Handle “what next?” before any calculation has run

If the user asks:

```text
what next?
```

but:

```python
_last_calculation_result is None
```

read the authoritative workflow state.

If:

```python
assessment["status"] == "ready_for_calculation"
```

the deterministic answer should indicate that the currently available next action is:

```text
feed_phase
```

Option A — return directly:

```python
{
    "next_step": "feed_phase",
    "next_step_available": True,
    "message": (
        "The problem is ready for calculation. "
        "The next implemented calculation step is feed-phase evaluation."
    )
}
```

Option B — automatically execute the feed phase.

For now, prefer **Option A** for `"what next?"`.

Reserve execution for:

```text
yes
go ahead
proceed
calculate it
```

This keeps `"what next?"` informational rather than mutating.

# Step 18 — Add a deterministic pre-calculation progress result

Implement a helper such as:

```python
def get_precalculation_progress():
    assessment = get_binary_distillation_problem()

    if assessment["status"] == "ready_for_calculation":
        return {
            "calculation_available": False,
            "calculation_progress": {
                "completed_steps": [],
                "next_step": "feed_phase",
                "next_step_available": True,
                "remaining_steps": [
                    "feed_phase",
                ],
                "blocked_reason": None,
                "message": (
                    "The problem is ready. "
                    "The next implemented calculation step is feed-phase evaluation."
                ),
            },
        }

    return {
        "calculation_available": False,
        "calculation_progress": {
            "completed_steps": [],
            "next_step": None,
            "next_step_available": False,
            "remaining_steps": [],
            "blocked_reason": "workflow_not_ready",
            "message": assessment["message"],
        },
    }
```

This gives `"what next?"` deterministic meaning even before the first calculation.

# Step 19 — Add SYSTEM_PROMPT calculation-progress truth rule

Add:

```text
CALCULATION-PROGRESS TRUTH RULE

The deterministic calculation state is the sole authority for:

- which engineering calculations have been completed
- which calculated values are available
- what calculation step is available next
- what calculation steps remain
- whether a remaining step is implemented
- whether calculation results are stale or unavailable

Never infer calculation progress from conversation history.

Never claim a calculation was completed unless the latest deterministic
calculation result lists it in completed_steps.

Never claim a next calculation is available unless
next_step_available is true.

Never ask the user to re-enter engineering information merely because
they ask "what next?", "continue", "what remains?", or similar.

For progress questions, use the calculation-progress state.
```

# Step 20 — Add explicit anti-repetition rule

Add:

```text
DO NOT RE-ASK STORED INPUTS

If the authoritative workflow state already contains components,
flows, units, composition, thermal condition, pressure, case-defining
variables, reflux condition, and optimum-feed-plate confirmation,
do not ask for them again unless the deterministic checker reports
that they are missing, inconsistent, or have been invalidated.

A question such as "what next?" does not mean the user is starting a
new separation problem.
```

This directly prevents the observed failure.

# Step 21 — Update post-calculation final-answer guidance

After a feed-phase calculation, avoid repeating the full problem-definition summary unless relevant.

Prefer:

```text
The feed-phase calculation is complete.

BioSTEAM result:
- Phase: vapor
- Vapor fraction: 1.0
- Liquid fraction: 0.0

The remaining Case D design calculation is not yet implemented.
```

rather than repeatedly beginning with:

```text
Your binary-distillation problem is fully specified...
```

# Step 22 — Define exact current “what next?” behavior

For the current Case D example, after feed phase is complete:

```text
User:
okay what next
```

the deterministic path should be:

```text
is_calculation_progress_question() → True
        ↓
get_binary_distillation_calculation_status()
        ↓
latest progress says:
    completed = feed_phase
    next_step_available = False
    remaining = case_D_design
    blocked_reason = not_implemented
        ↓
_chat_without_tools()
```

Expected answer:

```text
The feed-phase evaluation is complete.

There is no additional implemented calculation step yet. For this
Case D problem, the remaining design quantities are D, B, QR, Qc, N,
Nfeed, and column diameter. Those Case D calculations have not yet
been implemented in this pipeline.
```

The assistant must not ask for feed information again.

# Step 23 — Add calculation-progress unit tests

Create:

```text
tools/chopper/test_binary_distillation_calculation_progress.py
```

Add:

## Test 1 — Successful feed phase marks completed

Assert:

```python
progress["completed_steps"] == [
    "feed_phase"
]
```

## Test 2 — Current Case D has no executable next step

Assert:

```python
progress["next_step"] is None
progress["next_step_available"] is False
progress["remaining_steps"] == [
    "case_D_design"
]
progress["blocked_reason"] == "not_implemented"
```

## Test 3 — Incomplete workflow reports blocked

Assert:

```python
progress["blocked_reason"] == "workflow_not_ready"
```

## Test 4 — Remaining outputs derive from workflow

For Case D, verify:

```python
"D"
"B"
"QR"
"Qc"
"N"
"Nfeed"
```

etc. come from the workflow's `would_calculate` information if that implementation is used.

# Step 24 — Add calculation-state READ tests

Test:

```python
get_binary_distillation_calculation_status()
```

before any calculation.

Assert:

```python
result["calculation_available"] is False
```

After a calculation:

```python
calculate_current_binary_distillation_problem()
```

assert:

```python
result["calculation_available"] is True
```

and returned progress matches `_last_calculation_result`.

# Step 25 — Test reset invalidation

Sequence:

```text
complete problem
→ calculate phase
→ reset
→ get calculation status
```

Assert:

```python
calculation_available is False
```

# Step 26 — Test WRITE invalidation

Sequence:

```text
complete problem
→ calculate phase
→ modify feed temperature
```

Assert:

```python
_last_calculation_result is None
```

or equivalent public behavior:

```python
get_binary_distillation_calculation_status()[
    "calculation_available"
] is False
```

This prevents stale phase results after changing engineering state.

# Step 27 — Add exact agent regression test

Reproduce:

```text
User:
[complete Methanol/Water Case D problem]

User:
yes
```

Assert:

```text
calculate_current_binary_distillation_problem()
```

runs.

Then:

```text
User:
okay what next
```

Assert:

```text
get_binary_distillation_calculation_status()
```

is used.

Assert:

```text
update_binary_distillation_problem()
```

is not called.

Assert the model is finalized without tools.

# Step 28 — Test no repeated input request

Use a fake final model response fixture or assertion framework.

Verify that after `"okay what next"` the answer does not request:

```text
components
feed flow
composition
temperature
pressure
xD
xB
boilup ratio
reflux condition
optimum feed plate
```

unless deterministic state actually reports one of those as missing.

# Step 29 — Test progress query before calculation

Complete the problem but do not calculate.

Then:

```text
User:
what next?
```

Assert deterministic progress says:

```python
next_step == "feed_phase"
next_step_available is True
```

Do not automatically rerun state collection.

# Step 30 — Test “continue” after calculation

After feed phase is complete:

```text
User:
continue
```

Current expected result:

```python
next_step_available is False
blocked_reason == "not_implemented"
```

The assistant should explain that no additional implemented calculation step exists.

Do not silently pretend to perform Case D design.

# Step 31 — Run full regression suite

Run the new progress tests first.

Then run:

```bash
pytest tools/chopper/test_binary_distillation_calculation_progress.py -v
```

Then existing calculation tests:

```bash
pytest tools/chopper/test_binary_distillation_workflow_agent_calculation.py -v
```

Then existing workflow/pending/controller tests.

Finally run the complete `tools/chopper/` suite.

All existing tests must continue passing.

# Step 32 — Replay the manual conversation

Run:

```bash
python binary_distillation_workflow_agent.py
```

Enter the complete Case D example.

Then:

```text
yes
```

Expected:

```text
[calling calculate_current_binary_distillation_problem({})]
```

Then:

```text
okay what next
```

Expected deterministic route:

```text
[calling get_binary_distillation_calculation_status({})]
```

or equivalent direct internal deterministic routing.

Expected answer:

```text
The feed-phase evaluation is complete. There is currently no further
implemented calculation step. The remaining Case D design calculations
are not yet implemented.
```

No request for components, flows, temperature, pressure, or case inputs should appear.

# Step 33 — Update `separation_tool.md`

Document the new distinction:

```text
Problem state
    = what inputs are known

Calculation state
    = what deterministic calculations have actually been performed

Calculation progress
    = what is complete, what is next, and what remains
```

Document:

```python
_last_calculation_result
get_binary_distillation_calculation_status()
```

and the invalidation rules.

Also document that calculation results are invalidated whenever engineering state changes or the session resets.

# Definition of done

- [ ] `binary_distillation_calculation.py` returns `calculation_progress`.
- [ ] Calculation steps use stable machine-readable IDs.
- [ ] Successful feed-phase calculation records `feed_phase` as completed.
- [ ] Case D correctly reports its remaining design calculation as unimplemented.
- [ ] `next_step_available` is deterministic.
- [ ] `blocked_reason` is deterministic.
- [ ] Remaining quantities can be surfaced from `would_calculate`.
- [ ] The agent stores the latest deterministic calculation result.
- [ ] A calculation READ operation exists.
- [ ] Calculation READ never reruns BioSTEAM.
- [ ] Reset clears calculation state.
- [ ] Engineering WRITEs invalidate stale calculation state.
- [ ] `"what next?"` is recognized deterministically.
- [ ] `"continue"` is recognized deterministically.
- [ ] `"what remains?"` is recognized deterministically.
- [ ] Progress questions do not cause the agent to re-ask stored inputs.
- [ ] Before calculation, `"what next?"` reports `feed_phase` as the next available step.
- [ ] After feed-phase calculation, `"what next?"` reports no further implemented step.
- [ ] The LLM cannot invent completed calculation steps.
- [ ] The LLM cannot invent an available next calculation.
- [ ] Agent finalization after a progress READ occurs without tools.
- [ ] Stale calculation results cannot survive changed engineering inputs.
- [ ] Existing workflow-state truth behavior still passes.
- [ ] Existing pending-request behavior still passes.
- [ ] Existing phase calculation behavior still passes.
- [ ] Full regression suite passes.
- [ ] `separation_tool.md` documents calculation-progress truth.

# Recommended implementation order

```text
1. Add calculation_progress schema
2. Add stable calculation-step IDs
3. Add build_calculation_progress()
4. Return progress from calculate_binary_distillation_problem()
5. Add _last_calculation_result
6. Store successful calculation results
7. Clear calculation state on reset
8. Invalidate calculation state on engineering WRITE
9. Add get_binary_distillation_calculation_status()
10. Register calculation READ
11. Add is_calculation_progress_question()
12. Add deterministic "what next?" routing
13. Add pre-calculation progress behavior
14. Add CALCULATION-PROGRESS TRUTH RULE
15. Add DO NOT RE-ASK STORED INPUTS rule
16. Improve post-calculation answer guidance
17. Add calculation-progress unit tests
18. Add READ/reset/invalidation tests
19. Add exact "okay what next" regression test
20. Run full suite
21. Replay the manual conversation
22. Update separation_tool.md
```