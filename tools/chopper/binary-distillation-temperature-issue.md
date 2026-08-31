I want you to fix a reproducible Qwen tool-use failure involving explicit feed temperature.

This task is ONLY about reliably capturing an explicitly stated feed temperature and writing it into binary-distillation state.

Do NOT refactor Wankat readiness, feed-screening readiness, BioSTEAM physics, routing, case logic, or downstream calculations in this task.

## Reproducible failure

This user message:

```text
Separate water and ethanol at 355 K and 101325 Pa pressure.
The feed composition is 50 kmol/hr ethanol and 50 kmol/hr water,
and the reflux is saturated liquid.
```

currently leads Qwen to call:

```python
update_binary_distillation_problem({
    'component_flows': {'Ethanol': 50, 'Water': 50},
    'total_flow': 100,
    'total_flow_units': 'kmol/hr',
    'pressure_Pa': 101325,
    'reflux_condition': 'saturated_liquid',
    'component_names': ['Water', 'Ethanol']
})
```

but it incorrectly omits:

```python
'feed_temperature_K': 355
```

Then, when the user says:

```text
I think I specified the feed temperature as 355 K
```

Qwen sometimes performs a READ:

```python
get_binary_distillation_problem({})
```

instead of the required corrective WRITE:

```python
update_binary_distillation_problem({
    'feed_temperature_K': 355
})
```

This is the bug to fix.

---

# Goal

After this task, whenever the user explicitly states a feed temperature in Kelvin, Qwen should reliably include it in the WRITE.

For example:

```text
at 355 K
feed temperature is 355 K
the feed is at 355 K
temperature = 355 K
I already said 355 K
I think I specified the feed temperature as 355 K
```

should all result in:

```python
feed_temperature_K = 355
```

when the value clearly refers to the feed thermal condition.

The system should not require the user to repeat the same value multiple times.

---

# Step 1 — Inspect the current agent/tool-selection path

Before editing anything, inspect:

- `tools/chopper/binary_distillation_workflow_agent.py`
- the system prompt
- tool docstrings/schema exposed to Qwen
- any deterministic short-reply or pending-request resolver
- the code that chooses between:
  - `update_binary_distillation_problem`
  - `get_binary_distillation_problem`
- tests for extraction and short/corrective replies

Identify exactly where the temperature value can be lost:

1. prompt interpretation,
2. tool-argument generation,
3. deterministic resolver,
4. schema mismatch,
5. tool-selection logic.

Do not assume the cause before inspecting.

---

# Step 2 — Confirm the update tool already supports `feed_temperature_K`

Verify that the update function accepts:

```python
feed_temperature_K
```

and that writing:

```python
update_binary_distillation_problem({
    "feed_temperature_K": 355
})
```

correctly stores the value.

If this already works, do not change the state schema.

This task should fix extraction/tool use, not the storage model.

---

# Step 3 — Strengthen the agent instruction for explicit engineering facts

Update the agent prompt/tool-use instructions so that:

> Every explicitly stated recognized engineering quantity must be included in the same WRITE when first provided.

Add a rule conceptually like:

```text
When the user explicitly states a recognized field and value, include it in
update_binary_distillation_problem immediately.

Do not omit an explicit value merely because other fields are also present.

Example:
"at 355 K and 101325 Pa"
must produce both:
feed_temperature_K = 355
pressure_Pa = 101325
```

Keep this concise and deterministic.

Do not add broad natural-language reasoning instructions.

---

# Step 4 — Add explicit temperature examples to the tool schema/docstring

In the update tool description, add examples showing that these phrases map to:

```python
feed_temperature_K
```

Examples:

```text
"feed temperature is 355 K"
→ feed_temperature_K=355

"at 355 K and 101325 Pa"
→ feed_temperature_K=355, pressure_Pa=101325

"the feed enters at 400 K"
→ feed_temperature_K=400
```

The key purpose is to teach Qwen that a bare operating-temperature phrase in the feed problem should not be ignored.

Do not imply conversion from Celsius in this task unless Celsius handling already exists and is tested.

---

# Step 5 — Add a deterministic corrective-write resolver

Inspect the existing `pending_request` / short-reply resolver.

If the current state is missing only a feed thermal condition and the new user message contains an explicit temperature, deterministically convert that message into a WRITE.

Examples:

```text
I think I specified the feed temperature as 355 K
Feed temperature is 355 K
It was 355 K
355 K
I already said 355 K
```

