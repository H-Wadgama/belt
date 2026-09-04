# Multicomponent Feed-Phase Agent Correction Plan

## Goal

Correct the current multicomponent agent so that it collects only grounded
feed facts, asks for every genuinely missing value or unit, calculates one
BioSTEAM `T/P` feed flash, and reports only:

- phase: `liquid`, `vapor`, or `vapor-liquid`;
- molar vapor fraction; and
- molar liquid fraction.

The implementation must work for any feed with at least three nonzero-flow
components. No logic may be hardcoded for exactly three components.

## Scope Boundaries

Do not add key selection, separation routing, column design, product
specifications, reflux calculations, partial-condensation screening, sweeps,
economics, or optimization. Saturated-liquid reflux remains only a documented
assumption and is not a requested input or part of this calculation.

For this version, remove enthalpy and feed quality from the multicomponent
state, tool schema, prompt, pending requests, calculation wrapper, and tests.
Temperature is the only accepted thermal input. The shared binary VLE core may
retain its existing `H/P` and `V/P` branches because the binary workflow still
uses them.

## Accepted Feed Descriptions

### Mode A: direct component flows

Require one positive flow for every named component and one shared unit:
`kmol/hr`, `mol/hr`, or `kg/hr`.

All component flows in one feed must use the same unit. If the user supplies
mixed component-flow units, do not convert or select one silently. Ask the user
to restate all component flows using one supported common unit.

### Mode B: total flow and composition

Require:

- total feed flow and its unit;
- fractions for N-1 of N named components, or all N fractions; and
- no conflicting composition bases.

Derive the last fraction as `1 - sum(given fractions)` when exactly N-1 are
given. If all N are supplied, validate that they sum to one within a documented
tolerance. Every resulting component must have positive flow because the agent
assumes all named components are nonzero.

All fractions must use one common composition basis. Inputs such as
`20 wt% Water, 40 mol% Ethanol, ...` are invalid. Ask the user to provide all
fractions on either a mass basis or a mole basis.

## Composition-Basis Rules

Apply these rules deterministically in this order:

1. If the user explicitly says `wt%`, `mass fraction`, `mol%`, or `mole
   fraction`, use that explicit basis.
2. If the fractions are bare percentages or decimals, defer their basis until
   the total-flow unit is known.
3. Infer a bare composition as mole basis when total flow is in `mol/hr` or
   `kmol/hr`.
4. Infer a bare composition as mass basis when total flow is in `kg/hr`.
5. If total-flow units are still missing, retain the fractions without a basis
   and ask for the total-flow units. Do not separately ask for composition
   basis unless the composition statements themselves conflict or remain
   ambiguous after the units are known.

Store basis provenance as `user_explicit` or
`inferred_from_total_flow_units`. An explicit basis always overrides the
unit-based inference, even when composition and total flow use different
bases.

Examples:

- Bare percentages with `100 kmol/hr` mean mole percentages.
- Bare percentages with `100 kg/hr` mean mass percentages.
- Explicit weight percentages with `100 kmol/hr` remain weight percentages;
  they must be converted using molecular weights.
- Explicit mole percentages with `100 kg/hr` remain mole percentages and must
  likewise be converted consistently.

## Canonical Molar-Flow Conversion

Keep user-entered quantities separate from calculated canonical values. Build
one canonical mapping named clearly, such as
`component_molar_flows_kmol_per_hr`, and always construct the BioSTEAM stream
from that mapping with `units='kmol/hr'`.

Use component molecular weights from the BioSTEAM chemical registry:

1. Convert mass fractions to mole fractions with
   `x_i = (w_i / MW_i) / sum(w_j / MW_j)`.
2. If total flow is molar, convert it to kmol/hr and multiply by each mole
   fraction.
3. If total flow is mass, calculate mixture molecular weight from the mole
   fractions, convert the total mass flow to total kmol/hr, and multiply by
   each mole fraction.
