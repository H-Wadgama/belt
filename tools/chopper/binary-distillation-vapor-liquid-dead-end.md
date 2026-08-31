I want you to modify the binary-distillation routing logic so that an initially two-phase feed no longer dead-ends immediately.

This task is ONLY about replacing the current `vapor_liquid -> stop` branch with reference-temperature conditioning. Do not refactor feed-screening readiness or Wankat-case readiness in this task.

## Current behavior

The current calculation pipeline does this after evaluating the feed phase at the user-specified feed conditions:

```text
feed
  ↓
evaluate_feed_phase()
  ↓
phase?
  ├─ liquid       → stop / future liquid-phase separation
  ├─ vapor        → reference-temperature HX/VLE screen at 313.15 K
  └─ vapor_liquid → stop as "two_phase_feed", not implemented
```

The `vapor_liquid` branch currently returns something like:

```python
{
    "route": "two_phase_feed",
    "implemented": False,
    "message": (
        "The feed is already a vapor-liquid mixture at the specified "
        "feed conditions. Routing of an initially two-phase feed is "
        "not implemented yet."
    ),
}
```

This is the behavior that must change.

---

# Goal

Change the routing so that:

```text
liquid
    ↓
stop as before

vapor
    ↓
reference-temperature conditioning at 313.15 K

vapor_liquid
    ↓
reference-temperature conditioning at 313.15 K
```

In other words:

> Any feed containing a vapor fraction should proceed through the existing rigorous BioSTEAM reference-temperature conditioning calculation.

The reference-temperature calculation should continue to use:

```python
REFERENCE_TEMPERATURE_K = 313.15
```

and the existing rigorous HX/VLE implementation.

Do NOT create a separate thermodynamic implementation for the initially two-phase case.

Reuse the same deterministic reference-temperature conditioning function already used for vapor feeds.

---

# Step 1 — Inspect the existing routing implementation

Before editing anything, locate:

- `calculate_binary_distillation_problem()` or equivalent main calculation entry point,
- the current `evaluate_feed_phase()` call,
- the current routing branch for:
  - `"liquid"`
  - `"vapor"`
  - `"vapor_liquid"`
- the reference-temperature conditioning function/module added previously,
- the current route/result schema,
- calculation-progress logic,
- tests covering vapor, liquid, and two-phase feed routing.

Identify the exact current branch where `vapor_liquid` returns the `two_phase_feed` stub.

Do not redesign unrelated code.

---

# Step 2 — Preserve the liquid-feed behavior exactly

If:

```python
feed_phase["phase"] == "liquid"
```

continue to stop immediately.

Do not run the reference-temperature HX/VLE calculation.

Continue to return the existing liquid-phase future-work route.

Conceptually:

```python
{
    "route": "liquid_phase_separation",
    "implemented": False,
    ...
}
```

Do not change this branch unless required for compatibility.

---

# Step 3 — Route both vapor and vapor-liquid feeds through the same conditioning function

Replace separate behavior for `"vapor"` and `"vapor_liquid"` with shared deterministic routing.

Conceptually:

```python
if feed_phase["phase"] == "liquid":
    return liquid_route

elif feed_phase["phase"] in ("vapor", "vapor_liquid"):
    conditioning = evaluate_vapor_feed_at_reference_temperature(...)
```

Use whatever function name currently exists.

If the function name is too vapor-specific, do NOT automatically rename it unless necessary. Prefer the smallest coherent change.

If renaming materially improves clarity and does not cause broad churn, a more general name such as:

```python
evaluate_feed_at_reference_temperature(...)
```

may be considered.

But preserving existing tested APIs is preferred.

---

# Step 4 — Use the overall feed stream, not only the initial vapor portion

For an initially two-phase feed, the reference-temperature conditioning step should evaluate the entire feed stream at 313.15 K.

Do NOT extract only the vapor phase and pass that vapor portion into the HX unless the existing BioSTEAM architecture explicitly requires that.

The intended calculation is:

```text
overall feed at original T/P
        ↓
copy overall feed
        ↓
set/evaluate at 313.15 K using rigorous HXutility
        ↓
new equilibrium liquid/vapor split
```

This lets BioSTEAM determine the final equilibrium state of the whole feed after conditioning.

---

# Step 5 — Preserve the initial phase-screening result

Do not overwrite the original feed-phase result.

The final structured result should contain both:

1. the phase state at the user's original feed conditions,
2. the phase state after reference-temperature conditioning.

For example:

```python
"checks": {
    "feed_phase": {
        "temperature_K": 355.0,
        "pressure_Pa": 101325.0,
        "phase": "vapor_liquid",
        "liquid_fraction": 0.25456,
        "vapor_fraction": 0.74544,
        ...
    },

    "reference_temperature_conditioning": {
        "target_temperature_K": 313.15,
        "liquid_fraction": ...,
        "vapor_fraction": ...,
        ...
    },

    "routing": {
        ...
    }
}
```

Follow existing key names if they already exist.

The important requirement is that both states remain inspectable.

---

# Step 6 — Keep reference-temperature conditioning deterministic

Use the existing rigorous BioSTEAM calculation.

Conceptually:

```python
heatex = bst.units.HXutility(
    ins=feed_copy,
    T=313.15,
    rigorous=True,
)

heatex.simulate()
```

Do not:

- manually calculate the VLE split,
- let Qwen estimate condensation,
- assume complete condensation,
- infer final phase from temperature alone.

BioSTEAM remains the physical source of truth.

---

# Step 7 — Preserve cooling/heating reporting

The conditioning step should continue reporting whether moving to 313.15 K corresponds to:

```python
"cooling"
```

if:

```python
initial_T > 313.15
```

or:

```python
"heating"
```

if:

```python
initial_T < 313.15
```

or:

```python
"none"
```

if equal.

This applies equally to an initially vapor-liquid feed.

Do not assume a two-phase feed is always cooled.

---

# Step 8 — Apply the existing 50% liquid criterion after conditioning

Do not apply the 50% rule to the original feed-phase result.

The routing threshold must be applied to the result AFTER conditioning at 313.15 K.

Use:

```python
if conditioned_liquid_fraction >= 0.50:
    ...
else:
    ...
```

Exactly 50 mol% liquid belongs to the `>= 0.50` branch.

---

# Step 9 — >=50% liquid after conditioning

If the conditioned stream has:

```python
liquid_fraction >= 0.50
```

retain the existing routing semantics for substantial condensation.

Report:

- X mol% is liquid at 313.15 K,
- this liquid fraction will eventually undergo liquid-phase separation,
- Y mol% remains vapor,
- this vapor fraction will eventually undergo vapor-phase separation,
- both downstream separation calculations are not implemented yet.

Use the existing route name if already implemented, such as:

```python
"liquid_and_vapor_separation_future"
```

Do not implement either downstream separator.

---

# Step 10 — <50% liquid after conditioning

If:

```python
liquid_fraction < 0.50
```

retain the existing majority-vapor routing logic.

Report:

- X mol% remains vapor at 313.15 K,
- Y mol% is liquid if useful,
- less than 50 mol% liquefied,
- vapor-phase separation is advisable,
- vapor-phase separation is not implemented yet.

Use the existing stable route name if available, such as:

```python
"vapor_separation_advisable"
```

Do not execute any vapor separator.

---

# Step 11 — Remove the two-phase dead-end route from active execution

The route:

```python
"two_phase_feed"
```

should no longer be the normal outcome for an initially two-phase feed.

A feed initially classified as `"vapor_liquid"` should proceed into reference-temperature conditioning.

If the `two_phase_feed` route constant/schema is used elsewhere, do not delete it blindly.

First inspect references.

If it is now truly unreachable and safe to remove, remove it cleanly.

If it is retained for backward compatibility, make sure it is no longer used by the normal calculation path.

---

# Step 12 — Update calculation progress

Previously, an initially two-phase feed likely produced something like:

```python
{
    "completed_steps": [
        "feed_phase",
    ],
    "remaining_steps": [
        "two_phase_feed_routing",
    ],
    "blocked_reason": "not_implemented",
}
```

That is no longer correct.

For both initially vapor and initially vapor-liquid feeds, successful conditioning should result in:

```python
"completed_steps": [
    "feed_phase",
    "vapor_condensation_screen",
]
```

or whatever existing step ID is already used for the 313.15 K conditioning.

Then:

### If conditioned liquid fraction >=50%

```python
{
    "completed_steps": [
        "feed_phase",
        "vapor_condensation_screen",
    ],
    "next_step": None,
    "next_step_available": False,
    "remaining_steps": [
        "liquid_phase_separation",
        "vapor_phase_separation",
    ],
    "blocked_reason": "not_implemented",
}
```

