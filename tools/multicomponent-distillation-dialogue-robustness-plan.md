# Multicomponent Feed-Phase Dialogue Robustness Plan

## Goal

Make the interactive multicomponent feed-phase agent reliably collect,
correct, and report feed information across multiple turns without relying on
scattered phrase-specific rules.

The finished agent must:

- interpret a short reply in the context of the question it just asked;
- prevent one number from grounding unrelated physical fields;
- preserve valid state when a proposed update is rejected;
- distinguish component identity changes from ordinary component mentions;
- retain units and provenance across partial turns;
- answer read-only questions about information already stored; and
- continue to calculate only feed phase and molar vapor/liquid fractions once
  the required feed information is complete.

This plan supersedes the dialogue, grounding, and state-mutation portions of
`multicomponent-distillation-feed-phase-plan.md`. It does not replace that
plan's feed-basis, unit-conversion, or BioSTEAM calculation requirements.

## Scope Boundaries

This change is limited to natural-language intake, conversational state,
grounding, validation/commit behavior, read-only state queries, diagnostics,
and their tests.

Do not add:

- separation routing or key-component selection;
- column design, recoveries, or reflux calculations;
- trial/sweep/economic/optimization modes;
- enthalpy or feed-quality input;
- a second model call to write the response; or
- ad hoc branches for exact phrases such as `it is 1`.

The deterministic feed-phase calculation remains the existing `T/P` BioSTEAM
calculation. Completed calculation output remains limited to phase, molar
vapor fraction, and molar liquid fraction.

## Architectural Principle

Use the model only to propose the meaning of the current message. Python owns
the dialogue state, field binding, grounding, validation, state commit,
derived calculations, pending question, state-query answer, and final phase
formatting.

Every turn follows one controller pipeline:

```text
current message + active request + state summary
                    |
                    v
          one structured interpretation
                    |
                    v
       pending-field binding and grounding
                    |
                    v
          validated candidate transition
                    |
          +---------+----------+
          |                    |
     read-only query       commit accepted
          |                logical groups
          +---------+----------+
                    |
                    v
       deterministic reply / next request
```

Do not allow a model proposal to write directly to persistent feed state.

## 1. Add Explicit Dialogue Session State

Introduce one session object owned by the REPL or caller. It should contain:

```python
{
    "feed_state": {...},
    "pending_request": None | {...},
    "provisional_value": None | {...},
    "confirmation": None | {...},
    "turn_number": 0,
}
```

The session must be passed into `process_turn`; it must not be reconstructed
from model history. Prefer a small dataclass or one documented dictionary
schema. It must be serializable for debugging.

`pending_request` must identify at least:

```python
{
    "field": "pressure",
    "kind": "value",  # value, unit, basis, identity, confirmation
    "allowed_units": ["Pa", "kPa", "bar", "atm"],
    "related_value": None,
    "asked_on_turn": 4,
}
```

The deterministic state assessor still selects the next missing engineering
field. The controller stores that selection as the active request so the next
turn can be interpreted as an answer to a specific question.

Remove persistent module-global state from the normal agent path. If temporary
compatibility wrappers are needed for existing direct-tool tests, isolate and
deprecate them; two independent sessions must never share feed facts.

## 2. Add a Structured Conversational-Intent Contract

Extend the model's structured-output schema with:

```python
intent = one of:
    provide_information
    answer_pending_request
    query_current_state
    correct_information
    confirm
    deny
    reset
    unclear

target_field = nullable registered field name

component_identity_action = one of:
    none
    initialize
    add
    remove
    replace
```

Retain the existing feed-fact fields, but add evidence for each non-null fact.
Scalar evidence may be a string. Component mapping evidence must be keyed by
component name.

Example:

```json
{
  "intent": "answer_pending_request",
  "target_field": "pressure",
  "component_identity_action": "none",
  "pressure": 1,
  "pressure_units": null,
  "evidence": {
    "pressure": "1"
  }
}
```

