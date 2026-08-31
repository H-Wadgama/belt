I want you to fix one specific routing edge case in the binary-distillation reference-temperature conditioning logic.

Do NOT refactor workflow readiness, Wankat case logic, extraction, or Qwen behavior in this task.

## Current problem

After reference-temperature conditioning at 313.15 K, the code currently applies a rule like:

```python
if liquid_fraction >= 0.50:
    route to future liquid + vapor separation
else:
    route to future vapor-phase separation
```

This incorrectly treats complete condensation the same as partial condensation.

Example:

```python
liquid_fraction = 1.0
vapor_fraction = 0.0
```

currently gets routed as though both liquid and vapor downstream separation pathways are needed.

That is physically inconsistent because no meaningful vapor stream remains.

---

# Goal

Introduce a deterministic complete-condensation edge case.

Desired routing after the 313.15 K conditioning result is:

```text
conditioned phase split
        ↓
is vapor fraction effectively zero?
        ├── yes
        │     ↓
        │  liquid-phase separation only
        │
        └── no
              ↓
        is liquid fraction >= 0.50?
              ├── yes
              │     ↓
              │  liquid + vapor future separation
              │
              └── no
                    ↓
                 vapor-phase separation advisable
```

Use a numerical phase tolerance rather than exact equality.

---

# Step 1 — Inspect the current routing function

Locate the exact deterministic function that receives the conditioned liquid/vapor fractions after the 313.15 K BioSTEAM calculation.

Identify:

- the current `liquid_fraction >= 0.50` branch,
- route names currently returned,
- structured result fields,
- calculation-progress construction,
- tests covering:
  - `<50%`
  - `>=50%`
  - exactly `50%`
  - the new ethanol/water example that reaches `100% liquid`.

Do not modify anything yet.

---

# Step 2 — Add or reuse a phase tolerance

Check whether the codebase already defines a tolerance for deciding whether a phase fraction is effectively zero.

If one already exists, reuse it.

If not, introduce a small deterministic constant in the most appropriate existing module, for example:

```python
PHASE_FRACTION_TOLERANCE = 1e-9
```

Do not hard-code exact equality such as:

```python
vapor_fraction == 0.0
```

because thermodynamic calculations may return tiny values such as:

```python
2.4e-12
```

for an effectively absent phase.

Use the same tolerance consistently in routing and tests.

---

# Step 3 — Add the complete-condensation branch before the 50% branch

Change the routing order so complete condensation is checked first.

Conceptually:

```python
if vapor_fraction <= PHASE_FRACTION_TOLERANCE:
    # effectively fully liquid after conditioning
    ...

elif liquid_fraction >= 0.50:
    # genuine two-phase result with substantial liquid fraction
    ...

else:
    # majority vapor
    ...
```

The order matters.

Do not write:

```python
if liquid_fraction >= 0.50:
```

first, because `1.0` would still enter the mixed liquid+vapor branch.

---

# Step 4 — Define the complete-condensation route

For:

```python
vapor_fraction <= PHASE_FRACTION_TOLERANCE
```

return a deterministic route representing future liquid-phase separation only.

Prefer reusing the existing liquid route name if its semantics are compatible, for example:

```python
"liquid_phase_separation"
```

or the actual stable route identifier already used in the codebase.

Do not create a new route name unless necessary.

The result should clearly indicate:

```python
{
    "route": "liquid_phase_separation",
    "implemented": False,
    "liquid_fraction": ...,
    "vapor_fraction": ...,
    "message": ...
}
```

Use existing schema conventions.

---

# Step 5 — Use physically accurate message wording

For effectively complete condensation, do NOT say:

```text
substantial partial condensation
```

Instead use wording conceptually like:

```text
At 313.15 K, the conditioned stream is effectively fully liquid.
No meaningful vapor phase remains.
The next downstream pathway is liquid-phase separation, which is not yet implemented.
```

Keep the message deterministic in Python.

Qwen should only present this returned result.

---

