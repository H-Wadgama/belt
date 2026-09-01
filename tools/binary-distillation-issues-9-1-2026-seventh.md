# Implementation Plan: Strengthen Deterministic Workflow Routing and Make the Separation Architecture Scalable

## Objective

Implement the four currently observed fixes in the binary-distillation assistant, but do so by strengthening the general architecture rather than adding prompt-specific patches.

The system should continue following this architectural principle:

> The LLM interprets user language and proposes semantic intent. Deterministic Python owns engineering state, workflow truth, allowed actions, required inputs, calculation readiness, and execution.

The implementation must remain compatible with the current binary-distillation workflow while making the underlying abstractions reusable for future additions such as:

- multicomponent distillation,
- flash calculations,
- absorption/stripping,
- extraction,
- adsorption,
- membranes,
- crystallization,
- additional distillation design methods,
- additional workflow stages and engineering screening calculations.

Do not redesign the application around those future workflows now. Instead, ensure that the abstractions changed in this task do not hard-code assumptions that only make sense for the current four Wankat binary-distillation cases.

---

# 1. Architectural invariants that must remain true

Before modifying code, preserve the following invariants.

### State ownership

Canonical engineering values belong in the deterministic problem-state layer.

Examples:

```text
component_names
component_flows
component_flow_units
feed_temperature_K
pressure_Pa
reflux_condition
xD
xB
boilup_ratio_VB
...
```

Do not place workflow metadata, questions, derived readiness flags, or model interpretations into the mutable engineering-state schema unless they are genuinely part of the engineering problem specification.

For example:

```text
missing_case_inputs
design_option_requirements
feed_screening_ready
```

must not become fake mutable engineering fields.

They should be derived deterministically from canonical state plus workflow definitions.

---

### LLM ownership

The model may:

- identify user intent,
- extract candidate engineering updates,
- classify questions,
- select a semantic action,
- identify the semantic subject of a workflow-information question.

The model must not decide:

- whether an engineering stage is actually ready,
- which fields are authoritative requirements,
- whether a calculation may execute,
- which Python implementation function should run,
- what the official requirements of a design case are,
- whether a value should silently be assumed.

---

### Deterministic execution

All accepted state changes must continue going through the canonical WRITE path.

Preserve:

- zero WRITEs when validation fails,
- one canonical atomic WRITE for an accepted update turn,
- existing transaction validation,
- existing keyed-collection normalization,
- existing deterministic pending-request handling,
- existing semantic retry behavior unless explicitly modified below.

Do not create side channels that mutate state outside the transaction layer.

---

# 2. Establish explicit domain boundaries before implementing the fixes

The current failures reveal that several concepts are too easy to confuse:

```text
engineering state
workflow state
workflow metadata
pending interaction
semantic action
implementation function
```

Make these distinctions explicit in code.

Do not perform a large refactor.

Instead, introduce small reusable interfaces where necessary so future workflows can plug into the same architecture.

The intended conceptual structure should be approximately:

```text
User language
      |
      v
Semantic interpretation
      |
      +------------------------------+
      |                              |
      v                              v
engineering update             query / command
      |                              |
      v                              v
transaction validation       deterministic router
      |                         /            \
      v                        v              v
canonical state WRITE   state query      workflow info
                            |
                            v
                     semantic action
                            |
                            v
                     action registry
                            |
                            v
                  engineering implementation
```

Pending requests operate before generic command/action routing.

---

# 3. Fix pending-request precedence generically

## Problem

A current turn can have an unresolved deterministic `pending_request`, but a short reply such as:

```text
Yes
```

can bypass it and trigger a generic proceed action.

That is architecturally incorrect.

The pending request describes the current unresolved interaction contract. Generic affirmative/proceed interpretation must not override it.

## Required behavior

Implement a general routing precedence rule:

```text
1. Load authoritative current state/workflow assessment.

2. Check whether there is an active pending_request.

3. If there is a pending_request:
      attempt deterministic pending-reply resolution.

      if resolved:
          compile the resulting canonical update/action.

      if unresolved:
          do NOT allow generic yes/proceed routing to execute
          an unrelated action.

          Instead:
              allow semantic interpretation specifically in the
              context of the pending request,
              or deterministically repeat/clarify the request.

4. Only when no unresolved pending_request exists may generic
   proceed/yes/action routing occur.
```

