# Multicomponent Agent Debugging-Output Plan

## Goal

Add optional turn-by-turn diagnostics to
`tools/chopper/multicomponent_distillation_agent.py` so a live conversation
shows exactly:

- what Qwen returned;
- what the grounding layer accepted and rejected;
- which Python function was called and with which arguments;
- how the authoritative feed state changed;
- what pending request or calculation result was returned; and
- which final text was shown to the user.

Debugging must be disabled by default and must not change normal agent
behavior.

## Explicit Non-Goals

This change must not fix or redesign:

- component identity replacement;
- pending-reply interpretation;
- field-to-number grounding;
- cross-turn unit or composition-basis handling;
- composition conversion;
- feed-phase calculations; or
- user-facing pending-question wording.

Those corrections should be designed from evidence collected by this trace in
a later change.

## Command-Line Interface

Add two mutually exclusive flags:

```powershell
python tools/chopper/multicomponent_distillation_agent.py --debug
python tools/chopper/multicomponent_distillation_agent.py --debug-json
```

- `--debug` prints a compact human-readable trace.
- `--debug-json` prints one complete JSON object per processed user turn.
- With neither flag, output remains exactly as it is now.
- Diagnostic output goes to `stderr`; the ordinary `Assistant:` response stays
  on `stdout`.
- Both flags work in interactive and one-shot modes.
- Replace the current raw `sys.argv` handling with `argparse` so flags are not
  accidentally included in the one-shot user prompt.

The debug trace contains the user's full message and model output. State this
plainly in `--help` because a captured trace may contain sensitive process
information.

## Diagnostic Record

Create one record for every call to `process_turn`. Use a stable,
JSON-serializable structure:

```python
{
    "turn": 1,
    "user_message": "methanol = 30 kg/hr",
    "pending_before": {...},
    "state_before": {...},
    "model": {
        "call_count": 1,
        "raw_responses": ["..."],
        "parsed_proposal": {...},
        "retry_used": False,
        "parse_succeeded": True,
    },
    "prechecks": {
        "detected_flow_units": ["kg/hr"],
        "detected_composition_bases": [],
        "mixed_flow_units": False,
        "mixed_composition_basis": False,
    },
    "grounding": {
        "accepted": {...},
        "rejected": {...},
    },
    "function_calls": [
        {
            "name": "update_multicomponent_feed",
            "arguments": {...},
            "result": {...},
        }
    ],
    "state_after": {...},
    "state_diff": {...},
    "reply": "What is the feed pressure?",
    "exit_path": "pending_request"
}
```

`exit_path` should use a small fixed vocabulary:

- `pending_request`;
- `complete_result`;
- `validation_error`;
- `conflict`;
- `mixed_flow_units`;
- `mixed_composition_basis`;
- `reset`;
- `model_parse_failure`; or
- `calculation_error`.

Record only JSON-safe values. Do not include BioSTEAM stream or chemical
objects.

## Small Diagnostics Module

Add `tools/chopper/multicomponent_diagnostics.py` containing only reusable,
side-effect-free helpers:

- `new_turn_record(turn_number, user_message)`;
- `to_jsonable(value)`;
- `compute_state_diff(before, after)`;
- `render_human_readable(record)`; and
- `render_json(record)`.

Keep printing and CLI decisions in the agent. The diagnostics module should
not import Ollama or BioSTEAM and must never mutate feed state.

The human-readable renderer should use the same sections on every turn:

```text
[debug turn 2]
[state before] ...
[model proposal] ...
[grounding accepted] ...
[grounding rejected] ...
[calling update_multicomponent_feed] ...
[function result] ...
[state diff] ...
[exit path] pending_request
```

Omit an empty section only when it carries no information.

## Read-Only State Access

Add a read-only function to `multicomponent_feed_tool.py`, for example:

```python
def get_multicomponent_feed_state():
    return copy.deepcopy(_feed_state)
```

Use this accessor to capture `state_before` and `state_after`. The diagnostics
code must not read or modify `_feed_state` directly.

