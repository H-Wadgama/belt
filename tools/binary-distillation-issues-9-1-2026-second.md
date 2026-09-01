## Round 2 Follow-up — Fix field alias coverage and WRITE-first routing

Do NOT proceed to Round 3 yet.

Two distinct issues were observed in live testing.

### Issue 1 — state query alias coverage

This works:

```text
what is the pressure?
```

and resolves deterministically to:

```python
pressure_Pa = 101325
```

But this previously failed:

```text
what is the temperature?
```

even though:

```python
feed_temperature_K = 355
```

is stored.

Therefore the state-query architecture is functioning, but field alias coverage is incomplete.

Do not redesign the entire resolver.

Inspect how field names/aliases are matched.

Add semantic alias handling so these map to `feed_temperature_K`:

```text
temperature
feed temperature
temp
feed temp
```

Likewise verify aliases for:

```text
pressure
boilup ratio
reflux ratio
xD
xB
ethanol flow
water flow
reflux condition
```

Do not solve this by adding isolated one-off full-sentence regexes.

Prefer a field-alias registry or equivalent normalized mapping.

---

### Issue 2 — explicit engineering facts are not reliably triggering WRITE

Live failure:

```text
User:
boilup ratio is 2

Assistant:
generic free-text response
```

No tool call occurred.

This violates the intended controller invariant:

```text
NEW EXPLICIT ENGINEERING FACT
→ WRITE FIRST
```

The system must store newly supplied engineering facts before any general model response.

For:

```text
boilup ratio is 2
```

expected call:

```python
update_binary_distillation_problem({
    "boilup_ratio_VB": 2.0
})
```

Then return the newly assessed state.

Do NOT ask again for feed composition, flow, temperature, or pressure if those are already stored.

---

### Required routing priority

The main agent flow should enforce:

```text
1. pending-request deterministic resolution
2. new explicit engineering facts → WRITE
3. explicit proceed/calculation request
4. stored-state query → READ
5. progress / what-next query
6. only then normal constrained model response
```

If the current order differs, report it and change it narrowly.

---

### Field/value distinction

Use deterministic handling where practical:

```text
"what is the boilup ratio?"
→ READ

"boilup ratio is 2"
→ WRITE

"did I give a boilup ratio?"
→ READ

"set boilup ratio to 2"
→ WRITE
```

The same principle should apply to:

```text
pressure
temperature
xD
xB
Lr
Hr
external reflux ratio
reflux multiplier
distillate flow
bottoms flow
reflux condition
optimum feed plate
component flows
```

Do not attempt to support arbitrary chemical-engineering fields outside the current schema.

---

### Important architectural rule

The LLM may interpret language, but it must not decide to ignore an explicit supported engineering value.

Once a supported field/value pair is recognized, WRITE is mandatory.

Conceptually:

```python
if explicit_supported_update:
    return update_binary_distillation_problem(explicit_supported_update)
```

before normal free-form response generation.

---

### Tests

With a fresh state containing:

```text
Water = 50 kmol/hr
Ethanol = 50 kmol/hr
T = 355 K
P = 101325 Pa
reflux = saturated liquid
```

test:

```text
what is the pressure?
```

Expected:
101325 Pa.

Test:

```text
what is the temperature?
```

Expected:
355 K.

Test:

```text
what is the feed temp?
```

Expected:
355 K.

Test:

```text
boilup ratio is 2
```

Expected:
WRITE with:

```python
{"boilup_ratio_VB": 2.0}
```

and stored state must contain that value.

Test:

```text
what is the boilup ratio?
```

Expected:
READ returning 2.0.

Test:

```text
xD is 0.95
```

Expected:
WRITE.

Test:

```text
what is xD?
```

Expected:
READ.

Test that after:

```text
boilup ratio is 2
```

the assistant does NOT ask for already-known:

```text
feed composition
flow rate
temperature
pressure
```

Run focused tests and the full `tools/chopper` suite.

Report:

1. exact files changed;
2. existing state-query alias mechanism;
3. why temperature failed but pressure succeeded;
4. previous `ask()` routing order;
5. new routing order;
6. how explicit field/value updates are detected;
7. boilup-ratio live result;
8. test counts.

Do not proceed to Round 3.