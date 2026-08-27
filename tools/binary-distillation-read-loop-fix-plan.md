# Plan: Stop Repeated READ-Tool Loops in the Binary-Distillation Workflow Agent

## Problem

The READ/WRITE separation described in
`binary-distillation-read-vs-append.md` is implemented, but the agent can
still enter an infinite tool loop:

```text
update_binary_distillation_problem(...)
get_binary_distillation_problem()
get_binary_distillation_problem()
get_binary_distillation_problem()
...
```

The deterministic workflow and state checker are not causing this loop.
The loop is in `binary_distillation_workflow_agent.py::ask()`:

```python
while response.message.tool_calls:
    ...
    response = client.chat(..., tools=TOOLS, ...)
```

After every tool result, Qwen is offered the complete tool list again. A
READ call returns the same authoritative state, but there is no change in
the available actions and no deterministic termination rule. Qwen can
therefore keep selecting the READ tool instead of producing a user-facing
answer. Prompt instructions alone cannot guarantee termination.

## Desired invariant

For one user turn:

```text
new engineering facts  -> one WRITE -> final prose
state question         -> one READ  -> final prose
new facts + question   -> one WRITE -> final prose from WRITE result
new problem            -> RESET -> one WRITE if needed -> final prose
```

Once an engineering-state tool has returned the full current state, no
additional READ is needed during that user turn.

The orchestrator, rather than Qwen, must enforce this invariant.

## Recommended fix

### 1. Replace the unbounded tool loop with a bounded turn controller

Refactor `ask()` into a small deterministic state machine. Track, for the
current user turn:

```python
reset_used: bool
engineering_tool_used: bool
tool_call_count: int
call_fingerprints: set[tuple]
```

Recommended allowed transitions:

```text
START
  |-- UPDATE ----------------------> FINALIZE
  |-- READ ------------------------> FINALIZE
  |-- RESET --> UPDATE or READ ----> FINALIZE
  `-- no tool ---------------------> DONE

FINALIZE
  `-- call Qwen without tools -----> DONE
```

`UPDATE` means `update_binary_distillation_problem` and `READ` means
`get_binary_distillation_problem`.

### 2. Force final-answer generation after an engineering tool

After either UPDATE or READ returns, append its tool result to `messages`,
then make the next model request with no tools exposed:

```python
response = client.chat(
    model=MODEL,
    messages=messages,
    think=False,
)
```

Do not pass `tools=TOOLS` on this finalization call. This makes another
READ call impossible and forces the model to explain the state in prose.

This is valid for all workflow statuses, including:

- `need_components`
- `unsupported_multicomponent`
- `inconsistent_input`
- `need_essential_inputs`
- `need_case_definition`
- `need_case_inputs`
- `ambiguous`
- `ready_for_calculation`

The tool result already contains everything needed to formulate the next
question or summary.

### 3. Preserve the RESET exception

RESET is housekeeping rather than an engineering-state result. If the
first call is `reset_workflow_session`, permit one additional tool-enabled
model round so Qwen can submit the new problem through UPDATE.

After the subsequent UPDATE or READ, immediately enter FINALIZE.

Also impose a hard per-turn ceiling, for example:

```python
MAX_TOOL_CALLS_PER_TURN = 2
```

This supports `RESET -> UPDATE` but makes every turn terminate even if the
model behaves unexpectedly.

### 4. Suppress redundant READ after WRITE

The WRITE tool already returns the full normalized workflow state. A READ
immediately after WRITE cannot add information.

If Qwen requests READ after WRITE in the same turn, do not execute it.
Proceed directly to the no-tools finalization call using the WRITE result.

Likewise, after READ has executed once, suppress any second READ during
the same turn.

### 5. Add duplicate-call detection as a defensive backstop

Create a stable fingerprint from the tool name and canonicalized JSON
arguments:

```python
fingerprint = (
    call.function.name,
    json.dumps(call.function.arguments, sort_keys=True),
)
```

If the same fingerprint appears twice during one user turn, stop exposing
tools and finalize from the latest result. This protects against future
loops involving WRITE or RESET as well as READ.

Duplicate detection is a safety mechanism; the primary termination rule
remains “one engineering-state operation, then finalize without tools.”

### 6. Handle multiple tool calls in one model response deterministically

If Qwen emits several calls together:

- Execute RESET first if it is valid for the turn.
- Execute at most one engineering call.
- Prefer UPDATE over READ when both are requested, because UPDATE returns
  the complete post-update state.
- Do not execute a READ after a successful UPDATE.
- Never execute the same tool call twice.

This prevents a single assistant message containing UPDATE plus READ from
bypassing the per-turn policy.

## Suggested implementation shape

Keep tool execution separate from response finalization:

