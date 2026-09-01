# Round 2 Architecture Stabilization — Scalable Turn Interpretation and State Access

## Objective

Fix the observed conversation and state-access failures by introducing a
small, schema-driven turn-transaction layer between natural language and the
existing deterministic workflow.

The implementation in this round remains scoped to the current
binary-distillation workflow. The shared interpretation and state-access
shapes, however, must not assume:

- exactly two components;
- exactly one feed or distillation column;
- ordinary distillation as the only separation technique;
- a permanently fixed list of engineering variables; or
- exactly one fact or question per user turn.

The eventual system may contain multicomponent feeds, several separation
techniques, and a flowsheet with multiple separation units. This round does not
implement those engineering capabilities. It establishes an extension boundary
so they can be added later without rewriting the conversational controller.

The guiding rule is:

~~~text
LLM understands language.
Python validates, executes, and owns truth.
~~~

Qwen may interpret intent, propose candidate fields, identify component and
unit-operation references, and decompose a turn. Python must validate all of
those proposals, own canonical state, derive values, execute workflow actions
and calculations, and produce authoritative focused answers.

Do not build a large regex/alias engine for arbitrary engineering language. Do
not build a universal separation ontology or general workflow engine in this
round.

---

# Scope and non-goals

This task changes conversation interpretation and state access around:

- binary_distillation_workflow_agent.py;
- the current canonical workflow state;
- update_binary_distillation_problem(), the existing WRITE path;
- get_binary_distillation_problem(), the existing broad READ path; and
- focused state-query formatting and tests.

This task does not change BioSTEAM thermodynamics, feed-phase calculations,
partial-condensation behavior, the 313.15 K conditioning screen, Design Option
A-D sizing, multicomponent calculation support, or flowsheet synthesis.

---

# Observed failures and required outcomes

## Failure 1 — mixed WRITE + READ turn loses the WRITE

~~~text
reflux condition is saturated liquid,
also what was the total flow rate of the feed?
~~~

This contains:

~~~text
WRITE: reflux_condition = saturated_liquid
READ: total feed flow
~~~

Both intents must survive. The WRITE executes first; the READ resolves from the
post-WRITE authoritative state.

## Failure 2 — derived total feed flow is not reliably retrievable

The normalized assessment may contain:

~~~python
"feed": {
    "component_flows": {"Ethanol": 50, "Water": 50},
    "total_flow": 100,
    "total_flow_provenance": "derived",
}
~~~

For “What is the total feed flow?”, answer:

~~~text
The total feed flow rate is 100 kmol/hr.
~~~

Do not add another sentence alias. The reader must access the normalized
assessment, not assume a derived total exists in the raw mutable accumulator.

## Failure 3 — unknown symbol is answered from model knowledge

For “What is zB?”, Qwen may propose zB as a candidate reference. Python must
validate it against the active workflow schema. An unknown current-state symbol
must not fall through to generic model knowledge.

## Failure 4 — intended tool call appears as assistant JSON text

For “Sorry, I meant xB”, the observed assistant output was tool-looking JSON in
ordinary chat content instead of an executed operation.

This round must identify the actual Ollama response shape and enforce a strict
interpretation boundary. Arbitrary assistant JSON must never become executable
tool input.

## Failure 5 — user is told to select a Design Option

The intended interaction is:

~~~text
user supplies engineering specifications
→ Python identifies the Design Option
~~~

The user must never be required to name or select A/B/C/D. This round does not
redesign the full Design Option workflow, but it does make the narrow
user-facing correction: ask for engineering quantities or explain acceptable
specification sets without asking the user to select an option letter.

---

# Core architectural principles

1. One canonical mutable problem state exists for the active workflow.
2. Assessments and snapshots are derived views, not second state stores.
3. update_binary_distillation_problem() remains the one canonical WRITE path.
4. One user message becomes one semantic transaction, not one tool call.
5. A transaction may contain multiple updates and multiple queries.
6. All updates validate before any mutation.
7. Valid updates are applied atomically in one WRITE call.
8. Reads use one post-WRITE authoritative snapshot.
9. Field, keyed entity, and target subject identity are separate concepts.
10. The structural intent schema is generic; active workflow registries own
    available fields and actions.
