# Binary-Distillation Turn Diagnostics and Recovery Plan

## Purpose

Implement end-to-end diagnostic visibility for
`tools/chopper/binary_distillation_workflow_agent.py` without reverting the
schema-driven `TurnIntent` / `TurnTransaction` architecture introduced by
`tools/binary-distillation-issues-9-1-2026-fifth.md`.

The implementation must make it possible to determine, for every user turn,
whether a failure originated in:

1. Qwen's semantic interpretation;
2. structured-output parsing;
3. active-schema validation;
4. transaction compilation;
5. Python operation dispatch;
6. workflow-state mutation; or
7. final response formatting.

This plan is intended to be executed by an LLM coding agent. Complete the
steps in order. Do not stop after adding logging: reproduce the reported
failure, fix the user-facing duplicate error, add regression coverage, and
run the required acceptance tests.

---

## Reported failure

Input:

```text
Separate water and ethanol at 355 K and 101325 Pa pressure. The feed
composition is 50 kmol/hr ethanol and 50 kmol/hr water
```

Observed output:

```text
I couldn't apply that value for component_flows (missing_entity). I couldn't
apply that value for component_flows (missing_entity).
```

Current evidence indicates that Qwen likely emitted two keyed
`component_flows` updates without an `entity`. The validator correctly
rejected both updates atomically, but the architecture currently hides the
successful structured response, the proposed updates, and the transaction
decision. The formatter then renders the same low-level rejection twice.

Confirm this hypothesis from a real diagnostic trace. Do not treat it as
proven until the raw model response is captured.

---

## Architectural invariants

Preserve all of these invariants:

1. `format=`-constrained structured output remains the only model
   interpretation mechanism.
2. Do not restore native Ollama engineering tool calling.
3. Qwen proposes intent; Python validates and executes it.
4. Invalid update batches remain atomic: one invalid or conflicting update
   causes zero updates from that batch.
5. Queries and actions continue to validate independently from updates.
6. Every state mutation continues through
   `update_binary_distillation_problem()`.
7. Diagnostic mode must not change routing, validation, execution, or state.
8. Default interactive output must remain concise.
9. Diagnostic records must contain only JSON-serializable values. Do not
   serialize Ollama client objects, BioSTEAM objects, or arbitrary exceptions.
10. Never invent an entity or engineering value merely to recover a failed
    model proposal.

---

## Target diagnostic pipeline

Every turn must be observable as:

```text
user input
  -> route selection
  -> raw Qwen structured output (if model interpretation was used)
  -> parsed TurnIntent
  -> validated TurnTransaction
  -> dispatched Python operations
  -> authoritative state diff
  -> final assistant response
```

Use a single per-turn diagnostic record with this conceptual shape:

```python
{
    "turn_id": "...",
    "user_text": "...",
    "route": "fast_path" | "model_interpretation",
    "interpretation": {
        "model": "...",
        "attempts": [
            {
                "raw_response": "...",
                "parse_result": {...},
            }
        ],
        "retry_used": False,
        "final_intent": {...} | None,
    },
    "validation": {
        "transaction": {...} | None,
        "invalid_updates": [...],
        "conflicts": [...],
    },
    "execution": {
        "operations": [...],
        "write_performed": False,
        "write_kwargs": {},
        "action": None,
        "query_results": [],
    },
    "state": {
        "before": {...},
        "after": {...},
        "changed_fields": [...],
    },
    "final_response": "...",
}
```

The exact implementation may use a dataclass, `TypedDict`, or plain
dictionaries, but external JSON output must follow one stable documented
schema.

---

## Step 1 - Establish the baseline

1. Read these files completely before editing:

   - `tools/binary-distillation-issues-9-1-2026-fifth.md`
   - `tools/separation_tool.md`
   - `tools/chopper/binary_distillation_workflow_agent.py`
   - `tools/chopper/turn_intent.py`
   - `tools/chopper/turn_transaction.py`
   - `tools/chopper/problem_field_registry.py`
   - `tools/chopper/problem_snapshot.py`
   - the directly related test files

