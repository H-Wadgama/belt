# Binary Distillation Column-Pressure and Condenser-Type Screening Workflow

## Purpose

This document defines the engineering workflow to add **column-pressure
and condenser-type screening** to the current binary-distillation
assistant.

The workflow is based on the Seider et al. passage and Figure 9.9
supplied for this project, adapted to the current BioSTEAM-based
implementation.

The central implementation rule is:

> **Qwen interprets what the user supplied. Deterministic Python
> resolves material balances, performs thermodynamic calculations,
> selects the condenser type and pressure, and reports the result.**

Qwen must **not** reason through the Seider pressure algorithm itself.

------------------------------------------------------------------------

## 1. Scope of this change

Implement a deterministic calculation layer that:

1.  obtains complete binary product flow rates and compositions from the
    already-identified Design Option;
2.  determines the condenser type and condenser pressure from the
    resolved distillate composition;
3.  estimates a screening bottoms pressure as the condenser pressure
    plus 10 psi;
4.  calculates the bottoms bubble-point temperature at that screening
    pressure;
5.  later compares that temperature with curated thermal-degradation /
    decomposition data.

Do **not** add a separate cooling-water-versus-refrigerant selection
workflow. That is not a decision the conversational model needs to make
in this implementation.

Do **not** ask Qwen to estimate `xD`, `xB`, `D`, or `B` when they can be
obtained deterministically from the supplied Design Option and material
balances.

------------------------------------------------------------------------

## 2. Existing Design Options must remain authoritative

The current project defines the Design Options as follows:

-   **Design Option A:** `xD` + `xB` + external reflux ratio `L0/D` +
    optimum feed plate.
-   **Design Option B:** fractional recoveries `Lr` + `Hr` + external
    reflux ratio `L0/D` + optimum feed plate.
-   **Design Option C:** one product flow (`D` or `B`) + one product
    composition (`xD` or `xB`) + external reflux ratio `L0/D` + optimum
    feed plate.
-   **Design Option D:** `xD` + `xB` + boilup ratio `V/B` + optimum feed
    plate.

Do not duplicate this Design Option identification logic inside the new
pressure-screening code.

The new calculation should consume the Design Option that the existing
deterministic workflow has already identified.

------------------------------------------------------------------------

## 3. Composition and flow basis

### Use a consistent molar basis

The current binary-distillation formulation uses molar quantities and
mole fractions. Therefore the product-balance calculation should remain
on a **molar basis**.

For component `i`:

\[ F = B + D \]

and

\[ F z_i = B x\_{B,i} + D x\_{D,i} \]

where:

-   `F` = total feed molar flow rate;
-   `D` = total distillate molar flow rate;
-   `B` = total bottoms molar flow rate;
-   `z_i` = feed mole fraction of component `i`;
-   `xD_i` = distillate mole fraction of the **same component `i`**;
-   `xB_i` = bottoms mole fraction of the **same component `i`**.

Never mix component identities in this equation. If `z_i` refers to
ethanol, `xD_i` and `xB_i` must also refer to ethanol.

### Do not convert to mass unnecessarily

A mass-balance form is also valid, but it would require mass flow rates
together with mass fractions:

\[ F_m w\_{F,i} = B_m w\_{B,i} + D_m w\_{D,i} \]

Do not combine mass flow rates with mole fractions.

Because the existing workflow is predominantly molar, **do not convert
to mass merely to perform these balances**. BioSTEAM may be used for
unit/basis conversion when a user actually supplies information on a
mass basis, but the internal resolved product state for this workflow
should use one clearly declared, consistent basis.

------------------------------------------------------------------------

## 4. Resolve the product state before pressure screening

The pressure/condenser calculation must receive a complete, physically
valid product state:

-   `F`
-   feed composition `z`
-   `D`
-   `B`
-   `xD`
-   `xB`

There should be no generic "estimate `xD`" step.

### Design Options A and D

The user already supplies `xD` and `xB`.

Use:

\[ D = F`\frac{z_i-x_{B,i}}{x_{D,i}-x_{B,i}}`{=tex} \]

\[ B = F-D \]

for either component `i`, using the same component consistently.

The binary complement provides the other component's composition.

### Design Option B

The user supplies light-key and heavy-key fractional recoveries.

For light key `L` and heavy key `H`:

\[ n\_{L,D}=L_r Fz_L \]

\[ n\_{L,B}=(1-L_r)Fz_L \]

\[ n\_{H,B}=H_r Fz_H \]

\[ n\_{H,D}=(1-H_r)Fz_H \]

Then:

\[ D=n\_{L,D}+n\_{H,D} \]

\[ B=n\_{L,B}+n\_{H,B} \]

and:

\[ x\_{D,L}=`\frac{n_{L,D}}{D}`{=tex} \]

\[ x\_{B,L}=`\frac{n_{L,B}}{B}`{=tex} \]

The heavy-key mole fractions are the binary complements.

Therefore Design Option B also produces deterministic `xD` and `xB`;
Qwen must not estimate them.

### Design Option C

One product flow and one product composition are supplied.

If `D` and `xD_i` are supplied:

\[ B=F-D \]

\[ x\_{B,i}=`\frac{Fz_i-Dx_{D,i}}{B}`{=tex} \]

If `B` and `xB_i` are supplied:

\[ D=F-B \]

\[ x\_{D,i}=`\frac{Fz_i-Bx_{B,i}}{D}`{=tex} \]

If the supplied flow and composition refer to opposite products, solve
the same two equations algebraically for the missing product
flow/composition rather than introducing a special heuristic.

### Validate the resolved product state

Before pressure screening, deterministically verify:

-   `F > 0`;
-   `D > 0`;
-   `B > 0`;
-   `F = D + B` within numerical tolerance;
-   every resolved mole fraction is between 0 and 1;
-   each binary composition sums to 1 within tolerance;
-   the component balance closes for both components within tolerance;
-   no division-by-zero or degenerate specification occurred.

If these checks fail, **do not run pressure screening**. Return a
structured invalid/infeasible result.

------------------------------------------------------------------------

## 5. Condenser-type and condenser-pressure workflow

Use the resolved **distillate composition `xD`**.

The reference temperature from the supplied Seider algorithm is:

\[ 120\^`\circ `{=tex}F `\approx 48.9`{=tex}\^`\circ `{=tex}C
`\approx 322.0`{=tex} K \]

Use a single canonical value in code and document it clearly.

### Step 1 --- Calculate the distillate bubble-point pressure

At the resolved distillate composition, calculate:

\[ P\_{`\text{bubble}`{=tex},D}(x_D,T=120\^`\circ `{=tex}F) \]

using the project's thermodynamic property system/BioSTEAM.

### Step 2 --- Low-pressure total-condenser branch

If:

\[ P\_{`\text{bubble}`{=tex},D}\<30 `\text{psia}`{=tex} \]

select:

-   `condenser_type = "total"`
-   `condenser_pressure = 30 psia`

This preserves Seider's instruction to avoid near-vacuum operation.

### Step 3 --- Normal total-condenser branch

If:

\[ 30`\le `{=tex}P\_{`\text{bubble}`{=tex},D}\<215 `\text{psia}`{=tex}
\]

select:

-   `condenser_type = "total"`
-   `condenser_pressure = P_bubble,D`

**Exception:** the supplied Seider text says to use a partial condenser
when a vapor distillate is explicitly required. If vapor-distillate
product state is not currently represented by the project, do not invent
it. Keep this exception documented for later support.

### Step 4 --- Partial-condenser branch

When the distillate bubble-point pressure reaches the high-pressure
branch (implementation convention: `P_bubble,D >= 215 psia`), calculate
the **distillate dew-point pressure at the same 120°F reference
temperature**:

\[ P\_{`\text{dew}`{=tex},D}(x_D,T=120\^`\circ `{=tex}F) \]

The dew-point pressure is not merely diagnostic. It becomes the
candidate condenser/distillate operating pressure for the
partial-condenser branch.

If:

\[ P\_{`\text{dew}`{=tex},D}\<365 `\text{psia}`{=tex} \]

select:

-   `condenser_type = "partial"`
-   `condenser_pressure = P_dew,D`
-   `condenser_pressure_basis = "distillate_dew_point_at_120F"`

### Step 5 --- Very-high-pressure branch

If the dew-point pressure reaches/exceeds the high-pressure cutoff
(implementation convention: `P_dew,D >= 365 psia`), select:

-   `condenser_type = "partial"`
-   `condenser_pressure = 415 psia`
-   `condenser_pressure_basis = "seider_high_pressure_rule"`