The important abstraction is:

> An active interaction contract has priority over generic commands.

This should not be implemented as:

```python
if reflux_condition_missing and message == "yes":
    ...
```

It must work for any future pending request.

Examples could later include:

```text
choose separation method
confirm thermodynamic model
specify column pressure
choose recovery basis
select solvent
confirm target product
```

The router should not need new special-case logic for each one.

---

# 4. Do not treat "yes" as an engineering value

For the current reflux-condition request:

```text
pending_request:
    field = reflux_condition
    request_type = string_choice
    allowed_values = ["saturated_liquid"]
```

a reply of:

```text
Yes
```

must NOT become:

```python
reflux_condition = "saturated_liquid"
```

The user has only affirmed something; they have not explicitly supplied the engineering condition.

Preserve the current principle that engineering values should not be silently inferred from an affirmative response when the pending request requires a value.

Expected result:

```text
User: Yes

Assistant:
Please state the reflux condition explicitly.
Currently supported: saturated_liquid.
```

But:

```text
User: reflux is saturated liquid
```

should resolve deterministically to:

```python
{"reflux_condition": "saturated_liquid"}
```

and proceed through the normal canonical WRITE path.

---

# 5. Add tests for generic pending-request precedence

Add unit/integration tests proving that the routing principle is general.

At minimum test:

### Case 1

Active `string_choice` pending request + `"yes"`.

Expected:

```text
no calculation
no unrelated action
no WRITE inventing the value
pending request remains unresolved
```

### Case 2

Active `string_choice` + explicit allowed choice.

Expected:

```text
one canonical WRITE
pending request resolves
```

### Case 3

No pending request + user says `"yes"` after an explicitly offered calculation.

Expected:

```text
generic proceed/action routing may execute
```

### Case 4

Existing numeric/boolean pending-request types.

Verify their current deterministic resolution behavior is unchanged.

### Case 5

Malformed/unrecognized reply to a pending request.

Expected:

```text
no unrelated generic action
no state mutation
```

---

# 6. Separate semantic action names from implementation function names

## Problem

The model generated:

```text
calculate_current_binary_distillation_problem
```

which is an implementation-level function name.

The intended model-facing semantic action is something like:

```text
calculate_current_step
```

The validator correctly rejected the internal function name, but the model should never have been taught that vocabulary.

## Architectural rule

Introduce or reinforce a strict boundary:

```text
semantic action name
        ↓
ACTION_REGISTRY
        ↓
Python implementation
```

For example:

```python
ACTION_REGISTRY = {
    "calculate_current_step": calculate_current_binary_distillation_problem,
    "reset_current_problem": reset_binary_distillation_problem,
}
```

The left-hand side is part of the semantic interface.

The right-hand side is internal implementation.

The model must only see the left-hand side.

---

# 7. Make the semantic action registry the authoritative source

Find every place where model-facing action names are currently declared or described:

- TurnIntent JSON/schema,
- system prompt,
- action catalog,
- examples,
- validator,
- documentation strings,
- action-routing prompt.

Remove duplicated independently maintained lists where practical.

Derive the allowed model-facing action vocabulary from the semantic registry or from a small central action-definition structure.

For example, a scalable definition could conceptually resemble:

```python
ActionDefinition(
    name="calculate_current_step",
    description="Run the currently available deterministic engineering calculation.",
    handler=calculate_current_binary_distillation_problem,
)
```

Do not necessarily introduce this exact class if it would cause unnecessary refactoring.

The important properties are:

```text
one authoritative semantic name
one deterministic handler binding
model sees semantic name only
```

---

# 8. Do not make the registry binary-distillation-specific

The registry mechanism should allow future entries such as:

```text
calculate_current_step
evaluate_feasibility
reset_current_problem
advance_workflow
generate_design
```

without requiring the model to learn implementation names such as:

```text
calculate_flash_vessel_vle
run_absorber_shortcut
calculate_multicomponent_column
```

Likewise, internal implementation functions may change without changing the model-facing contract.

This is important for long-term scalability.

