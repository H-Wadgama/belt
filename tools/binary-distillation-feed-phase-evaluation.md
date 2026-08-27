# Objective

Add a deterministic BioSTEAM-based **feed phase evaluation step** that runs only after the existing binary-distillation workflow reports:

```python
status == "ready_for_calculation"
```

The LLM must not generate arbitrary BioSTEAM code, invent missing values, or decide the feed phase itself.

The intended architecture is:

```text
User
  ↓
binary_distillation_workflow_agent.py
  ↓
assess_binary_distillation_problem()
  ↓
status != ready_for_calculation
  └── continue collecting missing information

status == ready_for_calculation
  ↓
calculation layer
  ↓
build canonical BioSTEAM feed
  ↓
evaluate feed equilibrium phase
  ↓
return structured phase result
  ↓
later feasibility/design calculations
```

The workflow-only agent must remain workflow-only. Do not add BioSTEAM imports or calculations to `binary_distillation_workflow.py` or `binary_distillation_workflow_agent.py`.

---

# Step 1 — Create a BioSTEAM feed adapter

Create:

```text
tools/chopper/biosteam_feed.py
```

Purpose:

Convert the authoritative normalized workflow state into one BioSTEAM `Stream`.

The function should consume deterministic workflow state rather than raw LLM-generated arguments.

Implement:

```python
def build_biosteam_feed(spec, assessment, *, stream_id="feed"):
    ...
```

Responsibilities:

1. Verify:

```python
assessment["status"] == "ready_for_calculation"
```

2. Read the normalized feed information from:

```python
assessment["feed"]
```

3. Extract:

```text
component names
component flows
flow units
pressure
thermal specification
```

4. Require exactly two components.

5. Call:

```python
bst.settings.set_thermo(component_names, cache=True)
```

6. Construct a BioSTEAM stream using the actual component flows.

Example target behavior:

```python
feed = bst.Stream(
    stream_id,
    Butane=50,
    Acetaldehyde=50,
    units="kmol/hr",
    P=101325,
)
```

Do not make Qwen construct this dictionary.

Do not infer missing flow values here. Feed-state normalization has already handled mathematically forced derivations upstream.

Return the `bst.Stream`.

---

# Step 2 — Keep feed thermal condition separate from stream construction

Do not silently assign:

```python
feed.T = feed.bubble_point_at_P().T
```

The current architecture explicitly requires the user's feed thermal condition instead of defaulting to bubble point. Preserve that behavior.

The feed thermal state must come from exactly one of:

```python
feed_temperature_K
feed_quality
feed_enthalpy_kJ_per_hr
```

The existing workflow already validates this requirement.

Do not add a fallback thermal state.

---

# Step 3 — Create the feed-phase calculation module

Create:

```text
tools/chopper/feed_phase.py
```

Implement a deterministic function such as:

```python
def evaluate_feed_phase(
    feed,
    *,
    pressure_Pa,
    feed_temperature_K=None,
    feed_quality=None,
    feed_enthalpy_kJ_per_hr=None,
    phase_tolerance=1e-6,
):
    ...
```

The function should make a copy:

```python
equilibrium_feed = feed.copy()
```

Never mutate the canonical input stream during the phase check.

---

# Step 4 — Perform the correct BioSTEAM VLE calculation

Select the calculation based only on the thermal specification already present in the authoritative state.

For temperature + pressure:

```python
equilibrium_feed.vle(
    T=feed_temperature_K,
    P=pressure_Pa,
)
```

For vapor quality + pressure:

```python
equilibrium_feed.vle(
    V=feed_quality,
    P=pressure_Pa,
)
```

For enthalpy + pressure:

```python
equilibrium_feed.vle(
    H=feed_enthalpy_kJ_per_hr,
    P=pressure_Pa,
)
```

Exactly one branch should run.

Do not use a hard-coded temperature such as:

```python
outlet.vle(T=270, P=101325)
```

unless `270 K` is actually the feed temperature supplied by the user.

For example, if the feed specification is:

```python
T = 405
P = 101325
```

then the phase calculation must use:

```python
equilibrium_feed.vle(
    T=405,
    P=101325,
)
```

---

# Step 5 — Deterministically classify the phase

Read:

```python
V = float(equilibrium_feed.vapor_fraction)
```

Classify using Python, not the LLM:

```python
if V <= phase_tolerance:
    phase = "liquid"

elif V >= 1.0 - phase_tolerance:
    phase = "vapor"

else:
    phase = "vapor_liquid"
```

Also calculate:

```python
liquid_fraction = 1.0 - V
```

The model must never be asked to interpret a vapor fraction and decide whether the stream is liquid, vapor, or two-phase.

---

# Step 6 — Extract phase compositions/flows

For every component in the feed, extract gas-phase and liquid-phase molar quantities.

Conceptually:

```python
vapor_mol = {
    ID: float(equilibrium_feed.imol["g", ID])
    for ID in component_names
}

liquid_mol = {
    ID: float(equilibrium_feed.imol["l", ID])
    for ID in component_names
}
```

