# Objective

Fix the inconsistency where the workflow can report:

```python
status == "ready_for_calculation"
```

while the downstream BioSTEAM calculation still cannot run because flow-rate units are missing.

The intended behavior is:

```text
workflow definition complete
        ↓
calculation-specific inputs complete?
        ↓
YES → ready_for_calculation
NO  → need_calculation_inputs
```

Do not solve this by defaulting units, reading them from conversation history, or letting the LLM infer them.

The authoritative state must contain the units before the calculation layer is allowed to run.

This preserves the project’s current state-truth architecture, where feed identity and quantity are accumulated deterministically rather than reconstructed by the LLM.

# Step 1 — Add calculation-readiness fields to the workflow result

Modify:

```text
tools/chopper/binary_distillation_workflow.py
```

Extend the return schema with:

```python
"calculation_inputs_complete": bool,
"missing_calculation_inputs": list[str],
```

Do not redefine Wankat Table 3-1 itself.

Keep:

```python
essential_complete
case_complete
optimum_feed_plate_confirmed
```

as their existing workflow concepts.

Add a separate calculation-readiness layer after those checks.

Target hierarchy:

```text
binary scope
    ↓
feed quantity/composition
    ↓
Wankat essential inputs
    ↓
case identification
    ↓
optimum feed plate
    ↓
calculation-specific inputs
    ↓
ready_for_calculation
```

# Step 2 — Define calculation-specific required inputs

For the current calculation pipeline, require enough information to construct the BioSTEAM stream.

At minimum check:

```python
component_flow_units
```

when `component_flows` are being used.

If the current feed representation can also use:

```python
total_flow
composition
total_flow_units
```

then support that path explicitly.

Recommended deterministic helper:

```python
def check_calculation_inputs(feed_state):
    missing = []

    if feed_state["component_flows"]:
        if not feed_state.get("component_flow_units"):
            missing.append("component_flow_units")

    elif feed_state.get("total_flow") is not None:
        if not feed_state.get("total_flow_units"):
            missing.append("total_flow_units")

    return {
        "complete": not missing,
        "missing": missing,
    }
```

Adapt field access to the actual `feed_state` schema.

Do not assume `"kmol/hr"`.

# Step 3 — Add a new workflow status

Add:

```python
status = "need_calculation_inputs"
```

Use it only after:

```python
essential_complete is True
case_complete is True
optimum_feed_plate_confirmed is True
```

but required calculation inputs are still missing.

Example result:

```python
{
    "essential_complete": True,
    "case_complete": True,
    "optimum_feed_plate_confirmed": True,

    "calculation_inputs_complete": False,
    "missing_calculation_inputs": [
        "component_flow_units"
    ],

    "status": "need_calculation_inputs",

    "message": (
        "The binary-distillation problem definition is complete, "
        "but component flow-rate units are required before the "
        "BioSTEAM calculation can run."
    )
}
```

Only return:

```python
status = "ready_for_calculation"
```

when:

```python
calculation_inputs_complete is True
```

# Step 4 — Generate a deterministic pending request for missing units

Extend `pending_request` generation.

When exactly one calculation input is missing:

```python
component_flow_units
```

return something like:

```python
{
    "field": "component_flow_units",
    "request_type": "flow_units",
    "prompt": "What units are the component flow rates in?"
}
```

For:

```python
total_flow_units
```

return:

```python
{
    "field": "total_flow_units",
    "request_type": "flow_units",
    "prompt": "What units is the total feed flow rate in?"
}
```

Do not generate a pending request if multiple genuinely ambiguous fields remain.

# Step 5 — Add deterministic unit normalization

In:

```text
tools/chopper/binary_distillation_workflow_agent.py
```

extend `resolve_pending_reply()` to support:

```python
request_type == "flow_units"
```

Normalize common variants.

For example:

```text
kmol/hr
kmol per hr
kmol per hour
kilomol/hr
kilomoles per hour
```

