I want you to refactor the binary-distillation workflow so that:

1. feed-phase evaluation and reference-temperature conditioning are one independent deterministic workflow, and
2. binary-distillation Design Options A–D are assessed independently in parallel.

The current architecture incorrectly requires a complete design case before the feed-phase calculation can run.

That must change.

Also rename all user-facing references to:

```text
Wankat Case A
Wankat Case B
Wankat Case C
Wankat Case D
```

to:

```text
Design Option A
Design Option B
Design Option C
Design Option D
```

The underlying engineering definitions are still based on the existing Wankat-derived implementation and provenance. Do NOT remove source provenance or rewrite the engineering definitions. This is primarily a user-facing terminology change.

---

# Core architectural goal

Current architecture is approximately:

```text
collect feed information
        ↓
collect pressure / thermal condition / reflux condition
        ↓
identify Case A-D
        ↓
complete case
        ↓
confirm optimum feed plate
        ↓
check calculation units
        ↓
ready_for_calculation
        ↓
feed phase evaluation
        ↓
reference-temperature conditioning
        ↓
physical routing
```

This is wrong because feed-phase evaluation does not require the design case.

Refactor it into:

```text
                         USER INPUT
                             ↓
                  STORE ALL EXPLICIT FACTS
                             ↓
                deterministic normalized state
                             ↓
             ┌───────────────┴────────────────┐
             ↓                                ↓
      FEED SCREENING                    DESIGN ASSESSMENT
             ↓                                ↓
  Are feed-screen inputs ready?      Which Design Option A-D?
             ↓                                ↓
        yes / no                    complete / incomplete /
             ↓                       ambiguous / undefined
             ↓
      BioSTEAM feed VLE
             ↓
   liquid / vapor-liquid / vapor
             ↓
if any meaningful vapor:
condition whole feed to 313.15 K
             ↓
deterministic phase routing
             ↓
liquid-phase / liquid+vapor /
vapor-phase future pathway
```

The two branches share the same stored problem facts but have separate readiness states.

---

# Architectural principle

Use this rule throughout the refactor:

```text
EXTRACT BROADLY
STORE BROADLY
EXECUTE HIERARCHICALLY
```

For example, if a user says:

```text
50 kmol/hr methanol
50 kmol/hr water
400 K
101325 Pa
xD = 0.95
xB = 0.01
V/B = 1.2
```

store ALL of those explicit facts immediately.

The design-assessment branch may already recognize:

```text
Design Option D
```

but that must not cause the Design Option calculation to execute before the feed screen.

Likewise, incomplete design information must not block the feed screen.

Information collection and execution order are separate concepts.

---

# Step 1 — Inspect the current dependency chain

Before editing anything, inspect:

- `binary_distillation_workflow.py`
- `binary_distillation_calculation.py`
- `binary_distillation_workflow_agent.py`
- `biosteam_feed.py`
- `feed_phase.py`
- `feed_partial_condensation.py`
- `problem_spec.py`
- relevant tests

Trace exactly where:

```python
status == "ready_for_calculation"
```

currently gates:

```python
build_biosteam_feed()
evaluate_feed_phase()
evaluate_vapor_feed_at_reference_temperature()
```

Identify all places where Design Option completeness is currently required before feed screening.

Do not patch around the gate.

Refactor the readiness model explicitly.

---

# Step 2 — Define feed-screening requirements independently

Create a deterministic function conceptually like:

```python
assess_feed_screening_readiness(spec)
```

or another clear name consistent with the codebase.

It must determine whether the current state contains everything required to perform:

```text
BioSTEAM feed construction
+
feed VLE
+
reference-temperature conditioning if needed
```

Feed screening should require ONLY the quantities physically required for those calculations.

Based on the current implementation, this should include:

```text
exactly two feed components
complete feed quantity/composition
flow-rate units required to build the BioSTEAM stream
pressure_Pa
exactly one feed thermal condition:
    feed_temperature_K
    OR feed_quality
    OR feed_enthalpy_kJ_per_hr
```