11. Current binary calculation scope is separate from state-model scalability.
12. Qwen proposes meaning but never owns engineering truth.

---

# Target architecture

~~~text
USER MESSAGE
     ↓
exclusive deterministic fast path, only if the whole turn is one
unambiguous already-supported intent
     ↓ otherwise
Qwen semantic interpretation
     ↓
untrusted structured TurnIntent
     ↓
Python structural and active-schema validation
     ↓
one validated TurnTransaction
     ├─ optional RESET under explicit reset policy
     ├─ validate ALL updates
     ├─ one atomic WRITE
     ├─ construct one post-WRITE ProblemSnapshot
     ├─ resolve zero or more READs
     └─ execute at most one compatible ACTION
     ↓
deterministic focused response or grounded broad/action response
~~~

TurnIntent is an LLM proposal. TurnTransaction is a validated execution plan.
ProblemSnapshot is a read-only view derived from canonical state. None is a
second mutable problem store.

Replace the current “one primary engineering tool per turn” rule for this path
with:

~~~text
one semantic transaction per turn
→ at most one atomic state mutation
→ zero or more reads
→ at most one compatible action
~~~

This preserves bounded execution without suppressing a valid READ accompanying
a WRITE.

---

# Part 1 — Add an active workflow schema boundary

The shared controller must not contain one branch per separation technique or
field. It consumes metadata for the active workflow.

For this round, only the binary-distillation schema is registered:

~~~python
ACTIVE_WORKFLOW_SCHEMA = {
    "schema_id": "binary_distillation_problem.v1",
    "fields": PROBLEM_FIELD_REGISTRY,
    "actions": ACTION_REGISTRY,
}
~~~

A future technique may provide another schema/adapter. The TurnIntent parser and
transaction executor should not require a new language-routing branch for each
field. Do not implement plugin discovery, a universal flowsheet model, or a
general ontology now; establish only this small extension seam.

---

# Part 2 — Create a model-facing problem field registry

Create one authoritative metadata registry describing fields supported by the
active workflow. The registry describes access; it does not store values.

Keep it separate from BINARY_DISTILLATION_QUANTITIES, which currently defines
calculated/reportable output symbols such as QR, Qc, and N. Input/state fields
and future calculated outputs are not the same registry today.

Conceptual entries:

~~~python
PROBLEM_FIELD_REGISTRY = {
    "feed_temperature_K": {
        "readable": True,
        "writable": True,
        "label": "feed temperature",
        "description": "Temperature of the feed entering the separation",
        "value_type": "number",
        "canonical_units": "K",
        "write_binding": "feed_temperature_K",
        "read_accessor": "inputs.feed_temperature_K",
        "allowed_subject_kinds": ["feed", "current_problem"],
    },
    "pressure_Pa": {
        "readable": True,
        "writable": True,
        "label": "column pressure",
        "value_type": "number",
        "canonical_units": "Pa",
        "write_binding": "pressure_Pa",
        "read_accessor": "inputs.pressure_Pa",
        "allowed_subject_kinds": ["unit_operation", "current_problem"],
    },
    "reflux_condition": {
        "readable": True,
        "writable": True,
        "label": "reflux condition",
        "value_type": "enum",
        "allowed_values": ["saturated_liquid"],
        "write_binding": "reflux_condition",
        "read_accessor": "inputs.reflux_condition",
    },
    "total_flow": {
        "readable": True,
        "writable": False,
        "label": "total feed flow rate",
        "value_type": "number",
        "read_accessor": "assessment.feed.total_flow",
        "units_accessor":
            "assessment.feed.total_flow_units or assessment.feed.component_flow_units",
        "provenance_accessor": "assessment.feed.total_flow_provenance",
        "source": "derived_or_explicit",
        "allowed_subject_kinds": ["feed", "current_problem"],
    },
    "component_flows": {
        "readable": True,
        "writable": True,
        "keyed": True,
        "entity_type": "component",
        "label": "component feed flow",
        "value_type": "number",
        "write_binding": "component_flows",
        "read_accessor": "assessment.feed.component_flows[{entity}]",
        "units_accessor": "assessment.feed.component_flow_units",
        "provenance_accessor":
            "assessment.feed.component_flows_provenance[{entity}]",
        "allowed_subject_kinds": ["feed", "current_problem"],
    },
    "xD": {
        "readable": True,
        "writable": True,
        "label": "distillate light-key mole fraction",
        "value_type": "number",
        "constraints": {"min": 0, "max": 1},
        "write_binding": "xD",
        "read_accessor": "inputs.xD",
    },
}
~~~