→

```python
"kmol/hr"
```

and:

```text
kg/hr
kg per hour
kilograms per hour
```

→

```python
"kg/hr"
```

Implement with a fixed mapping.

Example:

```python
_FLOW_UNIT_ALIASES = {
    "kmol/hr": "kmol/hr",
    "kmol per hr": "kmol/hr",
    "kmol per hour": "kmol/hr",
    "kilomoles per hour": "kmol/hr",

    "kg/hr": "kg/hr",
    "kg per hr": "kg/hr",
    "kg per hour": "kg/hr",
    "kilograms per hour": "kg/hr",
}
```

Then:

```python
if request_type == "flow_units":
    normalized = normalize_units_reply(text)

    if normalized is not None:
        return {
            pending_request["field"]: normalized
        }
```

# Step 6 — Ensure a units-only reply performs a WRITE

This conversation:

```text
Assistant:
What units are the component flow rates in?

User:
KMOL/HR
```

must deterministically become:

```python
update_binary_distillation_problem(
    component_flow_units="kmol/hr"
)
```

It must not become:

```python
get_binary_distillation_problem()
```

The existing pending-request resolver should get first refusal before model tool selection.

# Step 7 — Improve initial LLM extraction of explicit units

Update the tool docstring and/or `SYSTEM_PROMPT`.

Add a rule:

```text
FLOW-UNIT EXTRACTION RULE

Whenever the user states a flow rate together with units, preserve both
the numeric flow and the units in the same WRITE.

Example:

"50 kmol per hour methanol and 50 kmol per hour water"

must produce:

component_flows = {
    "Methanol": 50,
    "Water": 50
}

component_flow_units = "kmol/hr"

Never discard explicitly stated units.
```

This reduces how often the deterministic fallback is needed.

But the workflow must still reject missing units even if Qwen fails to extract them.

# Step 8 — Do not recover units from conversation history

Do not add logic like:

```python
if units_missing:
    search_messages_for_units()
```

Do not let:

```python
calculate_current_binary_distillation_problem()
```

read chat history.

The valid path remains:

```text
user statement
    ↓
WRITE
    ↓
authoritative state
    ↓
calculation
```

not:

```text
user statement
    ↓
conversation history
    ↓
calculation guesses/reconstructs state
```

# Step 9 — Keep BioSTEAM adapter strict

Keep:

```text
tools/chopper/biosteam_feed.py
```

strict.

If units are missing, it should still fail explicitly.

Do not add:

```python
units = units or "kmol/hr"
```

Do not silently convert or assume units.

# Step 10 — Make calculation-layer failures machine-readable

Update the calculation failure shape if necessary.

Prefer:

```python
{
    "calculation_performed": False,
    "error": "missing_calculation_inputs",
    "missing_calculation_inputs": [
        "component_flow_units"
    ],
    "message": (
        "Component flow-rate units are required to construct "
        "the BioSTEAM feed."
    )
}
```

This is a defensive backstop.

Under normal operation, the workflow should catch the missing units before this layer is reached.

# Step 11 — Prevent phase calculation when units are missing

Update the deterministic feed-phase routing in:

```text
binary_distillation_workflow_agent.py
```

The routing condition should remain:

```python
assessment["status"] == "ready_for_calculation"
```

Because missing units will now produce:

```python
status == "need_calculation_inputs"
```

the phase calculation will automatically not run.

For:

```text
User:
What is the feed phase?
```

with missing units, the assistant should surface the missing field instead.

# Step 12 — Add SYSTEM_PROMPT guidance for the new status

Add:

```text
NEED_CALCULATION_INPUTS

If the deterministic checker returns status="need_calculation_inputs",
the engineering problem definition may already be complete, but the
calculation cannot run yet.

Ask only for the fields listed in missing_calculation_inputs or follow
pending_request when present.

Do not claim the problem is ready_for_calculation.

Do not infer or default missing units.
```