---

# 9. Validate action names deterministically

The TurnIntent action schema should constrain the action name to recognized semantic names.

If technically practical, generate the enum from the same semantic action source.

Conceptually:

```json
{
  "type": "object",
  "properties": {
    "name": {
      "enum": [
        "calculate_current_step",
        "reset_current_problem"
      ]
    }
  }
}
```

Do not add:

```text
calculate_current_binary_distillation_problem
```

as an alias merely to make the observed failing conversation pass.

Its rejection is desirable.

The architectural fix is preventing implementation names from leaking into the semantic vocabulary.

---

# 10. Add action-registry tests

Verify:

```text
internal Python implementation name
    -> rejected as unknown semantic action

calculate_current_step
    -> accepted

calculate_current_step
    -> dispatched to the registered handler

model-facing catalog
    -> contains calculate_current_step

model-facing catalog/schema/prompt
    -> does not contain calculate_current_binary_distillation_problem
```

Also add a test making it easy to detect future registry/schema drift.

For example:

```text
semantic actions exposed by TurnIntent
==
semantic actions defined by the authoritative registry
```

where feasible.

---

# 11. Introduce a first-class distinction between state queries and workflow-information queries

## Problem

The user asked:

```text
What are the inputs required for the four cases?
```

The semantic layer translated this into something equivalent to:

```text
state field = missing_case_inputs
```

The state-query system then correctly rejected the field because it is not part of the engineering problem state.

The real error is the semantic category.

This is a workflow-metadata question, not an engineering-state query.

---

# 12. Create an extensible query taxonomy

Introduce a small explicit query distinction.

For example:

```json
{
  "query_type": "problem_field",
  "field": "pressure_Pa"
}
```

versus:

```json
{
  "query_type": "workflow_info",
  "name": "design_option_requirements"
}
```

Exact schema naming may differ.

Do not over-engineer the taxonomy.

A small scalable initial set is sufficient, for example:

```text
problem_field
workflow_info
```

Future query classes might eventually include:

```text
calculation_result
engineering_explanation
supported_capability
```

but do not implement speculative categories unless needed.

---

# 13. Keep the current state-query resolver focused on real state

Examples that should remain state queries:

```text
What pressure did I give you?
What is the feed temperature?
What is xD currently?
What are the component flow rates?
```

These should continue reading authoritative stored state.

Do not weaken the state-field validation merely to answer workflow questions.

Unknown fake fields should continue being rejected.

---

# 14. Add a deterministic workflow-information registry

Implement a small registry or equivalent dispatch mechanism for deterministic workflow metadata.

Conceptually:

```python
WORKFLOW_INFO_REGISTRY = {
    "design_option_requirements": resolve_design_option_requirements,
}
```

This is preferable to scattering clauses such as:

```python
if "four cases" in user_message:
```

through the agent.

The registry gives future workflows a stable place for authoritative metadata queries.

Possible future workflow-info entries might include:

```text
required_feed_inputs
supported_design_options
design_option_requirements
current_stage_requirements
supported_thermodynamic_models
supported_separation_methods
```

Do not implement those now unless already required.

Just ensure the mechanism can accommodate them.

---

# 15. Source workflow information from deterministic definitions

For:

```text
design_option_requirements
```

do not let Qwen compose the engineering requirements from memory.

Use the existing deterministic workflow definitions.

Current design assessment already contains information such as:

```text
missing_inputs_by_candidate
```

for cases A-D.

Reuse the authoritative underlying definitions that produce this structure.

Avoid making the answer depend solely on whatever happens to be missing from the current user state if the user asks for the complete theoretical requirement set.

If necessary, extract reusable design-option definitions from the existing assessment code so both:

```text
workflow assessment
```

and:

```text
workflow-information response
```

read from the same source.

For example, conceptually:

```python
DESIGN_OPTION_DEFINITIONS = {
    "A": ...,
    "B": ...,
    "C": ...,
    "D": ...,
}
```

Only introduce this if it reduces duplicated engineering truth.

Do not perform a broad workflow rewrite.

---

# 16. Preserve the current Wankat design requirements

The deterministic workflow-information response should represent the existing project definitions for cases A-D.