Keep these values in structured output.

Do not return the raw BioSTEAM stream object to the LLM-facing layer.

---

# Step 7 — Return a JSON-friendly result

Target output schema:

```python
{
    "check": "feed_phase",
    "valid": True,

    "phase": "vapor_liquid",

    "vapor_fraction": 0.37,
    "liquid_fraction": 0.63,

    "temperature_K": 405.0,
    "pressure_Pa": 101325.0,

    "components": [
        "Butane",
        "Acetaldehyde",
    ],

    "vapor_mol": {
        "Butane": ...,
        "Acetaldehyde": ...,
    },

    "liquid_mol": {
        "Butane": ...,
        "Acetaldehyde": ...,
    },

    "calculation": {
        "type": "VLE",
        "specification": "T_P",
    },

    "message": "Feed is a vapor-liquid mixture at the specified feed conditions."
}
```

For a pure liquid feed:

```python
"phase": "liquid"
```

For a pure vapor feed:

```python
"phase": "vapor"
```

---

# Step 8 — Handle calculation failures explicitly

Wrap the BioSTEAM equilibrium calculation in deterministic error handling.

Example:

```python
try:
    ...
except Exception as err:
    return {
        "check": "feed_phase",
        "valid": False,
        "error": "phase_calculation_failed",
        "message": str(err),
    }
```

Do not let Qwen reinterpret an exception and pretend a phase result exists.

---

# Step 9 — Add one calculation-pipeline entry point

Create:

```text
tools/chopper/binary_distillation_calculation.py
```

Implement something like:

```python
def calculate_binary_distillation_problem(spec):
    assessment = assess_binary_distillation_problem(spec)

    if assessment["status"] != "ready_for_calculation":
        return {
            "calculation_performed": False,
            "workflow": assessment,
            "checks": {},
        }

    feed = build_biosteam_feed(
        spec,
        assessment,
    )

    phase_result = evaluate_feed_phase(
        feed,
        pressure_Pa=spec["pressure_Pa"],
        feed_temperature_K=spec.get("feed_temperature_K"),
        feed_quality=spec.get("feed_quality"),
        feed_enthalpy_kJ_per_hr=spec.get(
            "feed_enthalpy_kJ_per_hr"
        ),
    )

    return {
        "calculation_performed": True,
        "workflow": assessment,
        "checks": {
            "feed_phase": phase_result,
        },
    }
```

For now, stop after feed-phase evaluation.

Do not run the existing distillation sizing/design calculation yet unless explicitly added in a later step.

---

# Step 10 — Preserve the workflow-agent boundary

Do not modify the following behavior:

```python
binary_distillation_workflow_agent.py
```

must still stop at:

```text
ready_for_calculation
```

and must still truthfully report that its own calculation layer is not enabled.

Do not import:

```text
BioSTEAM
feed_phase.py
case_design.py
optimizer.py
```

into the workflow-only agent.

The new calculation module should be a separate downstream layer.

This preserves the existing architecture:

```text
workflow definition
      ↓
deterministic engineering calculation
```

rather than:

```text
workflow agent
      ↓
LLM improvises calculation
```

---

# Step 11 — Add tests for `feed_phase.py`

Create:

```text
tools/chopper/test_feed_phase.py
```

Add at least the following tests.

## Test 1 — Binary feed at TP conditions

Provide:

```text
2 components
known component flows
known pressure
known feed temperature
```

Assert:

```python
result["valid"] is True
0 <= result["vapor_fraction"] <= 1
result["phase"] in {
    "liquid",
    "vapor",
    "vapor_liquid",
}
```

---

## Test 2 — Liquid phase classification

Use conditions expected to result in:

```python
vapor_fraction ≈ 0
```

Assert:

```python
result["phase"] == "liquid"
```

---

## Test 3 — Vapor phase classification

Use conditions expected to result in:

```python
vapor_fraction ≈ 1
```

Assert:

```python
result["phase"] == "vapor"
```

---

## Test 4 — Two-phase classification

Use conditions expected to produce:

```python
0 < vapor_fraction < 1
```

Assert:

```python
result["phase"] == "vapor_liquid"
```

---

## Test 5 — Quality-based state

Supply:

```python
feed_quality
pressure_Pa
```

Assert BioSTEAM determines a temperature and:

```python
result["vapor_fraction"]
```

matches the specified quality within tolerance.

---

## Test 6 — Invalid thermal specification

Pass more than one of:

```text
feed_temperature_K
feed_quality
feed_enthalpy_kJ_per_hr
```

Assert:

```python
result["valid"] is False
```

or preferably reject this before calling the function if the contract requires already-validated input.

---

## Test 7 — Missing thermal specification

Pass none of the thermal state fields.

Assert the function does not invent one.

---

## Test 8 — Unsupported component count

Supply more than two components directly to the calculation helper.

Assert it returns/rejects with:

```text
unsupported_component_count
```

even though the upstream workflow should normally prevent this.

This is a defensive calculation-layer check.

---