The implementation may use callables rather than string paths. Each entry must
tell Python how to validate, write, read, obtain units/provenance, and format a
field without duplicating its value.

Do not hard-code kmol/hr for feed-flow fields. Actual units come from the
snapshot. Expose canonical names, concise descriptions, keyed status, and
value/unit expectations to Qwen—not every sentence a user might say.

---

# Part 3 — Separate field, entity, and subject identity

- **field**: the property being accessed;
- **entity**: a key inside a keyed field, such as a component;
- **subject**: the feed, stream, column, or separation unit owning the field.

Do not create ethanol_flow, methanol_flow, column_1_pressure, and
column_2_pressure fields.

Use:

~~~python
{
    "field": "component_flows",
    "entity": "Ethanol",
    "subject": {"kind": "feed", "id": "feed"},
}
~~~

Later, a multicolumn state could use:

~~~python
{
    "field": "pressure_Pa",
    "entity": None,
    "subject": {"kind": "unit_operation", "id": "D2"},
}
~~~

The current single-feed/single-column workflow may default an omitted subject
to current_problem, but must validate any supplied subject. Do not claim live
multicolumn support until canonical state contains multiple units.

Component identity matching must be grounded in established state, using safe
normalization such as case-insensitive exact matching. Do not infer chemical
synonyms from model knowledge during state access.

The binary workflow may still reject more than two components for calculation.
That restriction belongs in workflow validation, not in the generic keyed
reader.

---

# Part 4 — Introduce a structurally generic TurnIntent

Qwen interprets the complete turn into:

~~~python
TurnIntent = {
    "version": 1,
    "updates": [
        {
            "field": str,
            "entity": str | None,
            "subject": {"kind": str, "id": str} | None,
            "value": object,
            "units": str | None,
            "basis": str | None,
        }
    ],
    "queries": [
        {
            "field": str,
            "entity": str | None,
            "subject": {"kind": str, "id": str} | None,
            "raw_reference": str | None,
        }
    ],
    "action": {"name": str, "arguments": dict} | None,
}
~~~

Field and action names remain strings in the transport schema. The active
registry performs semantic validation. This is important: Qwen must be able to
preserve an unknown candidate such as zB so Python can reject it rather than
forcing the model to invent a meaning or drop the query.

Mixed example:

~~~python
{
    "version": 1,
    "updates": [
        {"field": "reflux_condition", "value": "saturated_liquid"}
    ],
    "queries": [
        {
            "field": "total_flow",
            "subject": {"kind": "feed", "id": "feed"},
            "raw_reference": "total feed flow",
        }
    ],
    "action": None,
}
~~~

Multiple-query example:

~~~python
{
    "version": 1,
    "updates": [{"field": "xB", "value": 0.1}],
    "queries": [
        {"field": "feed_temperature_K"},
        {"field": "pressure_Pa"},
    ],
    "action": None,
}
~~~

Unknown example:

~~~python
{
    "version": 1,
    "updates": [],
    "queries": [{"field": "zB", "raw_reference": "zB"}],
    "action": None,
}
~~~

Qwen proposes neither authoritative answers nor executable operations.

---

# Part 5 — Define the interpretation boundary

Inspect the installed Ollama client and raw Qwen response before choosing the
adapter. Prefer schema-constrained structured output if supported reliably. If
native tool calling produces TurnIntent, expose only an intent-proposal
operation during interpretation—not engineering WRITE/READ tools.

Normalize either mechanism through:

~~~python
parse_turn_intent_response(raw_response) -> TurnIntentParseResult
~~~

The parser must:

- accept only the declared TurnIntent structure;
- reject malformed types and invalid top-level structure;
- never execute a tool named in ordinary message content;
- preserve unknown candidate fields for semantic validation;
- return structured parse errors rather than guessing; and
- never let a recognized current-state query with an invalid field fall
  through to a generic engineering answer.

This ordinary assistant content is not a TurnIntent and never executes:

~~~json
{"name": "get_binary_distillation_problem", "arguments": {}}
~~~

It may trigger one strict-schema retry; otherwise return a bounded
interpretation error. Do not add a regex that executes arbitrary JSON-looking
assistant content.

---

# Part 6 — Retain only exclusive deterministic fast paths

Existing pending-reply, temperature, progress, proceed, and query helpers
contain useful behavior. A fast path may bypass interpretation only when it
consumes the entire message as one unambiguous intent—for example:

- bare “yes” answering one live boolean pending request;
- bare “355 K” answering one live temperature request;
- an exact standalone progress phrase with no co-stated facts; or
- another whole-message deterministic form whose meaning is complete.

A detector must not intercept a message containing clauses it cannot
represent. Mixed turns go through TurnIntent.

Fast paths should produce the same TurnIntent or TurnTransaction shape as the
model interpreter. They are optimizations, not a parallel architecture.

---

# Part 7 — Validate TurnIntent deterministically and atomically

## Structural validation

Validate version, list/object shapes, entry keys and types, and at most one
action. Malformed model output becomes a data error, never a Python exception.

## Active workflow-schema validation

For each update, query, and action, Python verifies:

- field/action exists;
- requested read/write permission;
- valid subject kind and identifier;
- correct entity use for keyed fields;
- whether a WRITE may establish a new component identity;
- value type, range, units, and basis;
- duplicate-reference consistency;
- mutually exclusive field groups;
- cross-field constraints; and
- action compatibility with the turn and current state.

Identical duplicate updates may collapse. Conflicting duplicates require
clarification.

All updates validate before mutation. If one is invalid, perform no partial
WRITE. Combine validated keyed/scalar updates into one call:

~~~python
update_binary_distillation_problem(**validated_update_kwargs)
~~~

Do not create another mutation path.

---

# Part 8 — Execute one TurnTransaction

~~~python
TurnTransaction = {
    "reset_first": False,
    "update_kwargs": {"reflux_condition": "saturated_liquid"},
    "queries": [
        {
            "field": "total_flow",
            "subject": {"kind": "feed", "id": "feed"},
        }
    ],
    "action": None,
}
~~~

Execution order:

~~~text
1. validate the complete TurnIntent without mutation
2. if explicitly authorized, RESET
3. perform one atomic WRITE
4. build one post-WRITE ProblemSnapshot
5. resolve every state query from that snapshot, in user order
6. execute at most one compatible action against post-WRITE state
7. format one response containing the requested results
~~~

## Action policy

Register generic verbs:

~~~text
reset_current_problem
calculate_current_step
read_calculation_status
~~~

- RESET may combine with updates only for an explicit new/replaced problem;
  execute RESET, then the atomic WRITE.
- CALCULATE runs after updates and a new readiness assessment.
- Calculation-status READ uses authoritative calculation progress.
- Incompatible actions are rejected; Python does not choose silently.
- State queries may coexist with one compatible action.
- Reading a missing calculated output does not silently trigger a calculation.

Future workflows may register more actions without changing TurnIntent. Python
owns their prerequisites and execution.

---

# Part 9 — Build one authoritative ProblemSnapshot

The current system has explicit mutable inputs in _workflow_state and a
normalized assessment from get_binary_distillation_problem(). They are not
competing state stores.

Build a read-only per-transaction view:

~~~python
ProblemSnapshot = {
    "schema_id": "binary_distillation_problem.v1",
    "inputs": <read-only view/copy of canonical explicit state>,
    "assessment": get_binary_distillation_problem(),
    "calculation": <authoritative calculation status if requested>,
}
~~~

Create it after a successful WRITE. Every READ in the turn uses that snapshot.

