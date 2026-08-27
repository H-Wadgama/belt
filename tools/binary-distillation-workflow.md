# Binary Distillation Workflow-Only Refactor

## Objective

Refactor the current separation assistant so that, for now, it acts only as a **binary-distillation problem-definition and workflow-routing system**.

Do **not** perform distillation calculations, BioSTEAM simulations, reflux-ratio optimization, economic optimization, or equipment sizing during this phase.

The purpose of this phase is to verify that the assistant can:

1. recognize whether a problem is actually binary;
2. collect the mandatory binary-distillation information;
3. identify which Wankat binary-distillation design case (A–D) the supplied specifications correspond to;
4. identify exactly what information is still missing;
5. recognize when a user-supplied variable already determines the likely design case;
6. ask for the common optimum-feed-plate assumption separately;
7. report which variables **would be calculated** once the problem is fully specified; and
8. stop there without performing those calculations.

The engineering specification framework is based on:

**Wankat, Phillip C. _Separation Process Engineering: Includes Mass Transfer Analysis_. Pearson, 2022.**

Specifically:

- Table 3-1: usual specified variables for binary distillation
- Table 3-2: specifications and calculated variables for binary-distillation design problems

---

# 1. Architectural Principle

Do not rely on the LLM to reason internally about whether a problem corresponds to Case A, B, C, or D.

Implement the workflow as deterministic Python validation.

The architecture should be:

```text
User
  ↓
Qwen extracts supplied information
  ↓
Binary-distillation workflow checker
  ↓
Structured workflow result
  ↓
Qwen explains missing inputs / identified case / expected calculations
```

For this phase there should be **no downstream calculation step**.

Therefore:

```text
DO NOT CALL
    BioSTEAM BinaryDistillation
    run_separation()
    sweep_reflux_ratio()
    optimize_reflux_ratio()
    optimize_separation()
    economic calculations
```

The workflow checker is currently the terminal engineering tool.

---

# 2. First Gate — Enforce Binary Scope

The very first engineering check is the number of components in the requested separation.

Count distinct components with nonzero feed amount.

## Zero components

Return an incomplete-input response requesting the components.

Example:

```text
Please specify the two components you want to separate.
```

## One component

Do not proceed.

Return something equivalent to:

```text
Binary distillation requires two components. You have specified Methanol.
Please specify the second component.
```

## Exactly two components

Proceed to the essential-input check.

## More than two components

Do not attempt key selection, multicomponent shortcut distillation, or any other workaround.

Return something equivalent to:

```text
The current system supports binary distillation only. You specified
Methanol, Water, and Glycerol. Please define a separation containing
exactly two components.
```

The LLM must not silently ignore extra components.

---

# 3. Second Gate — Check the Five Essential Binary-Distillation Inputs

Once exactly two components are established, check the mandatory problem-definition information.

The required information is:

```text
1. Feed composition
2. Feed flow rate
3. Column pressure
4. Feed thermal condition
5. Reflux thermal condition
```

The feed thermal condition may be supplied as exactly one of:

```text
feed temperature
OR
feed enthalpy
OR
feed quality / vapor fraction
```

The reflux thermal condition may be represented by:

```text
reflux temperature
OR
reflux enthalpy
```

If the current implementation only supports saturated-liquid reflux, it is acceptable to represent this explicitly as:

```text
reflux_condition = "saturated_liquid"
```

but it must be explicitly supplied or explicitly confirmed by the user.

Do not silently assume saturated-liquid reflux.

Do not silently place the feed at its bubble point.

Do not silently assume 1 atm.

---

# 4. Treat Feed Composition and Flow Rate Carefully

Allow the user to describe the feed in either of two equivalent forms.

### Form 1 — Total flow + composition

Example:

```text
100 kmol/hr total feed
40 mol% methanol
60 mol% water
```

### Form 2 — Component flow rates

Example:

```text
40 kmol/hr methanol
60 kmol/hr water
```

In Form 2, the component flow rates contain enough information to determine both total feed flow and feed composition.

Do not unnecessarily ask the user for:

```text
total flow = 100 kmol/hr
```

if it can already be determined exactly from the component flows.

Internally normalize both forms to a common structured representation.

---

# 5. Missing Essential Inputs Take Priority

Before discussing Cases A–D, determine whether all five essential inputs are available.

If some are missing, return all missing essential inputs together.

Example:

```text
I have:
- Components: Methanol and Water
- Feed flow/composition: provided

I still need:
- Column pressure
- Feed temperature, enthalpy, or quality
- Reflux temperature or enthalpy
```

Do not ask about Case A–D specifications while basic feed/column information is still missing unless the user has already supplied those specifications voluntarily.

However, preserve any Case A–D information the user already gave for later use.

---

# 6. Store Information Across Follow-Up Turns