The original source associates this branch with a suitable refrigerant.
**Do not add a separate refrigerant-selection decision to this assistant
workflow.**

The important engineering result retained here is the selected **415
psia condenser pressure**, because that pressure affects the subsequent
bottoms-temperature screen.

### Threshold convention

The supplied prose uses strict phrases such as "less than" and "greater
than," which leave exact equality at 215 and 365 psia unstated.

To avoid undefined software behavior, use this explicit implementation
convention:

-   `< 30 psia` → 30 psia total-condenser branch;
-   `30 <= P_bubble < 215 psia` → normal total-condenser branch;
-   `P_bubble >= 215 psia` → partial-condenser/dew-point branch;
-   `P_dew < 365 psia` → use dew-point pressure;
-   `P_dew >= 365 psia` → use 415 psia.

Keep these equality choices documented as implementation conventions
rather than presenting them as additional textbook statements.

------------------------------------------------------------------------

## 6. Bottoms thermal-stability screening

Once condenser pressure `P_D` has been selected, estimate the bottoms
pressure for **screening purposes** as:

\[ P\_{B,`\text{screen}`{=tex}}=P_D+10 `\text{psia}`{=tex} \]

The sign is **plus**, not minus.

This does **not** mean the current BioSTEAM shortcut column suddenly
models a pressure profile. The `+10 psia` value is a separate
preliminary-design screening allowance taken from the supplied Seider
procedure.

Using the already-resolved bottoms composition `xB`, calculate:

\[ T\_{`\text{bubble}`{=tex},B} =
T\_{`\text{bubble}`{=tex}}(x_B,P\_{B,`\text{screen}`{=tex}}) \]

This is the estimated bottoms temperature used for the thermal-stability
check.

------------------------------------------------------------------------

## 7. Thermal-degradation data

Thermal-degradation/decomposition limits will be added separately once
reliable data have been curated.

Until that data exists, the pressure-screen calculation should still
return the calculated bottoms bubble-point temperature, but report:

``` text
thermal_stability_status = "not_evaluated"
thermal_stability_reason = "thermal_limit_unavailable"
```

Do not let Qwen invent a decomposition temperature.

Once curated data are available, compare the calculated bottoms
bubble-point temperature against the applicable verified limit.

Conceptually:

``` text
T_bottoms below applicable limit
    -> thermal screen passes

T_bottoms at/above applicable limit
    -> current pressure fails thermal screen
```

The source then says to reduce condenser pressure appropriately when the
bottoms temperature exceeds the decomposition or critical temperature.
**Do not silently change the user's operating pressure in the first
implementation.** Return the failed thermal screen and the relevant
calculated values. A later deterministic pressure-adjustment/search
routine can own repeated pressure reduction.

------------------------------------------------------------------------

## 8. Full deterministic workflow

``` text
Existing binary-distillation problem
        |
        v
Existing Python workflow identifies Design Option A/B/C/D
        |
        v
Resolve complete binary product state by material balance
        |
        +--> F
        +--> D
        +--> B
        +--> xD
        +--> xB
        |
        v
Validate product state and balance closure
        |
        +---- invalid --> STOP with structured failure
        |
        v
Calculate distillate bubble-point pressure at 120°F
        |
        +---- P_bubble < 30 psia
        |       |
        |       +--> total condenser
        |       +--> P_D = 30 psia
        |
        +---- 30 <= P_bubble < 215 psia
        |       |
        |       +--> total condenser
        |       +--> P_D = P_bubble
        |
        +---- P_bubble >= 215 psia
                |
                v
        Calculate distillate dew-point pressure at 120°F
                |
                +---- P_dew < 365 psia
                |       |
                |       +--> partial condenser
                |       +--> P_D = P_dew
                |
                +---- P_dew >= 365 psia
                        |
                        +--> partial condenser
                        +--> P_D = 415 psia
        |
        v
P_B,screen = P_D + 10 psia
        |
        v
Calculate bottoms bubble-point temperature
using resolved xB at P_B,screen
        |
        v
Thermal limit available?
        |
        +---- NO
        |       -> report thermal screen not evaluated
        |
        +---- YES
                |
                +---- T_bottoms below limit
                |       -> thermal screen passes
                |
                +---- T_bottoms at/above limit
                        -> thermal screen fails
                        -> recommend deterministic lower-pressure
                           evaluation; do not silently mutate pressure
```