Case A requires:

```text
xD
xB
external reflux specification
optimum feed location confirmation
```

Case B requires:

```text
light-component fractional recovery
heavy-component fractional recovery
external reflux specification
optimum feed location confirmation
```

Case C requires:

```text
one specified product composition: xD or xB
one specified product flow: distillate or bottoms
external reflux specification
optimum feed location confirmation
```

Case D requires:

```text
xD
xB
boilup ratio V/B
optimum feed location confirmation
```

The external reflux specification may continue following the existing supported representation, such as external reflux ratio or the currently supported multiplier alternative.

Do not change the engineering definitions as part of this task.

---

# 17. Keep workflow metadata separate from separation knowledge/RAG

Do not route these questions to generic RAG.

Questions such as:

```text
What inputs does Case A require?
Which variables are still missing for Case D?
What design options are currently supported?
```

are statements about the software's deterministic workflow schema.

They should come from Python definitions.

RAG remains useful for engineering knowledge such as:

```text
Why might corrosive components be removed early?
What heuristic applies to heat-sensitive compounds?
What does Wankat recommend in a particular separation context?
```

Maintain this distinction:

```text
software/workflow truth -> deterministic Python
engineering/reference knowledge -> RAG
language interpretation -> LLM
```

---

# 18. Add workflow-query tests

Test multiple semantically equivalent phrasings:

```text
What are the inputs required for the four cases?
What do I need for Case A?
What are the requirements for options A-D?
What inputs are required for the four cases you mentioned?
What is required for Case D?
```

Expected:

```text
classified as workflow_info
resolved deterministically
no attempt to read fake ProblemSnapshot field
no unknown_problem_field error
```

Also add regression tests:

```text
What pressure did I give?
What is xD?
```

must still route to the normal state-query resolver.

---

# 19. Correct feed-screening readiness

## Current inconsistency

The workflow can currently report something equivalent to:

```text
feed_screening.ready = True
```

while simultaneously requesting:

```text
reflux_condition
```

This violates the intended engineering workflow.

In this project, reflux condition is part of feed-phase screening.

Therefore feed screening must not be ready until a valid reflux condition is explicitly present.

---

# 20. Define feed-screening requirements in one deterministic place

Do not fix this by adding:

```python
and reflux_condition is not None
```

in one isolated conditional while leaving other readiness code with different requirements.

Identify the authoritative definition of feed-screening requirements.

Refactor only enough to ensure that these outputs derive from the same requirement definition:

```text
feed_screening.ready
feed_screening.missing_inputs
pending_request generation
assistant workflow message
calculation eligibility
```

There should not be multiple independent interpretations of what "feed screening ready" means.

---

# 21. Make stage requirements data-driven enough for future workflows

A useful scalable pattern is:

```text
workflow
    contains stages

stage
    defines deterministic requirements

stage assessment
    evaluates current state against those requirements
```

Conceptually:

```python
feed_screening_requirements = [
    ... binary feed definition ...,
    pressure_Pa,
    feed thermal specification,
    reflux_condition,
]
```

The exact implementation can remain aligned with the current code.

Do not create a generic workflow framework unless one already naturally exists.

The immediate goal is simply:

> stage readiness should be derived from explicit stage requirements rather than duplicated ad hoc conditionals.

That pattern will later support:

```text
multicomponent_feed_screening
thermodynamic_model_selection
azeotrope_screening
column_design
absorber_design
solvent_screening
```

without breaking the fundamental state architecture.

---

# 22. Reflux-condition rules for the current implementation

Currently supported:

```text
saturated_liquid
```

Therefore:

If `reflux_condition` is missing:

```text
feed_screening.ready = False
feed_screening.missing_inputs includes reflux_condition
```

If reflux condition is unsupported/invalid:

```text
feed_screening.ready = False
```

Do not silently map missing reflux to saturated liquid.

Once a valid explicit reflux condition has been stored:

```text
feed_screening may become ready
```

assuming all other feed-screening requirements are satisfied.

---

# 23. Reconcile legacy and new workflow assessments

The code currently has both:

```text
legacy essential-input logic
```

and:

```text
independent feed_screening/design_assessment branches
```

