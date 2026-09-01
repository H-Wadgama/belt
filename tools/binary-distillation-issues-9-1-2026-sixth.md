# Focused Fix Plan — Multi-Entity Keyed Field Extraction for `component_flows`

## Objective

Fix the specific live failure where Qwen cannot reliably associate multiple component flow values with their component names when they appear in the same user turn.

Observed failing examples:

```text
Separate water and ethanol at 355 K and 101325 Pa pressure.
The feed composition is 50 kmol/hr ethanol and 50 kmol/hr water.
```

and:

```text
The ethanol flow is 50 kmol/hr and the water flow is 50 kmol/hr.
```

Current observed structured interpretation:

```python
[
    {
        "field": "component_flows",
        "entity": None,
        "value": 50,
        "units": "kmol/hr",
    },
    {
        "field": "component_flows",
        "entity": None,
        "value": 50,
        "units": "kmol/hr",
    },
]
```

The validator correctly rejects these as:

```text
missing_entity
```

The goal of this task is to make the structured representation easier for Qwen to express reliably while preserving the current deterministic validation, atomic WRITE behavior, transaction execution, diagnostics, and state architecture.

Do not solve this by adding sentence regexes, guessing entities in Python, splitting one user turn into multiple hidden LLM calls, weakening validation, or changing feed-screening requirements.

---

# Architectural rule

Preserve this division:

```text
Qwen:
understands that several component/value pairs were supplied

Python:
validates each component/value pair
compiles them into the canonical WRITE
owns authoritative state
```

Python must never invent a component identity that was not explicitly represented in the structured interpretation.

---

# Target representation

Currently keyed fields are represented as repeated scalar entries:

```python
{
    "field": "component_flows",
    "entity": "Ethanol",
    "value": 50,
    "units": "kmol/hr",
}
```

This remains valid for a single keyed value.

Add a collection representation for multiple entries belonging to the same keyed field:

```python
{
    "field": "component_flows",
    "items": [
        {
            "entity": "Ethanol",
            "value": 50,
            "units": "kmol/hr",
        },
        {
            "entity": "Water",
            "value": 50,
            "units": "kmol/hr",
        },
    ],
}
```

The structured intent schema should allow either:

```text
single keyed update
OR
multi-item keyed update
```

Do not require Qwen to repeat the same `field` name once per component when several values belong to the same keyed field.

---

# Part 1 — Inspect current keyed-field schema

Read the current implementations of:

```text
tools/chopper/turn_intent.py
tools/chopper/turn_transaction.py
tools/chopper/problem_field_registry.py
tools/chopper/binary_distillation_workflow_agent.py
```

Also read the relevant tests and the diagnostics code.

Document:

1. current `TurnIntent` update schema;
2. how `component_flows` is identified as keyed;
3. where `missing_entity` is produced;
4. how multiple scalar keyed updates are merged into:
   ```python
   component_flows={...}
   ```
5. how units are compiled into `component_flow_units`;
6. how diagnostic records serialize updates;
7. how schema-constrained Qwen output is generated from the JSON schema.

Do not edit behavior until this path is understood.

---

# Part 2 — Extend the TurnIntent schema

Extend update entries so they support two mutually exclusive shapes.

## Scalar update

Existing form:

```python
{
    "field": str,
    "entity": str | None,
    "subject": dict | None,
    "value": object,
    "units": str | None,
    "basis": str | None,
}
```

## Collection update

New form:

```python
{
    "field": str,
    "subject": dict | None,
    "items": [
        {
            "entity": str,
            "value": object,
            "units": str | None,
            "basis": str | None,
        }
    ],
}
```

Rules:

- `items` is only valid for a registry field marked `keyed=True`;
- `items` must contain at least one entry;
- each item must contain an explicit `entity`;
- top-level `entity` and `value` must not coexist with `items`;
- collection entries must not silently inherit an entity;
- if top-level units are supported as a convenience, define deterministic precedence and test it;
- preferably keep units on each item initially unless the current schema strongly benefits from top-level shared units.