The schema should remain compact and fully constrained for `qwen3:8b`.
Continue to allow only one structured extraction call, plus the existing
single retry for malformed structured output.

## 3. Supply Context as Data, Not Conversation to Copy

Construct each extraction request from three explicitly labelled sections:

```text
ESTABLISHED STATE SUMMARY
...

ACTIVE REQUEST
...

CURRENT USER MESSAGE
...
```

The active request and state summary are controller-owned data. The current
message is the only source of new explicit facts. Do not send the entire raw
conversation as an undifferentiated extraction history.

Retain only narrowly required recent context for references such as `the
second component` or `yes`. Never ask the model to restate the established
feed specification.

## 4. Bind Short Replies to the Active Request

Implement one generic pending-field binder driven by the active request and a
field registry.

Rules:

1. If the current message explicitly names a physical field, use that field.
2. Otherwise, if the message is a compatible short answer and an active
   request exists, bind it only to the active request.
3. Do not offer that number or unit as evidence for any other field.
4. If a short answer is incompatible with the requested type, do not mutate
   state; ask for clarification.
5. If the message clearly supplies a different field, accept that field and
   leave the original request pending.

Required behavior:

```text
Assistant: What is the feed pressure?
User: 1
Assistant: What units is the pressure value 1 in? (Pa, kPa, bar, atm)
User: atm
```

This commits `pressure = 1 atm`. The number `1` cannot become a composition
fraction, component flow, total flow, or temperature.

Use confirmation only when there is genuine competing evidence:

```text
Assistant: Did you mean that the feed pressure is 1? If so, what units?
```

Do not add unnecessary confirmation to an otherwise unambiguous answer to the
immediately preceding question.

## 5. Replace Field-Agnostic Grounding with Role-Aware Grounding

Remove `_number_grounded(value, message)` as a sufficient acceptance test for
engineering facts.

Ground each proposed fact using all applicable context:

- intended field;
- active pending field;
- literal evidence span;
- component associated with the value, when applicable;
- unit or composition-basis wording;
- explicit field wording in the current message; and
- whether the fact is a correction.

For a normal component statement such as `water is 20 wt%`, the evidence must
associate `water`, `20`, and mass composition. A matching number elsewhere in
the message is insufficient.

For an answer such as `1`, the active request supplies the role `pressure`.
Only that field may use the token as evidence.

Each literal numeric token should be consumed by at most one incompatible
fact unless the message explicitly states that the same value applies to
several fields.

Continue to allow deterministic transforms such as `20% -> 0.20`, but only
after the token has been associated with the correct component and
composition role.

## 6. Protect Component Identity

Treat feed component identity as a separate state operation, not as a side
effect of mentioning a component in a flow or composition statement.

Apply these rules:

- `initialize` is permitted when the session has no established components.
- Restating the same complete component set is idempotent.
- A subset of established components is never a replacement.
- A component flow or fraction updates that component's quantity; it does not
  replace the identity list.
- `add` requires clear addition semantics or a response to a pending request
  for another component.
- `remove` or `replace` requires explicit user intent.
- Switching to an unrelated feed requires `reset` or an explicit replacement
  operation.
- A newly mentioned, unknown component in an ambiguous context triggers one
  clarification rather than silently changing identity.

Required regression:

```text
User: separate methanol, ethanol, water
User: methanol = 30 kg/hr
```

The component list remains methanol, ethanol, and water. Only methanol's
partial flow information is added.

Canonicalize component names case-insensitively against the chemical registry
while retaining a display name. Do not silently correct an unrecognized or
ambiguous chemical name.

## 7. Store Measurements with Their Own Units and Provenance

Replace a single mutable `component_flow_units` interpretation with
per-component explicit measurements:

```python
"component_flows": {
    "Methanol": {
        "value": 30,
        "unit": "kg/hr",
        "provenance": "user_explicit",
        "source_turn": 2,
        "evidence": "methanol = 30 kg/hr"
    }
}
```

The final Mode A requirement remains one shared component-flow unit. Derive a
shared unit only when the stored component measurements agree. Do not
reinterpret previously stored numbers when a later turn uses a different
unit.

