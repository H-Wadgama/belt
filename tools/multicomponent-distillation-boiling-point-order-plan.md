# Multicomponent Normal-Boiling-Point Ordering Plan

## Purpose

Before asking for light- and heavy-key specifications, extend
`tools/chopper/multicomponent_distillation_agent.py` so that deterministic
Python orders every committed feed component by normal boiling point.

This replaces the previous post-feed specification-intake plan for now. The
scope ends after calculating, storing, and debugging the ordered component
list.

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

## Output change

The agent must no longer explicitly return the existing terminal phase reply:

```text
Phase: vapor_liquid. Vapor fraction: 0.4338. Liquid fraction: 0.5662.
```

Feed temperature and pressure remain committed feed data, but phase and phase
fractions are no longer the user-facing output boundary. This plan does not
require deleting an internal phase calculation if another established path
still needs it; it requires removing the explicit phase-result response and
continuing to normal-boiling-point ordering.

This round does not automatically designate a light key or heavy key. The
ordered list is the prerequisite for a later key-selection step. In a
multicomponent feed, "lighter" means lower in this ordered list and "heavier"
means higher; it does not make any particular pair the separation keys.

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
- `--debug` shows the reference pressure, component values, final order,
  provenance, ties, and status;
- `--debug-json` contains the equivalent structured fields; and
- debug mode adds no model calls or state mutations.

## Completion criterion

This change is complete when a valid completed feed triggers deterministic
normal-boiling-point lookup and lowest-to-highest ordering for every nonzero
component, the former explicit phase-result reply is no longer the stopping
point, and the full ordered result is visible under `--debug` and
`--debug-json`.