Do not remove the legacy status system during this task.

However, eliminate contradictory statements such as:

```text
feed_screening.ready == True
```

while:

```text
legacy missing essentials == ["reflux_condition"]
```

Where both systems describe the same engineering prerequisite, they must derive from the same canonical requirement or produce logically consistent results.

This is important because future workflows may maintain multiple assessment views over the same state.

They must not each invent their own engineering truth.

---

# 24. Add feed-screening tests

Use the original conversation as one acceptance case.

Initial input:

```text
Separate water and ethanol at 355 K and 101325 Pa pressure.
The feed flow rates are 50 kmol/hr ethanol and 50 kmol/hr water.
```

Expected canonical WRITE:

```python
{
    "component_flows": {
        "Ethanol": 50.0,
        "Water": 50.0
    },
    "component_flow_units": "kmol/hr",
    "feed_temperature_K": 355.0,
    "pressure_Pa": 101325.0
}
```

After WRITE:

```text
feed_screening.ready == False
feed_screening.missing_inputs includes reflux_condition
```

Then:

```text
User: Yes
```

Expected:

```text
no calculation
no state mutation
explicit reflux-condition request remains
```

Then:

```text
User: reflux is saturated liquid
```

Expected:

```python
one canonical WRITE:
{"reflux_condition": "saturated_liquid"}
```

Then:

```text
feed_screening.ready == True
```

assuming all other feed-stage inputs are satisfied.

Also test:

```text
unsupported reflux condition
```

Expected:

```text
validation failure or unsupported-value result
feed_screening remains not ready
no silent substitution
```

---

# 25. Introduce a general deterministic routing order

After implementing the fixes, the top-level turn processing should have an explicit precedence contract.

Use approximately this order:

```text
1. Parse/extract semantic TurnIntent.

2. Read authoritative current engineering/workflow state.

3. If active pending interaction exists:
      pending resolver gets first refusal.

4. Validate and normalize candidate engineering updates.

5. If valid updates exist:
      compile one atomic canonical WRITE.

6. If user asks for stored problem state:
      state-query resolver.

7. If user asks about workflow/schema metadata:
      workflow-info resolver.

8. If user requests a supported semantic command:
      resolve via ACTION_REGISTRY.

9. Generic conversational/model response only where deterministic
   structures do not already own the answer.
```

Exact implementation order may differ where the current transaction design requires it.

The important precedence constraints are:

```text
pending interaction > generic proceed

canonical engineering state > model assumptions

workflow registry > model recollection of software requirements

semantic action name > implementation function name
```

---

# 26. Avoid binary-distillation-specific router branches

Do not add top-level router code resembling:

```python
if reflux_condition...
if case_A...
if case_B...
if case_C...
if case_D...
```

The router should deal with semantic categories such as:

```text
pending interaction
state update
state query
workflow info
semantic action
```

Binary-distillation-specific engineering logic should stay inside the binary-distillation workflow/domain module.

Later, another workflow should be able to register its own:

```text
requirements
workflow-info resolvers
actions
state schema
assessment logic
```

without rewriting the top-level language-routing architecture.

---

# 27. Preserve domain isolation for future separation methods

Do not expand the current ProblemSnapshot to include speculative fields for every future separation technology.

When future workflows are added, the desired architecture should be capable of resembling:

```text
Separation Assistant
│
├── shared semantic/routing layer
│
├── shared transaction infrastructure
│
├── shared workflow/query/action interfaces
│
└── domain workflows
    ├── binary_distillation
    ├── multicomponent_distillation
    ├── flash
    ├── absorption
    ├── extraction
    └── ...
```

Each domain should own its engineering rules.

Shared infrastructure should understand contracts, not chemical-engineering specifics.

Do not implement these domains now.

Ensure only that this task does not make them harder to add.

---

# 28. Keep component cardinality as a domain capability, not a universal engine assumption

The current supported workflow is binary distillation.

Therefore >2 components may continue to be rejected for the current workflow.

However, do not encode globally:

```python
separation_engine_requires_exactly_two_components
```

Instead, the binary-distillation workflow/domain should express its own capability constraint:

```text
required component cardinality = 2
```