should resolve to:

```python
update_binary_distillation_problem({
    "feed_temperature_K": 355
})
```

rather than a READ.

The resolver should run before Qwen chooses a tool, consistent with the existing deterministic pending-request architecture.

---

# Step 6 — Make the resolver context-sensitive

Do not treat every number followed by `K` as feed temperature in every possible context.

Use the live deterministic state.

Only auto-resolve to `feed_temperature_K` when one of the following is true:

1. the live missing/pending field is the feed thermal condition, or
2. the user explicitly says "feed temperature", "feed is at", or equivalent unambiguous wording.

Examples that SHOULD resolve:

```text
355 K
```

when the pending field is feed thermal condition.

```text
feed temperature is 355 K
```

even if no pending request exists.

Examples that should NOT blindly resolve without context:

```text
the condenser operates at 355 K
```

```text
the bottoms temperature is 355 K
```

if those fields are not supported or refer to another quantity.

---

# Step 7 — Do not use READ when the user supplies a missing value

Add an explicit agent rule:

```text
If the user message supplies a value for a currently missing recognized field,
perform a WRITE, not a READ.
```

A READ is appropriate for questions like:

```text
What temperature do you currently have stored?
What information is missing?
What case is this?
```

A WRITE is appropriate for:

```text
The feed temperature is 355 K.
I already said 355 K.
Use 355 K.
```

This distinction should be covered in tests.

---

# Step 8 — Preserve broad extraction in multi-field messages

The initial message should result in one WRITE containing all recognized explicit facts.

Expected first WRITE:

```python
{
    "component_names": ["Water", "Ethanol"],
    "component_flows": {
        "Ethanol": 50,
        "Water": 50,
    },
    "component_flow_units": "kmol/hr",
    "total_flow": 100,
    "total_flow_units": "kmol/hr",
    "feed_temperature_K": 355,
    "pressure_Pa": 101325,
    "reflux_condition": "saturated_liquid",
}
```

Use the exact currently supported schema.

If `component_flow_units` is not currently supported or normalized elsewhere, do not expand scope in this task.

The central assertion is that `feed_temperature_K=355` must be present.

---

# Step 9 — Add exact regression test for the original failure

Use this exact user utterance:

```text
Separate water and ethanol at 355 K and 101325 Pa pressure.
The feed composition is 50 kmol/hr ethanol and 50 kmol/hr water,
and the reflux is saturated liquid
```

Assert that the first tool call is:

```python
update_binary_distillation_problem(...)
```

and that its arguments include:

```python
feed_temperature_K == 355
pressure_Pa == 101325
```

Also verify the temperature is not omitted.

Do not assert irrelevant argument ordering.

---

# Step 10 — Add corrective-write regression tests

Test the following sequence:

Initial state:
```python
feed_temperature_K is missing
```

Then user says:

```text
I think I specified the feed temperature as 355 K
```

Expected:

```python
update_binary_distillation_problem({
    "feed_temperature_K": 355
})
```

NOT:

```python
get_binary_distillation_problem({})
```

Add equivalent tests for:

```text
Feed temperature is 355 K
```

```text
It is 355 K
```

when feed thermal condition is the live pending field.

```text
355 K
```

when feed thermal condition is the live pending field.

---

# Step 11 — Add READ-vs-WRITE distinction test

Test:

```text
What feed temperature do you currently have stored?
```

Expected:
READ/getter.

Then test:

```text
The feed temperature is 355 K.
```

Expected:
WRITE/updater.

This prevents the fix from turning every temperature-related sentence into an update.

---

# Step 12 — Add multi-value extraction test

Test a sentence like:

```text
The feed is 50 kmol/hr ethanol and 50 kmol/hr water at 355 K and 101325 Pa.
```

Verify one WRITE contains:

```python
component_flows
feed_temperature_K
pressure_Pa
```

This guards against the current behavior where pressure is captured but temperature is dropped.

---

# Step 13 — Add punctuation/typo robustness tests

Because the actual user interaction included typos, test common forms such as:

```text
Feed temperaturee is 355 K!
```

and:

```text
feed temp is 355 K
```

If the existing model-based extraction handles these naturally, regression-test them at the agent level.

Do not build a giant regex grammar for arbitrary language unless required.

---

# Step 14 — Prefer deterministic parsing for pending numeric replies

