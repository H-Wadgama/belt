# Implementation Plan: Fix the Current Binary-Distillation Workflow Without Making the Architecture Brittle

## Goal

Fix the four current problems:

1. `"Yes"` can accidentally trigger a calculation when the program is still waiting for a specific engineering value.
2. Qwen sometimes proposes internal Python function names instead of a stable high-level action.
3. Questions like `"What inputs are required for the four cases?"` are being treated like requests for a stored variable.
4. Feed-phase screening can currently say it is ready even when `reflux_condition` is still missing.

Implement these fixes in a way that also supports future workflows like multicomponent distillation, absorption, extraction, etc.

The main architecture rule is:

> Qwen should understand what the user means. Python should own the engineering rules, required inputs, allowed actions, readiness checks, and calculations.

Do not redesign the whole project.

---

# Step 1: Make the current unanswered question take priority

## Problem

If the program has just asked the user for something specific, for example:

```text
Please specify the reflux condition.
```

and the user replies:

```text
Yes
```

the system can currently interpret that as:

```text
go ahead and calculate
```

That is wrong.

## Change

In `binary_distillation_workflow_agent.py`, make the routing order:

```text
1. Check whether the workflow is currently waiting for a specific answer.
2. If it is, try to interpret the user's reply as an answer to that question.
3. If the reply does not actually provide the requested value, do not run another action.
4. Ask for the missing value again.
5. Only allow generic "yes", "continue", "go ahead", etc. when there is no unresolved question waiting for the user.
```

This must be a general rule.

Do not write reflux-specific code such as:

```python
if missing_reflux and user_said_yes:
```

The same logic should work later if the program is waiting for:

```text
pressure
solvent choice
thermodynamic model
product specification
recovery target
```

## Required behavior

Example:

```text
Assistant:
Please specify the reflux condition.

User:
Yes
```

Expected:

```text
No calculation.
No state change.
Ask the user to state the reflux condition explicitly.
```

But:

```text
User:
reflux is saturated liquid
```

should save:

```python
{"reflux_condition": "saturated_liquid"}
```

through the normal update path.

---

# Step 2: Make feed screening require reflux condition

## Problem

The workflow can currently report:

```text
feed screening is ready
```

while still asking for:

```text
reflux_condition
```

These two statements contradict each other.

In this project, reflux condition is part of feed-phase screening.

## Change

In `binary_distillation_workflow.py`, make the feed-screening requirements explicitly include:

```text
binary feed information
flow units
feed temperature / feed thermal information
pressure
reflux condition
```

Use one shared definition of these requirements wherever possible.

The following should all agree:

```text
feed_screening.ready
feed_screening.missing_inputs
whether the program asks for another feed input
whether feed screening can be calculated
```

Do not patch only one `if` statement if other parts of the workflow use a different definition.

## Required behavior

After:

```text
50 kmol/hr ethanol
50 kmol/hr water
355 K
101325 Pa
```

but no reflux condition:

```text
feed_screening.ready = False
missing_inputs includes reflux_condition
```

After:

```text
reflux is saturated liquid
```

then:

```text
feed_screening.ready = True
```

assuming the other feed-screening inputs are complete.

Do not silently assume saturated-liquid reflux.

---

# Step 3: Stop exposing internal Python function names to Qwen

## Problem

Qwen generated:

```text
calculate_current_binary_distillation_problem
```

That is an internal implementation function.

Qwen should not need to know which Python function performs the calculation.

## Change

Keep a small set of stable high-level actions that Qwen is allowed to request.

For example:

```text
calculate_current_step
reset_current_problem
```

Python then maps:

```text
calculate_current_step
```

to the correct implementation internally.

For the current binary-distillation workflow that may map to:

```python
calculate_current_binary_distillation_problem
```

Later, another workflow could map the same high-level request to a different function.

## Important

Do not add:

```text
calculate_current_binary_distillation_problem
```

as another allowed name just to make the current bug disappear.

Instead:

- hide internal function names from Qwen,
- expose only stable high-level action names,
- validate that Qwen only chooses from those names.

Where possible, use one source of truth for the list of allowed actions so the prompt, validator, and execution code cannot drift apart.

## Required tests

Verify:

```text
calculate_current_step
```

is accepted.

Verify:

```text
calculate_current_binary_distillation_problem
```

is rejected.

Verify the model-facing prompt/schema does not contain the internal function name.

---

# Step 4: Separate "what value did the user give?" from "how does this workflow work?"

## Problem

The user asked:

```text
What are the inputs required for the four cases?
```

The system treated this as though the user was asking for a stored variable such as:

```text
missing_case_inputs
```

That variable does not exist, so the system returned:

```text
unknown_problem_field
```

## Change

Keep two simple kinds of questions separate.

### Type A: questions about the current problem

Examples:

```text
What pressure did I give you?
What is xD?
What are the feed flow rates?
```

These should read the saved engineering problem.

### Type B: questions about how the workflow works

Examples:

```text
What does Case A require?
What inputs are needed for Cases A-D?
What do I still need for Case D?
```

These should read the deterministic workflow definitions.

Do not create fake saved variables such as:

```text
missing_case_inputs
design_option_requirements
```

inside the engineering problem state.

---

# Step 5: Make the Case A-D requirements come from one engineering definition

The workflow already knows what each design case requires.

Use those same deterministic definitions to answer user questions.

Do not let Qwen invent these requirements from memory.

The current definitions are:

```text
Case A:
xD
xB
external reflux specification
optimum feed location confirmation

Case B:
light-component recovery
heavy-component recovery
external reflux specification
optimum feed location confirmation

Case C:
one product composition: xD or xB
one product flow: distillate or bottoms
external reflux specification
optimum feed location confirmation

Case D:
xD
xB
boilup ratio V/B
optimum feed location confirmation
```

