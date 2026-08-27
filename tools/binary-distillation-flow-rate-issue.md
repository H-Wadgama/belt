# Binary Distillation Feed-Input Handling Refactor

## Objective

Refactor the binary-distillation workflow so that the system **never invents feed flow rates, compositions, or total feed flow when the user has not explicitly supplied enough information to determine them**.

The current workflow has two related failure modes:

1. When a user only names components, Qwen invents component flow rates.
2. When a user provides the flow rate of one component, the system incorrectly interprets that value as the total feed flow and derives a composition from information that is still incomplete.

For example, this is incorrect:

```text
User:
Separate methanol and water.

Tool call:
components = {
    "Methanol": 100,
    "Water": 80
}
```

The user never supplied `100` or `80`.

Likewise, this is incorrect:

```text
Existing components:
Methanol + Water

User:
Methanol feed rate is 50 kmol/hr.

Tool interprets:
total_flow = 50 kmol/hr
composition = ...
```

The user specified the **methanol component flow**, not the total feed flow.

The solution should be architectural rather than prompt-only.

The workflow should explicitly separate:

```text
component identity
component flow rates
total feed flow
feed composition
```

and should only derive quantities when they are mathematically determined from information actually supplied by the user.

---

# 1. Core Design Principle

Use the following rule throughout the implementation:

> **Unknown engineering quantities must remain unknown unless they are explicitly supplied by the user or can be deterministically calculated from explicitly supplied information.**

The LLM must never invent a value merely because the tool schema requires one.

There should therefore be three possible states for engineering information:

```text
1. USER_EXPLICIT
   Directly stated by the user.

2. DERIVED
   Deterministically calculated from USER_EXPLICIT information.

3. UNKNOWN
   Not supplied and cannot yet be calculated.
```

There should be no state corresponding to:

```text
ASSUMED_BY_LLM
```

---

# 2. Separate Component Identity From Component Amount

The current schema should not use a structure such as:

```python
components: dict[str, float]
```

for the workflow-only agent.

That representation combines two different concepts:

```text
Which chemicals are present?

and

How much of each chemical is present?
```

This encourages Qwen to invent numbers when the user only provides component names.

Instead, represent them separately.

For example:

```python
component_names: list[str] | None

component_flows: dict[str, float] | None
component_flow_units: str | None

total_flow: float | None
total_flow_units: str | None

composition: dict[str, float] | None
composition_basis: str | None
```

A possible internal state is:

```python
{
    "component_names": ["Methanol", "Water"],

    "component_flows": {},

    "component_flow_units": None,

    "total_flow": None,
    "total_flow_units": None,

    "composition": {},
    "composition_basis": None
}
```

The important rule is:

> **A component name never implies a component flow.**

---

# 3. Correct Interpretation of Component-Only Requests

If the user says:

```text
Separate methanol and water.
```

Qwen should extract only:

```python
{
    "component_names": ["Methanol", "Water"]
}
```

The resulting state should be:

```python
component_names = ["Methanol", "Water"]

component_flows = {}

total_flow = None

composition = {}
```

The workflow should recognize that:

```text
binary component requirement = COMPLETE

feed flow rate = INCOMPLETE

feed composition = INCOMPLETE
```

The assistant should therefore ask for feed information rather than inventing it.

For example:

```text
The binary pair is Methanol and Water.

I still need enough information to establish the feed flow rate and feed
composition.

I also need:
- column pressure;
- feed thermal condition; and
- reflux thermal condition.
```

---

# 4. Extract Only Information Explicitly Supplied in the Current Turn

Qwen should not reconstruct the entire process state on every message.

Instead, every new user message should generate a **partial state update**.

Architecture:

```text
Current problem state
        +
New user message
        ↓
LLM extracts only newly stated facts
        ↓
Partial update
        ↓
Deterministic merge
        ↓
Deterministic normalization
        ↓
Updated problem state
```

For example:

### Turn 1

```text
User:
Separate methanol and water.
```

Extract:

```python
{
    "component_names": ["Methanol", "Water"]
}
```

State:

```python
component_names = ["Methanol", "Water"]
component_flows = {}
total_flow = None
composition = {}
```

### Turn 2

```text
User:
Methanol feed rate is 50 kmol/hr.
```

Extract only:

```python
{
    "component_flows": {
        "Methanol": 50
    },
    "component_flow_units": "kmol/hr"
}
```