For a value whose unit is not yet given, store an incomplete measurement:

```python
{
    "value": 1,
    "unit": null,
    "status": "awaiting_unit"
}
```

A later unit-only answer attaches only to that pending measurement.

Use equivalent provenance for total flow, pressure, temperature, and
composition. Preserve the existing distinction between explicit composition
basis and `inferred_from_total_flow_units`.

If partial component flows acquire conflicting units across turns, retain the
last valid state and ask the user to restate all component flows in one common
supported unit. A complete common-unit restatement may replace the quantity
group atomically.

## 8. Make Updates Transactional

Split update processing into pure candidate construction and explicit commit:

```python
candidate = build_candidate(current_state, grounded_update)
assessment = assess_candidate(candidate)

if assessment.acceptable:
    committed_state = candidate
else:
    committed_state = current_state
```

Incomplete but internally consistent information is acceptable and may be
committed. Conflicting or invalid information must not alter authoritative
state.

Validate logical groups independently before one final state assignment:

- component identity;
- feed quantity/composition;
- pressure;
- temperature.

This allows an independently valid pressure statement to survive when an
unrelated proposed quantity is rejected, while preventing a partially applied
quantity group from becoming inconsistent.

On every accepted correction:

- overwrite only the explicitly corrected fact;
- clear affected derived values;
- recompute derivations from explicit facts; and
- retain provenance for the new value.

Return a transition result containing `candidate_state`, `committed_state`,
`accepted_groups`, `rejected_groups`, conflicts, and validation errors. Do not
expose non-serializable BioSTEAM objects in it.

## 9. Add Read-Only State Queries

Handle `query_current_state` before any write operation. Add a deterministic
query function such as:

```python
query_feed_state(session, target_field) -> dict
```

It must read a copied state and never invoke the state-changing feed update or
the VLE calculation.

Examples:

```text
User: What is the feed pressure?
Assistant: The feed pressure is 101325 Pa.
```

```text
User: What is the feed pressure?
Assistant: The feed pressure has not been provided yet.
```

```text
User: What pressure did I give?
Assistant: The pressure value is 1, but its units have not been specified.
```

Support read-only queries for every field in the registry, including
components, component flows, total flow, composition, pressure, and
temperature. Format answers from authoritative state, not model memory.

A query must not:

- mutate feed state;
- discard a provisional value;
- advance or replace the pending request; or
- count as supplying the queried value.

After answering a query, the controller may repeat the still-active pending
question in one concise sentence when necessary.

## 10. Use a Declarative Field Registry

Centralize conversational metadata rather than scattering field-specific
branches through the agent:

```python
FIELD_REGISTRY = {
    "pressure": {
        "value_type": "number",
        "unit_field": "pressure_units",
        "supported_units": ["Pa", "kPa", "bar", "atm"],
        "value_question": "What is the feed pressure?",
        "unit_question": "What units is the feed pressure in?",
        "validator": validate_pressure,
        "formatter": format_pressure,
    },
    # Other feed fields follow the same contract.
}
```

Use this registry to drive:

- expected pending-answer type;
- supported-unit prompts;
- short-answer binding;
- validation;
- read-only query formatting; and
- missing-input questions.

Domain rules necessarily differ by field, but they should be declared once
rather than repeated in conversational loops.

Replace the temperature prompt with concise wording. Remove `it is never
assumed to be the bubble point` from routine user-facing questions; retain the
no-bubble-point rule internally and in tests.

## 11. Preserve Deterministic Output Boundaries

Allow exactly these response categories:

1. next missing-information or clarification question;
2. deterministic answer to a read-only state query;
3. deterministic conflict or validation message; and
4. completed phase plus molar vapor/liquid fractions.

Do not call the model to generate any of these responses. The prior
phase-result restriction applies to category 4 and does not prevent the agent
from answering a user's explicit question about accumulated inputs.

## 12. Expand Debugging Around the New Boundary

Retain `--debug` and `--debug-json`. Extend each record with:

- `intent` and `target_field`;
- `active_request_before` and `active_request_after`;
- proposed evidence spans;
- pending-field binding decision;
- grounded facts and rejection reasons;
- candidate state;
- candidate validation;
- accepted and rejected logical groups;
- committed state;
- rollback status; and
- read-only query result, when applicable.

Fix `compute_state_diff` so an empty mapping becoming populated reports only
the added child entries, not both added children and removal of the empty
parent mapping.

Debugging remains observational: no additional model calls, BioSTEAM calls, or
state changes.

## Module-Level Changes

### `multicomponent_distillation_agent.py`

- Accept a session object in `process_turn`.
- Construct the labelled extraction context.
- Route structured intents.
- Invoke generic pending-field binding.
- Use deterministic reply/query formatters.
- Keep one extraction call per turn and no post-result model call.

### `multicomponent_dialogue.py` (new)

- Define the session, pending request, provisional value, and confirmation
  structures.
- Define the field registry.
- Bind short replies to active requests.
- Format pending questions and read-only query answers.
- Contain no Ollama or BioSTEAM calls.

### `multicomponent_grounding.py`

- Replace field-agnostic numeric matching with role-aware evidence grounding.
- Consume pending-field context explicitly.
- Associate mapping entries with both component and numeric evidence.
- Prevent a token from grounding incompatible facts.

### `multicomponent_feed_state.py`

- Store explicit measurements with unit, provenance, evidence, and source
  turn.
- Implement explicit component identity operations.
- Keep candidate construction and normalization pure.
- Recompute derived data after corrections.

### `multicomponent_feed_tool.py`

- Remove normal-agent dependence on module-global `_feed_state`.
- Assess candidate transitions before commit.
- Commit accepted logical groups once per turn.
- Expose a read-only state-query operation.

### `multicomponent_diagnostics.py`

- Record intent, binding, candidate, validation, commit, rollback, and query
  data.
- Correct the empty-mapping state-diff artifact.

The unit registry, molecular-weight conversion, and `T/P` VLE wrapper should
change only where required to consume the revised validated state shape.

## Required Automated Tests

### Pending-field binding

1. After asking for pressure, bare `1` binds only to pressure.
2. That `1` cannot ground a composition fraction, flow, or temperature even
   when the model proposes them.
3. A following `atm` attaches to the incomplete pressure measurement.
4. A bare value with no active request and no field wording triggers
   clarification without mutation.
5. An explicit different field is accepted while the original request stays
   pending.
6. `yes`, `no`, and unit-only replies operate only on an active compatible
   confirmation/request.

### Grounding and evidence

7. Identical numeric values assigned to different components retain their
   correct associations.
8. A number appearing only as pressure cannot ground a proposed fraction of
   the same numeric value.
9. Evidence that exists literally but describes the wrong field is rejected.
10. Percentage conversion occurs only after component and composition-role
    association.
11. Carried-forward facts copied by the model are not recommitted.
12. A model typo such as `meth,anol` cannot create a component.

### Component identity

13. `methanol = 30 kg/hr` does not replace an established three-component
    identity.
14. Restating the same complete component set is idempotent.
15. A subset is never treated as full replacement.
16. Explicit addition adds without clearing quantities.
17. Explicit replacement/reset clears quantities whose identities are no
    longer valid.
18. Ambiguous introduction of a new component asks for clarification.

### Transactional state

19. A conflicting candidate leaves the last valid committed state unchanged.
20. A rejected hallucinated composition cannot poison later turns.
21. Independently valid logical groups can commit while a rejected group does
    not.
22. Corrections clear and recompute all affected derived values.
23. Two agent sessions never share state.
24. A failed BioSTEAM calculation does not alter validated feed inputs.

### Units and partial quantities

25. Partial component flows preserve their individual source units.
26. Cross-turn `kg/hr` and `kmol/hr` component flows produce a common-unit
    restatement request without reinterpreting either value.
27. Same-turn mixed units remain rejected.
28. A complete common-unit restatement replaces the conflicted quantity group
    atomically.