Do NOT require:

```text
reflux_condition
xD
xB
Lr
Hr
distillate_flow
bottoms_flow
external reflux ratio
reflux multiplier
boilup ratio
optimum feed plate
```

for feed screening.

Those are design-definition inputs, not feed-VLE inputs.

---

# Step 3 — Re-evaluate whether `reflux_condition` belongs in feed readiness

The current workflow treats:

```python
reflux_condition
```

as an essential input.

That may remain an essential input for the distillation design branch.

It must NOT block feed screening.

The feed-phase BioSTEAM calculation does not physically need the condenser reflux thermal state to determine the feed's VLE state.

Therefore conceptually:

```python
feed_screening.requires_reflux_condition = False
design_assessment.requires_reflux_condition = True
```

Preserve the existing requirement wherever the Design Option definition needs it.

Do not delete the field.

---

# Step 4 — Introduce explicit parallel assessment structures

Refactor the main workflow return so it exposes BOTH states.

Preferred conceptual shape:

```python
{
    "valid_binary_scope": True,

    "feed": {...},

    "feed_screening": {
        "ready": True,
        "missing_inputs": [],
        "status": "ready",
        "message": "...",
    },

    "design_assessment": {
        "option": None,
        "option_candidates": ["A", "B", "C", "D"],
        "complete": False,
        "missing_inputs": {...},
        "status": "need_design_definition",
        "message": "...",
    },

    ...
}
```

Exact names may differ, but the conceptual separation must be explicit.

Do not use one overloaded Boolean such as:

```python
calculation_inputs_complete
```

to mean both things.

---

# Step 5 — Preserve compatibility where useful

Inspect existing tests and callers before changing the top-level schema.

If many callers currently rely on:

```python
case
case_candidates
case_complete
missing_case_inputs
essential_complete
calculation_inputs_complete
status
```

do not necessarily delete them immediately.

A safe migration strategy may be:

```python
"feed_screening": {...},
"design_assessment": {...},

# temporary compatibility
"case": ...,
"case_candidates": ...,
...
```

However, all NEW logic should consume the new explicit structures.

Do not continue using the old single-status field as the decision authority for feed calculation.

---

# Step 6 — Rename "Case" to "Design Option" in user-facing semantics

Change user-facing language:

```text
Wankat Case A
→ Design Option A

Wankat Case B
→ Design Option B

Wankat Case C
→ Design Option C

Wankat Case D
→ Design Option D
```

Examples:

Current:

```text
Your binary-distillation problem is fully specified as Wankat Case A.
```

Target:

```text
Your binary-distillation design specification matches Design Option A.
```

Current:

```text
This does not yet identify a Wankat design case.
```

Target:

```text
The distillation design specification does not yet identify a single Design Option.
```

---

# Step 7 — Keep source provenance intact

Do NOT remove Wankat from provenance.

User-facing workflow terminology and engineering provenance are different things.

It is perfectly acceptable for the result to contain:

```python
"design_option": "A"
```

while provenance still says conceptually:

```text
Design-option definitions derived from Wankat,
Separation Process Engineering, Table 3-2.
```

The UI should say:

```text
Design Option A
```

not:

```text
Wankat Case A
```

But the audit trail should still preserve the textbook basis.

---

# Step 8 — Decide whether to rename internal `case` variables

Prefer minimal churn.

It is acceptable initially to keep internal code names such as:

```python
case
case_candidates
identify_case()
CASE_A
```

if changing them would create broad unnecessary risk.

However, expose user-facing structured aliases such as:

```python
design_option
design_option_candidates
```

if practical.

If renaming the internals is low-risk and contained, you may rename them.

Do not make a broad cosmetic rewrite if it increases regression risk.

The important requirement is:

```text
Qwen and tool messages say "Design Option", not "Wankat Case".
```

---