If these requirements are currently duplicated in several places, refactor only enough that there is one authoritative definition and the rest of the workflow reads from it.

Do not do a large rewrite.

## Required behavior

Questions such as:

```text
What are the inputs required for the four cases?
What does Case A need?
What am I missing for Case D?
```

should be answered from the workflow definition.

They should never produce:

```text
unknown_problem_field
```

---

# Step 6: Keep binary-distillation rules inside the binary-distillation workflow

This is the main scalability requirement.

Do not put logic like this into the global assistant:

```python
if case_A:
if case_B:
if reflux_condition:
if number_of_components == 2:
```

Those are binary-distillation rules.

Keep them inside the binary-distillation workflow.

The shared assistant should only do things like:

```text
understand the user's message
check whether the current workflow is waiting for something
save valid user inputs
answer questions using the current workflow
request a calculation
```

The workflow itself should define:

```text
what inputs it needs
what stages it has
when a stage is ready
what design options exist
what calculations are available
```

This should allow the project to grow conceptually like:

```text
Separation Assistant
        |
        +-- Binary Distillation
        |
        +-- Multicomponent Distillation
        |
        +-- Absorption
        |
        +-- Extraction
        |
        +-- future workflows
```

Each workflow should own its own engineering rules.

Do not implement those future workflows now.

Just avoid making the shared routing code depend on binary-distillation-specific assumptions.

---

# Step 7: Keep the current state-update architecture unchanged

Do not change the successful parts of the current architecture.

Preserve:

```text
component-flow keyed extraction
one atomic update per valid turn
no update when validation fails
existing unit validation
existing transaction/update path
existing diagnostics where possible
existing retry behavior
```

All new user-provided engineering values must still go through the normal canonical update function.

Do not introduce another way to modify the problem state.

---

# Step 8: Add tests for the general rules

Do not only test the exact failing conversation.

Add tests for the underlying behavior.

## Test group A — unanswered question has priority

When waiting for a string value:

```text
User: yes
User: sure
User: okay
User: go ahead
```

Expected:

```text
do not calculate
do not invent the value
keep asking for the missing value
```

Explicit answer:

```text
reflux is saturated liquid
```

Expected:

```text
save reflux_condition
```

Also confirm existing numeric and boolean short-answer handling still works.

---

## Test group B — feed screening

With feed flows, units, temperature, and pressure but no reflux condition:

```text
ready = False
missing includes reflux_condition
```

After valid reflux condition:

```text
ready = True
```

Unsupported reflux condition:

```text
ready remains False
no silent substitution
```

---

## Test group C — calculations

Verify:

```text
calculate_current_step
```

runs the correct internal binary-distillation calculation.

Verify the internal Python function name is not accepted as a model-requested action.

---

## Test group D — questions

These should read saved values:

```text
What pressure did I give?
What is the feed temperature?
What is xD?
```

These should read workflow definitions:

```text
What does Case A require?
What are the inputs for Cases A-D?
What do I still need for Case D?
```

No fake engineering fields should be created.

---

# Step 9: Run this full live-Qwen acceptance conversation

Run:

```text
User:
Separate water and ethanol at 355 K and 101325 Pa pressure.
The feed flow rates are 50 kmol/hr ethanol and 50 kmol/hr water.
```

Expected:

```text
one update containing:
Ethanol = 50
Water = 50
units = kmol/hr
T = 355 K
P = 101325 Pa

feed screening not ready
asks for reflux condition
```

Then:

```text
User:
Yes
```

Expected:

```text
no calculation
no state change
asks for reflux condition explicitly
```

Then:

```text
User:
reflux is saturated liquid
```

Expected:

```text
one update:
reflux_condition = saturated_liquid

feed screening now ready
```

Then:

```text
User:
What are the inputs required for the four cases you mentioned?
```

Expected:

```text
answers Case A-D requirements from deterministic workflow definitions

no unknown_problem_field
no fake field
```

---

# Do not do these things

Do not:

- redesign the entire project,
- implement new separation methods,
- implement multicomponent calculations,
- hard-code the exact example sentences,
- make `"yes"` mean `"saturated_liquid"`,
- expose internal Python function names to Qwen,
- add workflow questions as fake engineering variables,
- let Qwen decide whether a calculation is ready,
- let Qwen invent Case A-D requirements,
- put Case A-D logic into the global assistant,
- put the two-component limitation into the global engine,
- create another state-update path.

The current binary-distillation workflow may still reject more than two components.

Just make sure that restriction belongs to the binary-distillation workflow so a future multicomponent workflow can support more components without changing the shared assistant.

---

# Definition of done

This work is complete when:

1. Feed screening requires reflux condition.
2. `"Yes"` cannot bypass a missing requested value.
3. Explicit reflux condition is saved correctly.
4. Qwen only requests stable high-level actions.
5. Internal Python function names stay internal.
6. Questions about current saved values still work.
7. Questions about Case A-D requirements are answered from the workflow definitions.
8. No fake workflow fields are added to the engineering problem state.
9. Existing component-flow and atomic-update behavior still works.
10. Binary-distillation-specific engineering rules remain inside the binary-distillation workflow.
11. All existing tests pass except tests that specifically encoded the incorrect behavior.
12. New tests and the live-Qwen acceptance conversation pass.

---

# Final report

After implementation, report only:

- files changed,
- what changed in each file,
- tests added,
- total test result,
- result of the live-Qwen conversation,
- whether any core state/update architecture was changed,
- any remaining limitation or concern about future scalability.