# Step 13 — Remove stale "calculation stage not enabled" wording

Update the `ready_for_calculation` guidance.

The current agent now has a limited calculation capability.

Do not say:

```text
"If the calculation stage were enabled..."
```

Instead use language such as:

```text
The problem definition is complete and ready for the currently
implemented calculation layer. The available calculation can evaluate
feed phase. The remaining Case D design calculations are not yet
implemented in this pipeline.
```

# Step 14 — Add workflow tests

Extend:

```text
tools/chopper/test_binary_distillation_workflow.py
```

Add:

## Test 1 — Missing component-flow units

Complete everything except:

```python
component_flow_units
```

Assert:

```python
result["essential_complete"] is True
result["case_complete"] is True

result["calculation_inputs_complete"] is False

result["missing_calculation_inputs"] == [
    "component_flow_units"
]

result["status"] == "need_calculation_inputs"
```

## Test 2 — Units present

Provide:

```python
component_flow_units="kmol/hr"
```

Assert:

```python
result["calculation_inputs_complete"] is True
result["missing_calculation_inputs"] == []
result["status"] == "ready_for_calculation"
```

## Test 3 — Total-flow form missing units

If total-flow + composition is supported:

```python
total_flow=100
composition={
    "Methanol": 0.5,
    "Water": 0.5
}
```

without:

```python
total_flow_units
```

must produce:

```python
status == "need_calculation_inputs"
```

# Step 15 — Add pending-request tests

Extend:

```text
tools/chopper/test_binary_distillation_pending_truth.py
```

Test:

```python
pending_request == {
    "field": "component_flow_units",
    "request_type": "flow_units",
    ...
}
```

when units are the only missing calculation input.

Add reply-resolution tests:

```text
KMOL/HR
```

→

```python
{"component_flow_units": "kmol/hr"}
```

Test variants:

```text
kmol per hour
kmol/hr
KMOL PER HR
kilomoles per hour
```

All should normalize consistently.

# Step 16 — Add agent test for the exact failure

In:

```text
tools/chopper/test_binary_distillation_workflow_agent_calculation.py
```

reproduce:

```text
Methanol = 50
Water = 50
T = 400 K
P = 101325 Pa
reflux_condition = saturated_liquid
boilup_ratio_VB = 1.2
xD = 0.95
xB = 0.01
use_optimum_feed_plate = True
```

but deliberately omit:

```python
component_flow_units
```

Assert:

```python
assessment["status"] == "need_calculation_inputs"
```

Then user sends:

```text
KMOL/HR
```

Assert the deterministic resolver performs:

```python
update_binary_distillation_problem(
    component_flow_units="kmol/hr"
)
```

Assert state now contains:

```python
component_flow_units == "kmol/hr"
```

and:

```python
status == "ready_for_calculation"
```

# Step 17 — Add end-to-end phase test

After the units WRITE, send:

```text
What is the feed phase?
```

Assert:

```text
calculate_current_binary_distillation_problem({})
```

runs.

Assert:

```python
result["calculation_performed"] is True
result["checks"]["feed_phase"]["valid"] is True
```

The assistant must not ask for units again.

# Step 18 — Add extraction regression test

Use a fake/scripted model for the first user turn:

```text
Each component has a flow rate of 50 kmol per hour.
```

Assert the desired tool call includes both:

```python
component_flows={
    "Methanol": 50,
    "Water": 50,
}
```

and:

```python
component_flow_units="kmol/hr"
```

This tests model guidance.

Keep the deterministic calculation-readiness test as the actual reliability safeguard.

# Step 19 — Run regression suite

Run:

```bash
pytest tools/chopper/test_feed_state.py -v
```

Then:

```bash
pytest tools/chopper/test_binary_distillation_workflow.py -v
```

Then:

```bash
pytest tools/chopper/test_binary_distillation_pending_truth.py -v
```

Then:

```bash
pytest tools/chopper/test_binary_distillation_workflow_agent.py -v
```