The assistant must maintain the accumulated problem state during one separation problem.

Example:

```text
User:
Separate methanol and water.

Assistant:
Please provide the missing feed information.

User:
100 kmol/hr, 40 mol% methanol.

Assistant:
...
```

The second user message must extend the existing problem rather than create a new separation problem.

Maintain a structured state object such as:

```python
BinaryDistillationProblemState
```

containing all information established so far.

Do not require Qwen to resend every previously supplied value on every tool call.

---

# 7. Do Not Default to Case A

Remove the current behavior that automatically defaults an unspecified problem to Case A.

For this workflow-validation stage:

```text
no distinguishing design specifications
≠
Case A
```

Instead return:

```text
case = None
case_candidates = ["A", "B", "C", "D"]
```

or an equivalent structured representation.

The purpose is to see whether the user's supplied variables genuinely establish a design case.

---

# 8. Wankat Case Definitions

After the essential inputs have been collected, classify the additional design specifications according to the following deterministic rules.

## Case A — Product Compositions + External Reflux Ratio

Required design specifications:

```text
xD
xB
external reflux ratio L0/D
use optimum feed plate
```

Where:

```text
xD = mole fraction of the more volatile component in distillate
xB = mole fraction of the more volatile component in bottoms
```

If complete, the designer would calculate:

```text
D
B
QR
Qc
N
optimum feed plate / Nfeed
column diameter
```

---

## Case B — Component Recoveries

Required design specifications:

```text
fractional recovery of specified component in distillate
fractional recovery of specified component in bottoms
external reflux ratio L0/D
use optimum feed plate
```

If complete, the designer would calculate:

```text
xD
xB
D
B
QR
Qc
N
Nfeed
column diameter
```

---

## Case C — Product Flow + Product Composition

Required design specifications:

```text
D OR B
xD OR xB
external reflux ratio L0/D
use optimum feed plate
```

If `D` was supplied, calculate `B`.

If `B` was supplied, calculate `D`.

If `xD` was supplied, calculate `xB`.

If `xB` was supplied, calculate `xD`.

Additional calculated quantities:

```text
QR
Qc
N
Nfeed
column diameter
```

---

## Case D — Product Compositions + Boilup Ratio

Required design specifications:

```text
xD
xB
boilup ratio V/B
use optimum feed plate
```

If complete, the designer would calculate:

```text
D
B
QR
Qc
N
Nfeed
column diameter
```

---

# 9. Case Identification Must Use Distinguishing Variables

Some variables occur in several cases and therefore must not be treated as evidence by themselves that a particular case was selected.

In particular:

```text
"use optimum feed plate"
```

appears in Cases A, B, C, and D.

Therefore:

```text
optimum_feed_plate = True
```

provides **zero information for case classification**.

Similarly:

```text
external reflux ratio
```

occurs in Cases A, B, and C.

Therefore an external reflux ratio alone cannot distinguish A, B, and C.

---

# 10. Strong Case Signals

Some variables strongly narrow the possible case.

Use deterministic rules.

### Boilup ratio V/B supplied

This is a strong signal for:

```text
Case D
```

because Case D is the Wankat design case that uses V/B as the specified operating ratio.

Then determine what Case D fields remain missing.

Example:

```text
User supplied:
V/B = 2.5
```

The system should respond conceptually:

```text
The boilup ratio identifies this as a Case D-type specification.

Still required:
- xD
- xB
- confirmation that optimum feed-plate placement should be used
```

Do not ask the user to choose between Cases A–D after V/B has already identified D.

---

### Fractional recoveries supplied

This points toward:

```text
Case B
```

Then request whatever Case B fields are still missing.

---

### Product flow D or B supplied

Together with a product composition specification, this points toward:

```text
Case C
```

Then request the missing Case C fields.

---

### xD and xB supplied

By themselves these do not distinguish A from D.

Determine whether the user has also supplied:

```text
external reflux ratio → Case A
boilup ratio V/B      → Case D
```

If neither has been supplied, return both possibilities:

```text
case_candidates = ["A", "D"]
```

and explain what distinguishing information is required.

Do not guess.

---

# 11. When No Design Case Can Yet Be Identified

Suppose the user says:

```text
I want to separate methanol and water using an optimum feed plate.
```

Assuming the five essential inputs are eventually supplied, the phrase:

```text
use an optimum feed plate
```

does not identify a Wankat case.

The assistant should explain that an additional design specification set is required.

It may present the four valid options:

```text
A. xD + xB + external reflux ratio
B. component recoveries + external reflux ratio
C. D or B + xD or xB + external reflux ratio
D. xD + xB + boilup ratio V/B
```

Do not require the user to literally answer:

```text
"Case A"
```

The user may simply provide engineering quantities.

For example:

```text
I want xD = 0.99, xB = 0.01, and L0/D = 2.5.
```

