# Multicomponent Distillation Model Context

## Purpose and Current Scope

This context file records the current scope, input contract, and conversation
behavior of `tools/chopper/multicomponent_distillation_agent.py`.

Assume every feed sent to this agent contains **three or more nonzero-flow
components**.

This agent currently performs multicomponent feed intake, deterministic
normal-boiling-point ordering, ideal-liquid adjacent relative-volatility
screening, product-purity collection, a direct light-first BioSTEAM
`ShortcutColumn` train, and on-demand feed-phase evaluation. It does
not inherit the binary workflow's routing, column-design, RAG, trial, sweep,
economic, or optimization machinery. Small shared thermodynamic helpers may
be reused when doing so does not import those unrelated behaviors.

## Feed-Phase Evaluation

For the current version, the feed thermal condition must be explicitly defined
by **temperature**. Enthalpy and feed quality are not accepted inputs. The
temperature must never be silently defaulted to the bubble point.

Feed phase is no longer evaluated or reported automatically when intake
finishes. If the user explicitly asks for the feed phase, vapor fraction, or
liquid fraction, deterministic Python runs the existing temperature/pressure
multicomponent VLE calculation using the committed feed state. The calculation
uses component molar flows, the committed feed temperature converted to K, and
the committed feed pressure converted to Pa.

The phase result is not supplied or calculated by Qwen. A successful query
reports the phase together with both molar phase fractions, for example:

```text
Phase: vapor_liquid. Vapor fraction: 0.4338. Liquid fraction: 0.5662.
```

This is a read-only computational query: it must not mutate feed facts, replace
the active request, or change the stored boiling-point order. If required feed
inputs are missing, the agent reports the next missing input instead of
guessing or running a partial phase calculation.

## Normal-Boiling-Point Ordering

Once the complete feed input contract is satisfied, deterministic Python
obtains `chemical.Tb` for every nonzero-flow feed component and orders the
components from lowest to highest normal boiling point. Normal boiling points
use the fixed reference pressure `101325 Pa` (`1 atm`) and are independent of
the committed feed pressure.

The ordering includes every feed component, preserves established component
spelling, and uses committed feed order as the stable tie rule. Exact ties are
reported in diagnostics. If any component lacks a finite positive normal
boiling point, the ordering fails structurally; the agent must not present a
partial list as complete or ask Qwen to supply a missing property.

The normal-boiling-point result establishes the volatility ordering used
internally to identify adjacent binary pairs and the keys for the fixed direct
sequence. The ordered component list is retained in structured results and
diagnostics but is not printed in the ordinary completion reply.

## Required Products and Relative Volatility

For the current version, every nonzero-flow feed component is assumed to be
required as its own individual product. Consequently, a feed with `n`
components has `n` required products and `n - 1` adjacent binary pairs. This
assumption is represented explicitly in the deterministic result so a later
version can replace it with user-selected product cuts without changing the
thermodynamic calculation boundary.

Once intake is complete, deterministic Python evaluates each component's
`chemical.Psat(T)` at the committed feed temperature. Under the ideal-liquid
assumption, the relative volatility for each internally ordered adjacent pair
is:

```text
alpha(more volatile / less volatile) = Psat(more volatile) / Psat(less volatile)
```

The saturation pressures and relative volatilities remain internal during the
automatic workflow. They are reported only for an explicit relative-volatility
query or when a value below the feasibility threshold must be identified.
Missing or invalid Psat data causes a structured calculation failure; Qwen must
not estimate or repair the property.

## Critical-Temperature Feasibility Gate

Before evaluating saturation pressures or relative volatilities, deterministic
Python obtains `chemical.Tc` for every feed component and compares it with the
committed feed temperature in K. If `T_feed > Tc` for any component, the
ordinary-distillation path is marked infeasible at that temperature and the
Psat/relative-volatility calculation is not run. The ordinary response names
every offending component and reports both its critical temperature and the
feed temperature. All component critical temperatures and the complete set of
violations remain available in structured results and diagnostics.