# Step 9 — Change the feed calculation gate

This is the central functional change.

Current behavior is effectively:

```python
assessment = assess_binary_distillation_problem(spec)

if assessment["status"] != "ready_for_calculation":
    return without running BioSTEAM
```

Replace this concept with:

```python
assessment = assess_binary_distillation_problem(spec)

feed_readiness = assessment["feed_screening"]

if not feed_readiness["ready"]:
    return without running BioSTEAM

# feed screen may run regardless of design option completeness
build feed
evaluate phase
condition if needed
route
```

The Design Option state must not block this.

---

# Step 10 — Make `biosteam_feed.py` depend on feed readiness, not design readiness

Currently `build_biosteam_feed()` reportedly requires:

```python
assessment["status"] == "ready_for_calculation"
```

Refactor this.

It should require only that:

```python
assessment["feed_screening"]["ready"] is True
```

or receive a feed-screening-specific validated object.

It should still defensively verify:

- exactly two components,
- all required component flows,
- flow units,
- pressure.

Do NOT weaken those engineering checks.

Only remove the irrelevant Design Option dependency.

---

# Step 11 — Preserve the existing feed-phase physics exactly

Do NOT modify the actual physical logic unless required by the readiness refactor.

The existing sequence should remain:

```text
build canonical overall feed
        ↓
evaluate feed VLE at specified feed condition
        ↓
phase?
```

If:

```text
liquid
```

then:

```text
do not run the 313.15 K conditioning screen
→ future liquid-phase separation pathway
```

If:

```text
vapor
```

or:

```text
vapor_liquid
```

then:

```text
condition the WHOLE overall feed to 313.15 K
using the existing rigorous BioSTEAM calculation
```

Do not alter this physics.

---

# Step 12 — Preserve the current 313.15 K routing

After conditioning:

```python
if vapor_fraction <= PHASE_FRACTION_TOLERANCE:
    route = "liquid_phase_separation"

elif liquid_fraction >= 0.50:
    route = "liquid_and_vapor_separation_future"

else:
    route = "vapor_separation_advisable"
```

Do not change:

```python
PHASE_FRACTION_TOLERANCE
LIQUEFACTION_THRESHOLD
REFERENCE_TEMPERATURE_K
```

in this task.

This refactor is about workflow readiness.

---

# Step 13 — Store the feed-screen result independently of design state

The calculation result should make the distinction clear.

Conceptually:

```python
{
    "feed_screening_performed": True,

    "feed_screening": {
        "feed_phase": {...},
        "reference_temperature_screen": {...},
        "routing": {...},
    },

    "design_assessment": {
        "design_option": None,
        "complete": False,
        ...
    }
}
```

The result must be able to truthfully represent:

```text
Feed screening is complete.
Design Option is not yet defined.
```

That combination is now valid.

---

# Step 14 — Do not call feed screening "Case calculation"

Update wording throughout the calculation layer.

Avoid statements like:

```text
Your Case A calculation is ready.
```

when only the feed phase can actually be calculated.

Prefer:

```text
The feed-screening calculation is ready.
```

and separately:

```text
The distillation design specification currently matches Design Option A.
```

This distinction should remain visible to Qwen.

---

# Step 15 — Redesign top-level workflow status carefully

The existing single field:

```python
status
```

currently mixes:

- missing feed data,
- missing design data,
- ready-for-calculation.

That becomes conceptually inadequate after this refactor.

Prefer subsystem statuses:

```python
feed_screening["status"]
design_assessment["status"]
```

For example:

```python
feed_screening = {
    "status": "ready",
    "ready": True,
}
```

while:

```python
design_assessment = {
    "status": "need_design_definition",
    "complete": False,
}
```

A top-level summary status may remain for backward compatibility, but it must not be used as the calculation gate.

---

# Step 16 — Define feed-screening statuses

Use a small deterministic vocabulary.

For example:

```text
need_components
unsupported_multicomponent
inconsistent_feed
need_feed_quantity
need_feed_units
need_pressure
need_feed_thermal_condition
ready
```

You do not have to use these exact strings.

The critical property is that the feed-screening status answers only:

> Can the feed VLE/conditioning screen run?

It must not mention Design Option inputs.

---

# Step 17 — Define design-assessment statuses separately

Conceptually:

```text
need_design_definition
need_design_inputs
ambiguous
complete
```

It may also have a separate field for:

```text
need_reflux_condition
need_optimum_feed_plate_confirmation
```

depending on current architecture.

Again, this answers only:

> How completely is the distillation design option defined?

It does not determine whether the feed screen can run.

---

# Step 18 — Run Design Option identification continuously

Do not wait until after feed screening to assess the Design Option.

Every state update should still run deterministic Design Option classification over whatever design fields are currently available.

Example:

```text
User gives:
feed + pressure + temperature + xD + xB + V/B
```

Result may simultaneously be:

```python
feed_screening = {
    "ready": True
}

design_assessment = {
    "design_option": "D",
    "complete": False or True depending on other required design inputs
}
```

This is desirable.

The design branch is informational until its execution stage becomes relevant.

---

# Step 19 — Preserve early storage of design facts

If the user provides:

```text
boilup ratio = 1.2
```

before feed screening, store it immediately.

If the user provides:

```text
xD = 0.95
xB = 0.01
```

store them immediately.

Do NOT discard or postpone these facts merely because feed screening executes first.

The rule is:

```text
storage order != execution order
```

---

# Step 20 — Change pending-request priority

This is important.

The agent currently may ask for Design Option information as soon as essential inputs are complete.

After the refactor, pending requests should prioritize whatever is needed to make the feed screen executable.

Preferred order:

```text
1. binary feed identity
2. feed quantity/composition
3. feed flow units
4. pressure
5. feed thermal condition
        ↓
FEED SCREEN READY
```

Once feed screening is ready, do NOT block execution by asking for:

```text
xD
xB
Lr
Hr
product flow
reflux ratio
boilup ratio
optimum feed plate
```

first.

Those can be requested later when the user moves into distillation-design definition.

---

# Step 21 — Do not ask for reflux condition before feed screening

If the only missing design essential is:

```python
reflux_condition
```

but feed screening is otherwise ready:

```python
feed_screening["ready"] == True
```

the user should be allowed to perform the feed screen.

Do not force:

```text
Please specify the reflux condition.
```

before evaluating feed phase.

That question belongs to the design branch.

---

# Step 22 — Update the CALCULATE trigger

Currently:

```text
yes
go ahead
calculate it
feed phase?
```

may be gated by full workflow `ready_for_calculation`.

Change deterministic routing so explicit feed-screen requests are gated by:

```python
feed_screening["ready"] == True
```

not by design-option completeness.

Examples:

```text
What phase is the feed?
Evaluate the feed phase.
Go ahead with the feed check.
What happens at 313.15 K?
```

should execute the feed screen whenever feed-screen inputs are ready.

---

# Step 23 — Decide default behavior when feed screen becomes ready

Do NOT automatically run BioSTEAM merely because the final required feed field was entered unless current interaction semantics intentionally do that.

Prefer preserving the existing conversational pattern:

```text
User supplies required facts
        ↓
tool reports feed screen is ready
        ↓
User says "yes" / "proceed" / asks feed-phase question
        ↓
run calculation
```

The important change is only that Design Option completion is not required.

---

# Step 24 — Update calculation-progress state

Current calculation progress should be changed so the first executable stage is:

```text
feed_phase
```

as soon as feed-screen readiness is true.

It must not say the next step is:

```text
Design Option A/B/C/D completion
```

when the physical screen can already run.

After feed screening:

```text
completed:
feed_phase
reference-temperature conditioning if applicable
```

then:

```text
remaining:
liquid_phase_separation
and/or
vapor_phase_separation
```

