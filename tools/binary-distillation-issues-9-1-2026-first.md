# Systematic Reliability-Fix Plan for the Binary-Distillation Agent

We have identified several failure modes through repeated live testing of `binary_distillation_workflow_agent.py`.

Do NOT fix everything in one large refactor.

Implement these fixes in FIVE SEPARATE ROUNDS.

After each round:

1. run its focused tests;
2. run the full `tools/chopper` test suite;
3. manually replay the relevant portion of the original conversation;
4. report results before proceeding to the next round.

The goal is to preserve a clear causal relationship between each bug and each fix.

The deterministic engineering layer should remain authoritative.

---

# Overall principle

The architecture should enforce:

```text
USER
  ↓
Qwen extracts intent/facts
  ↓
STRICT TOOL BOUNDARY
  ↓
AUTHORITATIVE PYTHON STATE
  ↓
DETERMINISTIC CONTROLLER
  ↓
DETERMINISTIC ENGINEERING
  ↓
STRUCTURED RESULT
  ↓
Qwen renders the result
```

Qwen must not become the engineering-state authority at either end of this pipeline.

---

# ROUND 1 — Harden the WRITE/tool-schema boundary

## Bug being fixed

Qwen generated:

```python
component_names = ["Water", "Ethanol"]

component_flows = [50, 50]

component_flow_units = ["kmol/hr", "kmol/hr"]
```

but the canonical schema expects approximately:

```python
component_names = ["Water", "Ethanol"]

component_flows = {
    "Water": 50,
    "Ethanol": 50,
}

component_flow_units = "kmol/hr"
```

This caused:

```text
AttributeError: 'list' object has no attribute 'items'
```

A malformed LLM payload must NEVER produce a raw Python attribute/type error.

---

## Step 1.1 — Inspect the actual generated Ollama tool schema

Inspect what Ollama/Qwen actually sees for:

```python
update_binary_distillation_problem
```

Do not inspect only the Python type hints.

Print or otherwise inspect the generated JSON tool schema.

Verify specifically:

```text
component_names
component_flows
component_flow_units
total_flow
total_flow_units
composition
```

Expected conceptual schema:

```text
component_names:
    array[string]

component_flows:
    object / mapping
    string -> number

component_flow_units:
    string
```

Report whether the generated schema is already correct.

If it is incorrect, fix the Python signature/type hints/docstring/schema generation first.

If it is already correct, treat this as Qwen schema-adherence failure.

---

## Step 1.2 — Add explicit tool-boundary validation

Before malformed values reach:

```python
feed_state.apply_user_update()
```

validate their types.

For example:

```python
component_flows
```

must ultimately become:

```python
dict[str, float]
```

and:

```python
component_flow_units
```

must ultimately become:

```python
str
```

Invalid input must NOT raise an implementation exception.

Return a structured result such as:

```python
{
    "valid": False,
    "error": "invalid_tool_arguments",
    "field": "component_flows",
    "expected": "mapping of component name to numeric flow",
    "received_type": "list",
    "message": "...",
}
```

Use whatever schema fits the project, but never leak:

```text
AttributeError
TypeError
KeyError
```

as the normal user-facing failure mechanism.

---

## Step 1.3 — Add narrow deterministic canonicalization for the observed error

Because this exact malformed representation is unambiguous:

```python
component_names = ["Water", "Ethanol"]
component_flows = [50, 50]
```

it MAY be deterministically normalized to:

```python
{
    "Water": 50,
    "Ethanol": 50,
}
```

ONLY when all of these are true:

```text
component_names is a sequence
component_flows is a sequence
same length
all names are unique strings
all flows are numeric
```

Likewise:

```python
component_flow_units = ["kmol/hr", "kmol/hr"]
```

may become:

```python
"kmol/hr"
```

ONLY if every value deterministically normalizes to the same unit.

For example:

```python
["KMOL/HR", "kmol per hour"]
```

can both normalize to:

```python
"kmol/hr"
```

and then collapse.

But:

```python
["kmol/hr", "kg/hr"]
```

must NOT be guessed or collapsed.

Return structured invalid/conflicting arguments.

---

## Step 1.4 — Keep canonical engineering state strict

Do NOT modify `feed_state.py` so lists become an officially supported engineering representation.

Canonical state remains:

```python
component_flows: dict[str, number]
component_flow_units: str
```

The repair belongs at the LLM/tool boundary.

Architecture:

```text
messy LLM representation
        ↓
tool argument normalizer
        ↓
canonical representation
        ↓
feed_state
```

---

## Round 1 regression tests