The deterministic checker should recognize Case A automatically.

The case letters are an organizational framework, not required user syntax.

---

# 12. Optimum Feed Plate Handling

Because optimum-feed-plate use is common to all four Wankat design cases, model it as a common design confirmation rather than part of case classification.

Suggested field:

```python
use_optimum_feed_plate: bool | None
```

If it has not been established, ask:

```text
Should the design use the optimum feed plate?
```

Do not silently set it to `True`.

If the current platform intends to support only optimum-feed-plate calculations, the response can instead say:

```text
The current binary-distillation workflow uses the optimum feed plate.
Is that acceptable for this design?
```

Store the user's confirmation.

---

# 13. Distinguish Reflux Quantities Explicitly

Maintain a strict distinction between:

```text
external reflux ratio:
R = L0/D

minimum reflux ratio:
Rmin

shortcut multiplier:
k = R/Rmin
```

Do not treat these as interchangeable.

Wankat Cases A–C are specified using the external reflux ratio L0/D.

The existing optimizer's `k = R/Rmin` is an internal BioSTEAM-oriented variable and should not replace the Wankat problem specification silently.

For this workflow-only phase, no conversion between them should be performed.

---

# 14. Final State — "Ready for Calculation"

Once:

1. exactly two components are established;
2. all five essential inputs are present;
3. exactly one Case A–D is fully identified;
4. all required specifications for that case are present; and
5. optimum-feed-plate use has been established;

return:

```python
{
    "status": "ready_for_calculation",
    "valid": True,
    "case": "...",
    "inputs": {...},
    "would_calculate": [...],
    "calculation_performed": False
}
```

The user-facing response should say something such as:

```text
Your binary-distillation problem is fully specified as Wankat Case D.

Specified:
- Methanol / Water
- feed ...
- pressure ...
- feed condition ...
- reflux condition ...
- xD ...
- xB ...
- V/B ...
- optimum feed plate: yes

If the calculation stage were enabled, the designer would calculate:
- distillate flow D
- bottoms flow B
- reboiler duty QR
- condenser duty Qc
- number of stages N
- optimum feed stage Nfeed
- column diameter

No distillation calculations have been performed.
```

This is the stopping point for the current development stage.

---

# 15. Suggested Structured Output From the Workflow Checker

Create a deterministic function such as:

```python
assess_binary_distillation_problem(spec: dict) -> dict
```

Suggested return schema:

```python
{
    "valid_binary_scope": bool,
    "component_count": int,
    "components": list[str],

    "essential_complete": bool,
    "missing_essential_inputs": list[str],

    "case": "A" | "B" | "C" | "D" | None,
    "case_candidates": list[str],
    "case_complete": bool,
    "missing_case_inputs": list[str],

    "optimum_feed_plate_confirmed": bool | None,

    "status": (
        "need_components"
        | "unsupported_multicomponent"
        | "need_essential_inputs"
        | "need_case_definition"
        | "need_case_inputs"
        | "ready_for_calculation"
        | "ambiguous"
    ),

    "would_calculate": list[str],

    "calculation_performed": False,

    "message": str,

    "provenance": {
        "source": "Wankat, Separation Process Engineering, 2022",
        "essential_inputs": "Table 3-1",
        "design_cases": "Table 3-2"
    }
}
```

Qwen should primarily communicate this structure rather than independently reproduce the engineering decision logic.

---

# 16. Suggested Decision Tree

Implement behavior equivalent to:

```text
START
  │
  ▼
How many nonzero feed components?
  │
  ├── 0 ──► Ask for two components
  │
  ├── 1 ──► Ask for second component
  │
  ├── >2 ─► Reject: binary only
  │
  └── 2
       │
       ▼
Check five essential inputs
       │
       ├── Missing
       │      └──► Report all missing essentials
       │
       └── Complete
              │
              ▼
       Inspect design specifications
              │
              ├── recoveries ───────────────► candidate B
              │
              ├── D/B + xD/xB ─────────────► candidate C
              │
              ├── V/B ─────────────────────► candidate D
              │
              ├── xD+xB+L0/D ──────────────► candidate A
              │
              ├── xD+xB only ──────────────► candidates A/D
              │
              └── none ────────────────────► explain A/B/C/D options
                                                   │
                                                   ▼
                                      Check missing fields for candidate
                                                   │
                                      ┌────────────┴────────────┐
                                      ▼                         ▼
                                  incomplete                 complete
                                      │                         │
                             ask only for missing              ▼
                                  information        optimum-feed-plate
                                                         confirmed?
                                                    ┌──────────┴─────────┐
                                                    ▼                    ▼
                                                   no                   yes
                                                    │                    │
                                                    ▼                    ▼
                                                  ask          READY FOR CALCULATION
                                                                     │
                                                                     ▼
                                                         report what would be
                                                              calculated
                                                                     │
                                                                     ▼
                                                                    STOP
```

