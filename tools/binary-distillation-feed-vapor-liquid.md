I want you to implement the next deterministic routing layer in my binary-distillation calculation pipeline.

## Context

The current architecture is intentionally hierarchical:

- The LLM/Qwen interprets user intent and explains results.
- Deterministic Python owns workflow state and routing truth.
- BioSTEAM owns thermodynamic and physical calculations.
- The LLM must NOT decide engineering branches that can be decided deterministically.
- Right now, the implemented scope is deliberately narrow: binary-distillation preprocessing/routing only.
- If a downstream separation method is not implemented, stop deterministically and report that it is future work. Do not invent calculations.

The feed-phase check has already been implemented.

The next task is to add deterministic routing immediately after the feed-phase check.

---

# Goal

After the feed phase is determined:

1. If the feed is liquid:
   - Stop the calculation pipeline.
   - Report that the feed should proceed to liquid-phase separation.
   - Explicitly state that liquid-phase separation calculations are not implemented yet.
   - Do NOT run the 313.15 K heat-exchanger/VLE screening calculation.

2. If the feed is vapor:
   - Evaluate the feed at a reference temperature of 313.15 K, approximately 40 °C.
   - Use BioSTEAM `HXutility` with `rigorous=True` so that the resulting vapor/liquid equilibrium split is determined thermodynamically.
   - Determine what molar fraction of the outlet is liquid and what molar fraction is vapor.
   - Route based on the resulting liquid fraction.

3. If the feed is already vapor-liquid/two-phase:
   - For now, stop deterministically.
   - Report the existing liquid and vapor percentages.
   - State that routing of an initially two-phase feed is not implemented yet.
   - Do not silently treat it as a vapor feed.

---

# Important interpretation of the 50% rule

Use the following routing criterion:

```python
if liquid_fraction >= 0.50:
    # substantial partial condensation
else:
    # majority of material remains vapor
```

This is intentional.

The criterion should be based on the fraction that LIQUEFIES, not on a second independent `<50% vaporized` condition, because those conditions otherwise overlap.

Exactly 50 mol% liquid must enter the `>= 0.50` branch.

---

# Step 1 — Inspect the existing implementation first

Before changing code, inspect the relevant existing files and determine:

- where `calculate_binary_distillation_problem()` lives,
- where the current feed stream is constructed,
- where `evaluate_feed_phase()` lives,
- what exact dictionary/schema `evaluate_feed_phase()` currently returns,
- how calculation progress is represented,
- how calculation results are stored for later `"what next?"` queries,
- how BioSTEAM streams and chemicals are currently initialized,
- whether there are existing utilities for safely copying streams,
- existing unit/integration tests for the calculation layer.

Do NOT redesign unrelated architecture.

Preserve existing public interfaces unless a small additive extension is necessary.

---

# Step 2 — Add a deterministic vapor-feed reference-temperature screening function

Prefer creating a focused module/function rather than embedding all of the BioSTEAM logic directly inside the main calculation function.

A reasonable location/name would be something like:

```text
feed_partial_condensation.py
```

with a function similar in responsibility to:

```python
evaluate_vapor_feed_at_reference_temperature(...)
```

The exact filename may be adapted to the repository's existing organization.

Define constants rather than scattering magic numbers:

```python
REFERENCE_TEMPERATURE_K = 313.15
LIQUEFACTION_THRESHOLD = 0.50
```

The function should accept the existing BioSTEAM feed stream and evaluate it at the reference temperature.

---

# Step 3 — Do not mutate the authoritative/original feed stream

The reference-temperature screening operation must not unexpectedly change the canonical feed used by the rest of the calculation.

Create an appropriate copy/temporary stream before passing it through the HX.

Follow the repository's existing BioSTEAM stream-copy conventions if any already exist.

Add a test confirming that the original feed temperature, pressure, flow, and composition remain unchanged after the screening calculation.

---

# Step 4 — Use BioSTEAM HXutility for the thermodynamic screen

For a vapor feed, use the equivalent of:

```python
heatex = bst.units.HXutility(
    ins=feed_copy,
    T=313.15,
    rigorous=True,
)

heatex.simulate()
```

Adapt IDs/outlet handling to the project's BioSTEAM conventions.

The operation may either cool or heat the feed:

```python
if initial_T > 313.15:
    operation = "cooling"
elif initial_T < 313.15:
    operation = "heating"
else:
    operation = "none"
```

Do not manually calculate an equilibrium split if BioSTEAM can provide it.

BioSTEAM remains the thermodynamic source of truth.

---

