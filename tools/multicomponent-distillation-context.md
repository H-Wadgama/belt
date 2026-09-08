# Multicomponent Distillation Model Context

## Purpose and Current Scope

This context file records the current scope, input contract, and conversation
behavior of `tools/chopper/multicomponent_distillation_agent.py`.

Assume every feed sent to this agent contains **three or more nonzero-flow
components**.

This agent is currently only a multicomponent feed-intake and feed-phase
calculator. It does not inherit the binary workflow's routing, column-design,
RAG, trial, sweep, economic, or optimization machinery. Small shared
thermodynamic helpers may be reused when doing so does not import those
unrelated behaviors.

## Feed-Phase Evaluation

For the current version, the feed thermal condition must be explicitly defined
by **temperature**. Enthalpy and feed quality are not accepted inputs. The
temperature must never be silently defaulted to the bubble point.

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

The agent collects these inputs over as many user turns as necessary. A
partial but valid input must remain available on later turns; the user must
not be required to repeat the entire feed description.

## Current Model Assumption

Reflux is assumed to be a saturated liquid. This is a current model
limitation, not an input the agent should request from the user, and it does
not add any calculation beyond feed-phase evaluation.

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
   read-only state answer, or completed phase result. The model is not called
   again to write the response.

The logical state groups are component identity, feed quantity/composition,
pressure, and temperature.

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

## Read-Only Questions

The user may ask about accumulated feed information during intake. For
example:

```text
User: What is the feed pressure?
Assistant: The feed pressure is 101325 Pa.
```

Answers must be formatted from a read-only snapshot of committed state, not
from model memory. A state query must not mutate the feed, run the VLE
calculation, discard incomplete information, or replace the current pending
request.

If the requested value is absent or incomplete, report that plainly. For
example, a stored pressure magnitude without a unit should be reported as a
value whose units have not yet been specified.

## Grounding Boundary

Qwen's output is a proposal, never authoritative feed data. Numbers, units,
component names, composition bases, identity operations, query targets, and
reset intent must be accepted only when supported by the current user message
or by an unambiguous answer to the active request.

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

The trace includes full user/model content and may therefore contain
sensitive process information.

## Output Boundary

Once the feed is complete, the agent reports only the equilibrium phase and
the molar vapor and liquid fractions. It does not route the feed, select a
separation, or perform a distillation design.

The phase-result restriction does not prevent concise missing-input questions,
validation messages, or explicit read-only answers about accumulated feed
inputs during the conversation.

## Known Follow-Up Work

The following robustness work remains separate from the already implemented
case-insensitive identity and direct pending-answer fixes:

- distinguish a pending component-flow unit from a pending total-flow unit in
  the total-flow-plus-composition input route;
- associate every number with its exact physical field and component in
  general multi-fact messages, not merely with any matching numeric token;
- verify reset, add, remove, and replace operations before allowing them to
  change or clear state;
- prevent a newly mentioned flow/composition entry from silently adding an
  unknown component without an explicit identity decision;
- normalize all accepted unit aliases to their canonical stored forms;
- complete confirmation/denial handling where genuine ambiguity requires it;
  and
- make debug `candidate_state` show the attempted candidate separately from
  the final committed state.