This gate does not disable or alter the explicit feed-phase query. Feed-phase
evaluation remains a separate read-only calculation using the committed feed
temperature, pressure, and molar flows. Likewise, when the user explicitly
asks for the boiling-point or separation order, deterministic Python returns
the component order based on normal boiling points even if the automatic
ordinary-distillation path was rejected by the critical-temperature gate.

## Essential Inputs (Table 3-1 Analog, Multicomponent)

1. **At least three component identities.**
2. **Feed quantity and composition**, given in either of these forms:
   - a flow rate for every component; or
   - the total feed flow rate and fractions for all but one component. The
     remaining fraction and all component flow rates are then calculated.
   All directly supplied component flows must use one shared unit. All
   composition fractions must use one common mole or mass basis.
3. **Units for the feed flow rate.** Units must be explicitly stated. When
   bare percentages are supplied, their basis is inferred deterministically
   from the total-flow unit: `mol/hr` or `kmol/hr` means mole basis, and
   `kg/hr` means mass basis. An explicitly stated composition basis overrides
   that inference and may differ from the total-flow basis; molecular-weight
   conversion is then required.
4. **Feed pressure.** Its units must be explicitly stated.
5. **Feed temperature.** Its units must be explicitly stated, and it must
   never be defaulted to the bubble point.
6. **Minimum product mole purities**, collected only after the critical-
   temperature and relative-volatility feasibility gates pass. The user may
   provide one mol% target for every individual component product or separate
   component-specific targets.

The agent collects these inputs over as many user turns as necessary. A
partial but valid input must remain available on later turns; the user must
not be required to repeat the entire feed description.

## Current Model Assumption

Reflux is assumed to be a saturated liquid for later column-model development.
This is not an input the current agent requests, and it has no effect on the
current feed-intake, boiling-point-ordering, or on-demand phase calculations.

The implemented column train uses a direct light-first sequence. For the
normal-boiling-point order `C1, C2, ..., Cn`, it creates `n - 1` columns with
adjacent keys `(C1, C2)`, `(C2, C3)`, ..., `(C[n-1], Cn)`. Every product except
the least volatile is a distillate; the least volatile component is the final
bottoms product.

Every column is currently a BioSTEAM `ShortcutColumn` with `k=2`,
`partial_condenser=False`, `P=101325 Pa`, zero assumed inter-column pressure
drop, and composition specifications. These are fixed implementation
assumptions, not user inputs.

The user supplies total-stream minimum mole purities, not `y_top` or `x_bot`.
Deterministic Python optimizes every column's `y_top` and `x_bot`, checks the
actual component mole fraction in every final product stream, and reports the
chosen values so the design can be reproduced independently in BioSTEAM. The
current placeholder objective minimizes composition-specification severity
subject to all purity constraints; it is not yet a recovery or economic
optimization.

## Initially Supported Units

- Component or total flow: `kmol/hr`, `mol/hr`, or `kg/hr`.
- Pressure: `Pa`, `kPa`, `bar`, or `atm`.
- Temperature: `K` or `degC`.

If a value that requires units is provided without them, the agent must ask
for the units and list the supported choices. It must never infer units.

The agent may infer only a bare composition's basis from an explicitly given
total-flow unit according to the rule above. It must not infer pressure,
temperature, component flows, or their units.

## Component Identity and Partial Flow Collection

Component identities and component quantities are separate concepts.
Mentioning one component while supplying its flow must not replace the full
component list.

Component matching is case-insensitive across turns. The first established
spelling remains the stored/display spelling, so `ethanol` and `Ethanol`
refer to one component rather than two. This rule applies to component lists,
flows, compositions, additions, removals, and replacements.

For example:

```text
User: separate methanol, ethanol, water
User: water = 50 kmol/hr, Ethanol = 20 kmol/hr
User: methanol = 50 kmol/hr
```