This will allow a future multicomponent-distillation workflow to coexist without dismantling the shared transaction/routing architecture.

No multicomponent calculations need to be implemented in this task.

---

# 29. Treat design Cases A-D as workflow-local options

Cases A-D are part of the current binary-distillation design method.

Do not put them into universal action routing.

Prefer conceptually:

```text
binary_distillation workflow
    └── design options
        ├── A
        ├── B
        ├── C
        └── D
```

rather than:

```text
global engine
    ├── case_A
    ├── case_B
    ...
```

This prevents future separation workflows from colliding with local option names.

---

# 30. Maintain one source of engineering truth per concept

As you implement the fixes, specifically inspect for duplicated definitions of:

```text
supported semantic actions
feed-screening required inputs
binary-distillation design-option requirements
supported reflux conditions
pending-request allowed values
```

Where feasible, make each concept have one deterministic authoritative definition and make other views derive from it.

Avoid creating a giant global configuration object.

Local authoritative definitions inside the appropriate domain module are preferred.

The goal is:

```text
single source of truth
```

not:

```text
single file containing everything
```

---

# 31. Diagnostics

Extend diagnostics where useful so failures can clearly show which architectural layer made a decision.

Helpful diagnostic concepts include:

```text
pending_request_detected
pending_resolution_result

normalized_updates

query_type
workflow_info_name

semantic_action_requested
semantic_action_resolved

workflow_stage
stage_missing_inputs
stage_ready
```

Do not expose internal implementation function names to the model solely for diagnostics.

Internal developer diagnostics may include the handler name if useful, but it must remain separate from the model-facing semantic vocabulary.

---

# 32. Required regression protection

All existing tests should continue passing unless an existing test explicitly encodes the incorrect behavior being fixed.

Pay special attention to preserving:

```text
keyed component-flow extraction
collection normalization
atomic WRITE behavior
units/basis validation
semantic retry behavior
state-query functionality
pending numeric resolution
pending boolean resolution
existing Wankat design assessment
legacy workflow status
reset behavior
diagnostics
```

Do not weaken validators merely to get acceptance tests to pass.

---

# 33. Add architecture-level tests, not only conversation tests

In addition to tests matching the observed conversation, add tests for the abstractions themselves.

Examples:

### Pending precedence invariant

```text
Any unresolved pending_request prevents unrelated generic proceed action.
```

### Semantic action invariant

```text
Only registered semantic action names are accepted from TurnIntent.
```

### Workflow metadata invariant

```text
workflow_info queries never require fake ProblemSnapshot fields.
```

### Stage-readiness invariant

```text
ready == true only if the deterministic stage requirement evaluator
reports no unresolved required inputs.
```

### Engineering-state invariant

```text
derived workflow metadata cannot be written through
update_binary_distillation_problem().
```

These tests are more important for scalability than only reproducing the four user prompts.

---

# 34. Live-Qwen acceptance test

After deterministic tests pass, run the following real conversation through the CLI/model.

### Turn 1

```text
Separate water and ethanol at 355 K and 101325 Pa pressure.
The feed flow rates are 50 kmol/hr ethanol and 50 kmol/hr water.
```

Required behavior:

```text
one atomic canonical WRITE
component flows correctly keyed
units stored
T stored
P stored

feed screening NOT ready
reflux_condition reported/requested
```

### Turn 2

```text
Yes
```

Required behavior:

```text
no calculation
no reflux assumption
no state mutation
assistant explicitly asks for reflux condition
```

### Turn 3

```text
reflux is saturated liquid
```

Required behavior:

```text
one canonical WRITE:
reflux_condition = saturated_liquid

no attempt to call:
calculate_current_binary_distillation_problem

feed screening becomes ready if all remaining requirements satisfied
```

### Turn 4

```text
What are the inputs required for the four cases you mentioned?
```

Required behavior:

```text
classified as workflow-information query

deterministic response describing A-D

no fake field such as:
missing_case_inputs

no:
unknown_problem_field
```

---

# 35. Additional adversarial acceptance tests

Test phrasing variation so the implementation is not fitted only to the exact transcript.

Examples:

```text
Yep
Sure
Go ahead
Okay
```

while a string-value pending request is unresolved.