Preserve unknown field names so Python can reject them normally.

---

# Part 3 — Update the model-facing schema description

Update the structured-output JSON schema and prompt/catalog metadata shown to Qwen.

For keyed fields, explicitly explain:

```text
For one component value:
use entity + value.

For multiple component values belonging to the same keyed field:
use one update with items=[...], where every item contains its component entity and value.
```

Add an example specifically for `component_flows`:

```python
{
    "field": "component_flows",
    "items": [
        {
            "entity": "Ethanol",
            "value": 50,
            "units": "kmol/hr"
        },
        {
            "entity": "Water",
            "value": 50,
            "units": "kmol/hr"
        }
    ]
}
```

Also include a single-entry example:

```python
{
    "field": "component_flows",
    "entity": "Ethanol",
    "value": 50,
    "units": "kmol/hr"
}
```

The model should be told:

```text
Do not emit multiple component_flows scalar updates with entity=null.
When several named components and values occur in the same turn, preserve each name/value association inside items.
```

Do not add phrase-specific instructions for ethanol/water beyond using them as an example.

---

# Part 4 — Normalize both representations into one internal form

Add a deterministic normalization step before semantic validation.

Conceptually:

```python
normalize_turn_intent_updates(...)
```

Examples.

Input:

```python
{
    "field": "component_flows",
    "entity": "Ethanol",
    "value": 50,
    "units": "kmol/hr",
}
```

normalizes internally to:

```python
[
    {
        "field": "component_flows",
        "entity": "Ethanol",
        "value": 50,
        "units": "kmol/hr",
    }
]
```

Input:

```python
{
    "field": "component_flows",
    "items": [
        {"entity": "Ethanol", "value": 50, "units": "kmol/hr"},
        {"entity": "Water", "value": 50, "units": "kmol/hr"},
    ],
}
```

normalizes to:

```python
[
    {
        "field": "component_flows",
        "entity": "Ethanol",
        "value": 50,
        "units": "kmol/hr",
    },
    {
        "field": "component_flows",
        "entity": "Water",
        "value": 50,
        "units": "kmol/hr",
    },
]
```

After normalization, reuse the existing validator and transaction compiler wherever possible.

Do not create a second validation path for collections.

---

# Part 5 — Preserve atomic validation

Keep the existing rule:

```text
all updates validate
before any state mutation occurs
```

For example:

```python
{
    "field": "component_flows",
    "items": [
        {"entity": "Ethanol", "value": 50},
        {"entity": "Water", "value": "banana"},
    ],
}
```

must cause:

```text
zero WRITE
```

not:

```text
save Ethanol
reject Water
```

Likewise, conflicting duplicate entities must reject deterministically.

Example:

```python
items=[
    {"entity": "Ethanol", "value": 50},
    {"entity": "Ethanol", "value": 60},
]
```

should produce a conflict and no mutation.

Identical duplicates may collapse if that matches current validator semantics.

---

# Part 6 — Compile collection updates into the existing WRITE path

Do not change the canonical mutation function.

The final validated transaction should still call:

```python
update_binary_distillation_problem(...)
```

exactly once.

For:

```python
{
    "field": "component_flows",
    "items": [
        {"entity": "Ethanol", "value": 50, "units": "kmol/hr"},
        {"entity": "Water", "value": 50, "units": "kmol/hr"},
    ],
}
```

compile to:

```python
{
    "component_flows": {
        "Ethanol": 50,
        "Water": 50,
    },
    "component_flow_units": "kmol/hr",
}
```

For the full user statement:

```text
Separate water and ethanol at 355 K and 101325 Pa pressure.
The feed flow rates are 50 kmol/hr ethanol and 50 kmol/hr water.
```

the final WRITE kwargs must be:

```python
{
    "component_flows": {
        "Ethanol": 50,
        "Water": 50,
    },
    "component_flow_units": "kmol/hr",
    "feed_temperature_K": 355,
    "pressure_Pa": 101325,
}
```

