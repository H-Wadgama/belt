# Multicomponent Post-Feed Specification Intake Plan

## Purpose and current scope

This document defines the next conversational step for
`tools/chopper/multicomponent_distillation_agent.py` after its existing
feed phase evaluation.

The current implementation already collects and validates the multicomponent
feed, including component identities, component molar flows, total feed molar
flow `F`, feed mole fractions `z`, pressure, and temperature. The feed handed
to this next step must be available on a consistent molar basis and normalized
to `kmol/hr` where needed.

After reporting the feed phase and phase fractions, the agent must collect one
of the two currently supported pairs of separation specifications, verify that
the selected pair is complete, and ask whether the user wants to proceed with
the calculation.

This implementation round ends at that confirmation question. It does not run
a column calculation or perform condenser, thermal, economic, or optimization
work.

## Replace inherited binary Design Options

The former binary Design Options A-D are not authoritative for this
multicomponent agent and must not be copied or re-identified here.

There are two alternative specification modes and three conversation states:

1. `collecting_separation_specifications`;
2. `separation_specifications_complete`, awaiting confirmation; and
3. `calculation_confirmed`, a handoff point for future work.

These are conversation states, not different column-design methods.

## Information already known

Do not ask the user to re-enter committed feed information. Consume a
read-only snapshot of:

- component identities and component molar flows;
- total feed molar flow `F` in `kmol/hr`;
- feed mole fractions `z`;
- feed pressure and temperature; and
- evaluated phase and molar phase fractions.

If another supported flow unit was supplied, deterministic Python must convert
it to `kmol/hr` and record the conversion. Qwen must not perform conversions.

The later product calculation must use a consistent molar basis:

\[
F = B + D
\]

and, for every feed component `i`,

\[
Fz_i = Bx_{B,i} + Dx_{D,i}.
\]

Component identities must remain aligned across `z_i`, `xB_i`, and `xD_i`.
This intake step must not claim that two key specifications alone determine
every non-key product composition. A future shortcut-column calculation must
resolve non-key distributions and validate all component balances.

## Light and heavy keys

Both specification modes require one light key (`LK`) and one heavy key
(`HK`). Both must already exist in the committed feed and must be different
components.

If the keys are not known, collect them before asking for recoveries or
compositions. Do not infer key identities from component order, boiling point,
molecular weight, or Qwen's general knowledge.

Key matching follows the feed-intake workflow's case-insensitive identity
rules while preserving the established display spelling.

## Supported specification modes

Accept exactly one complete pair from either mode.

### Mode 1: key recoveries

Collect both:

- `Lr`: fractional recovery of the light key in the distillate; and
- `Hr`: fractional recovery of the heavy key in the bottoms.

\[
L_r = \frac{n_{LK,D}}{n_{LK,F}}, \qquad
H_r = \frac{n_{HK,B}}{n_{HK,F}}.
\]

Both values must be finite dimensionless fractions strictly between 0 and 1.
Percentages may be accepted and normalized deterministically.

### Mode 2: light-key product compositions

Collect both:

- `xD_LK`: mole fraction of the light key in the distillate; and
- `xB_LK`: mole fraction of the light key in the bottoms.

Both values must be finite dimensionless mole fractions strictly between 0
and 1. Their product locations must never be swapped.

Before passing these values to BioSTEAM, a later implementation must document
whether the public values are overall product mole fractions or the
key-pair-normalized `y_top` and `x_bot` values used by `ShortcutColumn`. These
definitions must not be silently treated as interchangeable.

### Deferred mixed modes

Do not accept mixed pairs as complete in this round, including:

- `Lr` plus either `xD_LK` or `xB_LK`;
- `Hr` plus either product composition;
- `D` or `B` plus a product composition; or
- any other pair requiring a solver to calculate the remaining specification.

## Required prompt after phase evaluation

The phase result must still be reported, for example:

```text
Phase: vapor_liquid. Vapor fraction: 0.4338. Liquid fraction: 0.5662.
```

The response must then continue into separation-specification intake. If the
keys are known, ask:

```text
Please specify either:
1. the recovery of the light key in the distillate and the recovery of the
   heavy key in the bottoms; or
2. the mole fraction of the light key in the distillate and the mole fraction
   of the light key in the bottoms.
```

Use the actual committed key names when available. If the key identities are
not known, ask for the light and heavy keys first and then present the two
supported modes.

## Deterministic interpretation and validation

Qwen may propose what the user meant, but deterministic Python remains the
authority for accepting and storing facts.

For each turn:

1. use the existing schema-constrained interpretation boundary;
2. ground every key, value, basis, product location, and specification type in
   the current message or an unambiguous active-request answer;
3. validate candidate facts without changing committed state;
4. commit only valid logical groups atomically;
5. determine the selected mode from committed facts; and
6. return the next deterministic question or confirmation prompt.

Validation must ensure:

- both keys exist in the feed and `LK != HK`;
- all values are finite and satisfy `0 < value < 1` after normalization;
- each value is tied to its exact component, product, and meaning;
- Mode 1 is complete only with both `Lr` and `Hr`;
- Mode 2 is complete only with both `xD_LK` and `xB_LK`; and
- values from different modes are not silently combined.

Partial valid input persists across turns. Rejected input must not erase
committed facts. An explicit mode change must be validated atomically.
Deterministic short-answer binding has priority for an active request.

## Completion and confirmation

The supported input contract is complete only when:

- the committed feed snapshot is complete;
- distinct valid light and heavy keys are committed; and
- either `Lr + Hr` or `xD_LK + xB_LK` is complete.

This means only that the supported inputs are complete; it does not mean that
`D`, `B`, or complete product compositions have been solved.

When incomplete, ask only for missing information. When complete, summarize
the committed keys and specification pair and ask:

```text
The required separation specifications are complete. Would you like to
proceed with the calculation?
```

An affirmative response changes the state to `calculation_confirmed`, but this
round then stops. A negative response preserves the inputs for correction. An
unclear response does not change confirmation state.

## State and provenance

Extend the existing per-conversation state. Store authoritative records for:

- light-key and heavy-key identities;
- active specification mode;
- the applicable specification values;
- completion and confirmation status;
- provenance, source turn, and grounding evidence.

Keep user values distinct from deterministic conversions and future calculated
values. Read-only questions must not mutate state or trigger confirmation.

## Out of scope

Do not yet implement:

- automatic key selection;
- mixed specification pairs;
- complete product-state calculation or non-key distribution;
- shortcut-column simulation;
- reflux ratio or boil-up intake;
- condenser or pressure screening;
- thermal-stability screening;
- costing; or
- optimization.

## Required tests

Test at least:

- phase reporting continues into key/specification intake;
- committed feed facts are not requested again;
- keys must be distinct components in the feed;
- valid `Lr + Hr` completes Mode 1;
- valid `xD_LK + xB_LK` completes Mode 2;
- partial pairs remain available across turns;
- mixed pairs are not treated as complete;
- invalid ranges and swapped product meanings are rejected atomically;
- Qwen cannot invent a missing value;
- a complete pair produces a deterministic summary and confirmation question;
- no calculation runs before or after confirmation in this round; and
- read-only questions do not count as confirmation.

## Completion criterion

This plan is complete when the agent can continue from a completed feed-phase
result, collect valid keys and either supported specification pair, verify the
input contract, and ask whether to proceed. Nothing after confirmation is part
of this plan.