Registry accessors decide the source:

- explicit pressure_Pa, xD, and reflux_condition come from inputs;
- derived total_flow, component flows, composition, units, and provenance come
  from assessment["feed"];
- future calculated outputs come only from authoritative calculation results.

Never copy derived snapshot values into canonical inputs. Reading or reporting a
derived value must not relabel it user-explicit.

---

# Part 10 — Add one generic state-value reader

~~~python
read_problem_value(
    snapshot: ProblemSnapshot,
    field: str,
    entity: str | None = None,
    subject: dict | None = None,
) -> dict
~~~

Derived total:

~~~python
{
    "valid": True,
    "found": True,
    "field": "total_flow",
    "value": 100,
    "units": "kmol/hr",
    "provenance": "derived",
}
~~~

Keyed component:

~~~python
{
    "valid": True,
    "found": True,
    "field": "component_flows",
    "entity": "Ethanol",
    "value": 50,
    "units": "kmol/hr",
    "provenance": "user_explicit",
}
~~~

Known but missing:

~~~python
{"valid": True, "found": False, "field": "xD"}
~~~

Unknown:

~~~python
{
    "valid": False,
    "error": "unknown_problem_field",
    "field": "zB",
    "near_matches": ["xB"],
}
~~~

Use separate unknown_problem_subject and unknown_problem_entity errors where
appropriate.

Keep get_binary_distillation_problem() for broad questions such as “Summarize
everything”, “What is missing?”, or “What is the workflow status?” Focused
queries use read_problem_value(). Both consume one canonical state.

---

# Part 11 — Focused responses are terminal

Once Python resolves focused queries, do not send their values through Qwen for
elaboration.

Single:

~~~text
The total feed flow rate is 100 kmol/hr.
~~~

Multiple values preserve query order:

~~~text
The feed temperature is 355 K. The specified pressure is 101325 Pa.
~~~

Mixed update/query:

~~~text
The reflux condition is now saturated liquid. The total feed flow rate is
100 kmol/hr.
~~~

Do not append missing-input dumps, Design Option summaries, or invitations to
continue. Broad summaries and calculation explanations may still use Qwen only
after Python supplies authoritative data and with mutation tools unavailable.

---

# Part 12 — Unknown fields remain bounded

For a current-state query:

~~~text
zB is not a recognized variable in the current binary-distillation workflow.
~~~

An optional deterministic near-match may ask “Did you mean xB?”, but must not
silently execute xB. A correction such as “Sorry, I meant xB” creates a new
validated READ.

A genuinely general educational question may be handled outside the state-query
path. The controller must make that distinction explicitly; an invalid state
field must never fall through accidentally.

---

# Part 13 — Pending requests remain derived

Do not create mutable pending-request storage. A side READ does not mutate the
problem, so the next assessment recomputes the same pending request.

~~~text
Assistant: Should the optimum feed plate be used?
User: Before I answer that, what is the feed temperature?
Assistant: The feed temperature is 355 K.
User: yes
~~~

The final “yes” still resolves against use_optimum_feed_plate.

If a mixed turn supplies the pending value and asks a question, the value enters
the transaction's update set; after WRITE, the snapshot naturally recomputes
the next pending state.

---

# Part 14 — Resolve textual tool-call leakage at the boundary

Temporarily log a sanitized raw Ollama/Qwen response and determine:

1. whether the call appears in structured tool_calls;
2. whether it appears in message.content;
3. whether the current loop dropped or misclassified it;
4. whether prompt/schema changes caused JSON imitation; and
5. whether schema-constrained output works in the installed client.

Then implement one explicit Part 5 adapter.

The post-change invariant is:

~~~text
Qwen proposes TurnIntent.
Python executes registered workflow operations.
Assistant content never directly invokes a tool.
~~~

---

# Part 15 — Never require Design Option selection

Make the narrow user-facing correction now.

When design-defining fields are absent, say:

~~~text
To define the column design, provide one supported set of engineering
specifications—for example product compositions and reflux ratio, component
recoveries and reflux ratio, a product flow with a product composition and
reflux ratio, or product compositions with a boilup ratio.
~~~