Then:

```bash
pytest tools/chopper/test_binary_distillation_workflow_agent_calculation.py -v
```

Then run the entire folder test suite.

All existing tests must continue to pass.

# Step 20 — Replay the original conversation manually

Use:

```bash
python binary_distillation_workflow_agent.py
```

Enter:

```text
Separate methanol and water, each has a flow rate of 50 kmol per hour,
and the feed temperature is 400 K. The pressure is 101325 Pa, and the
reflux can be thought of as a saturated liquid. The boil up ratio is
1.2. xD = 0.95, and xB = 0.01. Optimum feed location can be assumed.
```

Preferred first tool call:

```python
update_binary_distillation_problem({
    "component_names": ["Methanol", "Water"],
    "component_flows": {
        "Methanol": 50,
        "Water": 50
    },
    "component_flow_units": "kmol/hr",
    ...
})
```

Then:

```text
What is the feed phase?
```

Expected:

```text
[calling calculate_current_binary_distillation_problem({})]
```

If the model again drops units on the first turn, expected fallback is:

```text
status = need_calculation_inputs

Assistant:
What units are the component flow rates in?
```

Then:

```text
KMOL/HR
```

Expected:

```text
[calling update_binary_distillation_problem(
    {'component_flow_units': 'kmol/hr'}
)]
```

Then:

```text
What is the feed phase?
```

Expected:

```text
[calling calculate_current_binary_distillation_problem({})]
```

The assistant must not ask for units a second time.

# Step 21 — Update `separation_tool.md`

Document the distinction:

```text
workflow definition complete
```

is not automatically equivalent to:

```text
calculation ready
```

Add:

```python
calculation_inputs_complete
missing_calculation_inputs
```

and:

```text
need_calculation_inputs
```

to the documented workflow schema/statuses.

Document that flow units are calculation-adapter requirements, not newly invented Wankat Table 3-1 fields.

# Definition of done

- [ ] Flow units are stored in authoritative state when explicitly supplied.
- [ ] Explicit flow units are never discarded intentionally by the extraction prompt/tool documentation.
- [ ] Missing flow units prevent `ready_for_calculation`.
- [ ] Wankat `essential_complete` remains conceptually separate from computational readiness.
- [ ] `calculation_inputs_complete` exists.
- [ ] `missing_calculation_inputs` exists.
- [ ] `need_calculation_inputs` exists.
- [ ] `component_flow_units` can generate a deterministic `pending_request`.
- [ ] `"KMOL/HR"` resolves to a real WRITE.
- [ ] Units-only replies do not become READ calls when units are pending.
- [ ] No default unit is introduced.
- [ ] Conversation history is not used as a hidden source of units.
- [ ] BioSTEAM feed construction remains strict.
- [ ] Missing calculation inputs produce machine-readable failures.
- [ ] Feed-phase calculation cannot run before computational readiness.
- [ ] Once units are written, the phase calculation runs successfully.
- [ ] Pending-reply behavior for existing fields still passes.
- [ ] Existing workflow tests still pass.
- [ ] Existing calculation tests still pass.
- [ ] Full chopper regression suite passes.
- [ ] `separation_tool.md` documents the new readiness layer.

# Recommended implementation order

```text
1. Add calculation_inputs_complete / missing_calculation_inputs
2. Add need_calculation_inputs status
3. Add flow-unit pending_request
4. Add deterministic unit normalization
5. Wire units-only replies into WRITE resolution
6. Strengthen tool docstring / SYSTEM_PROMPT unit extraction
7. Keep BioSTEAM adapter strict
8. Add machine-readable calculation failure
9. Update agent status handling
10. Remove stale "calculation layer disabled" wording
11. Add workflow tests
12. Add pending-unit tests
13. Add exact regression test
14. Add end-to-end phase test
15. Run full test suite
16. Replay the manual conversation
17. Update separation_tool.md
```