# Objective

Connect the newly implemented deterministic feed-phase calculation layer to `binary_distillation_workflow_agent.py` without weakening the current architecture.

The workflow agent must continue to treat the deterministic state as the sole engineering truth. The LLM must not infer feed phase, vapor fraction, boiling behavior, or related thermodynamic properties from general knowledge.

The desired behavior is:

```text
User
  ↓
binary_distillation_workflow_agent.py
  ↓
authoritative workflow state
  ↓
ready_for_calculation
  ↓
calculate current problem
  ↓
binary_distillation_calculation.py
  ↓
BioSTEAM feed-phase calculation
  ↓
structured result
  ↓
LLM explains result only
```

The existing workflow layer already deliberately separates problem definition from engineering calculation, so preserve that boundary.

---

# Step 1 — Do not modify the core workflow checker

Leave:

```text
tools/chopper/binary_distillation_workflow.py
```

unchanged.

It must continue to:

```python
"calculation_performed": False
```

and only determine whether the problem is:

```python
"status": "ready_for_calculation"
```

Do not import BioSTEAM into this module.

Do not call:

```python
build_biosteam_feed()
evaluate_feed_phase()
calculate_binary_distillation_problem()
```

from this module.

---

# Step 2 — Keep the new calculation modules unchanged

Do not move the existing calculation logic into the agent.

Keep:

```text
tools/chopper/biosteam_feed.py
tools/chopper/feed_phase.py
tools/chopper/binary_distillation_calculation.py
```

as deterministic engineering modules.

The agent should call this layer rather than reimplementing any thermodynamic calculation.

---

# Step 3 — Add an agent-facing calculation wrapper

In:

```text
tools/chopper/binary_distillation_workflow_agent.py
```

import:

```python
from binary_distillation_calculation import (
    calculate_binary_distillation_problem,
)
```

Then add a zero-argument wrapper:

```python
def calculate_current_binary_distillation_problem():
    """
    Run deterministic engineering calculations for the currently
    accumulated binary-distillation problem.

    This tool reads the authoritative workflow state directly.
    It must not be used to add, modify, guess, or restate engineering
    inputs.

    The calculation only proceeds when the current problem is
    ready_for_calculation.
    """
    spec = _effective_spec()

    return calculate_binary_distillation_problem(spec)
```

Important:

The function exposed to Qwen must take no engineering arguments.

Do not create:

```python
def calculate_current_binary_distillation_problem(
    components,
    pressure_Pa,
    feed_temperature_K,
    ...
):
```

The model must not reconstruct the problem from conversation history.

The source of truth must remain:

```text
_workflow_state
      ↓
_effective_spec()
      ↓
calculation
```

---

# Step 4 — Register the new calculation tool

Add the wrapper to the available tools.

Conceptually:

```python
TOOLS = [
    update_binary_distillation_problem,
    get_binary_distillation_problem,
    calculate_current_binary_distillation_problem,
    reset_workflow_session,
]
```

and:

```python
TOOL_FUNCTIONS = {
    "update_binary_distillation_problem":
        update_binary_distillation_problem,

    "get_binary_distillation_problem":
        get_binary_distillation_problem,

    "calculate_current_binary_distillation_problem":
        calculate_current_binary_distillation_problem,

    "reset_workflow_session":
        reset_workflow_session,
}
```

Adapt this to the current structure of the file rather than replacing working controller logic unnecessarily.

---

# Step 5 — Extend the per-turn controller safely

The existing controller currently permits at most one engineering-state READ/WRITE operation per turn, with RESET allowed before it.

Preserve that behavior.

Add calculation as a separate operation category.

Recommended categories:

```text
STATE WRITE
update_binary_distillation_problem

STATE READ
get_binary_distillation_problem

CALCULATION
calculate_current_binary_distillation_problem

HOUSEKEEPING
reset_workflow_session
```

For a normal user turn, permit:

```text
RESET -> STATE
```

or:

```text
STATE
```

or:

```text
CALCULATION
```

Do not permit uncontrolled loops such as:

```text
READ
→ CALCULATION
→ READ
→ CALCULATION
→ ...
```

After a calculation tool executes, finalize with:

```python
_chat_without_tools(...)
```

so Qwen can only explain the returned calculation.

---

# Step 6 — Do not require a READ before calculation

The calculation wrapper already reads:

```python
_effective_spec()
```

itself.

Therefore this sequence is unnecessary:

```text
get_binary_distillation_problem()
        ↓
calculate_current_binary_distillation_problem()
```

for a simple phase question.

Prefer:

```text
calculate_current_binary_distillation_problem()
```

directly.

This avoids redundant tool calls and keeps the current bounded-call philosophy.

---

# Step 7 — Add a calculated-state rule to SYSTEM_PROMPT

Add a strong rule similar to:

```text
CALCULATED ENGINEERING STATE RULE

Thermodynamic properties and calculated engineering results are not
conversation facts.

This includes, but is not limited to:

- feed phase
- vapor fraction
- liquid fraction
- bubble point
- dew point
- equilibrium temperature
- equilibrium phase compositions
- boiling behavior

Never infer, estimate, or state these values from general chemical
knowledge, remembered boiling points, or conversation context.

If the user asks for one of these values:

1. If the deterministic calculation tool is available and the
   authoritative problem is ready for calculation, call
   calculate_current_binary_distillation_problem.

2. If the problem is incomplete, use the deterministic workflow state
   to identify the missing inputs.

3. If the calculation layer cannot determine the requested property,
   state that explicitly.

Never replace a deterministic thermodynamic calculation with qualitative
reasoning such as:
"If the temperature is above the boiling point, the feed is probably vapor."
```

This directly prevents the behavior observed in the test.

---

# Step 8 — Add a tool-routing rule for feed-phase questions

Add guidance such as:

```text
FEED-PHASE ROUTING RULE

Questions such as:

- "What is the feed phase?"
- "Is the feed liquid or vapor?"
- "What is the vapor fraction?"
- "Is the feed two-phase?"
- "How much of the feed is vapor?"
- "How much is liquid?"

are calculation questions.

Do not answer them from the workflow state alone.

Call:
calculate_current_binary_distillation_problem

when the authoritative state is ready_for_calculation.
```

---

# Step 9 — Prefer deterministic routing for explicit feed-phase questions

Add a small Python helper:

```python
def is_feed_phase_question(text: str) -> bool:
    normalized = normalize_short_reply(text)

    phase_phrases = (
        "what is the feed phase",
        "what phase is the feed",
        "is the feed liquid",
        "is the feed vapor",
        "is the feed vapour",
        "is the feed two phase",
        "is the feed two-phase",
        "what is the vapor fraction",
        "what is the vapour fraction",
        "how much of the feed is vapor",
        "how much of the feed is vapour",
        "how much of the feed is liquid",
    )

    return any(
        phrase in normalized
        for phrase in phase_phrases
    )
```

Do not make this parser overly broad.

Its purpose is only to catch obvious, explicit phase questions.

---

# Step 10 — Route explicit phase questions before model tool selection

Inside `ask()`:

1. Preserve the current pending-request resolver as the first authority for short replies.

2. After pending resolution, inspect the current authoritative assessment.

3. If the user explicitly asks a feed-phase question, route deterministically.

Conceptually:

```python
assessment = get_binary_distillation_problem()

if is_feed_phase_question(user_text):

    if assessment["status"] == "ready_for_calculation":

        result = calculate_current_binary_distillation_problem()

        # Append a synthetic tool-call/tool-result pair if required
        # by the current message-history convention.

        return _chat_without_tools(...)
```

This means the model never gets to decide whether a feed-phase question should be answered using remembered chemical knowledge.

---

# Step 11 — Handle incomplete problems deterministically

For:

```text
User:
"What is the feed phase?"
```

when:

```python
assessment["status"] != "ready_for_calculation"
```

do not run BioSTEAM.

Instead, preserve the workflow result.

For example:

```python
{
    "calculation_performed": False,
    "workflow": assessment,
    "checks": {}
}
```

Then the assistant should explain which required inputs are still missing.

Example:

```text
I cannot calculate the feed phase yet because the feed thermal
condition is missing.
```

Do not answer using assumptions.

---

# Step 12 — Preserve pending-request priority

The current deterministic pending-request resolver must continue to get first refusal.

Example:

```text
Assistant:
Should the optimum feed plate be used?

User:
yes
```

must still resolve:

```python
use_optimum_feed_plate = True
```

It must not accidentally be routed as a calculation request.

Recommended order:

```text
1. resolve_pending_reply()
2. ready-state boundary checks
3. deterministic feed-phase routing
4. normal model tool selection
```

Adjust ordering slightly if required by the current implementation, but pending-state truth must remain authoritative.

---

# Step 13 — Update ready-state behavior