4. For direct component flows, convert `mol/hr` to `kmol/hr`, convert `kg/hr`
   component-by-component using molecular weight, and leave `kmol/hr`
   unchanged.

Do not compare redundant flow information until all values have been converted
to canonical kmol/hr. This fixes both false conflicts and false agreement
between numerically similar values expressed in different bases or units.

Required regression example:

```text
20 wt% Water, 20 wt% Methanol, 60 wt% Ethanol; total flow = 100 kmol/hr
```

Expected component molar flows, using BioSTEAM molecular weights and an
appropriate numerical tolerance:

- Water: approximately `36.56 kmol/hr`;
- Methanol: approximately `20.55 kmol/hr`;
- Ethanol: approximately `42.89 kmol/hr`.

## Hard Grounding Boundary

The current tool trusts whatever arguments Qwen generates. A prompt alone
cannot prevent invented pressure or flow values. Add a deterministic boundary
between the model's proposed update and the persistent state.

The controller, not the model, must supply the exact current user message to a
field-by-field grounding validator. Do not expose this trusted source text as a
model-controlled tool argument.

For every proposed field, the validator must verify:

- each component name is grounded in the current user message;
- each numeric value is grounded in the message, allowing only explicit,
  deterministic transformations such as `20% -> 0.20`;
- each proposed unit is grounded by a supported alias in the message;
- the value is used for the correct physical field, so a temperature cannot
  serve as pressure or flow evidence;
- composition bases are grounded by explicit wording or are inferred later by
  the deterministic total-flow-unit rule; and
- component flows are not synthesized from compositions by the model.

Discard ungrounded proposed fields before the state update while retaining and
applying any independently grounded fields from the same message. Record the
rejected fields in internal diagnostics. Thus the example message
`separate Ethanol, Methanol, and Water at 335 K` stores only the three
components and `335 K`; invented `101325 Pa` and invented component flows can
never enter the authoritative state.

## One State Update Per User Turn

Remove the open-ended model/tool loop for this agent.

For each user turn:

1. Let the model propose at most one structured feed update.
2. Ground that proposal against the current user message.
3. Apply the grounded fields atomically once.
4. Reassess the accumulated state deterministically.
5. Return either the next pending question, a validation correction, or the
   final phase result directly from Python.
6. Do not call the model again after the tool result on the same user turn.

Pending questions and final phase output should use deterministic formatters,
not another generation step. This prevents Qwen from seeing a missing-input
response and immediately making a second, fabricated tool call before the user
has answered.

If Qwen fails to produce a usable structured update despite explicit facts, a
single bounded extraction retry is acceptable before asking the user to
restate the information. The retry must not mutate state.

## State and Validation Changes

Update `multicomponent_feed_state.py` so that it:

- stores raw explicit feed facts separately from canonical derived flows;
- supports composition-basis provenance and deferred inference;
- removes enthalpy and quality fields;
- keeps only temperature and temperature units;
- clears and recomputes all derived values after corrections;
- detects mixed component-flow units and mixed composition bases;
- validates finite numeric values, positive flows, positive pressure,
  temperature above absolute zero, valid fractions, and at least three
  positive-flow components; and
- returns exactly one ordered missing-input request.

The missing-input order should be:

1. component identities;
2. feed quantities/composition;
3. shared flow or total-flow units;
4. composition-basis conflict, if one exists;
5. pressure value;
6. pressure units;
7. feed temperature;
8. temperature units.

When bare composition has no basis and total-flow units are missing, the next
question is for total-flow units, including the supported choices. Once those
units arrive, infer the basis and continue without a redundant basis question.

## Module-Level Changes

- `multicomponent_units.py`: retain flow, pressure, and temperature units;
  remove multicomponent enthalpy support; add helpers that distinguish molar
  from mass flow units.
- `multicomponent_feed_state.py`: implement the raw/canonical separation,
  deferred basis inference, common-basis/unit validation, and physical-value
  checks described above.