based on the existing physical routing.

Design Option progress should be tracked separately.

---

# Step 25 — Keep design progress independent

If useful, add:

```python
design_progress
```

or keep it inside:

```python
design_assessment
```

For example:

```python
{
    "design_option": "A",
    "complete": False,
    "missing_inputs": [
        "xD",
        "xB",
        "external_reflux_ratio_LD"
    ]
}
```

This is not part of:

```python
calculation_progress["remaining_steps"]
```

for the feed screen.

Do not mix design-definition work with physical feed-routing work.

---

# Step 26 — Clarify downstream architecture

For now, after feed screening the physical routing should remain authoritative:

```text
Feed screen
    ↓
liquid pathway
OR
liquid + vapor pathways
OR
vapor pathway
```

Do NOT immediately execute Design Option A-D sizing afterward.

Design Options A-D should remain an independently accumulated definition for the future distillation-design stage.

This refactor should make it possible later to decide:

```text
Is distillation still the applicable liquid-phase method?
```

before executing a detailed Design Option.

Do not wire full Case/Design Option calculations in this task.

---

# Step 27 — Update Qwen system prompt

Add a clear architecture rule:

```text
FEED SCREENING VS DISTILLATION DESIGN RULE

Feed-phase screening and distillation Design Option identification are
separate deterministic workflows.

The model must store all explicit user facts immediately.

Feed screening depends only on feed construction, pressure, flow units,
and the explicit feed thermal condition.

Design Options A-D are assessed independently from design specifications.

Do not require a complete Design Option before offering or performing
feed-phase evaluation.

Do not infer physical routing yourself. Use the deterministic feed-screen
result.
```

---

# Step 28 — Change Qwen terminology

Update all prompt instructions and tool descriptions from:

```text
Wankat Case A-D
```

to:

```text
Design Options A-D
```

For example:

```text
Design Option A
= xD + xB + external reflux ratio + optimum feed plate
```

etc.

Keep the definitions exactly the same as the current deterministic code.

---

# Step 29 — Preserve authoritative source wording in provenance only

The user-facing response can say:

```text
Design Option A
```

while the raw deterministic object can retain:

```python
"provenance": {
    "design_options_source": "... Wankat ... Table 3-2 ..."
}
```

This is desirable.

Do not pretend the design options were invented by the project.

Only change the workflow-facing name.

---

# Step 30 — Add the most important regression test

Construct a problem with:

```text
Water + Ethanol
50 kmol/hr each
component flow units = kmol/hr
355 K
101325 Pa
```

and NO:

```text
xD
xB
reflux ratio
boilup ratio
product flow
optimum feed plate
reflux condition
```

Expected deterministic assessment:

```python
feed_screening["ready"] is True
```

while:

```python
design_assessment["complete"] is False
design_assessment["design_option"] is None
```

Then:

```python
calculate_current_binary_distillation_problem()
```

must perform the real BioSTEAM feed-phase evaluation.

This is the core acceptance test.

---

# Step 31 — Verify the existing Water/Ethanol physical result

For the existing regression:

```text
Water = 50 kmol/hr
Ethanol = 50 kmol/hr
T = 355 K
P = 101325 Pa
```

the current BioSTEAM path has produced approximately:

```text
initial:
~25.46% liquid
~74.54% vapor
```

followed by conditioning at:

```text
313.15 K
```

to an effectively fully-liquid feed in the current regression.

After this refactor, the same physical result should occur WITHOUT requiring any Design Option fields.

Do not hard-code those fractions into production logic.

Use the existing real-BioSTEAM regression and tolerances.

---

# Step 32 — Test incomplete feed + complete Design Option information

Construct a state containing enough design fields to identify an option, for example:

```text
xD
xB
boilup_ratio_VB
optimum feed plate
reflux condition
```

but omit the feed thermal condition.

Expected:

```python
design_assessment["design_option"] == "D"
```