If the current pending request is needed in `pending_before`, expose it through
a similarly read-only assessment function or derive it from a copied state.
Do not call the state-changing update function merely to inspect state.

## Capture the Raw Model Proposal

Change `propose_feed_update` so it can return diagnostic metadata alongside
its existing parsed proposal:

- every raw structured-output response;
- number of model calls;
- whether the bounded retry ran;
- whether parsing ultimately succeeded; and
- the final parsed proposal.

This metadata is observational only. The same parsed proposal must continue
through the existing control flow unchanged.

## Instrument Every Exit Path

Update `process_turn` to build one diagnostic record incrementally:

1. Capture state and pending request before model extraction.
2. Capture raw and parsed model output.
3. Capture mixed-unit and mixed-basis precheck results.
4. Capture the complete `accepted` and `rejected` dictionaries returned by
   `ground_proposed_update`; do not discard `_rejected`.
5. Record each actual Python function invocation and its arguments/result.
6. Capture state after processing and compute the state diff.
7. Record the deterministic reply and exit path.
8. Emit the record exactly once, including for early returns and exceptions.

Use one finalization helper or a `try/finally`-style structure so reset,
mixed-unit, malformed-model-output, validation-error, and successful
calculation paths cannot accidentally skip diagnostic emission.

Do not add another model call to produce or summarize debugging output.

## Human-Readable State Diff

The state diff should distinguish:

- `added` fields;
- `changed` fields;
- `removed` fields; and
- unchanged fields, which should not be printed in human-readable mode.

Nested component mappings should be compared by component key so the trace can
show events such as:

```text
changed.component_names:
  before: [Methanol, Ethanol, Water]
  after:  [Methanol]

removed.component_flows.Ethanol: 20
changed.component_flow_units:
  before: kg/hr
  after:  kmol/hr
```

The JSON form may retain the complete before/after states in addition to the
compact diff.

## Required Tests

Add focused tests that do not require a live Ollama server:

1. Debugging disabled produces no diagnostic output and does not change the
   normal reply.
2. `--debug` writes a human-readable record to `stderr` and keeps the ordinary
   reply on `stdout`.
3. `--debug-json` emits valid JSON containing the required top-level fields.
4. CLI flags are not included in a one-shot prompt.
5. State snapshots are deep copies and cannot mutate authoritative state.
6. The raw model response, parsed proposal, accepted fields, and rejected
   fields all appear in the record.
7. The exact `335 K` fabricated-pressure example shows `101325 Pa` under the
   model proposal and grounding rejection, never under accepted fields.
8. The partial-flow conversation records any component-list replacement and
   the resulting state diff without changing current behavior.
9. A mixed-unit early return still emits exactly one complete record.
10. A reset path records the reset function call and state removal.
11. A malformed-output retry records both raw responses and `call_count == 2`.
12. A completed phase calculation records the restricted result without
    attempting to serialize a BioSTEAM object.
13. Human and JSON rendering do not invoke Ollama, BioSTEAM, or a state-changing
    function.
14. Existing multicomponent and binary tests remain unchanged and pass.

## Manual Acceptance Check

Run the reported conversation with human-readable debugging enabled:

```text
separate methanol, ethanol, water
methanol = 30 kg/hr
water = 50 kmol/hr, ethanol = 20 kmol/hr
```

The trace must make it possible to answer, without inference:

- Did Qwen propose `component_names` or `add_component_names`?
- Which fields passed grounding?
- Did the component list change?
- Was the Methanol flow stored or removed?
- Did the shared flow unit change?
- Which pending request caused each assistant response?

Also repeat the `wt.%` example and confirm the trace shows whether Qwen
proposed `composition` or `component_flows`, which basis it proposed, what the
grounding layer accepted, and the actual values passed to the feed tool.

## Completion Criteria

This debugging-only change is complete when every user turn can produce one
accurate trace from user message through final reply, normal mode remains
unchanged, debug mode performs no additional engineering or model calls, and
the two reported conversations can be diagnosed from their traces without
reading private module state or guessing what Qwen did.