Do NOT generate:

```python
total_flow = 50
```

Do NOT generate a composition.

After merging:

```python
component_names = ["Methanol", "Water"]

component_flows = {
    "Methanol": 50
}

component_flow_units = "kmol/hr"

total_flow = None

composition = {}
```

The feed remains incomplete.

---

# 5. Use Non-Destructive State Merging

Implement a deterministic function conceptually similar to:

```python
apply_user_update(current_state, update)
```

It should follow these rules:

```text
1. Only fields explicitly contained in the update are modified.

2. Missing fields in an update do not erase previously established values.

3. Explicit user values supersede previously derived values when appropriate.

4. Derived quantities are recalculated after relevant explicit inputs change.

5. The LLM does not overwrite the complete engineering state.

6. Unknown values remain unknown.
```

For example:

```python
CURRENT STATE

component_names = ["Methanol", "Water"]
component_flows = {}
```

New update:

```python
component_flows = {"Methanol": 50}
```

Merged result:

```python
component_names = ["Methanol", "Water"]

component_flows = {
    "Methanol": 50
}
```

Nothing else should appear merely because the update occurred.

---

# 6. Add a Deterministic Feed-Normalization Layer

After merging explicit information, run a deterministic normalization function.

Conceptually:

```python
normalize_feed_state(state)
```

Its purpose is to derive values **only when mathematics uniquely determines them**.

The LLM should not perform this normalization.

The architecture should therefore become:

```text
USER
  ↓
LLM extracts explicit facts
  ↓
PARTIAL UPDATE
  ↓
apply_user_update()
  ↓
normalize_feed_state()
  ↓
assess_binary_distillation_problem()
  ↓
structured workflow result
  ↓
LLM explanation
```

This creates three clearly separated responsibilities:

```text
EXTRACTION
What did the user actually say?

NORMALIZATION
What can be mathematically determined from those facts?

WORKFLOW ASSESSMENT
Do we have enough information to proceed?
```

---

# 7. Deterministic Feed-Normalization Rules

Implement the following rules.

## Situation 1 — Only component identities are known

Example:

```text
Methanol
Water
```

State:

```python
component_names = ["Methanol", "Water"]

component_flows = {}

total_flow = None

composition = {}
```

Result:

```text
Total flow: UNKNOWN
Composition: UNKNOWN
```

Do not derive anything.

---

## Situation 2 — Only one component flow is known

Example:

```text
Methanol = 50 kmol/hr
Water = unknown
```

State:

```python
component_flows = {
    "Methanol": 50
}
```

Result:

```text
Total flow: UNKNOWN
Composition: UNKNOWN
Water flow: UNKNOWN
```

The feed is incomplete.

Do not treat 50 kmol/hr as the total feed.

---

## Situation 3 — Both binary component flows are known

Example:

```text
Methanol = 50 kmol/hr
Water = 30 kmol/hr
```

Now the system may deterministically calculate:

```text
Total flow = 80 kmol/hr

zMethanol = 50 / 80 = 0.625

zWater = 30 / 80 = 0.375
```

These values should be marked:

```text
DERIVED
```

rather than:

```text
USER_EXPLICIT
```

---

## Situation 4 — Total flow and complete composition are known

Example:

```text
Total feed = 100 kmol/hr

Methanol = 0.40 mole fraction
Water = 0.60 mole fraction
```

The system may derive:

```text
Methanol flow = 40 kmol/hr
Water flow = 60 kmol/hr
```

Again, these component flows are `DERIVED`.

---

## Situation 5 — Total flow and one component flow are known for an established binary

Example:

```text
Components:
Methanol + Water

Total flow = 100 kmol/hr

Methanol flow = 40 kmol/hr
```

Because the system has already established that there are exactly two components:

```text
Water flow = 100 - 40 = 60 kmol/hr

zMethanol = 0.40
zWater = 0.60
```

These values may be deterministically derived.

---

## Situation 6 — One composition fraction is known for an established binary

Example:

```text
Components:
Methanol + Water

Methanol mole fraction = 0.40
```

Because this is a confirmed binary:

```text
Water mole fraction = 1 - 0.40 = 0.60
```

Therefore:

```text
Feed composition = COMPLETE
Feed total flow = UNKNOWN
```

Do not invent the total flow.

---

# 8. Determine Feed Completeness From the State

The Wankat workflow requires:

```text
feed composition
feed flow rate
```

However, these should be treated as **information states**, not necessarily literal fields the user must type.

Add something conceptually similar to:

```python
feed_flow_complete: bool
feed_composition_complete: bool
```

Calculate these deterministically.

For feed flow:

```python
if total_flow is known:
    feed_flow_complete = True

elif flows are known for all binary components:
    derive total_flow
    feed_flow_complete = True

else:
    feed_flow_complete = False
```

For feed composition:

```python
if complete composition is explicitly known:
    feed_composition_complete = True

elif flows are known for both binary components:
    derive composition
    feed_composition_complete = True

elif exactly one composition fraction is known for a confirmed binary:
    derive the complementary fraction
    feed_composition_complete = True

else:
    feed_composition_complete = False
```

---

# 9. Improve Missing-Information Responses

The workflow checker should distinguish between:

```text
No feed quantitative information exists
```

and:

```text
Some feed quantitative information exists, but it is insufficient.
```

For example:

```text
User:
Separate methanol and water.

User:
Methanol feed rate is 50 kmol/hr.
```

The assistant should respond approximately:

```text
I know that the methanol feed rate is 50 kmol/hr, but the overall
binary feed is not yet fully defined.

I still need enough information to determine the total feed flow and
composition. For example, you can provide the water flow rate, or
provide the total feed flow together with sufficient composition
information.

I also still need:
- column pressure;
- feed thermal condition; and
- reflux thermal condition.
```

It should NOT respond as though:

```text
total feed = 50 kmol/hr
```

has already been established.

---

# 10. Preserve Provenance of Quantitative Information

Internally, track where each engineering quantity came from.

For example:

```python
{
    "component_flows": {
        "Methanol": {
            "value": 50,
            "units": "kmol/hr",
            "source": "user_explicit"
        }
    }
}
```

A derived total flow might be:

```python
{
    "total_flow": {
        "value": 80,
        "units": "kmol/hr",
        "source": "derived",
        "derived_from": [
            "component_flows.Methanol",
            "component_flows.Water"
        ]
    }
}
```

Recommended source states:

```text
user_explicit
derived
unknown
```

This does not necessarily need to be shown to the user.

Its purpose is to make the workflow auditable and easier to debug.

---

# 11. Add Consistency Validation

When redundant information is supplied, use it to check consistency.

Do not silently overwrite conflicting information.

Example:

```text
Methanol = 50 kmol/hr
Water = 50 kmol/hr
Total feed = 120 kmol/hr
```

The component flows imply:

```text
Total feed = 100 kmol/hr
```

but the user explicitly supplied:

```text
120 kmol/hr
```

Return something such as:

```python
{
    "status": "inconsistent_input",
    "conflicts": [
        "Component flows sum to 100 kmol/hr, but total flow was specified as 120 kmol/hr."
    ]
}
```

Likewise:

```text
Methanol = 50 kmol/hr
Water = 50 kmol/hr
Methanol mole fraction = 0.70
```

should be flagged because the component flows imply:

```text
Methanol mole fraction = 0.50
```

The system should ask the user to resolve the contradiction.

The LLM should not decide which value to trust.

---

# 12. Component-Scope Changes Across Conversation Turns

The state manager should distinguish between:

```text
adding information to the existing separation
```

and:

```text
replacing the separation problem
```

Example:

```text
User:
I want to separate water, methanol, and butanol.
```

Result:

```text
unsupported_multicomponent
```

Then:

```text
User:
I want to separate water.
```

This wording should be interpreted as a new/replacement component definition:

```python
component_names = ["Water"]
component_flows = {}
composition = {}
total_flow = None
```

Then:

```text
User:
Methanol.
```

If interpreted as providing the requested second component:

```python
component_names = ["Water", "Methanol"]
```

But critically:

```python
component_flows = {}
composition = {}
total_flow = None
```

No previous invented or stale component flows should survive.

---

# 13. Updated Tool Schema

The workflow-only tool should expose separate optional fields.

Conceptually:

```python
def assess_binary_distillation(
    component_names: list[str] | None = None,

    component_flows: dict[str, float] | None = None,
    component_flow_units: str | None = None,

    total_flow: float | None = None,
    total_flow_units: str | None = None,

    composition: dict[str, float] | None = None,
    composition_basis: str | None = None,

    pressure_Pa: float | None = None,

    feed_temperature_K: float | None = None,
    feed_enthalpy_kJ_per_hr: float | None = None,
    feed_quality: float | None = None,

    reflux_temperature_K: float | None = None,
    reflux_enthalpy_kJ_per_hr: float | None = None,
    reflux_condition: str | None = None,

    ...
) -> dict:
```