or equivalent,

while:

```python
feed_screening["ready"] is False
```

and attempting feed screening performs NO BioSTEAM calculation.

This proves the branches are actually independent.

---

# Step 33 — Test feed ready + partially specified Design Option

Example:

```text
complete feed-screen inputs
+
xD = 0.95
```

Expected:

```python
feed_screening["ready"] is True
```

and:

```python
design_assessment
```

reflects whatever candidates remain consistent with `xD`.

Feed screening must still execute.

---

# Step 34 — Test feed ready + complete Design Option D

Example:

```text
Methanol 50 kmol/hr
Water 50 kmol/hr
400 K
101325 Pa
xD = 0.95
xB = 0.01
V/B = 1.2
optimum feed plate = yes
reflux condition = saturated liquid
```

Expected:

```python
feed_screening["ready"] is True

design_assessment["design_option"] == "D"
design_assessment["complete"] is True
```

When the user asks to proceed:

```text
feed screening runs first
```

Do NOT execute Design Option D sizing.

---

# Step 35 — Test early Design Option facts are retained

Use a multi-turn sequence:

```text
Turn 1:
xD = 0.95 and xB = 0.01

Turn 2:
feed is methanol/water, 50 kmol/hr each

Turn 3:
400 K and 101325 Pa

Turn 4:
V/B = 1.2
```

Verify all explicitly supplied facts remain in state.

When feed screening becomes ready, it can run.

Design Option identification should use all previously supplied design facts.

No data should be lost because it was provided "too early."

---

# Step 36 — Test reflux condition independence

Feed:

```text
complete feed composition
units
temperature
pressure
```

but:

```python
reflux_condition is None
```

Expected:

```python
feed_screening["ready"] is True
```

while design assessment reports reflux condition missing if required.

This is an important architectural regression test.

---

# Step 37 — Test optimum feed plate independence

Feed screen complete, but:

```python
use_optimum_feed_plate is None
```

Expected:

```python
feed_screening["ready"] is True
```

No feed calculation should ever be blocked on optimum-feed-stage preference.

---

# Step 38 — Test no Design Option defaults

The existing rule must remain:

```text
No design-specific information
≠
Design Option A
```

When feed-screen inputs are ready but no design fields have been given:

```python
design_option is None
design_option_candidates == ["A", "B", "C", "D"]
```

or equivalent.

Do not silently pick Design Option A.

---

# Step 39 — Test terminology migration

Add tests ensuring user-facing messages no longer contain:

```text
Wankat Case A
Wankat Case B
Wankat Case C
Wankat Case D
```

They should contain:

```text
Design Option A
Design Option B
Design Option C
Design Option D
```

However provenance should still retain the Wankat citation.

---

# Step 40 — Preserve deterministic engineering-output metadata

Do not undo the recently added:

```python
would_calculate_details
```

quantity metadata.

If Design Option A is complete, it should still deterministically expose meanings such as:

```text
QR → reboiler duty
Qc → condenser duty
```

The terminology refactor must not reintroduce bare-symbol interpretation by Qwen.

---

# Step 41 — Update "what next?" behavior

This is important.

Before feed screening has run:

If:

```python
feed_screening["ready"] == True
```

then:

```text
"What next?"
```

should deterministically report:

```text
Next executable step: feed-phase evaluation.
```

It should NOT say:

```text
Please first choose Design Option A-D.
```

After feed screening has run:

"What next?" should continue using stored:

```python
calculation_progress
```

and report the physical pathway.

Do not rerun BioSTEAM unnecessarily.

---

# Step 42 — Preserve calculation invalidation

Any engineering WRITE that can affect the feed calculation should invalidate:

```python
_last_calculation_result
```

At minimum changes to:

```text
components
component flows
composition
flow units
pressure
feed thermal condition
```

must invalidate it.

The current implementation invalidates on any non-empty engineering WRITE, which is conservative and acceptable.