29. Bare composition waits for total-flow units before basis inference.
30. Explicit composition basis continues to override total-flow-unit basis.

### Read-only queries

31. `What is the feed pressure?` returns the stored value and unit.
32. Querying a missing pressure says it has not been provided.
33. Querying an incomplete pressure reports the value and missing unit.
34. Queries never call the state-changing update function.
35. Queries do not change state, provisional data, or the active request.
36. Component, flow, composition, pressure, and temperature queries all use
    the same registry-driven path.

### Diagnostics and regression

37. Debug output distinguishes proposed, candidate, committed, and rolled-back
    state.
38. Empty-to-populated mappings do not generate a false parent removal.
39. Normal mode remains free of diagnostics.
40. No turn makes more than the allowed extraction call plus malformed-output
    retry.
41. Existing unit conversion and three-/five-component phase tests pass.
42. Existing binary workflow tests remain unchanged and pass.

Use scripted model outputs for CI. Live Ollama conversations are manual smoke
tests, not required CI dependencies.

## Manual Interactive Acceptance Conversations

Run with `--debug` and inspect both the reply and state transition.

### Bare pressure followed by unit

```text
Assistant: What is the feed pressure?
User: 1
Assistant: What units is the pressure value 1 in? (Pa, kPa, bar, atm)
User: atm
```

Expected: only `pressure = 1 atm` is committed; no composition changes occur.

### Read-only pressure question

```text
User: What is the feed pressure?
Assistant: The feed pressure is 1 atm.
```

Expected: no state change and no change to the active missing-input request.

### Partial component flows

```text
User: separate methanol, ethanol, water
User: methanol = 30 kg/hr
User: water = 50 kmol/hr, ethanol = 20 kmol/hr
```

Expected: the three-component identity persists; the third turn reports the
cross-turn unit conflict without reinterpreting or deleting prior facts.

### Correction after a conflict

```text
User: methanol = 30 kmol/hr, water = 50 kmol/hr, ethanol = 20 kmol/hr
```

Expected: the complete common-unit restatement replaces the quantity group,
clears the unit conflict, and proceeds to the next missing field.

### Reproduce the reported numeric collision

Use the original sequence that caused Qwen to propose `water: 1.0` while the
user was answering the pressure question.

Expected debug evidence:

- intent is `answer_pending_request`;
- target field is pressure;
- `1` binds only to pressure;
- any proposed `water: 1.0` is rejected as wrong-role evidence;
- candidate and committed composition remain unchanged; and
- the next request asks for pressure units.

## Execution Order

1. Add failing transcript tests for the reported pressure/composition collision,
   partial component identity loss, cross-turn units, and state queries.
2. Add the session object and declarative field registry without changing VLE
   behavior.
3. Extend the structured interpretation schema and labelled turn context.
4. Implement pending-field binding and role-aware evidence grounding.
5. Implement explicit component identity operations.
6. Migrate measurements to per-value units/provenance and preserve the
   existing composition-basis rules.
7. Introduce candidate validation and transactional logical-group commit.
8. Add deterministic read-only query responses.
9. Extend diagnostics and correct the state-diff artifact.
10. Run focused tests, the full `tools/chopper` suite, and binary regressions.
11. Run every manual acceptance conversation against live `qwen3:8b` with
    `--debug` enabled.

Make each step independently testable. Do not combine this work with new
distillation-design capabilities.

## Completion Criteria

The work is complete when:

- a short answer is interpreted only in the context of the active request;
- numeric evidence cannot cross physical-field or component roles;
- component mentions cannot accidentally replace feed identity;
- invalid/conflicting proposals never corrupt the last valid state;
- partial measurements retain their actual units across turns;
- read-only questions are answered from authoritative state without mutation;
- all user-facing follow-up questions are concise and registry-driven;
- debug output proves what was proposed, rejected, validated, and committed;
- three- and five-component feed-phase calculations remain correct; and
- the full multicomponent and binary regression suites pass.