The exact implementation may differ, but the key requirement is:

```text
component identity must not require a numeric component flow.
```

---

# 14. Qwen System-Prompt Rules

After fixing the schema and deterministic state logic, update the workflow agent's prompt.

Include rules equivalent to:

```text
Component identity and component amount are separate concepts.

Never invent a component flow merely because a component was named.

If the user names components without quantities, populate only
component_names.

Extract only information explicitly provided in the current user
message.

Do not reconstruct missing feed information from previous guesses.

If the user specifies a component-specific flow, store it under
component_flows.

Never interpret a component-specific flow as total_flow unless the user
explicitly says it is the total feed flow.

Do not calculate feed composition yourself.

The deterministic normalization layer will derive total flow,
composition, or complementary binary quantities when sufficient
information exists.

Unknown values must remain unknown.

Never invent values to satisfy the tool schema.
```

The prompt is a behavioral safeguard.

The **schema and deterministic normalization logic remain the primary safeguards**.

---

# 15. Correct Behavior for Problem Example 1

Conversation:

```text
User:
I want to separate water and methanol and butanol.
```

Tool update:

```python
{
    "component_names": [
        "Water",
        "Methanol",
        "Butanol"
    ]
}
```

Result:

```text
The current system supports binary distillation only.
Please specify exactly two components.
```

Then:

```text
User:
I want to separate water.
```

State becomes:

```python
component_names = ["Water"]

component_flows = {}

total_flow = None

composition = {}
```

Result:

```text
Binary distillation requires two components.
Please specify the second component.
```

Then:

```text
User:
Methanol.
```

State becomes:

```python
component_names = ["Water", "Methanol"]

component_flows = {}

total_flow = None

composition = {}
```

The assistant should now say that the binary pair is established but feed flow and composition are still missing.

At no point should numbers such as:

```text
Water = 80
Methanol = 100
```

appear unless supplied by the user.

---

# 16. Correct Behavior for Problem Example 2

Conversation:

```text
User:
Separate methanol and water.
```

State:

```python
component_names = ["Methanol", "Water"]

component_flows = {}

total_flow = None

composition = {}
```

Then:

```text
User:
Methanol feed rate is 50 kmol/hr.
```

Partial update:

```python
{
    "component_flows": {
        "Methanol": 50
    },
    "component_flow_units": "kmol/hr"
}
```

Merged state:

```python
component_names = ["Methanol", "Water"]

component_flows = {
    "Methanol": 50
}

total_flow = None

composition = {}
```

The assistant should respond approximately:

```text
I know the methanol feed rate is 50 kmol/hr, but the overall feed is
not yet fully defined.

I still need enough information to determine the total feed flow and
composition—for example, the water flow rate or the total feed flow
together with sufficient composition information.

I also still need:
- column pressure;
- feed thermal condition;
- reflux thermal condition.
```

The system must NOT transform this into:

```text
total_flow = 50 kmol/hr
```

and must NOT derive a composition.

---

# 17. New Acceptance Tests

Add automated tests specifically targeting feed-state handling.

## Test 1 — Component names only

Input:

```text
Separate methanol and water.
```

Expected:

```python
component_names == ["Methanol", "Water"]
component_flows == {}
total_flow is None
composition == {}
```

No numerical feed values may be generated.

---

## Test 2 — One component flow

Existing pair:

```text
Methanol + Water
```

Input:

```text
Methanol feed is 50 kmol/hr.
```

Expected:

```python
component_flows == {"Methanol": 50}
total_flow is None
composition == {}
```

---

## Test 3 — Both component flows

Input sequence:

```text
Methanol = 50 kmol/hr
Water = 30 kmol/hr
```

Expected derived values:

```python
total_flow == 80

composition == {
    "Methanol": 0.625,
    "Water": 0.375
}
```

Mark total flow and composition as derived.

---

## Test 4 — Total flow plus one component flow

Confirmed binary:

```text
Methanol + Water
```

Inputs:

```text
Total feed = 100 kmol/hr
Methanol = 40 kmol/hr
```

Expected:

```text
Water = 60 kmol/hr
Methanol fraction = 0.40
Water fraction = 0.60
```

---

## Test 5 — One binary mole fraction

Confirmed binary:

```text
Methanol + Water
```

Input:

```text
Feed is 40 mol% methanol.
```

Expected:

```text
Methanol mole fraction = 0.40
Water mole fraction = 0.60
```

But:

```python
total_flow is None
```

---

## Test 6 — Component flow without established binary

Input:

```text
Methanol feed is 50 kmol/hr.
```

Expected:

Do not infer total flow.

Do not infer composition.

Ask for the second component and remaining feed definition.

---

## Test 7 — Component names never create flows

Assert:

```text
Naming a component must never populate component_flows.
```

---

## Test 8 — Component flow never automatically becomes total flow

Assert:

```text
component_flows["Methanol"] = 50
```

does not produce:

```text
total_flow = 50
```

unless additional information mathematically establishes that result.

---

## Test 9 — Provenance

Explicit value:

```text
Methanol = 50 kmol/hr
```

must be marked:

```text
user_explicit
```

Derived total flow from two component flows must be marked:

```text
derived
```

---

## Test 10 — Conflicting total flow

Input:

```text
Methanol = 50 kmol/hr
Water = 50 kmol/hr
Total = 120 kmol/hr
```

Expected:

```text
status = inconsistent_input
```

---

## Test 11 — Conflicting composition

Input:

```text
Methanol = 50 kmol/hr
Water = 50 kmol/hr
Methanol mole fraction = 0.70
```

Expected:

```text
status = inconsistent_input
```

---

## Test 12 — Replacement of invalid multicomponent problem

Conversation:

```text
Separate water, methanol, and butanol.
```

followed by:

```text
I want to separate water.
```

Expected:

The old three-component definition should not retain invented/stale feed values.

State should become:

```python
component_names = ["Water"]
component_flows = {}
total_flow = None
composition = {}
```

---

# 18. Relationship to the Existing Binary-Distillation Workflow

Do not replace the existing Wankat workflow.

Insert this feed-state layer **before it**.

The overall architecture should now be:

```text
Natural-language request
          ↓
Explicit-fact extraction
          ↓
Partial state update
          ↓
Deterministic state merge
          ↓
Deterministic feed normalization
          ↓
Binary-scope gate
          ↓
Five essential Wankat inputs complete?
          ↓
Case A/B/C/D identification
          ↓
Case-specific inputs complete?
          ↓
Optimum feed plate confirmed?
          ↓
READY FOR CALCULATION
          ↓
Report what would be calculated
          ↓
STOP
```

The calculation layer remains disabled in this workflow-only agent.

---

# 19. Design Philosophy

The important distinction is:

```text
LLM extraction:
"What did the user say?"

Deterministic normalization:
"What follows mathematically from what the user said?"

Workflow checker:
"Is the engineering problem sufficiently defined?"

Future deterministic calculation:
"What is the engineering result?"
```

Qwen should not be responsible for answering all four questions.

The LLM should primarily handle the first and communicate the results of the others.

This follows the broader architecture of the project:

```text
LLM
= interpretation + orchestration + explanation

Deterministic Python
= state management + normalization + workflow logic

BioSTEAM
= future engineering calculations

Validation
= consistency and physical checks
```

---

# 20. Definition of Done

This refactor is complete when all of the following are true:

- Component names can exist without component flows.
- Qwen never invents numerical flows merely because components were named.
- A component-specific flow is never automatically interpreted as total feed flow.
- Partial quantitative information remains partial.
- State persists correctly across conversation turns.
- New messages update rather than reconstruct the entire problem state.
- Total flow is derived only when mathematically determined.
- Composition is derived only when mathematically determined.
- Complementary binary composition can be derived when valid.
- Derived values are distinguishable from user-supplied values.
- Contradictory redundant information is detected.
- Unknown quantities remain explicitly unknown.
- The feed-normalization layer feeds into the existing binary-scope and Wankat Case A–D workflow.
- The workflow-only agent still performs no BioSTEAM calculations or optimization.
- All existing binary-distillation workflow tests continue to pass.
- All new feed-state acceptance tests pass.

The core rule to preserve throughout the implementation is:

> **Never invent engineering information to complete the problem. Extract what the user supplied, deterministically derive only what must follow from it, and leave everything else unknown until the user provides sufficient information.**