Do not weaken this safety rule during the refactor.

---

# Step 43 — Update tool descriptions

The update tool should clearly say:

```text
This tool stores both feed-screening information and distillation-design
information.

All explicit recognized facts should be written immediately, even if they
belong to a later design stage.
```

The calculation tool should clearly say:

```text
This tool performs the feed-screening calculation only.

It does not require a complete Design Option A-D.

It does not perform full distillation Design Option calculations.
```

---

# Step 44 — Keep Qwen outside physical routing

Qwen must NOT decide:

```text
feed is probably vapor
cooling should be used
enough condensed
liquid separation should be chosen
```

Those remain deterministic outputs of:

```text
feed_phase.py
feed_partial_condensation.py
binary_distillation_calculation.py
```

No change to that division of responsibility.

---

# Step 45 — Do not implement downstream separation technology selection

This task ends at the existing physical routing:

```text
liquid_phase_separation
liquid_and_vapor_separation_future
vapor_separation_advisable
```

Do NOT implement:

- extraction,
- adsorption,
- membrane separation,
- another distillation column,
- liquid-liquid separation,
- vapor separator design,
- RAG-based technology screening.

Those are future branches.

---

# Step 46 — Do not implement full Design Option execution

Do NOT wire:

```text
Design Option A sizing
Design Option B sizing
Design Option C sizing
Design Option D sizing
```

into this agent yet.

The design branch should only:

```text
collect
classify
validate
report completeness
```

in this task.

The physical feed screen executes independently.

---

# Step 47 — Keep the architecture extensible

The target should make later additions natural:

```text
Feed screening
       ↓
physical phase routing
       ↓
technology screening
       ↓
candidate separation method
       ↓
distillation selected?
       ↓
use already-stored Design Option specification
       ↓
execute deterministic distillation design
```

That is why the Design Option information should be retained even though it is not used to gate the feed screen.

---

# Target final architecture

```text
                    USER
                      ↓
                Qwen extraction
                      ↓
        update_binary_distillation_problem()
                      ↓
             AUTHORITATIVE STATE
                      ↓
        ┌─────────────┴─────────────┐
        ↓                           ↓
 FEED-SCREEN ASSESSMENT       DESIGN ASSESSMENT
        ↓                           ↓
components?                    Design Option A-D?
quantity?                      required fields?
units?                         reflux condition?
pressure?                      optimum feed?
thermal spec?                  complete?
        ↓                           ↓
ready / not ready              complete / incomplete
        ↓                           ↓
        │                       stored only
        ↓
BioSTEAM feed VLE
        ↓
phase classification
        ↓
 liquid ───────────────→ liquid-phase pathway

 vapor
   │
   └──→ condition whole feed at 313.15 K
                             ↓
 vapor-liquid ───────────────┘
                             ↓
                  conditioned phase split
                             ↓
             ┌───────────────┼────────────────┐
             ↓               ↓                ↓
      effectively liquid   >=50% liquid     <50% liquid
             ↓               ↓                ↓
        liquid pathway    liquid + vapor    vapor pathway
                             pathways
```

The Design Option branch remains available in parallel:

```text
stored design facts
       ↓
Design Option A/B/C/D identified
       ↓
complete when enough information exists
       ↓
future detailed distillation-design stage
```

---

# Expected example after refactor

User:

```text
Separate water and ethanol at 355 K and 101325 Pa.
The feed is 50 kmol/hr ethanol and 50 kmol/hr water.
```

Expected state:

```python
feed_screening = {
    "ready": True,
    "missing_inputs": [],
}
```

while:

```python
design_assessment = {
    "design_option": None,
    "design_option_candidates": ["A", "B", "C", "D"],
    "complete": False,
}
```

Assistant should say conceptually:

```text
The feed information is sufficient for feed-phase screening.

The distillation design specification does not yet identify a single
Design Option, but that does not block the feed-phase evaluation.

I can proceed with the feed-phase check.
```

