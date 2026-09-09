# Multicomponent Direct ShortcutColumn Train Plan

## Current Decisions

- Use the direct, light-first sequence only.
- Require every feed component as an individual product.
- Screen critical temperatures first and adjacent relative volatilities second.
- Reject ordinary distillation when any `T_feed > Tc` or adjacent `alpha < 1.05`.
- Suppress passing relative-volatility values unless explicitly queried.
- Ask the user for minimum total-stream mole purity for every product.
- Use BioSTEAM `ShortcutColumn` with `k=2`, `partial_condenser=False`,
  `P=101325 Pa`, and zero inter-column pressure drop.
- Optimize and report every `y_top` and `x_bot`.

## Direct Sequence

For normal-boiling-point order `C1, ..., Cn`, build `n-1` columns:

1. Column 1 uses `(C1, C2)` and produces `C1` as distillate.
2. Column 2 uses `(C2, C3)` and receives the preceding bottoms.
3. Continue through `(C[n-1], Cn)`.
4. `Cn` is the final bottoms product.

## Initial Optimization

Use all `2(n-1)` composition specifications as bounded decision variables.
Simulate the complete train for every candidate and constrain the actual total-
stream mole purity of every product to meet its requested minimum. The current
placeholder objective minimizes squared distance from non-extreme composition
specifications (`y_top=0.5`, `x_bot=0.5`).

This objective intentionally supplies a deterministic first implementation. It
does not claim economic optimality and must later be replaced or extended with
recovery constraints and an annualized-cost objective.

## Required Result Boundary

Return only plain structured data: sequence, column keys, optimized `y_top` and
`x_bot`, fixed assumptions, achieved product purities and recoveries, stages,
reflux values, and available BioSTEAM costs. Never return live BioSTEAM objects.

## Verification

- Ternary ethanol/water/glycerol at 50 kmol/hr each, 355 K.
- One common 90 mol% target and unequal per-component targets.
- Critical-temperature and relative-volatility gates prevent column execution.
- Seven ordered components create six columns and twelve specifications.
- Feed-phase, boiling-order, and relative-volatility queries remain read-only.