If the current pending resolver already parses short numeric replies, extend it minimally so a pending feed thermal condition can recognize:

```text
355 K
```

and optionally:

```text
355
```

ONLY if the pending request explicitly identifies the expected field as `feed_temperature_K` and the current architecture already permits unitless short replies.

Do not introduce unit assumptions if the current workflow forbids them.

If unitless replies are not currently allowed, keep requiring `K`.

---

# Step 15 — Preserve exactly-one-thermal-spec behavior

Do not weaken the existing rule that the feed thermal condition is specified by exactly one of:

```python
feed_temperature_K
feed_quality
feed_enthalpy_kJ_per_hr
```

The fix must not automatically add temperature if the user explicitly supplies a different thermal specification instead.

Examples:

```text
feed quality is 0.5
```

should remain `feed_quality`.

```text
feed enthalpy is ...
```

should remain feed enthalpy.

This task only fixes missed explicit temperature.

---

# Step 16 — Handle conflicting thermal specifications deterministically

If the user says something like:

```text
feed temperature is 355 K and feed quality is 0.4
```

do not silently choose one.

Preserve the current workflow's conflict/validation behavior.

The extraction layer should capture both explicit facts if the schema permits it, and deterministic validation should reject or request clarification according to current rules.

Do not have Qwen arbitrarily decide which one wins.

---

# Step 17 — Do not infer temperature from unrelated numbers

Add a negative regression test.

For example:

```text
The pressure is 101325 Pa and the reflux ratio is 2.
```

must not produce:

```python
feed_temperature_K
```

Likewise:

```text
xD = 0.95
```

must not be interpreted as a temperature.

---

# Step 18 — Keep deterministic state authoritative

After a successful corrective WRITE:

```python
feed_temperature_K = 355
```

verify the raw tool result reports:

```python
essential_complete == True
```

assuming all other essential fields are already present.

The agent must then respond from that returned state.

Do not let Qwen continue claiming the thermal condition is missing after the WRITE succeeds.

---

# Step 19 — Keep diagnostic logging available during testing

Retain the current raw-tool-result debug logging while implementing this change.

Use it to verify:

```text
user sentence
↓
tool selected
↓
arguments sent
↓
raw deterministic result
↓
Qwen response
```

This task is specifically about the first two transitions, so keep them observable.

Do not remove diagnostic logging as part of this change.

---

# Step 20 — Run focused and full tests

Run:

1. new temperature-extraction tests,
2. pending/corrective-reply tests,
3. agent tool-selection tests,
4. existing binary-distillation workflow tests,
5. full `tools/chopper` test suite.

All existing tests must continue to pass.

---

# Target behavior after this task

The original interaction should become:

```text
User:
Separate water and ethanol at 355 K and 101325 Pa pressure.
The feed composition is 50 kmol/hr ethanol and 50 kmol/hr water,
and the reflux is saturated liquid.

[calling update_binary_distillation_problem({
    ...
    'feed_temperature_K': 355,
    'pressure_Pa': 101325,
    ...
})]
```

The system should NOT ask for feed temperature again.

If temperature is somehow still missing and the user says:

```text
I think I specified the feed temperature as 355 K
```

the system should call:

```python
update_binary_distillation_problem({
    'feed_temperature_K': 355
})
```

immediately.

It should NOT call the getter first.

---

# Definition of done

This task is complete when:

1. The exact original sentence captures `feed_temperature_K=355` on the first WRITE.
2. Pressure and temperature can both be extracted from the same phrase.
3. A corrective statement containing an explicit temperature triggers a WRITE, not a READ.
4. Short replies like `355 K` resolve correctly when feed temperature is pending.
5. Temperature-related questions still use READ appropriately.
6. No temperature is fabricated when the user does not state one.
7. Existing exactly-one-thermal-spec validation remains intact.
8. No changes are made to Wankat case classification.
9. No changes are made to BioSTEAM or routing.
10. Focused tests pass.
11. Full `tools/chopper` suite passes.

---

# Report back

After implementation, report:

- exact files changed,
- root cause you identified,
- whether the fix was prompt-level, resolver-level, or both,
- tests added,
- focused test results,
- full-suite test results,
- the exact tool call now produced for the original 355 K / 101325 Pa sentence,
- the exact tool call now produced for:
  `I think I specified the feed temperature as 355 K`.

Do not proceed to any other architecture changes after completing this task.