The resulting feed has exactly three components and these flows:

- methanol: `50 kmol/hr`;
- ethanol: `20 kmol/hr`; and
- water: `50 kmol/hr`.

The total flow is then derived as `120 kmol/hr`, and the next requested input
is pressure.

## Conversation and State Architecture

Each conversation owns an independent session containing the committed feed
state, the active pending request, and the turn number. Feed information must
not leak between sessions.

For each user turn:

1. Qwen makes one schema-constrained interpretation proposal. One bounded
   retry is allowed only if its output is malformed.
2. Deterministic Python checks the current message and active request before
   accepting any proposed fact.
3. Accepted facts are evaluated as a candidate state transition.
4. Valid logical groups are committed; a rejected group must not corrupt the
   previously committed state.
5. Python deterministically returns the next question, validation message,
   read-only state answer, on-demand phase/volatility/order result, feasibility
   warning, or completed ShortcutColumn train. The model is not called again to
   write the response.

The logical state groups are component identity, feed quantity/composition,
pressure, temperature, and product-purity requirements.

Each stored measurement has one authoritative record containing its value,
unit where applicable, completion status, provenance, source turn, and
grounding evidence. Derived totals, compositions, and bases are marked as
derived and must be recomputed after corrections.

## Active-Request and Short-Answer Behavior

The active pending request supplies the meaning of an otherwise unlabelled,
unambiguous response. Deterministic parsing has priority over a conflicting
Qwen proposal for supported direct answers.

Required behavior:

```text
Assistant: What is the feed pressure?
User: 3
Assistant: What are the units of the feed pressure? (Pa, kPa, bar, atm)
```

The literal `3` must be stored as the pressure magnitude even if Qwen proposes
another number, another target field, or classifies the turn as unclear. It
must not also become a composition fraction, flow, or temperature.

The same principle applies to:

- an unambiguous pending temperature or total-flow value;
- a supported unit-only response;
- a mole/mass composition-basis response; and
- explicitly named component flows stated with one supported common flow
  unit.

For explicitly named component-flow replies, deterministic parsing accepts
only the components paired with numbers in the current message. It must not
reapply other flows merely because Qwen copied them from established state.
More complicated natural-language descriptions may still use the model's
proposal, but every accepted fact remains subject to grounding.

When there is no active request, a singular model-proposed `target_field` is
not allowed to truncate a multi-fact message. For example, if Qwen labels a
complete initial feed statement with `target_field="component_names"` while
also proposing grounded flows, pressure, and temperature, all proposed facts
are sent to deterministic grounding. Unsupported or derived proposals are
still rejected there.

When an active request does exist, its field scope and deterministic direct-
answer rules remain authoritative so that a short answer cannot populate
unrelated fields.

## Read-Only and Computational Questions

The user may ask about accumulated feed information during intake. For
example:

```text
User: What is the feed pressure?
Assistant: The feed pressure is 101325 Pa.
```

Stored-value answers must be formatted from a read-only snapshot of committed
state, not from model memory. Such a state query must not run the VLE
calculation, discard incomplete information, or replace the current pending
request.

If the requested value is absent or incomplete, report that plainly. For
example, a stored pressure magnitude without a unit should be reported as a
value whose units have not yet been specified.

The query targets `phase`, `vapor_fraction`, and `liquid_fraction` are the
explicit exception to the no-calculation rule: after deterministic query-target
verification, they run the read-only phase calculation described above. They
are computed query targets, not stored user-input fields.

## Grounding Boundary

Qwen's output is a proposal, never authoritative feed data. Numbers, units,
component names, composition bases, identity operations, query targets, and
reset intent must be accepted only when supported by the current user message
or by an unambiguous answer to the active request.

Numeric presence alone is not sufficient when it would associate a value with
the wrong physical field. In particular, numbers presented as component flow
rates must not ground a model-proposed composition unless the message explicitly
uses composition/fraction wording or composition is the active request. This
prevents copied flow values from invalidating an otherwise valid quantity
group.