Do not say “Select Design Option A, B, C, or D.” Python continues to identify
the internal case. Add deterministic and agent-level regressions proving that a
feed-ready/design-incomplete conversation never asks for an option letter.
Full stage-aware Design Option dialogue remains later work.

---

# Part 16 — Tools represent verbs, not fields or techniques

Do not create get_temperature(), get_ethanol_flow(), get_xD(), or one
calculate tool per engineering case.

Prefer:

~~~text
interpret turn
read focused value
read broad state
write validated state
calculate current step
read calculation status
reset current problem
~~~

Fields, entities, subjects, and active schemas are data passed to stable verbs.
A future technique registers fields, actions, validation, and access behind the
workflow boundary. The controller does not gain a language branch for every
new engineering variable.

---

# Part 17 — Preserve current calculation behavior

Do not change feed_screening/design_assessment independence, readiness rules,
feed-phase execution, calculation-progress truth, partial-condensation routing,
binary-scope calculation rejection, or numeric grounding.

For:

~~~text
The feed temperature is 355 K; calculate the current step.
~~~

WRITE the temperature, recompute readiness, then calculate. If still blocked,
return the authoritative post-WRITE reason. Never calculate from old state.

---

# Required acceptance conversation

From a fresh session:

~~~text
Separate water and ethanol at 355 K and 101325 Pa pressure.
The feed composition is 50 kmol/hr ethanol and 50 kmol/hr water.
~~~

Then:

~~~text
reflux condition is saturated liquid,
also what was the total flow rate of the feed?
~~~

Required:

1. complete intent validates;
2. one WRITE stores saturated_liquid;
3. one post-WRITE snapshot is built;
4. total_flow resolves to derived 100 with current units;
5. response answers both requested parts; and
6. assessment shows reflux_condition_given == True.

Acceptable response:

~~~text
The reflux condition is now saturated liquid. The total feed flow rate is
100 kmol/hr.
~~~

Then verify:

~~~text
I just told you the reflux condition, didn't I?
→ Yes. The reflux condition is saturated liquid.

What are the ethanol feed flow, total feed flow, temperature, and pressure?
→ four focused values in that order; no workflow dump.

What is zB?
→ bounded unknown_problem_field; no invented definition.

Sorry, I meant xB.
→ real validated READ; no textual tool JSON; if absent, xB is not specified.
~~~

Finally, confirm the assistant asks for engineering specifications but never
asks the user to select Design Option A/B/C/D.

---

# Transaction acceptance tests

Test the interpreter and executor separately with fake/scripted model responses.

Interpreter tests:

- one and multiple updates;
- one and multiple queries;
- mixed updates + queries;
- update + compatible action;
- keyed entity and supplied subject;
- unknown candidate field preserved;
- malformed intent rejected;
- tool-looking JSON content rejected; and
- no engineering operation during interpretation.

Direct TurnIntent validator/executor tests:

- all updates validate before mutation;
- invalid second update causes zero writes;
- identical duplicates collapse;
- conflicting duplicates reject;
- mutually exclusive field groups retain current semantics;
- keyed updates compile into one WRITE argument;
- exactly one WRITE for a multi-update transaction;
- reads use post-WRITE state and preserve order;
- actions evaluate readiness post-WRITE;
- side READs do not mutate state or calculation progress;
- WRITE still invalidates stale calculation results;
- reset + explicit replacement follows policy; and
- incompatible actions reject deterministically.

Do not rely on a live LLM for transaction correctness.

---

# Scalability acceptance tests

These validate architecture, not currently supported calculations.

## Keyed multicomponent access

With an artificial normalized snapshot:

~~~python
component_flows = {
    "Water": 50,
    "Ethanol": 50,
    "Methanol": 20,
    "Acetone": 10,
}
~~~

retrieve Methanol using field="component_flows", entity="Methanol" without a
Methanol-specific resolver. The binary calculation workflow may still reject
the feed.

## Subject-aware access