### If conditioned liquid fraction <50%

```python
{
    "completed_steps": [
        "feed_phase",
        "vapor_condensation_screen",
    ],
    "next_step": None,
    "next_step_available": False,
    "remaining_steps": [
        "vapor_phase_separation",
    ],
    "blocked_reason": "not_implemented",
}
```

Do not invent a new two-phase-progress branch.

---

# Step 13 — Preserve original feed immutability

This is especially important for initially two-phase feeds.

The conditioning calculation must use a copy/temporary stream.

After the calculation, the original feed should still represent the user's actual feed conditions.

For example, if the user supplied:

```python
T = 355.0
P = 101325.0
```

then after conditioning at 313.15 K, the original feed should still retain:

```python
T == 355.0
P == 101325.0
```

as well as the same total component flows.

Do not mutate the authoritative feed into the conditioned feed.

---

# Step 14 — Preserve both initial and conditioned phase fractions

For an initially two-phase feed, the result should make it possible to distinguish:

```python
initial_liquid_fraction
initial_vapor_fraction
```

from:

```python
conditioned_liquid_fraction
conditioned_vapor_fraction
```

Do not reuse ambiguous fields at the same dictionary level if doing so would overwrite one set.

The result should support an explanation like:

```text
At the original feed conditions of 355 K and 101325 Pa,
the feed was 25.5 mol% liquid and 74.5 mol% vapor.

After conditioning the overall feed to 313.15 K,
the equilibrium split becomes X mol% liquid and Y mol% vapor.

Based on the conditioned split, ...
```

The numbers themselves must come from Python/BioSTEAM.

---

# Step 15 — Keep Qwen out of the routing decision

Do not add prompt logic such as:

```text
If the feed seems substantially vaporized, consider cooling it...
```

The branch must happen entirely in Python.

Qwen may explain the structured result after the tool returns.

Qwen must not decide:

- whether an initially two-phase feed should be conditioned,
- whether the 50% threshold is met,
- which final route is selected.

---

# Step 16 — Add/modify tests

Update the existing two-phase routing tests.

At minimum add the following tests.

## Test A — Initially two-phase feed no longer stops

Construct or use an existing feed that evaluates as:

```python
phase == "vapor_liquid"
```

at the original feed conditions.

Verify:

- the reference-temperature conditioning function IS called,
- the result does not return the old immediate `two_phase_feed` route,
- the conditioning result is present,
- routing is based on the conditioned phase split.

---

## Test B — Preserve original feed-phase result

For an initially two-phase feed, assert that:

```python
checks["feed_phase"]["phase"] == "vapor_liquid"
```

and its original fractions remain available after conditioning.

---

## Test C — Conditioned >=50% liquid

Mock or construct a two-phase initial feed whose conditioned result gives:

```python
liquid_fraction >= 0.50
```

Verify:

- final route is the liquid+vapor future-separation route,
- both conditioned fractions are reported,
- remaining steps include liquid- and vapor-phase separation.

---

## Test D — Conditioned <50% liquid

Mock or construct a two-phase initial feed whose conditioned result gives:

```python
liquid_fraction < 0.50
```

Verify:

- final route is the vapor-separation-advisable route,
- vapor-phase separation is marked unimplemented,
- remaining steps contain vapor-phase separation.

---

## Test E — Exactly 50%

Verify:

```python
conditioned_liquid_fraction == 0.50
```

enters the `>= 0.50` branch.

---

## Test F — Original feed is unchanged

For an initially two-phase feed:

1. record original `T`,
2. record original `P`,
3. record component molar flows,
4. run conditioning,
5. verify all original values are unchanged.

---

## Test G — Initial vapor behavior still works

Existing pure-vapor routing must remain unchanged.

A vapor feed should still run the same reference-temperature conditioning function and produce the same structured route as before.

---

## Test H — Initial liquid behavior still works

A fully liquid feed should still skip the conditioning HX entirely.

Patch/mock the conditioning function and assert it is not called.

---

## Test I — Conditioning failure

Force the rigorous HX/VLE conditioning calculation to fail for an initially two-phase feed.

Verify:

- a deterministic error result is returned,
- no final separation route is fabricated,
- Qwen is not required to infer what happened.

---

## Test J — Calculation progress

Verify that an initially two-phase feed now records both:

```python
"feed_phase"
```

and:

```python
"vapor_condensation_screen"
```

as completed after successful conditioning.