2. Run the existing focused tests before making changes.
3. Run the full `tools/chopper` test suite before making changes.
4. Record test counts and failures. Do not modify unrelated failing tests.
5. If the local Ollama server and configured Qwen model are available, run
   the reported prompt once and retain the observed baseline output.

Recommended commands from the repository root:

```powershell
pytest tools/chopper/test_turn_intent_parser.py -v
pytest tools/chopper/test_turn_transaction.py -v
pytest tools/chopper/test_binary_distillation_workflow_agent.py -v
pytest tools/chopper -v
python tools/chopper/binary_distillation_workflow_agent.py
```

---

## Step 2 - Add a diagnostic data model

Create a narrowly scoped module such as:

```text
tools/chopper/turn_diagnostics.py
```

It should own:

1. construction of an empty per-turn diagnostic record;
2. safe conversion of nested values to JSON-compatible data;
3. a bounded human-readable console renderer;
4. JSON Lines serialization; and
5. state-diff construction.

Keep this module independent of Ollama and BioSTEAM. It must not execute
workflow operations.

The human-readable renderer should emit sections resembling:

```text
[TURN]
[ROUTE]
[INTERPRETATION ATTEMPT 1]
[PARSED INTENT]
[VALIDATION]
[EXECUTION]
[STATE DIFF]
[FINAL RESPONSE]
```

Do not print the complete workflow assessment to the console by default.
Prefer a bounded state diff and exact rejected updates. The JSONL record may
contain fuller snapshots if they are safely serializable and useful.

---

## Step 3 - Preserve every raw interpretation attempt

Update `propose_turn_intent()` in `turn_intent.py`.

Currently, successful parsing returns the normalized intent but discards the
raw Qwen content. Change the result so both successful and unsuccessful calls
retain their raw responses.

Required information:

```python
{
    "ok": True,
    "intent": {...},
    "attempts": [
        {
            "raw": "<exact response.message.content>",
            "parse_result": {...},
        }
    ],
    "retry_used": False,
}
```

If the strict-schema retry runs, retain both attempts in order and set
`retry_used=True`. Avoid recursive structures: an attempt's `parse_result`
must not contain the enclosing attempts list.

Keep existing callers compatible where practical. At minimum, preserve the
existing `ok` and `intent` keys.

---

## Step 4 - Enrich validation diagnostics

Update `validate_turn_intent()` in `turn_transaction.py` so every invalid
update includes enough context to diagnose it without consulting the
original model response.

For example:

```python
{
    "update_index": 0,
    "update": {
        "field": "component_flows",
        "entity": None,
        "value": 50,
        "units": "kmol/hr",
    },
    "reason": "missing_entity",
    "field_metadata": {
        "keyed": True,
        "entity_type": "component",
        "value_type": "number",
        "write_binding": "component_flows",
    },
    "effect": "entire_update_batch_rejected",
}
```

Do not place callable registry accessors into diagnostics. Copy only a small
allowlist of serializable metadata.

Preserve the existing transaction keys unless a deliberate migration is
covered by tests.

---

## Step 5 - Instrument routing and execution

Thread one diagnostic context through `ask()` and
`_dispatch_transaction()` in
`binary_distillation_workflow_agent.py`.

Record:

1. current user text;
2. whether `_fast_path_transaction()` or Qwen interpretation won;
3. all interpretation attempts;
4. final parsed intent;
5. validated transaction;
6. exact Python operations selected;
7. exact `update_binary_distillation_problem(**kwargs)` arguments;
8. whether a WRITE actually ran;
9. action name and arguments, if any;
10. query requests and results;
11. authoritative state before execution;
12. authoritative state after execution;
13. a bounded state diff; and
14. final assistant response.

For the reported failure, the execution trace must explicitly show:

```text
write_performed: false
write_kwargs: {}
reason: atomic update rejection
```

Do not describe Python dispatches as Qwen "tool calls." Use terminology such
as `proposed intent`, `validated transaction`, and `dispatched operation`.