With an artificial D1/D2 snapshot, verify field="pressure_Pa" and
subject={"kind": "unit_operation", "id": "D2"} select D2 without creating
column_2_pressure or editing controller code. This does not claim live
multicolumn support.

## Registry extension

Add one artificial field and one artificial action to test registries. Prove
the generic validator/reader can handle them without editing turn-routing
logic.

---

# Architectural invariants

~~~text
1. One canonical mutable state per active workflow session.
2. ProblemSnapshot is derived/read-only, not duplicated state.
3. One canonical WRITE path.
4. At most one validated TurnTransaction per user turn.
5. Every update validates before mutation.
6. At most one atomic engineering WRITE per transaction.
7. Reads use one post-WRITE authoritative snapshot.
8. A turn may contain multiple updates and queries.
9. Field, entity, and subject identity remain distinct.
10. Qwen proposes intent but never owns truth.
11. Python rejects unknown fields/actions/entities/subjects.
12. Focused READs are terminal and deterministic.
13. Derived values retain derived provenance.
14. Pending requests remain derived.
15. Assistant content never directly executes a tool.
16. Users supply specifications; Python identifies Design Options.
17. Binary calculation scope is separate from access-layer scalability.
18. Stable verbs operate on registry data.
~~~

---

# Suggested implementation order

## Step A — document current behavior

Record ask() routing, deterministic fast paths, aliases/display templates, the
one-primary-operation rule, native tool parsing, raw textual-JSON response,
canonical state, assessment construction, derived-value locations,
pending-request recomputation, and tests encoding WRITE-over-READ suppression.

## Step B — build registries and ProblemSnapshot

Implement binary field/action metadata, snapshot construction, and the generic
reader. Keep the old resolver temporarily for regression comparison; add no new
sentence aliases.

## Step C — implement deterministic formatting

Cover single/multiple values, missing/unknown fields, keyed entities, and
dynamic units/provenance.

## Step D — implement TurnIntent parsing

Select one inspected Ollama adapter and test it strictly. Assistant content does
not execute engineering tools.

## Step E — compile and validate TurnTransaction

Implement complete-intent validation, keyed/scalar WRITE compilation,
atomicity, and action compatibility.

## Step F — integrate into ask()

Keep only exclusive fast paths. Route other turns through interpretation,
validation, WRITE, snapshot, READs, and action. Replace the one-primary-tool
assumption for this path.

## Step G — correct Design Option wording

Update deterministic/model-facing wording and prohibit requests for an option
letter in tests.

## Step H — retire obsolete aliases carefully

Keep aliases only for justified exclusive compatibility paths. Remove them once
transaction tests cover the behavior. Do not maintain two full language
systems.

## Step I — regression testing

Run registry/snapshot/reader, parser, validator/executor, scripted-agent,
acceptance-conversation, scalability, and full tools/chopper tests.

---

# Do not over-refactor

Do not build a universal separation ontology, production multicolumn state,
multicomponent thermodynamics, a general workflow engine, dynamic plugin
discovery, technique-selection expert system, or new BioSTEAM calculations.

Build only:

~~~text
semantic interpretation
→ active-schema validation
→ atomic state transaction
→ authoritative snapshot
→ scalable state access/action dispatch
~~~

Extension seams should be testable now, but production abstractions must be
justified by current failures.

---

# Report back

Report:

1. files changed;
2. previous routing and one-primary-operation behavior;
3. selected Ollama/TurnIntent adapter;
4. root cause of textual tool JSON;
5. final TurnIntent and TurnTransaction schemas;
6. field/action registries;
7. ProblemSnapshot construction;
8. generic reader API;
9. field/entity/subject handling;
10. atomic WRITE behavior;
11. mixed WRITE+READ execution;
12. multiple-query formatting;
13. unknown reference handling;
14. pending behavior through side questions;
15. Design Option UX regression;
16. remaining aliases and why;
17. required acceptance transcript;
18. multicomponent keyed-reader test;
19. subject-aware multicolumn fixture;
20. registry-extension test;
21. focused and full test counts; and
22. remaining limitations.

Do not begin later calculation, full Design Option UX, multicomponent, or
multicolumn implementation rounds until this stabilization passes.