# Step 6 — Do not create a vapor downstream step when no vapor remains

For complete condensation:

```python
vapor_fraction <= tolerance
```

the result must NOT include future vapor separation as a remaining step.

Expected progress should be conceptually:

```python
{
    "completed_steps": [
        "feed_phase",
        "vapor_condensation_screen",
    ],
    "remaining_steps": [
        "liquid_phase_separation",
    ],
    "blocked_reason": "not_implemented",
    "next_step": None,
    "next_step_available": False,
}
```

Use the actual existing step IDs.

The key requirement is:

```python
"vapor_phase_separation"
```

must not appear in `remaining_steps` when the vapor fraction is effectively zero.

---

# Step 7 — Preserve the existing genuine partial-condensation branch

Do not break this case:

```python
liquid_fraction >= 0.50
vapor_fraction > PHASE_FRACTION_TOLERANCE
```

Example:

```python
liquid_fraction = 0.70
vapor_fraction = 0.30
```

This should continue to route to both future pathways:

```text
liquid-phase separation
+
vapor-phase separation
```

No behavior change is intended for genuine two-phase conditioned streams.

---

# Step 8 — Preserve exactly-50% behavior

The existing threshold interpretation remains:

```python
liquid_fraction >= 0.50
```

belongs to the substantial-condensation branch, provided meaningful vapor still remains.

Example:

```python
liquid_fraction = 0.50
vapor_fraction = 0.50
```

must continue to route to both liquid and vapor future separation pathways.

Do not change the threshold definition.

---

# Step 9 — Preserve the <50% branch

Example:

```python
liquid_fraction = 0.25
vapor_fraction = 0.75
```

must continue to route to:

```text
vapor-phase separation advisable
```

Do not alter this behavior.

---

# Step 10 — Consider the symmetric all-vapor condition

Inspect whether the existing `<50% liquid` branch already handles:

```python
liquid_fraction <= PHASE_FRACTION_TOLERANCE
```

correctly.

If:

```python
liquid_fraction ≈ 0
vapor_fraction ≈ 1
```

the existing vapor-separation route is probably already semantically correct.

Do not add a new branch unless required for clarity or schema consistency.

This task is primarily about the complete-liquid edge case.

---

# Step 11 — Update calculation-progress logic

Locate any progress-building code that currently assumes:

```python
liquid_fraction >= 0.50
```

means both liquid and vapor separation remain.

Update it so progress uses the same routing classification as the main calculation result.

Do not duplicate the branching logic independently if avoidable.

Prefer one deterministic classification/result that both:

```python
calculate_binary_distillation_problem()
```

and:

```python
build_calculation_progress()
```

consume.

If the existing architecture currently duplicates the condition, make the smallest safe change necessary so the two cannot disagree.

---

# Step 12 — Add regression test for complete condensation

Use the current Water/Ethanol integration case if it reliably produces complete condensation after conditioning:

```text
Water + Ethanol
50 kmol/hr Water
50 kmol/hr Ethanol
T = 355 K
P = 101325 Pa
reference conditioning T = 313.15 K
```

The recent run produced:

```python
conditioned_liquid_fraction = 1.0
conditioned_vapor_fraction = 0.0
```

Verify that after this patch:

```python
route == "liquid_phase_separation"
```

or the equivalent existing route identifier.

Also verify:

```python
"liquid_phase_separation" in remaining_steps
```

and:

```python
"vapor_phase_separation" not in remaining_steps
```

Do not hard-code exact thermodynamic fractions into production logic.

Use numerical tolerances in tests if needed.

---

# Step 13 — Add a near-zero-vapor tolerance test

Test something like:

```python
liquid_fraction = 0.999999999999
vapor_fraction = 1e-12
```

assuming this lies within the chosen tolerance.

Expected:

```text
liquid-phase separation only
```

This proves the implementation is not dependent on exact `0.0`.

---

# Step 14 — Add a just-above-tolerance test

Construct a result where vapor is small but intentionally above tolerance.