The current workflow-only agent has a fixed response for phrases such as:

```text
go ahead
proceed
calculate it
```

because calculations were intentionally unavailable.

Now decide narrowly how this boundary should behave.

Recommended change:

If:

```python
assessment["status"] == "ready_for_calculation"
```

and the user says:

```text
calculate it
go ahead
proceed
```

call:

```python
calculate_current_binary_distillation_problem()
```

instead of returning the old:

```text
"The calculation layer is not enabled here."
```

However, because the current calculation pipeline only performs the feed-phase check, the final response must not imply that the full Wankat Case D design has been completed.

For example:

```text
The calculation layer has started. The currently implemented
calculation stage evaluated the feed phase. The remaining Case D
distillation calculations are not yet implemented in this pipeline.
```

---

# Step 14 — Make calculation scope explicit

The current function:

```python
calculate_binary_distillation_problem(spec)
```

currently performs only the first calculation stage:

```text
feed phase
```

Therefore the tool result and system prompt must not imply:

```text
D
B
QR
Qc
N
Nfeed
column diameter
```

have been calculated.

The tool should return only what was actually calculated.

For example:

```python
{
    "calculation_performed": True,
    "workflow": ...,
    "checks": {
        "feed_phase": {...}
    }
}
```

Qwen must describe exactly that result.

---

# Step 15 — Add agent tests

Extend:

```text
tools/chopper/test_binary_distillation_workflow_agent.py
```

or create:

```text
tools/chopper/test_binary_distillation_workflow_agent_calculation.py
```

Add the following tests.

## Test 1 — Ready problem + feed-phase question

Establish a complete binary-distillation problem.

Then send:

```text
what is the feed phase?
```

Assert:

```text
calculate_current_binary_distillation_problem
```

is called.

Assert:

```text
get_binary_distillation_problem
```

is not unnecessarily called as the model-selected engineering operation if deterministic routing already has the state.

---

## Test 2 — Calculation result controls answer

Mock calculation result:

```python
{
    "calculation_performed": True,
    "checks": {
        "feed_phase": {
            "valid": True,
            "phase": "vapor",
            "vapor_fraction": 1.0,
        }
    }
}
```

Assert the final model response is generated only after this result is available.

---

## Test 3 — Incomplete problem does not calculate

Establish a problem missing:

```text
feed thermal condition
```

Ask:

```text
what is the feed phase?
```

Assert:

```text
calculate_current_binary_distillation_problem
```

does not perform BioSTEAM calculation.

Assert the missing input is reported.

---

## Test 4 — No qualitative phase inference

Use a fake model response that attempts to say:

```text
400 K is above methanol's boiling point, so the feed is vapor.
```

Ensure the routing/controller does not permit this to become the authoritative answer when a deterministic calculation is available.

The final answer must be grounded in the calculation result.

---

## Test 5 — Vapor-fraction question routes to calculation

User:

```text
what is the vapor fraction?
```

Assert calculation tool runs.

---

## Test 6 — Liquid/vapor yes-no question routes to calculation

User:

```text
is the feed vapor?
```

Assert calculation tool runs.

---

## Test 7 — Pending confirmation still wins

Establish:

```python
pending_request = {
    "field": "use_optimum_feed_plate",
    ...
}
```

User:

```text
yes
```

Assert:

```python
update_binary_distillation_problem(
    use_optimum_feed_plate=True
)
```

runs.

Assert calculation does not run.

---

## Test 8 — Calculation tool takes zero arguments

Assert Qwen-facing schema exposes:

```python
calculate_current_binary_distillation_problem()
```

with no engineering fields.

This prevents the model from restating or altering the problem.

---

## Test 9 — No repeated calculation loop

Use a pathological fake client that continually asks for:

```text
calculate_current_binary_distillation_problem
```

Assert only one calculation executes in the turn.

After the result, force finalization without tools.

---

# Step 16 — Add an integration test using the real calculation pipeline

Create a full state equivalent to:

```text
Methanol: 50 kmol/hr
Water: 50 kmol/hr
T = 400 K
P = 101325 Pa
reflux_condition = saturated_liquid
boilup_ratio_VB = 1.2
xD = 0.95
xB = 0.01
use_optimum_feed_plate = True
```

Confirm:

```python
assessment["status"] == "ready_for_calculation"
```

Then call:

```python
calculate_current_binary_distillation_problem()
```

Assert:

```python
result["calculation_performed"] is True
```