At minimum test:

### Valid canonical form

```python
component_names=["Water", "Ethanol"]
component_flows={"Water": 50, "Ethanol": 50}
component_flow_units="kmol/hr"
```

works unchanged.

### Recoverable parallel-array form

```python
component_names=["Water", "Ethanol"]
component_flows=[50, 50]
```

normalizes safely.

### Recoverable repeated units

```python
component_flow_units=["kmol/hr", "kmol/hr"]
```

normalizes safely.

### Conflicting units

```python
["kmol/hr", "kg/hr"]
```

returns structured error.

### Length mismatch

```python
component_names=["Water", "Ethanol"]
component_flows=[50]
```

returns structured error.

### Nonnumeric flow

returns structured error.

### No raw exceptions

Every malformed case returns JSON-friendly structured output.

---

## Round 1 manual acceptance test

Replay EXACTLY:

```text
Separate water and ethanol at 355 K and 101325 Pa pressure.
The feed composition is 50 kmol/hr ethanol and 50 kmol/hr water,
and the reflux is saturated liquid.
```

The first WRITE must no longer crash.

Confirm that state contains:

```text
Water = 50 kmol/hr
Ethanol = 50 kmol/hr
T = 355 K
P = 101325 Pa
reflux_condition = saturated_liquid
```

STOP after Round 1 and report results.

---

# ROUND 2 — Make specific state questions deterministic

## Bug being fixed

User asked:

```text
Did I already specify the flow rate of ethanol?
If yes, what was it?
```

The READ tool returned:

```python
component_flows = {
    "Ethanol": 50,
    "Water": 50
}
```

but Qwen ignored the answer and talked about Design Options.

That means the deterministic state was correct but presentation failed.

---

# Architectural requirement

Specific state queries should not depend on Qwen deciding which portion of a huge state object is important.

Add deterministic routing for common state lookup questions.

Conceptually:

```text
"What was the ethanol flow?"
        ↓
deterministic state query
        ↓
{
    field: "component_flows.Ethanol",
    found: True,
    value: 50,
    units: "kmol/hr"
}
        ↓
Qwen merely verbalizes it
```

---

## Step 2.1 — Add a state-query resolver

Inspect the best location in:

```text
binary_distillation_workflow_agent.py
```

for a narrow deterministic resolver.

It should recognize questions about known stored quantities such as:

```text
what pressure did I specify?
what was the feed temperature?
what is the ethanol flow?
did I give the water flow?
what is xD?
did I give a boilup ratio?
what reflux condition did I specify?
```

Do not try to build a universal natural-language parser.

Start with the actual project fields and narrow patterns.

---

## Step 2.2 — Return a focused state-query result

Prefer a small structure like:

```python
{
    "query_type": "stored_field",
    "field": "component_flows.Ethanol",
    "found": True,
    "value": 50,
    "units": "kmol/hr",
    "provenance": "user_explicit",
}
```

rather than giving Qwen the entire assessment when only one field was requested.

If not found:

```python
{
    "found": False,
    "field": ...
}
```

Then Qwen can say:

```text
No, that value has not been specified yet.
```

---

## Step 2.3 — Add a prompt/state-truth rule

Add:

```text
SPECIFIC STATE QUERY RULE

When the user asks whether a specific quantity was supplied or asks
for its stored value, answer the requested quantity directly from
the deterministic state result.

Do not replace the answer with general workflow guidance.

Do not ask again for a quantity that the deterministic state says is known.
```

---

## Round 2 tests

Test at minimum:

```text
"What was the ethanol flow?"
→ 50 kmol/hr
```

```text
"Did I already give the water flow?"
→ yes, 50 kmol/hr
```

```text
"What pressure did I specify?"
→ 101325 Pa
```

```text
"What feed temperature did I give?"
→ 355 K
```

and one genuinely unknown field:

```text
"Did I specify xD?"
→ no
```

Ensure no Design Option lecture replaces the requested answer.

STOP and report.

---

# ROUND 3 — Ground presentation of deterministic calculation results

## Bugs being fixed

The tool returned:

```python
liquid_percent = 100.0
vapor_percent = 0.0
route = "liquid_phase_separation"
```

but Qwen said:

```text
Since 50 mol% liquefies...
```

and invented:

```text
liquid_phase_separation_advisable
```

Both are unacceptable.

---

# Architectural requirement

Qwen must not recalculate, reinterpret, threshold, rename, or manufacture deterministic engineering results.

---

## Step 3.1 — Create presentation-ready result fields if necessary

Inspect whether the calculation result already exposes enough semantic information.