Verify that:

```python
"two_phase_feed_routing"
```

is no longer reported as the remaining blocked step.

---

## Test K — "what next?" continuity

After completing the two-phase -> conditioning route, exercise the existing follow-up behavior.

A later:

```text
what next?
```

should use the stored conditioned routing result.

It must not:

- rerun the HX unnecessarily,
- fall back to the old `two_phase_feed` message,
- forget the conditioned liquid/vapor fractions.

---

# Step 17 — Use the existing ethanol/water example as an integration regression

Use the existing example that already produces an initially two-phase feed:

```text
Water + Ethanol
50 kmol/hr Ethanol
50 kmol/hr Water
T = 355 K
P = 101325 Pa
```

The current feed-phase calculation produces approximately:

```python
phase = "vapor_liquid"
liquid_fraction ≈ 0.25456
vapor_fraction ≈ 0.74544
```

Do not hard-code these values into production code.

Use this case as an integration test or manual regression check.

Expected behavior after this change:

```text
355 K / 101325 Pa
        ↓
initial BioSTEAM VLE
        ↓
~25.5% liquid / ~74.5% vapor
        ↓
DO NOT STOP
        ↓
condition overall feed to 313.15 K
using rigorous HXutility
        ↓
BioSTEAM determines new L/V split
        ↓
apply 50% conditioned-liquid threshold
        ↓
return deterministic downstream route
```

The test should verify the routing sequence, not necessarily exact final conditioned fractions unless they are stable enough for the installed BioSTEAM version.

Use numerical tolerances where appropriate.

---

# Step 18 — Do not expand scope

Do NOT implement:

- liquid-phase separation calculations,
- vapor-phase separation calculations,
- actual separator equipment,
- Wankat Case A design calculations,
- column stages,
- condenser/reboiler duties,
- feed-readiness refactoring,
- case-readiness refactoring,
- new extraction logic,
- Qwen prompt redesign.

Those are separate tasks.

This change ends after:

```text
initial phase
    ↓
optional reference-temperature conditioning
    ↓
conditioned phase split
    ↓
future-route determination
```

---

# Target architecture after this task

```text
USER-SPECIFIED FEED
        ↓
BioSTEAM feed-phase calculation
at original T and P
        ↓
                phase
         /        |        \
        /         |         \
    LIQUID    VAPOR-LIQUID   VAPOR
      │            │           │
      ↓            └─────┬─────┘
stop / future            ↓
liquid route       copy overall feed
                          ↓
                 HXutility @ 313.15 K
                    rigorous=True
                          ↓
                  equilibrium L/V split
                          ↓
                 liquid_fraction >= 0.50?
                      /            \
                    yes             no
                     │               │
                     ↓               ↓
              liquid + vapor     vapor-phase
              future routes      separation
                                 advisable
```

---

# Definition of done

This task is complete when:

1. An initially two-phase feed no longer stops immediately.
2. Both initially vapor and initially vapor-liquid feeds run the same reference-temperature conditioning pathway.
3. The entire overall feed is conditioned, not only its initial vapor portion.
4. The initial feed-phase result remains stored and inspectable.
5. The conditioned result is stored separately.
6. The 50% routing threshold is applied only to the conditioned liquid fraction.
7. Initially liquid feeds still skip the HX.
8. Original feed state remains unchanged.
9. Calculation progress no longer contains the old two-phase dead-end.
10. `"what next?"` uses the stored conditioned result.
11. Failures remain deterministic.
12. Existing vapor/liquid behavior still passes its tests.
13. New two-phase-conditioning tests pass.
14. No unrelated architecture is refactored.

---

# Implementation workflow

Please work systematically:

1. Inspect the current routing code.
2. Identify the exact old `vapor_liquid` dead-end branch.
3. Identify the existing reference-temperature conditioning function.
4. Modify the branch so `vapor` and `vapor_liquid` share the conditioning pathway.
5. Preserve the initial feed-phase result.
6. Update calculation-progress logic.
7. Update/remove the old two-phase route only where safe.
8. Add focused tests.
9. Run the relevant test subset.
10. Run the full chopper test suite.
11. Report:
   - exact files changed,
   - exact behavior changed,
   - tests added/updated,
   - test results,
   - whether the old `two_phase_feed` route remains anywhere and why,
   - any BioSTEAM behavior that required adaptation.

Do not proceed to the separate feed-screening-readiness architecture refactor in this task.