and:

```python
result["checks"]["feed_phase"]["valid"] is True
```

and:

```python
result["checks"]["feed_phase"]["phase"] in {
    "liquid",
    "vapor",
    "vapor_liquid",
}
```

Do not hard-code the expected phase in the agent test unless using a thermodynamic case specifically chosen for a stable expected result.

---

# Step 17 — Preserve the state-truth rule

The existing state-truth principle must now extend to calculated values.

There are now two authoritative truth sources:

```text
Engineering inputs
    = deterministic workflow state

Calculated engineering results
    = deterministic calculation output
```

Conversation history is authoritative for neither.

The LLM may explain these values but must not create or modify them.

Conceptually:

```text
User statements
      ↓
deterministic WRITE
      ↓
workflow state
      ↓
deterministic calculation
      ↓
calculation result
      ↓
LLM explanation
```

This remains aligned with the project's broader principle that Python/BioSTEAM, rather than the LLM, provides engineering calculation and verification.

---

# Step 18 — Update `separation_tool.md`

Add the calculation-tool connection to the maintained documentation.

Document:

```text
binary_distillation_workflow_agent.py
```

now has four conceptual capabilities:

```text
WRITE state
READ state
RESET state
CALCULATE current authoritative problem
```

Explain that:

```python
calculate_current_binary_distillation_problem()
```

takes zero engineering arguments and reads the accumulated authoritative state.

Also document that the current calculation pipeline only evaluates the feed phase and does not yet execute the full Case A-D calculation.

---

# Definition of done

- [ ] `binary_distillation_workflow.py` remains free of BioSTEAM.
- [ ] Existing feed-phase calculation modules remain deterministic.
- [ ] The workflow agent imports the calculation entry point.
- [ ] A zero-argument `calculate_current_binary_distillation_problem()` wrapper exists.
- [ ] The wrapper reads `_effective_spec()` directly.
- [ ] Qwen cannot pass or restate engineering values into the calculation tool.
- [ ] The calculation tool is registered with the agent.
- [ ] Feed-phase questions route to the calculation layer.
- [ ] Vapor-fraction questions route to the calculation layer.
- [ ] Liquid/vapor/two-phase questions route to the calculation layer.
- [ ] The LLM is explicitly prohibited from thermodynamic phase inference.
- [ ] Pending-request resolution still has priority.
- [ ] Incomplete problems do not trigger BioSTEAM.
- [ ] Calculation executes only after `ready_for_calculation`.
- [ ] A calculation result is executed at most once per user turn.
- [ ] After calculation, the model receives no further tools for that turn.
- [ ] The final answer reports only calculated values actually present in the result.
- [ ] The agent does not claim the full Wankat design was calculated when only feed phase was evaluated.
- [ ] Agent tests cover ready, incomplete, phase, vapor fraction, pending reply, and loop suppression.
- [ ] Full existing test suite still passes.
- [ ] `separation_tool.md` documents the new connection.

# Recommended implementation order

```text
1. Add calculate_current_binary_distillation_problem()
2. Register the calculation tool
3. Add calculated-state SYSTEM_PROMPT rule
4. Add feed-phase routing rule
5. Add deterministic is_feed_phase_question()
6. Wire deterministic phase routing into ask()
7. Update ready-state "calculate/go ahead" behavior
8. Add controller safeguards against repeated calculation
9. Add agent unit tests
10. Add real calculation integration test
11. Run the full chopper test suite
12. Manually repeat the original Methanol/Water conversation
13. Update separation_tool.md
```

# Expected manual behavior after implementation

Input:

```text
You:
Separate methanol and water, each has a flow rate of 50 kmol per hour,
and the feed temperature is 400 K. The pressure is 101325 Pa, and the
reflux can be thought of as a saturated liquid. The boil up ratio is
1.2. xD = 0.95, and xB = 0.01. Optimum feed location can be assumed.
```

Expected:

```text
[calling update_binary_distillation_problem(...)]
```

Then:

```text
Assistant:
The problem is fully specified as Case D and is ready for calculation.
```

Then:

```text
You:
what is the feed phase?
```

Expected:

```text
[calling calculate_current_binary_distillation_problem({})]
```

Not:

```text
[calling get_binary_distillation_problem({})]
```

and definitely not:

```text
"If the temperature is above the boiling point..."
```

The final response should instead report the exact deterministic BioSTEAM phase result contained in:

```python
result["checks"]["feed_phase"]
```