It already includes items such as:

```python
liquid_percent
vapor_percent
route
message
```

Prefer having Python return the exact engineering statements Qwen should render.

If useful, add a compact model-facing summary such as:

```python
"presentation": {
    "initial_phase": "vapor_liquid",
    "initial_liquid_percent": 25.456,
    "initial_vapor_percent": 74.544,
    "conditioned_liquid_percent": 100.0,
    "conditioned_vapor_percent": 0.0,
    "route": "liquid_phase_separation",
    "route_label": "liquid-phase separation",
}
```

Do not duplicate engineering calculations; derive these from the already-computed result.

---

## Step 3.2 — Add a numerical grounding rule

Prompt rule:

```text
CALCULATED VALUE GROUNDING RULE

If a deterministic calculation tool supplies a numeric value,
use that value.

Do not replace it with a threshold, approximation, reconstructed value,
or value derived from model knowledge.

Example:

liquid_percent = 100.0
means 100% liquid.

It must never be rendered as "50% liquefies" merely because 50% is a
routing threshold elsewhere.
```

---

## Step 3.3 — Add exact route-ID grounding

Prompt rule:

```text
ROUTE IDENTIFIER RULE

Machine-readable route identifiers come exclusively from Python.

If the tool returns:

route = "liquid_phase_separation"

never rename it to:

liquid_phase_separation_advisable
liquid_separation_recommended
or any other invented identifier.
```

Qwen can separately say:

```text
The next pathway is liquid-phase separation.
```

But machine IDs must remain exact.

---

## Round 3 tests

Feed a scripted tool result containing:

```python
liquid_percent = 100.0
vapor_percent = 0.0
route = "liquid_phase_separation"
```

Verify assistant output:

- says 100%, not 50%;
- never says `liquid_phase_separation_advisable`;
- does not invent another vapor fraction;
- accurately describes complete condensation.

Replay the real Water/Ethanol case.

STOP and report.

---

# ROUND 4 — Fix Design Option interaction and stage-aware pending requests

## Bugs being fixed

The model currently says things such as:

```text
You must choose Design Option A, B, C, or D.
```

That is contrary to the intended architecture.

The user should provide engineering variables.

Python should classify the matching Design Option.

Also, after feed screening became ready, the legacy state still exposed:

```python
pending_request = reflux_condition
```

even though the next executable physical step was feed screening.

That creates ambiguity around replies such as:

```text
yes
proceed
go ahead
```

---

## Step 4.1 — Change Design Option UX

Qwen should NEVER require a user to know or select A/B/C/D manually unless the user explicitly wants to.

Instead:

```text
Provide the design information you know, such as product compositions,
recoveries, product flow, reflux ratio, or boilup ratio.

The deterministic workflow will identify the matching Design Option.
```

Design Option is a classification.

It is not a user-selected mode.

---

## Step 4.2 — Make pending requests stage-aware

Current execution priority should be:

```text
feed screen missing inputs
        ↓
feed screen ready
        ↓
feed screen executable
        ↓
feed screening performed
        ↓
downstream/design information
```

Therefore, once:

```python
feed_screening["ready"] == True
```

and feed screening has not yet run, do not leave a downstream design question as the active conversational pending request.

Preferred state:

```python
pending_request = None
```

with a deterministic:

```python
next_action = "feed_phase"
```

or equivalent.

Only after the relevant physical stage is complete should design-stage pending fields become conversationally active.

---

## Step 4.3 — Ensure "yes" cannot answer the wrong stage

Test:

```text
feed_screening.ready = True
reflux_condition missing
user says "yes"
```

The system must not accidentally interpret `"yes"` as a reflux condition.

If `"yes"` is currently a proceed trigger, it should proceed with the feed calculation.

If the architecture requires an explicit phrase such as `"proceed"`, preserve that existing behavior consistently.

Do not allow simultaneous interpretations.

---

## Round 4 tests

Test:

- feed ready + reflux condition missing;
- feed ready + optimum feed confirmation missing;
- `"proceed"` runs feed phase;
- `"what next?"` reports feed phase before design information;
- Design Option classification occurs from supplied engineering values;
- assistant never says user **must choose A/B/C/D**.

STOP and report.

---

# ROUND 5 — Create a model-facing state projection

This is lower priority than Rounds 1–4.

Do this only after the earlier behavior is stable.

---

## Problem

For backward compatibility, the raw workflow currently contains combinations such as:

```python
feed_screening["ready"] == True
```

while also containing:

```python
status == "need_essential_inputs"
```