User:

```text
Proceed.
```

Then execute:

```text
feed VLE at 355 K / 101325 Pa
        ↓
vapor-liquid
        ↓
condition whole feed at 313.15 K
        ↓
existing deterministic phase routing
```

No xD/xB/reflux/boilup information is required first.

---

# Expected example with early design information

User:

```text
Separate methanol and water, 50 kmol/hr each,
400 K, 101325 Pa.
xD = 0.95, xB = 0.01, V/B = 1.2.
Use the optimum feed plate.
```

Expected:

```python
feed_screening["ready"] == True
```

and simultaneously:

```python
design_assessment["design_option"] == "D"
```

assuming the current Design Option D deterministic definition matches those fields.

If reflux condition is still required for full design completeness:

```python
design_assessment["complete"] == False
```

may remain appropriate.

But feed screening must still run.

The assistant should not force completion of Design Option D before evaluating the feed.

---

# Definition of done

The refactor is complete when:

1. Feed screening has its own deterministic readiness assessment.
2. Design Options A-D have a separate deterministic assessment.
3. Feed screening does not require a Design Option.
4. Feed screening does not require reflux condition.
5. Feed screening does not require optimum-feed-plate confirmation.
6. Feed screening does require all physical inputs actually needed by BioSTEAM.
7. A feed-ready/no-design-option problem can run feed VLE.
8. A design-complete/feed-incomplete problem cannot run feed VLE.
9. Early design facts are stored and classified immediately.
10. Feed phase still uses the existing BioSTEAM calculation.
11. Vapor and vapor-liquid feeds still use the existing 313.15 K whole-feed conditioning calculation.
12. Existing complete-condensation/partial-condensation/vapor routing remains unchanged.
13. "What next?" identifies feed phase as the next executable step as soon as feed readiness is true.
14. Design Option completeness is not mixed into physical `calculation_progress`.
15. User-facing terminology says `Design Option A-D`.
16. User-facing terminology no longer says `Wankat Case A-D`.
17. Wankat source provenance remains preserved.
18. No Design Option is silently defaulted.
19. QR/Qc structured semantic metadata remains intact.
20. The full `tools/chopper` test suite passes.

---

# Testing requirements

At minimum add/update tests for:

1. feed ready + no Design Option;
2. feed ready + partial Design Option;
3. feed ready + complete Design Option;
4. complete Design Option + missing feed thermal condition;
5. complete Design Option + missing feed units;
6. feed ready + missing reflux condition;
7. feed ready + missing optimum-feed confirmation;
8. initial liquid feed;
9. initial vapor feed;
10. initial vapor-liquid feed;
11. complete condensation at 313.15 K;
12. genuine partial condensation;
13. <50% conditioned liquid;
14. early Design Option facts retained across turns;
15. no default to Design Option A;
16. "what next?" before feed screening;
17. "what next?" after feed screening;
18. calculation invalidation after state changes;
19. all user-facing `Design Option` terminology;
20. Wankat provenance remains present.

Run focused tests first and then the complete:

```text
tools/chopper
```

suite.

---

# Report back after implementation

Report:

1. exact files changed;
2. new feed-screening readiness function/schema;
3. new design-assessment schema;
4. whether legacy `status`/`case` fields were retained for compatibility;
5. exact new gate used by `calculate_binary_distillation_problem()`;
6. exact new gate used by `build_biosteam_feed()`;
7. how pending-request priority changed;
8. how "what next?" changed;
9. all `Wankat Case` → `Design Option` user-facing terminology changes;
10. confirmation that Wankat provenance remains;
11. tests added/updated;
12. focused test result;
13. full-suite test result;
14. a raw example showing:

```python
feed_screening["ready"] == True
design_assessment["complete"] == False
```

followed by a successful real BioSTEAM feed-phase calculation.

Do not continue into downstream liquid/vapor separation implementation or full Design Option sizing after this refactor.