---

## Step 6 - Add CLI diagnostic controls

Extend the script entry point with:

```text
--debug
--debug-json PATH
```

Behavior:

- no flags: preserve normal concise REPL behavior;
- `--debug`: print the bounded readable diagnostic after each turn;
- `--debug-json PATH`: append one complete JSON object per turn;
- both flags: do both;
- one-shot mode must support the same flags;
- diagnostic output must not be inserted into conversation history; and
- inability to write a diagnostic file must produce a clear error without
  silently changing workflow state.

Use `argparse` or the project's established CLI pattern. Do not introduce a
new dependency.

---

## Step 7 - Fix duplicate and opaque rejection formatting

Update `format_transaction_response()` and its helpers.

Group identical invalid updates by at least:

```python
(field, reason)
```

Two missing-entity failures for `component_flows` must generate one
user-facing sentence, while the diagnostic record retains both rejected
updates.

Use registry metadata to render useful messages. For `missing_entity` on a
keyed field, prefer:

```text
I failed to associate the stated component flow values with their component
names, so none of the values from this message were saved.
```

The wording must:

1. avoid blaming the user when their sentence was unambiguous;
2. state that nothing was saved because validation is atomic;
3. avoid exposing only an internal error token such as `missing_entity`; and
4. remain generic enough to support future keyed fields.

Debug output must still show the exact internal reason code.

---

## Step 8 - Add focused tests for diagnostics

Add a dedicated test module, for example:

```text
tools/chopper/test_turn_diagnostics.py
```

Cover at least:

1. a successful model parse retains the exact raw response;
2. a parsing retry retains both attempts in order;
3. diagnostics are JSON serializable;
4. callable registry accessors never leak into diagnostics;
5. missing keyed entities include update indexes and safe field metadata;
6. an invalid atomic batch reports `write_performed=False`;
7. a valid batch reports the exact dispatched WRITE kwargs;
8. state diff includes changed values and excludes unchanged values;
9. fast-path turns state `route="fast_path"`;
10. model-interpreted turns state `route="model_interpretation"`;
11. debug mode does not change final state or final response;
12. JSONL output contains exactly one valid JSON object per completed turn;
13. two identical `missing_entity` failures produce one user-facing sentence;
14. both invalid entries remain present in the diagnostic record; and
15. diagnostic content is not appended to model conversation history.

Use the existing fake Ollama client infrastructure. Tests must not require a
running Ollama server.

---

## Step 9 - Add the reported-prompt regression test

Add a scripted-client regression using this exact current user message:

```text
Separate water and ethanol at 355 K and 101325 Pa pressure. The feed
composition is 50 kmol/hr ethanol and 50 kmol/hr water
```

Test both interpretations:

### Valid Qwen proposal