because the legacy top-level state still considers downstream distillation inputs.

This is internally valid, but it is unnecessarily difficult for Qwen to interpret.

---

## Goal

Keep the full deterministic/internal report for:

- tests;
- debugging;
- compatibility;
- audit.

But create a smaller model-facing projection.

Conceptually:

```python
{
    "feed_screening": {
        "ready": True,
        "status": "ready",
        "missing_inputs": [],
    },

    "design_assessment": {
        "complete": False,
        "design_option": None,
        "design_option_candidates": ["A", "B", "C", "D"],
        ...
    },

    "execution": {
        "next_action": "feed_phase",
        "next_action_available": True,
    },

    "relevant_pending_request": None
}
```

Do NOT expose every legacy compatibility field to Qwen unless it is actually useful for that response.

---

## Important distinction

Do NOT remove legacy state merely to make Qwen happier.

Instead:

```text
full internal truth
        ↓
deterministic projection
        ↓
minimal model-facing truth
```

This preserves auditability without forcing an 8B model to reason over implementation artifacts.

---

## Round 5 tests

Ensure:

1. internal full state remains unchanged;
2. legacy tests continue to pass;
3. model-facing output contains feed/design distinction;
4. model-facing output does not contain contradictory-looking irrelevant statuses;
5. all facts needed by Qwen remain available;
6. state queries still work;
7. calculation-result grounding still works.

STOP and report.

---

# FINAL REPLAY TEST

Only after all five rounds are individually stable, replay this entire conversation from a fresh session:

```text
Separate water and ethanol at 355 K and 101325 Pa pressure.
The feed composition is 50 kmol/hr ethanol and 50 kmol/hr water,
and the reflux is saturated liquid.
```

Expected:

- no malformed-list crash;
- all explicit facts stored in one WRITE.

Then:

```text
Proceed with the feed phase evaluation.
```

Expected:

- actual BioSTEAM calculation;
- initial vapor/liquid split correctly reported;
- conditioned liquid = 100%;
- conditioned vapor = 0%;
- route exactly `liquid_phase_separation`;
- no invented "50% liquefies."

Then:

```text
What other information do you still need?
```

Expected:

- deterministic current-state answer;
- do NOT request feed values already stored;
- distinguish feed screening from incomplete design definition;
- do NOT force user to choose A/B/C/D.

Then:

```text
Did I already specify the flow rate of ethanol?
If yes, what was it?
```

Expected:

```text
Yes. The stored ethanol feed flow is 50 kmol/hr.
```

No unrelated Design Option explanation.

---

# Implementation ordering

Implement strictly in this order:

```text
ROUND 1
Tool input boundary

↓ full tests

ROUND 2
Specific state reads

↓ full tests

ROUND 3
Calculation-output grounding

↓ full tests

ROUND 4
Design Option UX + pending-stage semantics

↓ full tests

ROUND 5
Model-facing state projection
```

Do not combine Round 1 and Round 5 into a large schema refactor.

Do not change BioSTEAM thermodynamics in any round.

Do not change the 313.15 K conditioning physics.

Do not change the existing phase-fraction thresholds/tolerances.

Do not implement downstream liquid/vapor separation methods.

Do not implement full Design Option sizing.

---

# Why this order

Round 1 fixes:

```text
Can valid user information safely enter the system?
```

Round 2 fixes:

```text
Can the system reliably retrieve authoritative stored information?
```

Round 3 fixes:

```text
Can deterministic engineering results reach the user without corruption?
```

Round 4 fixes:

```text
Does the workflow ask for the correct thing at the correct stage?
```

Round 5 fixes:

```text
Can Qwen consume a cleaner representation of the overall state?
```

This intentionally hardens the system from the outside inward before performing presentation/schema cleanup.

---

# Definition of done

The reliability pass is finished when:

1. malformed Qwen tool arguments never produce raw Python exceptions;
2. safely recoverable parallel-list inputs normalize deterministically;
3. ambiguous malformed inputs are rejected structurally rather than guessed;
4. specific stored-value questions produce specific stored-value answers;
5. Qwen never asks again for an already-known value unless state says it is missing;
6. deterministic numeric results are rendered without reinterpretation;
7. route IDs are never renamed or invented;
8. Design Options are classified from engineering inputs rather than manually selected by the user;
9. active pending requests correspond to the current executable stage;
10. feed-screen readiness is not confused with downstream design incompleteness;
11. a model-facing state projection exists if needed without changing internal truth;
12. the complete original conversation replay behaves correctly;
13. all existing tests plus new regression tests pass.