------------------------------------------------------------------------

## 9. Suggested structured result

The calculation should return enough information to audit every decision
without requiring Qwen to reconstruct the reasoning.

For example:

``` python
{
    "valid": True,

    "product_state": {
        "basis": "molar",
        "feed_flow": ...,
        "distillate_flow": ...,
        "bottoms_flow": ...,
        "feed_composition": {...},
        "distillate_composition": {...},
        "bottoms_composition": {...},
        "balance_closed": True,
        "source_design_option": "A"
    },

    "condenser_screen": {
        "reference_temperature_K": ...,
        "distillate_bubble_pressure_Pa": ...,
        "distillate_dew_pressure_Pa": ...,  # None when not needed
        "condenser_type": "total",          # or "partial"
        "condenser_pressure_Pa": ...,
        "condenser_pressure_basis": "distillate_bubble_point_at_120F"
    },

    "bottoms_thermal_screen": {
        "screen_pressure_Pa": ...,
        "pressure_drop_allowance_Pa": ...,
        "bottoms_bubble_temperature_K": ...,
        "thermal_limit_K": None,
        "thermal_stability_status": "not_evaluated",
        "thermal_stability_reason": "thermal_limit_unavailable"
    }
}
```

Use the project's existing naming conventions where they already exist.
Do not create duplicate mutable problem fields merely to hold derived
calculation results.

------------------------------------------------------------------------

## 10. Where the engineering assumptions belong

Do not make Qwen remember the assumptions of the implemented calculation
method.

Facts about **what the implemented software assumes or supports** should
live in deterministic calculation/workflow metadata or documentation.

Examples:

-   binary-feed-only scope;
-   constant-pressure shortcut-column model;
-   which Design Options are implemented;
-   material-balance equations;
-   condenser-pressure algorithm;
-   calculation readiness requirements.

Engineering guidance about **when a shortcut distillation method is
appropriate**, such as applicability to ideal liquid mixtures or
suitable hydrocarbon systems, can remain in curated engineering
knowledge/RAG until a deterministic applicability test exists.

Likewise, source-backed thermal-degradation data may be stored in a
curated engineering knowledge/data layer, but once a verified numerical
thermal limit is available to the calculation, **Python should perform
the comparison**.

Do not use RAG as the authority for facts about what the software itself
implements.

------------------------------------------------------------------------

## 11. Implementation instructions

1.  **Do not change Design Option identification.** Reuse the existing
    A-D definitions and current authoritative problem state.

2.  **Add one deterministic product-state resolver** that turns a
    complete Design Option plus the feed into `D`, `B`, `xD`, and `xB`.
    Keep it independent of Qwen.

3.  **Keep the resolver on a consistent molar basis** unless input
    conversion is actually required. Never combine mass flow with mole
    fractions.

4.  **Validate material-balance closure before thermodynamics.** A
    failed/degenerate balance must block pressure screening.

5.  **Add one deterministic condenser-pressure screen** that accepts the
    resolved distillate composition and performs the 120°F bubble/dew
    calculations and threshold decisions above.

6.  **Do not ask Qwen to select total versus partial condenser.** Python
    returns the condenser type and selected condenser pressure.

7.  **Do not add cooling-utility selection logic.** Retain the 415 psia
    engineering pressure rule, but do not create a conversational
    decision about refrigerant selection.

8.  **Add the separate bottoms screening pressure** `P_D + 10 psia`. Do
    not alter the shortcut column model to pretend it simulates this
    pressure drop.

9.  **Calculate the bottoms bubble-point temperature from the resolved
    `xB`.**

10. **Keep thermal degradation optional for this implementation round.**
    Return `not_evaluated` until curated data are available. Never infer
    a thermal limit.

11. **Preserve provenance.** Distinguish user-specified quantities from
    deterministically derived quantities and from Seider screening
    assumptions.

12. **Preserve existing architecture.** Do not replace the canonical
    state-update path, atomic validation, diagnostics, or existing
    feed/design workflow merely to add this calculation.

------------------------------------------------------------------------

## 12. Required tests

### Material-balance tests

Test at least:

-   Design Option A: supplied `xD`/`xB` correctly produce `D` and `B`;
-   Design Option B: supplied `Lr`/`Hr` correctly produce component
    product flows, `D`, `B`, `xD`, and `xB`;
-   Design Option C with `D + xD`;
-   Design Option C with `B + xB`;
-   Design Option D: supplied `xD`/`xB` correctly produce `D` and `B`;
-   calculated compositions remain within `[0, 1]`;
-   invalid/degenerate balances are rejected;
-   total and both component balances close within tolerance;
-   the same component identity is used consistently in every component
    balance.

### Condenser decision tests

Use controlled/mock thermodynamic results so the branch logic itself can
be tested independently.

Test:

-   bubble pressure below 30 psia → total condenser, `P_D = 30 psia`;
-   bubble pressure between 30 and 215 psia → total condenser,
    `P_D = P_bubble`;
-   bubble pressure at/above 215 psia → dew-point calculation is
    required;
-   dew pressure below 365 psia → partial condenser, `P_D = P_dew`;
-   dew pressure at/above 365 psia → partial condenser,
    `P_D = 415 psia`;
-   dew-point calculation is **not** performed on total-condenser
    branches;
-   equality behavior at 215 and 365 psia follows the documented
    implementation convention.

### Bottoms-screen tests

Test:

-   `P_B,screen = P_D + 10 psia`;
-   the bottoms bubble-point calculation uses the resolved `xB`;
-   no thermal data → `not_evaluated`;
-   later, known safe limit → pass;
-   later, exceeded limit → fail;
-   a failed thermal screen does not silently mutate the user's stored
    operating pressure.

### Integration tests

For each Design Option A-D, verify the full deterministic chain:

``` text
complete design specification
-> resolved product state
-> condenser decision
-> selected condenser pressure
-> bottoms screening pressure
-> bottoms bubble-point temperature
```

The test should verify numerical/state outputs, not merely assistant
prose.

After deterministic tests pass, run live-Qwen conversations only to
verify that Qwen correctly extracts the user's Design Option inputs and
accurately explains the deterministic result. **Do not use live-Qwen
success as evidence that the engineering calculations themselves are
correct.**

------------------------------------------------------------------------

## 13. Explicit non-goals

Do not:

-   make Qwen implement or interpret the Seider flowchart;
-   estimate `xD` or `xB` with an LLM;
-   duplicate Design Option A-D logic;
-   convert molar balances to mass balances without a real
    basis-conversion need;
-   mix mass flows with mole fractions;
-   add cooling-water/refrigerant selection as an LLM decision;
-   invent thermal-degradation temperatures;
-   silently lower the user's pressure after a failed thermal screen;
-   change the shortcut column into a pressure-drop model;
-   weaken existing validation or atomic state-update behavior;
-   add special cases for particular chemicals such as ethanol/water.

------------------------------------------------------------------------

## 14. Definition of done

This implementation is complete when:

1.  every complete Design Option A-D produces a deterministic, validated
    binary product state containing `D`, `B`, `xD`, and `xB`;
2.  the pressure screen uses that resolved `xD`, never an LLM estimate;
3.  the total/partial condenser decision follows the documented
    30/215/365/415 psia branches;
4.  the dew-point pressure becomes the condenser operating pressure on
    the applicable partial-condenser branch;
5.  the bottoms screen uses `P_D + 10 psia`, not `P_D - 10 psia`;
6.  the bottoms bubble-point temperature is calculated from the resolved
    `xB`;
7.  absent thermal-limit data are reported explicitly rather than
    guessed;
8.  all engineering decisions are made by deterministic Python;
9.  existing binary-distillation state/validation architecture remains
    intact;
10. regression, branch, and integration tests pass.

------------------------------------------------------------------------

## Source basis and implementation notes

The condenser-pressure thresholds and sequence in this document are
based on the Seider et al. passage/Figure 9.9 supplied by the project
owner.

The existing Design Option A-D definitions come from the project's
current Wankat-derived binary-distillation workflow.

Two adaptations are intentionally explicit:

1.  cooling-utility/refrigerant selection is not exposed as a separate
    assistant decision;
2.  exact equality at the 215 and 365 psia thresholds is resolved by
    documented software conventions so the deterministic implementation
    has no undefined boundary.

These adaptations should remain documented rather than being presented
as verbatim textbook rules.