The existing updater should continue deriving any dependent values such as total flow and composition according to current workflow behavior.

---

# Part 7 — Component identity behavior

When explicit keyed `component_flows` entities are present:

```python
"Ethanol"
"Water"
```

they may establish the component identities for the current problem if that is already compatible with the canonical updater semantics.

Do not require a separate prior turn:

```text
The components are ethanol and water.
```

when the current turn already explicitly associates flow values with those names.

Do not invent synonyms or inferred chemical identities.

Use only the entities supplied by the model interpretation after safe normalization such as case-insensitive exact matching.

---

# Part 8 — Keep diagnostics compatible

Update turn diagnostics so collection-form model output is visible clearly.

The diagnostic trace should show:

```text
raw Qwen structured output
→ collection update with items
→ normalized keyed entries
→ validated transaction
→ final WRITE kwargs
→ state diff
```

Do not hide the collection form by only logging the normalized result.

Retain both:

1. model-proposed representation;
2. normalized internal representation.

Existing JSON serialization and debug CLI behavior must continue to work.

---

# Part 9 — Do not use semantic retry as the main solution

Keep the existing semantic retry feature unchanged unless schema changes require compatibility updates.

Do not enable it by default solely for this fix.

The live diagnostic evidence already showed that retrying the same representation did not correct the missing-entity problem reliably.

The primary fix is the new keyed collection representation.

---

# Part 10 — Do not split user messages into hidden sub-turns

Do not implement:

```text
one multi-component sentence
→ several separate Qwen calls
```

For example, do not split:

```text
Ethanol is 50 and water is 50 kmol/hr
```

into:

```text
Ethanol is 50
Water is 50
```

and interpret them independently.

One user message must remain one semantic turn and one transaction.

---

# Part 11 — Required unit tests

Add focused tests covering both structured representations.

## Single keyed value still works

Input intent:

```python
{
    "updates": [
        {
            "field": "component_flows",
            "entity": "Ethanol",
            "value": 50,
            "units": "kmol/hr",
        }
    ]
}
```

Expected:

```python
component_flows={"Ethanol": 50}
component_flow_units="kmol/hr"
```

## Multi-item keyed update works

Input intent:

```python
{
    "updates": [
        {
            "field": "component_flows",
            "items": [
                {
                    "entity": "Ethanol",
                    "value": 50,
                    "units": "kmol/hr",
                },
                {
                    "entity": "Water",
                    "value": 50,
                    "units": "kmol/hr",
                },
            ],
        }
    ]
}
```

Expected:

```python
component_flows={
    "Ethanol": 50,
    "Water": 50,
}
component_flow_units="kmol/hr"
```

## Invalid keyed item rejects atomically

One valid item plus one item missing `entity`:

```text
zero WRITE
```

## Conflicting duplicate entity

```python
Ethanol=50
Ethanol=60
```

Expected deterministic conflict and zero WRITE.

## Mixed units

If current workflow requires one common component-flow unit, test:

```python
Ethanol=50 kmol/hr
Water=100 kg/hr
```

and preserve current unit-validation semantics.

Do not silently combine incompatible units.

## Collection on non-keyed field

Example:

```python
{
    "field": "pressure_Pa",
    "items": [...]
}
```

must reject structurally or semantically.

---

# Part 12 — Required scripted-model tests

Using the existing fake/scripted Qwen client, test that a model response containing:

```python
{
    "updates": [
        {
            "field": "component_flows",
            "items": [
                {"entity": "Ethanol", "value": 50, "units": "kmol/hr"},
                {"entity": "Water", "value": 50, "units": "kmol/hr"},
            ],
        },
        {
            "field": "feed_temperature_K",
            "value": 355,
        },
        {
            "field": "pressure_Pa",
            "value": 101325,
        },
    ],
    "queries": [],
    "action": None,
}
```

produces exactly one WRITE:

```python
update_binary_distillation_problem(
    component_flows={
        "Ethanol": 50,
        "Water": 50,
    },
    component_flow_units="kmol/hr",
    feed_temperature_K=355,
    pressure_Pa=101325,
)
```

and no partial or duplicate writes.

---

# Part 13 — Required live-Qwen acceptance tests

Run these against the actual local `qwen3:8b` model through the real CLI entry point.

Test each from a fresh session.

### Case 1

```text
The ethanol flow is 50 kmol/hr.
```

Must still work.

### Case 2

```text
The ethanol flow is 50 kmol/hr and the water flow is 50 kmol/hr.
```

Required final state:

```python
component_flows == {
    "Ethanol": 50,
    "Water": 50,
}
```

### Case 3

```text
The flow rates of ethanol and water are both 50 kmol/hr.
```

Required same state.

### Case 4

```text
The flow rate is 50 kmol/hr each for water and ethanol.
```

Required same state.

### Case 5

```text
Separate water and ethanol at 355 K and 101325 Pa pressure.
The feed flow rates are 50 kmol/hr ethanol and 50 kmol/hr water.
```

Required state:

```python
component_flows == {
    "Ethanol": 50,
    "Water": 50,
}

component_flow_units == "kmol/hr"

feed_temperature_K == 355

pressure_Pa == 101325

total_flow == 100
```

Any current feed-phase requirement such as reflux condition should remain unchanged.

Do not modify feed-screen readiness logic as part of this task.

---

# Part 14 — Evaluate whether Qwen actually uses the new representation

Run with diagnostics enabled.

For each multi-entity acceptance prompt, record:

```text
raw Qwen structured output
parsed TurnIntent
normalized updates
validated TurnTransaction
WRITE kwargs
state diff
final response
```

The primary success criterion is that Qwen now emits:

```python
{
    "field": "component_flows",
    "items": [...]
}
```

with explicit entities.

If Qwen continues emitting two scalar updates with `entity=null`, do not declare success merely because unit tests pass.

At that point, inspect whether:

1. the structured-output JSON schema actually exposes `items` clearly;
2. prompt examples are visible in the model context;
3. schema wording makes scalar-vs-collection behavior unambiguous;
4. the model is constrained by a schema shape that still biases toward scalar entries.

Adjust only the schema/prompt representation required to make collection extraction reliable.

Do not add deterministic entity guessing.

---

# Completion criteria

This task is complete only when:

1. single keyed updates still work;
2. multi-item keyed updates are valid TurnIntent representations;
3. collection updates normalize into the existing internal keyed form;
4. all keyed values validate before mutation;
5. one atomic WRITE remains the only mutation;
6. diagnostics retain both raw collection form and normalized form;
7. no sentence aliases are added;
8. no hidden message splitting is added;
9. semantic retry remains optional;
10. the full existing test suite passes;
11. the live local Qwen successfully handles the required multi-entity prompts through the real CLI; and
12. the original failing prompt stores both component flow rates in one turn.

---

# Out of scope

Do not modify:

- feed-phase screening requirements;
- reflux-condition requirements;
- BioSTEAM calculations;
- Design Option A-D logic;
- pending-request logic;
- calculation-result grounding;
- multicomponent calculation support;
- multicolumn execution;
- generic workflow orchestration;
- broad alias systems;
- native Ollama engineering tool calling.

This task is only:

```text
make multi-entity keyed fields representable and reliably extractable
without weakening deterministic validation.
```

---

# Final report

Report:

1. files changed;
2. previous keyed-field schema;
3. new scalar + collection schema;
4. normalization behavior;
5. validation behavior;
6. exact WRITE compilation;
7. diagnostic changes;
8. new focused tests;
9. full test count;
10. raw Qwen output for every live acceptance case;
11. whether Qwen reliably selected `items`;
12. final canonical state for the original failing prompt; and
13. any remaining limitations.

Do not begin any other workflow round until this specific live-Qwen failure is fixed.