These must not accidentally execute a calculation.

Test:

```text
The reflux is a saturated liquid.
Use saturated liquid reflux.
Reflux condition: saturated_liquid.
```

These should resolve the pending value.

Test:

```text
What does option B require?
What do I still need for option D?
What are all the supported design cases?
```

These should use deterministic workflow metadata.

Test intentionally generated internal function names and ensure deterministic rejection.

---

# 36. Files likely to require changes

Inspect the current implementations before editing, but expected files include:

```text
tools/chopper/binary_distillation_workflow.py
tools/chopper/binary_distillation_workflow_agent.py
tools/chopper/turn_intent.py
tools/chopper/turn_transaction.py
tools/chopper/turn_diagnostics.py
```

Potentially introduce one small shared module if needed for something like:

```text
semantic action definitions
workflow-info registry interfaces
```

Only do so if it removes duplicated truth or prevents circular imports.

Do not split the project into many new modules merely for architectural aesthetics.

---

# 37. Documentation updates

Update the architecture documentation to explicitly state:

### Semantic layer

```text
The LLM classifies and extracts intent.
It does not own engineering workflow truth.
```

### Pending interaction

```text
An unresolved pending request takes precedence over generic proceed commands.
```

### Actions

```text
Model-facing semantic actions are stable API names.
Python implementation function names are private.
```

### Query classes

```text
problem_field queries read mutable engineering state.

workflow_info queries read deterministic workflow/schema metadata.
```

### Workflow stages

```text
stage readiness is derived from deterministic stage requirements.
```

### Domain scalability

```text
binary-distillation-specific rules remain within the
binary-distillation domain so future separation workflows can share
the orchestration infrastructure without sharing engineering assumptions.
```

---

# 38. Explicit non-goals

Do NOT:

- implement multicomponent distillation,
- implement additional separation methods,
- redesign the entire workflow engine,
- replace deterministic Python with RAG,
- use RAG for workflow schema questions,
- make Qwen decide readiness,
- make Qwen decide design-case requirements,
- add `missing_case_inputs` to engineering state,
- alias internal Python function names as semantic actions,
- silently interpret `"yes"` as `"saturated_liquid"`,
- remove the canonical transaction/WRITE path,
- introduce separate state mutation paths,
- weaken validation,
- hard-code exact user sentences,
- create reflux-specific logic in the global router,
- create Case-A/B/C/D-specific logic in the global router.

---

# 39. Definition of done

The implementation is complete when all of the following are true:

1. Reflux condition is part of feed-screening readiness.

2. Feed screening cannot report ready while reflux condition is unresolved.

3. Bare affirmative responses cannot bypass an active pending request.

4. Bare `"yes"` does not silently provide an engineering string-choice value.

5. Explicit `"reflux is saturated liquid"` resolves through the canonical WRITE path.

6. Qwen only sees stable semantic action names.

7. Internal Python implementation function names cannot be emitted as valid actions.

8. Workflow metadata questions are distinct from engineering-state queries.

9. Questions about Case A-D requirements are answered deterministically from workflow definitions.

10. No fake workflow metadata fields are added to ProblemSnapshot.

11. Existing keyed-collection and atomic transaction behavior remains intact.

12. Existing binary-distillation tests continue to pass.

13. New abstraction-level tests pass.

14. The full original live-Qwen conversation behaves correctly.

15. The implementation does not make the global routing engine depend on binary-distillation-specific fields or Case A-D.

16. Future workflows can conceptually supply their own engineering requirements, workflow-info resolvers, and action handlers behind the same shared semantic interfaces.

---

# 40. Final implementation report

After completing the work, report:

1. files changed,
2. new abstractions introduced,
3. exact routing-order change,
4. how pending-request precedence is enforced,
5. where semantic action names are now sourced,
6. how internal implementation names are hidden,
7. how workflow-info queries differ from problem-field queries,
8. where feed-screening requirements are defined,
9. how reflux condition participates in readiness,
10. tests added,
11. total test results,
12. live-Qwen acceptance-test transcript/result,
13. any remaining architectural limitations.

Also explicitly state whether any changes altered the canonical state model, transaction atomicity, or existing keyed-collection architecture.