# Step 12 — Add integration tests

Create:

```text
tools/chopper/test_binary_distillation_calculation.py
```

Test the full transition:

```text
incomplete workflow
      ↓
no calculation

complete workflow
      ↓
phase calculation occurs
```

Required test:

```python
result = calculate_binary_distillation_problem(
    incomplete_spec
)

assert result["calculation_performed"] is False
```

Then:

```python
result = calculate_binary_distillation_problem(
    complete_spec
)

assert result["calculation_performed"] is True
assert "feed_phase" in result["checks"]
```

---

# Step 13 — Confirm no LLM inference is needed for phase evaluation

Add tests or code inspection ensuring:

```text
feed_phase.py
biosteam_feed.py
binary_distillation_calculation.py
```

do not import:

```python
ollama
openai
```

These modules must be deterministic engineering code only.

---

# Step 14 — Keep state provenance intact

The normalized feed state currently distinguishes user-explicit and mathematically derived quantities.

Do not replace this with a flattened LLM-generated dictionary before the calculation.

The calculation adapter may consume derived values, but it should not relabel them as user-provided.

The authoritative state remains:

```python
assessment["feed"]
```

The BioSTEAM stream is a computational representation of that state, not a new source of input truth.

---

# Step 15 — Add phase result to the future engineering-check hierarchy

Design the result structure so additional deterministic checks can later be added alongside it:

```python
{
    "checks": {
        "feed_phase": {...},

        # Future:
        "relative_volatility": {...},
        "azeotrope": {...},
        "thermal_stability": {...},
        "condensability": {...},
        "critical_temperature_margin": {...},
    }
}
```

Do not build those checks yet.

Only make the structure ready for them.

---

# Step 16 — Prepare for RAG integration, but do not connect it yet

The existing knowledge base contains phase-dependent separation-technique heuristics.

Eventually the logic should be:

```text
BioSTEAM determines phase
        ↓
phase == vapor
        ↓
deterministic fact:
feed is vapor
        ↓
retrieve/apply vapor-feed heuristic
```

not:

```text
user says something vague
        ↓
LLM decides feed sounds vapor-like
        ↓
heuristic fires
```

For this implementation, stop after returning the phase result.

Do not yet automatically retrieve heuristics.

---

# Step 17 — Example expected call

Given an authoritative complete problem containing:

```python
{
    "component_flows": {
        "Butane": 50,
        "Acetaldehyde": 50,
    },

    "component_flow_units": "kmol/hr",

    "pressure_Pa": 101325,

    "feed_temperature_K": 405,

    ...
}
```

the deterministic calculation should effectively execute:

```python
bst.settings.set_thermo(
    ["Butane", "Acetaldehyde"],
    cache=True,
)

feed = bst.Stream(
    "feed",
    Butane=50,
    Acetaldehyde=50,
    units="kmol/hr",
    P=101325,
)

equilibrium_feed = feed.copy()

equilibrium_feed.vle(
    T=405,
    P=101325,
)
```

Then Python should read:

```python
equilibrium_feed.vapor_fraction
equilibrium_feed.imol["g"]
equilibrium_feed.imol["l"]
```

and return those values as structured JSON-friendly output.

---

# Step 18 — Definition of done

This feature is complete when all of the following are true:

- [ ] The existing workflow-only agent remains unable to perform BioSTEAM calculations.
- [ ] A new deterministic calculation layer exists downstream of `ready_for_calculation`.
- [ ] The normalized workflow feed state can be converted into a BioSTEAM stream without LLM involvement.
- [ ] No component names, flows, pressure, or thermal states are invented.
- [ ] Feed temperature is not silently replaced by bubble point.
- [ ] TP phase evaluation works.
- [ ] Quality-pressure phase evaluation works.
- [ ] Enthalpy-pressure phase evaluation is either supported and tested or explicitly returned as not implemented.
- [ ] Vapor fraction is calculated by BioSTEAM.
- [ ] Liquid/vapor/two-phase classification is performed deterministically in Python.
- [ ] Gas-phase component quantities are returned.
- [ ] Liquid-phase component quantities are returned.
- [ ] Results are JSON-friendly.
- [ ] Calculation failures are explicit.
- [ ] Incomplete workflow state cannot trigger the BioSTEAM calculation.
- [ ] Binary scope is checked again defensively at the calculation layer.
- [ ] Unit tests for phase evaluation pass.
- [ ] Integration tests for `ready_for_calculation → phase calculation` pass.
- [ ] No LLM package is imported into the deterministic phase-calculation modules.
- [ ] The returned structure is ready to hold later feasibility checks.

# Recommended implementation order

Implement in this order:

```text
1. biosteam_feed.py
2. feed_phase.py
3. test_feed_phase.py
4. binary_distillation_calculation.py
5. test_binary_distillation_calculation.py
6. run existing workflow tests
7. run new calculation tests
8. manually test one Butane/Acetaldehyde case
```

Do not modify the RAG layer, distillation optimizer, or full agent routing until this isolated phase-calculation stage is working and tested.