# Step 5 — Determine liquid and vapor molar fractions robustly

After the HX simulation, determine:

```python
liquid_mol
vapor_mol
total_mol
liquid_fraction
vapor_fraction
```

where:

```python
liquid_fraction = liquid_mol / total_mol
vapor_fraction = vapor_mol / total_mol
```

Do NOT assume a phase-indexing API without first checking how the installed/current BioSTEAM version exposes phase-specific molar flows.

Inspect existing project usage and/or the installed BioSTEAM API before implementing this portion.

The implementation must correctly handle the actual outlet representation generated by `HXutility(..., rigorous=True)`.

Fractions should satisfy approximately:

```python
liquid_fraction + vapor_fraction == 1.0
```

within an appropriate numerical tolerance.

Handle zero-flow or malformed outlet cases deterministically.

For example, return an error object rather than allowing a division-by-zero exception or asking the LLM to interpret the failure.

---

# Step 6 — Return structured calculation truth, not only prose

The vapor-screening function should return structured information that downstream code and the LLM can consume.

Use the repository's existing result conventions where possible.

Conceptually, include fields such as:

```python
{
    "valid": True,
    "check": "vapor_feed_reference_temperature",
    "target_temperature_K": 313.15,
    "initial_temperature_K": ...,
    "operation": "cooling" | "heating" | "none",

    "liquid_fraction": ...,
    "vapor_fraction": ...,
    "liquid_percent": ...,
    "vapor_percent": ...,

    "route": ...,
    "implemented": False,
    "message": ...,
}
```

Do not make the LLM recompute percentages from raw stream data.

Python should calculate and store them.

---

# Step 7 — Implement the >=50% liquid branch

If:

```python
liquid_fraction >= 0.50
```

then report BOTH phases.

The deterministic result should communicate:

- X mol% of the feed is liquid at 313.15 K.
- That liquid fraction is intended to undergo a liquid-phase separation method.
- Liquid-phase separation calculations are not implemented yet.
- Y mol% remains vapor.
- That vapor fraction is intended to undergo a vapor-phase separation method.
- Vapor-phase separation calculations are not implemented yet.

Use a stable machine-readable route name, for example:

```python
"liquid_and_vapor_separation_future"
```

or another name consistent with existing project naming.

The percentages shown to the user should be generated from the structured deterministic values.

Do not continue into an imaginary separator calculation.

---

# Step 8 — Implement the <50% liquid branch

If:

```python
liquid_fraction < 0.50
```

then the majority of the feed remains vapor.

Report:

- X mol% remains vapor at 313.15 K.
- Y mol% has liquefied if useful for context.
- Since less than 50 mol% liquefies, a vapor-phase separation method is advisable.
- Vapor-phase separation calculations are not implemented yet.

Use a stable machine-readable route name such as:

```python
"vapor_separation_advisable"
```

Do not execute a vapor-phase separator because that pathway does not exist yet.

---

# Step 9 — Add routing to calculate_binary_distillation_problem()

Immediately after the existing feed-phase check, add deterministic branching.

Conceptually:

```python
feed_phase = evaluate_feed_phase(...)

checks = {
    "feed_phase": feed_phase,
}

if not feed_phase["valid"]:
    return deterministic_error_result
```

Then:

```python
if feed_phase["phase"] == "liquid":
    ...
elif feed_phase["phase"] == "vapor":
    ...
elif feed_phase["phase"] == "vapor_liquid":
    ...
else:
    ...
```

The LLM must never decide which of these branches to use.

`calculate_binary_distillation_problem()` should perform the transition automatically based on deterministic calculation results.

---

# Step 10 — Liquid-feed branch

For an initial liquid feed:

Do NOT call the HX reference-temperature screening function.

Return a structured routing result similar in meaning to:

```python
{
    "valid": True,
    "route": "liquid_phase_separation",
    "implemented": False,
    "message": (
        "The feed is liquid at the specified feed conditions. "
        "It should proceed to the liquid-phase separation pathway. "
        "Liquid-phase separation calculations are not implemented "
        "in this pipeline yet."
    ),
}
```

Adapt wording/schema to existing project conventions.

This is a successful calculation/routing outcome, NOT an error.

The pipeline simply reached an intentionally unimplemented downstream boundary.

---

# Step 11 — Initially two-phase branch

If the current feed-phase evaluator returns something equivalent to:

```python
phase == "vapor_liquid"
```

do not silently route it into the vapor-feed HX calculation.

Return a deterministic result containing its currently calculated liquid and vapor fractions.

Conceptually:

```python
{
    "valid": True,
    "route": "two_phase_feed",
    "implemented": False,
    "liquid_fraction": ...,
    "vapor_fraction": ...,
    "message": (
        "The feed is already two-phase at the specified feed conditions. "
        "Routing of an initially two-phase feed is not implemented yet."
    ),
}
```

This can be extended later.

---

# Step 12 — Extend calculation-progress tracking

Update the existing calculation-progress representation rather than building a parallel state system.

Add stable step IDs as needed, conceptually:

```python
STEP_FEED_PHASE = "feed_phase"
STEP_VAPOR_CONDENSATION_SCREEN = "vapor_condensation_screen"
STEP_LIQUID_PHASE_SEPARATION = "liquid_phase_separation"
STEP_VAPOR_PHASE_SEPARATION = "vapor_phase_separation"
```

Follow current naming conventions if equivalent constants already exist.

## Liquid initial feed

Expected logical state:

```python
{
    "completed_steps": [
        "feed_phase",
    ],
    "next_step": None,
    "next_step_available": False,
    "remaining_steps": [
        "liquid_phase_separation",
    ],
    "blocked_reason": "not_implemented",
}
```

## Vapor feed, >=50% liquid after HX

Expected logical state:

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

## Vapor feed, <50% liquid after HX

Expected logical state:

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

Adapt this to the exact current calculation-progress schema rather than replacing the current structure.

---

# Step 13 — Preserve calculation-result continuity

If the system already stores the most recent deterministic calculation result, make sure this new routing information is stored there too.

A later user query such as:

```text
what next?
```

must be answerable from the stored calculation result/progress.

It must NOT:

- rebuild the problem,
- ask again for temperature,
- rerun the HX unnecessarily,
- ask Qwen to decide the separation branch,
- lose the previously calculated liquid/vapor percentages.

The most recent deterministic result should remain authoritative until the problem changes or is reset.

---

# Step 14 — Keep Qwen's role narrow

If there is a workflow-agent/system-prompt layer, make only the minimum update required so Qwen understands the newly returned calculation states.

Qwen may explain:

```text
68.4 mol% of the feed liquefies at 313.15 K...
```

but Qwen must not independently decide:

```text
I think we should use a liquid separator.
```

The route must already exist in deterministic structured output.

Do NOT embed the 50% threshold only in the prompt.

The threshold belongs in Python.

---

# Step 15 — Error handling

Return deterministic structured failures for BioSTEAM/HX/VLE errors.

Examples could include:

```python
{
    "valid": False,
    "error": "reference_temperature_flash_failed",
    ...
}
```

or whatever error schema the repository already uses.

Do not catch every exception and silently classify the feed.

Do not allow Qwen to infer a phase split when BioSTEAM fails.

Useful failures should preserve enough technical detail for debugging while keeping user-facing output understandable.

---

# Step 16 — Tests

Add focused unit and integration tests.

At minimum test the following.

## Test A — Initial liquid feed

Given a feed classified as liquid:

- feed-phase check succeeds,
- HX reference-temperature screening is NOT called,
- route is liquid-phase separation,
- `implemented` is false,
- result says liquid separation is future work,
- progress stops after feed phase.

Where practical, mock/patch the HX-screening function and assert it was never called.

---

## Test B — Vapor feed hotter than 313.15 K

Given a vapor feed with:

```python
feed.T > 313.15
```

verify:

```python
operation == "cooling"
```

and that the rigorous HX calculation runs.

---

## Test C — Vapor feed colder than 313.15 K

Given a vapor feed with:

```python
feed.T < 313.15
```

verify:

```python
operation == "heating"
```

Do not prohibit this case merely because the device is called a heat exchanger.

---

## Test D — Exactly 50% liquid

Mock or construct a case where:

```python
liquid_fraction == 0.50
```

Verify it enters:

```python
liquid_fraction >= 0.50
```

and routes to both future liquid- and vapor-phase pathways.

---

## Test E — More than 50% liquid

Example conceptual outcome:

```python
liquid_fraction = 0.70
vapor_fraction = 0.30
```

Verify:

- both fractions are reported,
- liquid + vapor percentages total ~100%,
- both future separation routes are represented,
- no downstream separator is simulated.

---

## Test F — Less than 50% liquid

Example conceptual outcome:

```python
liquid_fraction = 0.20
vapor_fraction = 0.80
```

Verify:

- the vapor percentage is reported,
- vapor-phase separation is recommended,
- vapor separation is marked unimplemented,
- progress shows vapor-phase separation as remaining.

---