```python
def _chat_with_tools(client, messages):
    return client.chat(
        model=MODEL,
        messages=messages,
        tools=TOOLS,
        think=False,
    )


def _chat_without_tools(client, messages):
    return client.chat(
        model=MODEL,
        messages=messages,
        think=False,
    )


def ask(client, messages):
    response = _chat_with_tools(client, messages)
    messages.append(response.message)

    reset_used = False
    engineering_tool_used = False
    fingerprints = set()
    calls_used = 0

    while response.message.tool_calls and calls_used < MAX_TOOL_CALLS_PER_TURN:
        selected_calls = select_allowed_calls(
            response.message.tool_calls,
            reset_used=reset_used,
            engineering_tool_used=engineering_tool_used,
            fingerprints=fingerprints,
        )

        for call in selected_calls:
            result = _run_tool_call(call)
            append_tool_result(messages, call, result)
            calls_used += 1

            if call.function.name == "reset_workflow_session":
                reset_used = True
            else:
                engineering_tool_used = True

        if engineering_tool_used or not selected_calls:
            response = _chat_without_tools(client, messages)
        else:
            # RESET occurred; allow one tool-enabled round for the new state.
            response = _chat_with_tools(client, messages)

        messages.append(response.message)

    if response.message.tool_calls:
        # Hard-stop fallback: do not execute more calls.
        response = _chat_without_tools(client, messages)
        messages.append(response.message)

    return response.message.content
```

The exact code can be simpler, but termination must be enforced by Python,
not left to the prompt.

## Tests to add

Create `tools/chopper/test_binary_distillation_workflow_agent.py` using a
fake or mocked Ollama client. Do not require a running Ollama server for
these tests.

### Test 1: WRITE finalizes without READ

Simulate Qwen requesting:

```text
update_binary_distillation_problem(component_names=[Methanol, Water])
```

Assert:

- UPDATE runs exactly once.
- The next chat call has no tools.
- READ never runs.
- `ask()` returns prose.

### Test 2: READ finalizes after one call

Simulate a state question followed by a READ request.

Assert:

- READ runs exactly once.
- The next chat call has no tools.
- State is unchanged.
- `ask()` terminates.

### Test 3: Model attempts repeated READ

Configure the fake model to request READ whenever tools are available.

Assert that the controller exposes tools only for the first READ and then
forces a no-tools response. The test must terminate without depending on
the model voluntarily stopping.

### Test 4: Mixed turn uses only WRITE

For:

```text
Water is 90 kmol/hr. What is the composition now?
```

Assert:

- Only the new Water flow is passed to WRITE.
- WRITE returns the normalized state.
- No subsequent READ occurs.
- Final prose is generated from the WRITE result.

### Test 5: RESET then WRITE

Assert that one turn may execute:

```text
RESET -> UPDATE -> no-tools finalization
```

and cannot execute a third tool.

### Test 6: UPDATE plus READ in one response

If one model response contains both calls, assert that UPDATE is executed
and READ is suppressed.

### Test 7: Duplicate fingerprint

Present the same tool name and arguments twice. Assert that it is executed
only once and the agent finalizes.

### Test 8: Hard call budget

Simulate pathological tool choices. Assert that the number of executed
tool calls never exceeds `MAX_TOOL_CALLS_PER_TURN` and `ask()` always
returns or raises a clear bounded error.

### Test 9: Existing deterministic tests remain green

Run:

```powershell
conda run -n pyfuel pytest `
  tools/chopper/test_feed_state.py `
  tools/chopper/test_binary_distillation_workflow.py `
  tools/chopper/test_binary_distillation_workflow_agent.py -q
```

## Prompt changes

Keep the READ/WRITE prompt rules, but add one concise statement explaining
the enforced lifecycle:

```text
Each user turn permits at most one engineering-state operation. Both READ
and WRITE return the full authoritative state. After either operation,
answer the user from that result; never request another state tool during
the same turn.
```

This prompt change improves model behavior, but it is not the loop fix.
The Python controller is the loop fix.

## Documentation updates

After implementation:

1. Update `tools/separation_tool.md` to list the current three workflow-agent
   tools rather than the obsolete `assess_binary_distillation` interface.
2. Document the per-turn state machine and hard tool-call budget.
3. Record the new workflow-agent test suite and its command.
4. Note that UPDATE returns the full state, so UPDATE followed by READ is
   intentionally suppressed.

## Acceptance criteria

The fix is complete when:

- `separate methanol and water` produces one UPDATE call followed by a
  user-facing response.
- A state question produces one READ call followed by a user-facing
  response.
- A mixed update/question turn produces one WRITE and no READ.
- RESET may be followed by one UPDATE for a new problem.
- No user turn can execute an unbounded number of tools.
- Repeated identical calls are detected and stopped.
- READ remains non-mutating and provenance remains unchanged.
- The consistency checker remains strict.
- No BioSTEAM calculation, sizing, or optimization becomes reachable from
  the workflow-only agent.
- Existing feed/workflow tests and the new orchestration tests all pass.

## Priority order

1. Force no-tools finalization after UPDATE or READ.
2. Add the hard per-turn tool-call budget.
3. Suppress redundant READ-after-WRITE and repeated READ.
4. Add mocked orchestration regression tests.
5. Update `separation_tool.md`.

The first three items remove the infinite loop even when Qwen ignores the
prompt. The remaining items prevent regression and bring the documentation
back into sync.