The parsed intent should contain:

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
    {"field": "feed_temperature_K", "value": 355},
    {"field": "pressure_Pa", "value": 101325},
]
```

The compiled WRITE must be:

```python
{
    "component_flows": {"Ethanol": 50, "Water": 50},
    "component_flow_units": "kmol/hr",
    "feed_temperature_K": 355,
    "pressure_Pa": 101325,
}
```

The resulting feed identity should be established from the keyed flows; a
separate `component_names` update is not required.

### Broken Qwen proposal

Script Qwen to return two `component_flows` updates with `entity=null`.
Assert:

- both are diagnosed as `missing_entity`;
- zero WRITE values are applied;
- state is unchanged;
- only one user-facing failure sentence is returned; and
- the raw Qwen response is visible in the diagnostic record.

---

## Step 10 - Evaluate a bounded semantic retry

Implement this step only after the diagnostic path and tests above work.
Keep it behind an explicit feature flag initially, such as:

```text
--semantic-retry
```

A semantic retry is different from the existing malformed-JSON retry. It
may run only when:

1. JSON parsing succeeded;
2. semantic validation rejected the update batch;
3. no mutation has occurred;
4. every failure is in a small allowlist of potentially repairable reasons,
   initially only `missing_entity` for keyed fields; and
5. no semantic retry has already occurred this turn.

Send Qwen:

- the original current user message;
- its rejected TurnIntent;
- exact validator diagnostics;
- the relevant registry metadata; and
- an instruction to return a corrected complete TurnIntent without
  inventing facts.

Example repair instruction:

```text
Your JSON matched the structural schema but failed semantic validation.
component_flows is keyed by component name. Each component_flows update
requires entity="<component name>". Correct the TurnIntent using only the
current user's statement. Do not invent values.
```

Revalidate the entire replacement intent from scratch. Never merge selected
pieces of the rejected and repaired intents.

If retry validation fails, perform zero writes and retain both proposals and
both validation results in diagnostics.

Add tests proving:

1. the known missing-entity failure can be repaired;
2. retry is capped at one;
3. retry never follows a mutation;
4. non-allowlisted failures do not retry;
5. failed retry leaves state unchanged; and
6. disabling the flag preserves the non-retry behavior.

Do not enable semantic retry by default until the live-Qwen acceptance run
shows that it improves behavior reliably.

---

## Step 11 - Run focused and full verification

Run:

```powershell
pytest tools/chopper/test_turn_intent_parser.py -v
pytest tools/chopper/test_turn_transaction.py -v
pytest tools/chopper/test_turn_diagnostics.py -v
pytest tools/chopper/test_binary_distillation_workflow_agent.py -v
pytest tools/chopper -v
```

Also run any formatter, linter, or type checker already configured for this
repository. Do not introduce a new formatter or broad mechanical rewrite.

Compare before/after test counts. Investigate every new failure.

---

## Step 12 - Perform the live-Qwen acceptance run

When a local Ollama server and the configured model are available, run the
agent in diagnostic mode with the exact reported input.

Required artifacts:

1. raw Qwen structured output;
2. parsed TurnIntent;
3. full validator result;
4. exact dispatched WRITE kwargs, or an explicit statement that no WRITE
   occurred;
5. before/after state diff;
6. final assistant response;
7. whether structural or semantic retry occurred;
8. model name and deterministic decoding settings; and
9. classification of the root cause as one or more of:

   - model semantic interpretation;
   - prompt/catalog design;
   - JSON/schema adapter;
   - deterministic validator;
   - transaction compiler;
   - operation dispatcher;
   - state layer; or
   - response formatter.

The successful acceptance state must contain:

```python
component_flows = {"Ethanol": 50, "Water": 50}
component_flow_units = "kmol/hr"
feed_temperature_K = 355
pressure_Pa = 101325
```

The phrase "feed composition" in the user input must not cause the numeric
flow rates to be stored as mole fractions. Explicit `kmol/hr` quantities are
component flow rates. A later natural-language response may clarify the
terminology, but the turn must not be rejected for that wording alone.

---

## Completion criteria

The task is complete only when all of the following are true:

- raw successful Qwen outputs are inspectable;
- every rejected update carries actionable structured diagnostics;
- exact dispatched Python operations are visible;
- before/after state changes are visible;
- diagnostic mode is available in interactive and one-shot execution;
- JSONL diagnostic output works;
- duplicate low-level rejection sentences are eliminated;
- atomic update behavior remains unchanged;
- focused and full test suites pass, aside from clearly documented unrelated
  pre-existing failures;
- the exact reported input has a regression test;
- a live-Qwen run is completed when the local runtime is available; and
- the final implementation report identifies the actual failure layer from
  evidence rather than inference.

---

## Required final report

Report back with:

1. files added and changed;
2. baseline and final test counts;
3. final diagnostic schema;
4. CLI usage examples;
5. the captured raw TurnIntent for the reported prompt;
6. the validated TurnTransaction;
7. the exact operation dispatch and state diff;
8. the root cause;
9. the user-facing formatting fix;
10. semantic-retry results and whether it was enabled by default;
11. any remaining Qwen interpretation limitations; and
12. any work deliberately left out of scope.