- `multicomponent_biosteam_feed.py`: perform molecular-weight-aware conversion
  to canonical component kmol/hr and build the stream only from those values.
- `multicomponent_feed_phase.py`: expose only the multicomponent `T/P` path;
  leave the shared binary VLE behavior unchanged.
- `multicomponent_feed_tool.py`: remove enthalpy and quality arguments, accept
  one partial temperature-only update, and return deterministic pending/error/
  result data.
- `multicomponent_distillation_agent.py`: enforce grounding, one state update
  per user turn, and terminal deterministic formatting.

Do not copy the binary agent's case-routing, RAG, or design machinery. Reuse a
small existing helper only when it directly supports grounding or pending
request handling without importing unrelated binary workflow behavior.

## Required Tests

### Composition and unit conversion

1. Bare percentages plus `kmol/hr` infer mole basis.
2. Bare percentages plus `mol/hr` infer mole basis.
3. Bare percentages plus `kg/hr` infer mass basis.
4. Bare percentages are retained when total-flow units are absent; the tool
   asks for those units and infers the basis after the answer.
5. Explicit weight percentages plus molar total flow reproduce the
   `36.56/20.55/42.89 kmol/hr` regression example.
6. Explicit mole percentages plus mass total flow convert correctly.
7. Direct `kg/hr`, `mol/hr`, and `kmol/hr` component feeds produce equivalent
   canonical molar flows when physically equivalent.
8. Mixed component-flow units are rejected with a common-unit request.
9. Mixed mole/mass composition bases are rejected with a common-basis request.
10. N-1 fraction derivation works for three and five components.
11. Redundant total and component flows are compared only after canonical
    conversion.

### Missing facts and physical validation

12. Missing pressure value is requested and never defaulted.
13. A pressure value without units triggers a question listing
    `Pa`, `kPa`, `bar`, and `atm`.
14. Missing temperature is requested and never replaced by bubble point,
    enthalpy, or quality.
15. Temperature without units triggers a question listing `K` and `degC`.
16. Enthalpy and quality are absent from the tool schema and cannot make the
    multicomponent state ready.
17. Nonpositive pressure, temperatures below absolute zero, non-finite values,
    invalid fractions, zero/negative component flows, and unknown chemicals
    fail without a phase calculation.
18. Later corrections remove stale inferred basis and canonical flow values.

### Architectural regression tests

19. For `separate Ethanol, Methanol, and Water at 335 K`, only the component
    identities and temperature enter state; pressure and flows remain missing.
20. A fabricated `101325 Pa` tool proposal is rejected when those facts are
    absent from the user message.
21. Fabricated component flows are rejected when no flows appear in the user
    message.
22. A pending request ends the current turn without another model call.
23. Only one state-changing update can execute per user turn.
24. The next user reply supplies only its newly stated fact and correctly
    updates the accumulated state.
25. Final user-facing output contains only phase and molar vapor/liquid
    fractions.
26. Existing binary feed-phase tests remain unchanged and pass.

Use mocked model responses for the architectural tests. Keep a live Ollama run
as a manual smoke test rather than a CI dependency.

## Execution Order

1. Update the context, schemas, and temperature-only input contract.
2. Implement basis inference and canonical molecular-weight conversion.
3. Add the field-level grounding validator.
4. Replace the open-ended tool loop with one-update-per-turn control and
   deterministic terminal formatting.
5. Update focused tests and run the full `tools/chopper` regression suite.
6. Manually repeat the reported `335 K` conversation and the explicit-weight-
   percent/molar-total-flow example through the live agent.

The correction is complete only when no value absent from the current user
message can enter authoritative state, every missing value or unit produces a
specific question, mixed bases are rejected, cross-basis feeds are converted
to component kmol/hr correctly, and the agent stops immediately after
reporting phase and molar phase fractions.