---

# 17. Important Behavioral Requirement for Qwen

Update the system prompt so that Qwen is explicitly told:

```text
You are not the binary-distillation decision engine.

Extract information from the user's message and pass it to the deterministic
binary-distillation workflow checker.

Never infer a Wankat case when the workflow checker has not identified one.

Never invent missing engineering specifications.

Never assume pressure, feed thermal condition, reflux thermal condition,
product purity, recovery, reflux ratio, boilup ratio, or product flow.

Do not perform binary-distillation calculations during this development phase.

When the checker reports ready_for_calculation, tell the user which quantities
would be calculated and stop.
```

---

# 18. Temporarily Disable the Existing Calculation Tools

The current project already contains calculation and optimization functionality.

Do not delete it.

Instead, isolate it from this workflow test.

Options:

```text
A. Remove calculation tools from TOOLS exposed to Qwen temporarily

or

B. Keep them in the repository but add a workflow_mode flag that prevents
   execution

or preferably

C. Expose only assess_binary_distillation_problem() to Qwen in a dedicated
   workflow-testing agent.
```

Option C is preferred because it makes the experiment clean.

Create something conceptually like:

```text
binary_distillation_workflow_agent.py

TOOLS = [
    assess_binary_distillation_problem
]
```

Do not expose `optimize_separation()` to this test agent.

---

# 19. Acceptance Tests

Implement automated tests for at least the following conversations.

### Test 1 — One component

Input:

```text
I want to distill methanol.
```

Expected:

```text
status = need_components
```

Ask for another component.

---

### Test 2 — Three components

Input:

```text
Separate methanol, water, and glycerol.
```

Expected:

```text
status = unsupported_multicomponent
```

Do not calculate anything.

---

### Test 3 — Two components but no operating data

Input:

```text
Separate methanol and water.
```

Expected:

Report the missing five-essential-input information.

Do not assume bubble point or atmospheric pressure.

---

### Test 4 — Optimum feed plate only

Input includes:

```text
Use an optimum feed plate.
```

Expected:

This does NOT identify a case.

After essentials are complete:

```text
case = None
case_candidates = ["A", "B", "C", "D"]
```

Explain the valid specification sets.

---

### Test 5 — Boilup ratio supplied

Input includes:

```text
V/B = 2.0
```

Expected:

```text
case = D
```

Request:

```text
xD
xB
```

and optimum-feed-plate confirmation if not already established.

Do not ask the user to choose a case letter.

---

### Test 6 — Complete Case D

Input includes all essentials plus:

```text
xD = ...
xB = ...
V/B = ...
use optimum feed plate = yes
```

Expected:

```text
status = ready_for_calculation
case = D
```

Report:

```text
would_calculate =
[D, B, QR, Qc, N, Nfeed, column diameter]
```

Perform no calculations.

---

### Test 7 — xD and xB only

Expected:

```text
case_candidates = ["A", "D"]
```

Explain:

```text
external reflux ratio → Case A
boilup ratio V/B → Case D
```

Do not guess.

---

### Test 8 — Complete Case A

Expected:

```text
case = A
would_calculate =
[D, B, QR, Qc, N, Nfeed, column diameter]
```

No calculation.

---

### Test 9 — Recoveries

Expected:

```text
case = B
```

Report any missing Case B specifications.

---

### Test 10 — Product flow + product composition

Expected:

```text
case = C
```

Correctly identify whether D/B and xD/xB are inputs versus outputs.

---

### Test 11 — Component flows imply total flow and composition

Input:

```text
40 kmol/hr methanol
60 kmol/hr water
```

Expected:

Do not ask separately for feed flow rate and feed composition.

Normalize internally to:

```text
total flow = 100 kmol/hr
z_methanol = 0.4
z_water = 0.6
```

---

### Test 12 — Reflux-ratio terminology

Input:

```text
R = 2.5
```

Expected:

Treat as external reflux ratio only if context clearly means L0/D.

Never silently reinterpret it as:

```text
k = R/Rmin
```

---

# 20. Definition of Done

This phase is complete when:

- binary-only scope is deterministically enforced;
- all five essential inputs are checked;
- information persists across conversation turns;
- Cases A–D are deterministically identified;
- Case A is no longer silently defaulted;
- optimum feed plate does not influence case identification;
- V/B correctly routes toward Case D;
- incomplete cases return exact missing fields;
- ambiguous partial specifications return possible cases instead of guesses;
- actual reflux ratio and R/Rmin remain distinct;
- a complete specification returns the correct list of quantities the designer would calculate;
- no BioSTEAM calculation occurs;
- no optimization occurs; and
- Qwen can explain the structured workflow result without overriding it.