The model must never calculate or propose derived totals, missing fractions,
mass/mole conversions, or phase results. Those operations belong to
deterministic Python and BioSTEAM.

## Debugging

Debugging is optional and disabled by default:

```powershell
python tools/chopper/multicomponent_distillation_agent.py --debug
python tools/chopper/multicomponent_distillation_agent.py --debug-json
```

Diagnostics go to `stderr`; ordinary assistant output remains on `stdout`.
The trace records the user message, active request, model proposal, binding
decision, grounding acceptance/rejection, state transition, function result,
state difference, exit path, and reply. Debugging must not add model calls,
BioSTEAM calculations, or state mutations.

For a completed feed, the trace includes a dedicated
`normal_boiling_point_order` section with the `101325 Pa` reference pressure,
each component's `chemical.Tb` value and property source, the final order,
ties, and status. It also includes `product_specification` and
`critical_temperature_check` sections with the individual-product assumption,
product count, every component Tc, and any violations. When the critical-
temperature gate passes, a `relative_volatility` section also records the feed
temperature, component Psat values, adjacent pairs, and ratios.

For an explicit phase query, the trace includes a separate
`feed_phase_evaluation` section with the actual temperature in K, pressure in
Pa, component molar flows used, calculation type, phase, vapor and liquid
fractions, status, and any structured error. This section demonstrates that
the VLE calculation actually ran; boiling-point ordering alone is not evidence
of phase evaluation.

The trace includes full user/model content and may therefore contain
sensitive process information.

## Output Boundary

Once the feed facts are complete, the automatic workflow runs its feasibility
gates without printing passing Psat, relative-volatility, or normal-boiling-
point data. A feasible feed advances to product-purity collection and then to
the direct ShortcutColumn design.

The critical-temperature feasibility gate takes precedence over column
modeling. If the feed temperature exceeds any component critical
temperature, the reply instead reports that ordinary distillation is infeasible
at the stated temperature, lists each offending component with `T_feed` and
`Tc`, and explains that the required vapor-liquid equilibrium does not exist at
those temperature conditions. Psat and relative-volatility values are
suppressed because they are not evaluated after the gate fails.

When the critical-temperature gate passes, adjacent relative volatilities are
calculated but suppressed from the automatic reply. If any adjacent value is
below `1.05`, ordinary distillation is rejected before purity collection and
the offending pairs and values are reported. If all pairs pass, the agent asks
for minimum product mole purities. Once every product target is known, it
builds and optimizes the direct ShortcutColumn train and reports each column's
keys, `y_top`, `x_bot`, and every achieved product purity. An explicit relative-
volatility query still reports all adjacent values without mutating state or
discarding the pending purity request.

This default boundary does not prevent concise missing-input questions,
validation messages, stored-state answers, or an explicit on-demand phase
calculation. Boiling-point ordering and feed-phase evaluation are independent:
the former uses component identities and normal `Tb` values at `101325 Pa`;
the latter uses the committed mixture flows, feed temperature, and feed
pressure.

## Known Follow-Up Work

The following robustness work remains separate from the implemented
case-insensitive identity, direct pending-answer, initial multi-fact binding,
flow-versus-composition grounding, boiling-point-ordering, and on-demand phase
query fixes:

- distinguish a pending component-flow unit from a pending total-flow unit in
  the total-flow-plus-composition input route;
- extend exact number-to-field/component association beyond the implemented
  protection that prevents flow-only wording from grounding composition;
- verify reset, add, remove, and replace operations before allowing them to
  change or clear state;
- prevent a newly mentioned flow/composition entry from silently adding an
  unknown component without an explicit identity decision;
- normalize all accepted unit aliases to their canonical stored forms;
- complete confirmation/denial handling where genuine ambiguity requires it;
  and
- make debug `candidate_state` show the attempted candidate separately from
  the final committed state.
