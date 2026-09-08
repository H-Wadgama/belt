# Multicomponent Normal-Boiling-Point Ordering Plan

## Purpose

Before asking for light- and heavy-key specifications, extend
`tools/chopper/multicomponent_distillation_agent.py` so that deterministic
Python orders every committed feed component by normal boiling point.

This plan is independent of the post-feed specification-intake plan. Its main
automatic result is the ordered component list. It also preserves feed-phase
evaluation as an on-demand diagnostic calculation when the user explicitly
asks for the feed phase.

## Required behavior

Once the multicomponent feed is complete and valid:

1. Obtain the normal boiling point of every nonzero-flow feed component from
   the project's ThermoSTEAM/BioSTEAM chemical property system.
2. Use one documented reference pressure for "normal": `101325 Pa` (`1 atm`).
3. Validate that every boiling point is present, finite, and physically valid.
4. Sort all feed components from lowest to highest normal boiling point.
5. Store the result as deterministic derived state with property provenance.

Qwen may interpret user-supplied feed information, but it must not supply,
estimate, rank, or repair boiling points.

The ordering must include all nonzero-flow components, not only two proposed
keys. Preserve the feed's established component spelling in displayed and
debug output. For exactly equal boiling points, preserve committed feed order
as a deterministic tie rule and mark the tie in diagnostics.

## Default output change

When a feed first becomes complete, the agent must not automatically return
the former terminal phase reply:

```text
Phase: vapor_liquid. Vapor fraction: 0.4338. Liquid fraction: 0.5662.
```

Instead, the automatic completion reply reports the normal-boiling-point order.
Feed phase and phase fractions are no longer the default output boundary, but
they remain supported as an explicit on-demand calculation described below.

This round does not automatically designate a light key or heavy key. The
ordered list is the prerequisite for a later key-selection step. In a
multicomponent feed, "lighter" means lower in this ordered list and "heavier"
means higher; it does not make any particular pair the separation keys.

## On-demand feed-phase evaluation

If the user explicitly asks for the feed phase after the required feed data
are committed, deterministic Python must run the existing multicomponent
feed-phase calculation and report its result. For example:

```text
User: What is the phase of the feed?
Assistant: Phase: vapor_liquid. Vapor fraction: 0.4338. Liquid fraction: 0.5662.
```

The calculation must use the committed values for:

- every component molar flow or the deterministically resolved feed mole
  fractions;
- feed temperature, converted deterministically to K; and
- feed pressure, converted deterministically to Pa.

The normal-boiling-point reference pressure of `101325 Pa` must **not** replace
the committed feed pressure in the phase calculation. Normal-boiling-point
ordering and feed-phase evaluation are separate calculations with separate
inputs.

The model may classify the user's request, but it must not calculate or guess
the phase. Python must recognize and ground explicit phase-query wording, then
call the existing phase evaluator directly. `phase`, `vapor fraction`, and
`liquid fraction` must be supported computational query targets rather than
being rejected merely because they are not user-entered feed fields.

Keep this path read-only with respect to authoritative feed facts. The query
must not change component flows, composition, pressure, temperature, active
requests, or boiling-point order. The simplest implementation is to calculate
the phase on demand without caching it in mutable feed state. If a derived
cache is introduced later, every relevant feed correction must invalidate it.

If the feed lacks any input required for phase evaluation, do not guess or run
a partial calculation. State exactly which feed input is missing. If the
thermodynamic calculation fails, return its structured deterministic error
rather than an LLM explanation.

Asking for the phase must not rerun or replace the normal-boiling-point
ordering. Conversely, calculating the order must not be treated as proof that
the phase was also evaluated.

## Debug requirements

When the program is run with `--debug`, the human-readable diagnostic trace on
`stderr` must include a distinct normal-boiling-point section containing:

- reference pressure in Pa;
- property source/method identifier when available;
- each component name and normal boiling point in K;
- the final lowest-to-highest component order;
- any ties; and
- success or structured failure status.

Suggested trace shape:

```text
normal_boiling_point_order:
  reference_pressure_Pa: 101325
  components:
    - component: <name>
      normal_boiling_point_K: <value>
      property_source: <source-or-method>
  order_low_to_high: [<component>, ...]
  ties: []
  status: complete
```

`--debug-json` must expose the same information as structured JSON. Ordinary
assistant output remains on `stdout`; diagnostics remain on `stderr`.

The debug trace must show values returned by deterministic Python, never a
Qwen-proposed ordering. Debugging must not cause an extra model call, property
calculation, or state mutation.

For an on-demand phase query, `--debug` must also show a separate
`feed_phase_evaluation` section containing:

- temperature in K actually passed to the evaluator;
- pressure in Pa actually passed to the evaluator;
- component molar flows or normalized mole fractions used;
- calculation type/specification;
- returned phase;
- vapor and liquid fractions;
- validity/status; and
- any structured error.

`--debug-json` must contain the equivalent structured result. This trace is
important because it distinguishes an actual phase calculation from a reply
constructed only from model text.

## Failure behavior

If any feed component lacks a usable normal boiling point:

- do not return a partial ordering as if it were complete;
- do not guess the missing value;
- record the affected component and reason in the debug trace; and
- return a concise structured failure through the normal deterministic reply
  path.

A failure must not corrupt the committed feed state.

## Out of scope

Do not yet implement:

- automatic light-key or heavy-key selection;
- recovery or product-composition intake;
- degrees-of-freedom confirmation;
- reflux ratio or boil-up input;
- product-flow or product-composition calculations;
- shortcut-column simulation;
- condenser or pressure screening;
- thermal-stability screening; or
- economic optimization.

On-demand feed-phase evaluation is explicitly in scope even though automatic
phase reporting is not.

The filename is retained for continuity even though condenser screening is not
part of this plan.

## Required tests

Test at least:

- three or more components are sorted from lowest to highest normal boiling
  point;
- all nonzero-flow feed components appear exactly once;
- established component spelling is preserved;
- the result is independent of Qwen output;
- equal values follow the documented stable tie rule and are flagged;
- a missing, nonfinite, or invalid property produces a structured failure;
- failure leaves committed feed state unchanged;
- the former phase-result sentence is not emitted as the terminal reply;
- an explicit phase query calls the deterministic multicomponent phase
  evaluator;
- the phase evaluator receives the committed composition, temperature, and
  pressure after unit conversion;
- the `101325 Pa` normal-boiling-point reference is not substituted for a
  different committed feed pressure;
- a phase query reports phase, vapor fraction, and liquid fraction;
- phase, vapor-fraction, and liquid-fraction query wording is accepted by the
  deterministic query boundary;
- incomplete phase inputs produce a precise missing-input response;
- a thermodynamic failure produces a structured deterministic error;
- an on-demand phase query does not mutate feed state or boiling-point order;
- boiling-point ordering does not implicitly claim that phase was evaluated;
- `--debug` shows the reference pressure, component values, final order,
  provenance, ties, and status;
- `--debug-json` contains the equivalent structured fields;
- debug output for a phase query shows the exact calculation inputs and phase
  result; and
- debug mode adds no model calls or state mutations.

## Completion criterion

This change is complete when a valid completed feed automatically triggers
deterministic normal-boiling-point ordering for every nonzero component, while
an explicit phase query independently runs the deterministic multicomponent
feed-phase evaluator using the committed feed state. The default order and the
on-demand phase calculation must each be visible and auditable under `--debug`
and `--debug-json`.