## Test G — Initially two-phase feed

Verify:

- no vapor-feed 313.15 K screening occurs,
- existing liquid and vapor percentages are reported,
- route is marked unimplemented,
- no downstream separator runs.

---

## Test H — Original stream is unchanged

Capture before screening:

```python
T
P
composition
total molar flow
```

Run the vapor-feed reference-temperature evaluation.

Verify the original canonical stream retains its original state.

---

## Test I — Fraction conservation

For every successful HX-screening result:

```python
abs(
    liquid_fraction
    + vapor_fraction
    - 1.0
) < tolerance
```

Use a sensible numerical tolerance.

---

## Test J — BioSTEAM failure

Force/mock an HX simulation failure.

Verify:

- the function returns the repository's deterministic failure representation,
- no route is fabricated,
- no LLM interpretation is required to determine whether the calculation succeeded.

---

## Test K — "what next?" continuity

After obtaining one of the new calculation results, exercise the existing follow-up path.

Verify that asking an equivalent of:

```text
what next?
```

returns/explains the stored deterministic route.

It must not rerun the HX or ask for already-known binary-distillation inputs.

---

# Step 17 — Do not over-expand scope

Do NOT implement any of the following in this task:

- actual liquid-liquid separation,
- membranes,
- adsorption,
- absorption,
- vapor-phase separator design,
- multicomponent distillation,
- column sizing,
- stage calculations beyond what is already implemented,
- equipment optimization,
- automatic selection among every possible separation technology.

The intended endpoint is currently:

```text
feed
↓
feed phase
↓
deterministic routing
↓
optional 313.15 K rigorous HX/VLE screen for vapor feeds
↓
report phase fractions
↓
stop at intentionally unimplemented downstream separation pathway
```

---

# Step 18 — Keep results machine-readable

Avoid making future code parse prose such as:

```text
"Most of the feed is vapor, so..."
```

Instead store facts explicitly:

```python
{
    "liquid_fraction": 0.32,
    "vapor_fraction": 0.68,
    "liquid_percent": 32.0,
    "vapor_percent": 68.0,
    "route": "vapor_separation_advisable",
    "implemented": False,
}
```

Then derive user-facing prose from those values.

---

# Expected architecture after this change

```text
USER
  ↓
Qwen
  ↓
authoritative binary-distillation workflow
  ↓
calculate_binary_distillation_problem()
  ↓
build BioSTEAM feed
  ↓
evaluate_feed_phase()
  ↓
             ┌──────────────────────────────┐
             │                              │
          LIQUID                         VAPOR
             │                              │
             ↓                              ↓
   stop deterministically        evaluate at 313.15 K
             │                   HXutility(rigorous=True)
             │                              │
             │                              ↓
             │                     equilibrium L/V split
             │                              │
             │                    liquid_fraction >= 0.50?
             │                         /             \
             │                       yes              no
             │                        │                │
             ↓                        ↓                ↓
 liquid-phase separation     report liquid +     vapor-phase
     future work             vapor fractions     separation
                              both pathways       advisable
                               future work        future work


INITIAL TWO-PHASE
        │
        ↓
report existing L/V fractions
        │
        ↓
stop — routing future work
```

---

# Definition of done

The task is complete when:

1. Liquid feeds stop immediately after the feed-phase check and do not invoke the HX.
2. Vapor feeds automatically undergo a rigorous BioSTEAM reference-temperature calculation at 313.15 K.
3. The code obtains deterministic liquid and vapor molar fractions from BioSTEAM.
4. `liquid_fraction >= 0.50` routes to future liquid + vapor separation pathways.
5. `liquid_fraction < 0.50` recommends a future vapor-phase separation pathway.
6. Initially two-phase feeds stop cleanly as currently unsupported.
7. The original feed stream is not mutated.
8. Calculation progress reflects the new routing states.
9. Follow-up queries can use the stored result without recalculation.
10. Qwen does not own any phase/routing decision.
11. All new behavior is covered by tests.
12. Existing tests continue to pass.

---

# Implementation approach

Please implement this incrementally.

First inspect the repository and tell me which exact files/functions need modification.

Then make the smallest coherent implementation.

After implementation:

1. show the files changed,
2. summarize the responsibility of each change,
3. show the important structured result schemas,
4. run the relevant tests,
5. report test results,
6. call out any BioSTEAM API behavior you had to verify or adapt,
7. explicitly identify anything you intentionally left unimplemented.

Do not redesign unrelated portions of the system.
Do not move engineering decisions into the LLM prompt.
Do not replace deterministic state with conversational inference.