For example, if:

```python
PHASE_FRACTION_TOLERANCE = 1e-9
```

test something like:

```python
vapor_fraction = 1e-6
liquid_fraction = 0.999999
```

Expected:

```text
liquid + vapor future separation
```

because a meaningful nonzero vapor phase remains according to the deterministic tolerance.

This verifies the boundary.

---

# Step 15 — Retain all existing threshold tests

Make sure these still pass:

```python
liquid_fraction = 0.49
vapor_fraction = 0.51
```

→ vapor separation advisable

```python
liquid_fraction = 0.50
vapor_fraction = 0.50
```

→ liquid + vapor future separation

```python
liquid_fraction = 0.75
vapor_fraction = 0.25
```

→ liquid + vapor future separation

```python
liquid_fraction = 1.0
vapor_fraction = 0.0
```

→ liquid separation only

These four cases should make the routing semantics explicit.

---

# Step 16 — Verify the structured result and Qwen-facing message

After the patch, manually run the existing conversation through the agent.

For the ethanol/water case, the deterministic tool result should conceptually say:

```python
{
    "liquid_fraction": 1.0,
    "vapor_fraction": 0.0,
    "route": "liquid_phase_separation",
    "implemented": False,
    "message": (
        "At 313.15 K, the conditioned feed is effectively fully liquid. "
        "No meaningful vapor phase remains. "
        "Liquid-phase separation is the next future pathway, but it is not yet implemented."
    )
}
```

Then confirm Qwen does not say:

```text
substantial partial condensation
```

and does not mention a residual vapor separation pathway.

If Python is correct but Qwen still invents a vapor pathway, record that as a separate presentation-grounding bug.

Do not fix broader Qwen grounding in this task unless an extremely small wording update is necessary to reflect the new route.

---

# Step 17 — Do not expand scope

Do NOT modify:

- feed-screening readiness,
- Wankat-case readiness,
- case classification,
- Qwen extraction behavior,
- missing-temperature handling,
- pending-request resolution,
- `QR`/`Qc` presentation issues,
- liquid separator implementation,
- vapor separator implementation,
- full column design.

Those belong to separate tasks.

---

# Target routing logic after this task

```text
conditioned stream at 313.15 K
            ↓
vapor_fraction <= phase tolerance?
        /                \
      yes                 no
       ↓                   ↓
fully/effectively     liquid_fraction >= 0.50?
liquid                 /               \
       ↓             yes                no
liquid-phase            ↓                 ↓
separation only     liquid + vapor      vapor-phase
                   future pathways      separation
                                        advisable
```

---

# Definition of done

This task is complete when:

1. Complete condensation no longer routes to both liquid and vapor separation.
2. Near-zero vapor fractions are treated using a numerical tolerance.
3. A completely/effectively liquid conditioned stream routes only to future liquid-phase separation.
4. `"vapor_phase_separation"` is absent from progress for complete condensation.
5. Genuine partial condensation with meaningful vapor still routes to both downstream pathways.
6. Exactly 50% liquid remains in the dual-path branch.
7. <50% liquid behavior remains unchanged.
8. Existing vapor and two-phase conditioning tests still pass.
9. New complete-condensation and tolerance-boundary tests pass.
10. The full `tools/chopper` suite passes.
11. No unrelated workflow architecture is changed.

---

# Implementation workflow

Please:

1. Inspect the current conditioned-stream routing function.
2. Find or define the phase-fraction tolerance.
3. Add the complete-condensation branch before the 50% branch.
4. Update progress logic consistently.
5. Add focused unit tests.
6. Add/update the Water/Ethanol regression test.
7. Run the focused tests.
8. Run the full chopper test suite.
9. Report:
   - exact files changed,
   - chosen tolerance and why,
   - final route names,
   - tests added/updated,
   - full test results,
   - confirmation that the 100%-liquid case no longer leaves vapor separation pending.

Do not proceed to any larger architectural refactor after completing this change.