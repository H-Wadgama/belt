# Binary Distillation State Read/Write Separation Refactor

## Objective

Refactor the binary-distillation workflow so that the system clearly distinguishes between:

1. **Updating the problem state when the user provides new engineering information**, and
2. **Reading the existing problem state when the user asks a question about information that has already been supplied or derived.**

The current issue is that the same tool is being used for both operations.

This causes Qwen to sometimes convert a simple question such as:

```text
What is the composition and flow rate of the feed?
```

into a new problem update.

For example, after the user has already supplied:

```text
Methanol = 30 kmol/hr
Water = 90 kmol/hr
```

the correct current state is:

```text
Total feed = 120 kmol/hr
Methanol mole fraction = 0.25
Water mole fraction = 0.75
```

However, the model incorrectly made a new tool call such as:

```python
assess_binary_distillation(
    composition={"Methanol": 0.25, "Water": 0.75},
    total_flow=100,
    total_flow_units="kmol/hr"
)
```

The value `100 kmol/hr` was fabricated.

The deterministic consistency checker correctly detected the contradiction:

```text
Component flows = 30 + 90 = 120 kmol/hr
Specified total flow = 100 kmol/hr
```

Therefore, the consistency checker should **not** be weakened.

The actual problem is that the LLM is being allowed to use a state-update operation when the user is only asking to inspect existing state.

The solution is to separate **READ** and **WRITE** operations.

---

# 1. Core Architectural Change

The current architecture is approximately:

```text
User
  ↓
Qwen
  ↓
assess_binary_distillation(...)
  ↓
possibly modify problem state
  ↓
answer
```

Replace it with:

```text
                         USER
                           ↓
                         Qwen
                           ↓
              ┌────────────┴────────────┐
              │                         │
      NEW ENGINEERING INFO?       QUESTION ABOUT
              │                  EXISTING STATE?
              ▼                         ▼
 update_binary_problem()      get_binary_problem_state()
              │                         │
              ▼                         ▼
 deterministic merge              READ ONLY
              │                  no mutation
              ▼
 deterministic normalization
              │
              ▼
 consistency validation
              │
              ▼
 workflow assessment
              │
              └────────────┬────────────┘
                           ▼
                 authoritative state
                           ↓
                    Qwen explains
```

The key principle is:

> **A question about existing engineering state must never be treated as a new engineering input.**

---

# 2. Split State Updating From State Reading

Expose two separate operations to the workflow agent.

---

## Tool 1 — Update the Binary-Distillation Problem

Create a mutation tool conceptually similar to:

```python
update_binary_distillation_problem(
    component_names=None,

    component_flows=None,
    component_flow_units=None,

    total_flow=None,
    total_flow_units=None,

    composition=None,
    composition_basis=None,

    pressure_Pa=None,

    feed_temperature_K=None,
    feed_quality=None,
    feed_enthalpy_kJ_per_hr=None,

    reflux_temperature_K=None,
    reflux_enthalpy_kJ_per_hr=None,
    reflux_condition=None,

    xD=None,
    xB=None,

    Lr=None,
    Hr=None,

    external_reflux_ratio=None,
    boilup_ratio=None,

    distillate_flow=None,
    bottoms_flow=None,

    use_optimum_feed_plate=None,
)
```

The exact signature may differ, but its role must be clear.

This tool is used **only when the user has provided new engineering facts**.

Its workflow should be:

```text
New explicit user facts
        ↓
merge into existing state
        ↓
normalize deterministically
        ↓
derive mathematically determined values
        ↓
check consistency
        ↓
assess Wankat workflow
        ↓
return complete current state
```

Only values newly and explicitly supplied in the user's current message should be sent to this tool.

---

## Tool 2 — Read the Existing Binary-Distillation Problem

Create a second tool:

```python
get_binary_distillation_problem()
```

This tool should take **no engineering-value arguments**.

Its only purpose is to return the authoritative current state.

For example:

```python
{
    "component_names": [
        "Methanol",
        "Water"
    ],

    "component_flows": {
        "Methanol": {
            "value": 30,
            "units": "kmol/hr",
            "source": "user_explicit"
        },
        "Water": {
            "value": 90,
            "units": "kmol/hr",
            "source": "user_explicit"
        }
    },

    "total_flow": {
        "value": 120,
        "units": "kmol/hr",
        "source": "derived"
    },

    "composition": {
        "Methanol": {
            "value": 0.25,
            "basis": "mole",
            "source": "derived"
        },
        "Water": {
            "value": 0.75,
            "basis": "mole",
            "source": "derived"
        }
    },

    "pressure_Pa": {
        "value": 101325,
        "source": "user_explicit"
    },

    "feed_temperature_K": {
        "value": 350,
        "source": "user_explicit"
    },

    "reflux_condition": {
        "value": "saturated_liquid",
        "source": "user_explicit"
    },

    "workflow": {
        "case": None,
        "case_candidates": ["A", "B", "C", "D"],
        "status": "need_case_definition"
    }
}
```

This operation must be strictly **read-only**.

It should never:

```text
modify state
derive new user inputs
change provenance
overwrite existing values
invent values
```

---

# 3. User Questions About Existing State Must Use the Read Tool

Questions such as the following are not engineering updates:

```text
What is the feed composition?

What is the feed flow rate?

What is the composition and flow rate?

What pressure did I specify?

What temperature did I give you?

What information do you have so far?

What is still missing?

Which Wankat case am I in?

What values would be calculated?

What component flows did I provide?
```

These questions should call:

```python
get_binary_distillation_problem()
```

They should **not** call:

```python
update_binary_distillation_problem(...)
```

with values copied from existing state.

---

# 4. Do Not Resubmit Existing or Derived Values as New User Inputs

This is a critical provenance rule.

Suppose the current state contains:

```text
Methanol flow = 30 kmol/hr
    source = user_explicit

Water flow = 90 kmol/hr
    source = user_explicit

Total flow = 120 kmol/hr
    source = derived

Methanol mole fraction = 0.25
    source = derived

Water mole fraction = 0.75
    source = derived
```

Then the user asks:

```text
What is the composition?
```

The system may report:

```text
Methanol = 0.25
Water = 0.75
```

But it must **not** make a new update:

```python
composition={
    "Methanol": 0.25,
    "Water": 0.75
}
```

because the user did not provide those numbers.

They were already derived by the deterministic normalization layer.

Use the following rule:

> **Reporting an existing or derived value does not convert that value into a new user-supplied input.**

The provenance must remain:

```text
derived
```

rather than becoming:

```text
user_explicit
```

---

# 5. Classify User Turns Into Three Types

The workflow agent should distinguish three broad turn types.

---

## Type 1 — New Engineering Information

Examples:

```text
Water flow rate is 90 kmol/hr.

Column pressure is 101325 Pa.

The feed temperature is 350 K.

Use xD = 0.98.

V/B is 2.0.

Yes, use the optimum feed plate.
```

Action:

```text
WRITE
```

Use:

```python
update_binary_distillation_problem(...)
```

Only send the new facts from that turn.

---

## Type 2 — Question About Existing State

Examples:

```text
What is the feed composition?

What is my total feed flow?

What values have I given you?

What information is missing?

Which Wankat case does this match?

What pressure did I specify?
```

Action:

```text
READ
```

Use:

```python
get_binary_distillation_problem()
```

Do not modify the state.

---

## Type 3 — New Information Plus a Question

Example:

```text
Water flow is 90 kmol/hr. What is the resulting feed composition?
```

This contains both:

```text
WRITE:
Water flow = 90 kmol/hr
```

and:

```text
READ:
What is the resulting composition?
```

Correct workflow:

```text
update_binary_distillation_problem(
    component_flows={"Water": 90},
    component_flow_units="kmol/hr"
)
        ↓
deterministic state merge
        ↓
normalization derives total flow and composition
        ↓
update tool returns updated state
        ↓
Qwen answers the question from the returned state
```

The model should not calculate or guess the composition independently.

If the update tool returns the full normalized state, a second read call is unnecessary.

---

# 6. Update Tool Should Return the Full Current State

The mutation tool should not return only:

```text
success
```

or:

```text
missing fields
```

It should return the complete normalized workflow state after every update.

For example:

```python
{
    "status": "need_case_definition",

    "state": {
        "component_names": [
            "Methanol",
            "Water"
        ],

        "component_flows": {
            "Methanol": {
                "value": 30,
                "units": "kmol/hr",
                "source": "user_explicit"
            },

            "Water": {
                "value": 90,
                "units": "kmol/hr",
                "source": "user_explicit"
            }
        },

        "total_flow": {
            "value": 120,
            "units": "kmol/hr",
            "source": "derived"
        },

        "composition": {
            "Methanol": {
                "value": 0.25,
                "basis": "mole",
                "source": "derived"
            },

            "Water": {
                "value": 0.75,
                "basis": "mole",
                "source": "derived"
            }
        },

        "pressure_Pa": {
            "value": 101325,
            "source": "user_explicit"
        },

        "feed_temperature_K": {
            "value": 350,
            "source": "user_explicit"
        },

        "reflux_condition": {
            "value": "saturated_liquid",
            "source": "user_explicit"
        }
    },

    "workflow": {
        "case": None,
        "case_candidates": [
            "A",
            "B",
            "C",
            "D"
        ]
    },

    "missing": [
        "case-defining specifications"
    ]
}
```

This lets Qwen answer mixed turns such as:

```text
Water is 90 kmol/hr. What is my composition now?
```

without making another tool call or reconstructing information.

---

# 7. Preserve the Existing Consistency Checker

Do not weaken or remove the inconsistency detector.

The current behavior:

```text
Component flows sum to 120 kmol/hr,
but total feed flow was specified as 100 kmol/hr.
```

is correct.

The consistency checker successfully caught a fabricated LLM input.

The proper fix is not:

```text
allow conflicting values
```

The proper fix is:

```text
prevent Qwen from writing a new total_flow value when the user only asked
to read the existing flow rate.
```

The consistency checker should remain the deterministic backstop.

---

# 8. Add an Explicit Read-Only State View

Consider implementing:

```python
build_binary_problem_state_view(state)
```

This can convert the internal state into a clean representation intended for Qwen.

For example:

```python
{
    "feed": {
        "components": [
            "Methanol",
            "Water"
        ],

        "component_flows": {
            "Methanol": {
                "value": 30,
                "units": "kmol/hr"
            },

            "Water": {
                "value": 90,
                "units": "kmol/hr"
            }
        },

        "total_flow": {
            "value": 120,
            "units": "kmol/hr"
        },

        "composition": {
            "Methanol": 0.25,
            "Water": 0.75
        },

        "composition_basis": "mole"
    },

    "column": {
        "pressure_Pa": 101325,

        "feed_condition": {
            "type": "temperature",
            "value": 350,
            "units": "K"
        },

        "reflux_condition": "saturated_liquid"
    },

    "workflow": {
        "status": "need_case_definition",

        "case": None,

        "case_candidates": [
            "A",
            "B",
            "C",
            "D"
        ]
    }
}
```

This gives the LLM one authoritative structured object to inspect.

Qwen should not need to reconstruct the current engineering problem from conversation history.

---

# 9. Do Not Use Conversation History as the Authoritative Engineering State

Conversation history is useful for natural-language interpretation, but it should not be the authoritative engineering database.

Use:

```text
conversation history
    = linguistic context
```

Use:

```text
BinaryDistillationProblemState
    = authoritative engineering state
```

Therefore, when the user asks:

```text
What is the feed flow?
```

Qwen should not search its own previous text response for:

```text
120 kmol/hr
```

It should read:

```python
get_binary_distillation_problem()
```

The deterministic state object should be the single source of truth.

---

# 10. System Prompt Update

Add explicit rules equivalent to the following:

```text
You have separate READ and WRITE operations for the binary-distillation
problem.

Use the WRITE/update tool only when the current user message provides new
engineering information.

Use the READ/state tool when the user asks about information already
supplied, derived, stored, or still missing.

Never use the update tool merely to answer a question about existing state.

Never reconstruct the engineering state from conversation history when the
read-only state tool is available.

Only values explicitly provided as new facts in the current user message
may be passed to the update tool.

Do not pass values to the update tool simply because they already exist in
the current state.

Do not pass derived values back through the update tool.

Reporting a value does not make it user-supplied.

Examples of READ questions include:
- What is my feed composition?
- What is my feed flow rate?
- What pressure did I specify?
- What information do you have so far?
- What is still missing?
- Which case am I in?
- What would be calculated?

If a user message contains both new engineering information and a question,
first update only the newly supplied information, then answer the question
from the resulting normalized state.
```

---

# 11. Correct Behavior for the Problematic Conversation

Given:

```text
User:
Separate methanol and water.
```

State:

```text
Methanol + Water
```

Then:

```text
User:
Methanol flow rate is 30 kmol/hr.
```

State:

```text
Methanol = 30 kmol/hr
Water = unknown
```

Then:

```text
User:
Water flow rate is 90 kmol/hr.
```

Deterministic normalization produces:

```text
Methanol = 30 kmol/hr
Water = 90 kmol/hr

Total feed = 120 kmol/hr

Methanol mole fraction = 0.25
Water mole fraction = 0.75
```

Then:

```text
User:
Column pressure is 101325 Pa, feed is 350 K, reflux is saturated liquid.
```

These values are stored.

Then:

```text
User:
What is the composition of the feed?
```

Correct action:

```text
[calling get_binary_distillation_problem()]
```

Correct answer:

```text
The feed composition is:

Methanol: 0.25 mole fraction
Water: 0.75 mole fraction
```

No state mutation.

Then:

```text
User:
What is the composition and flow rate of the feed?
```

Correct action:

```text
[calling get_binary_distillation_problem()]
```

Correct answer:

```text
The total feed flow is 120 kmol/hr.

Methanol:
- 30 kmol/hr
- mole fraction = 0.25

Water:
- 90 kmol/hr
- mole fraction = 0.75

The total flow and composition were derived from the individual component
flows you supplied.
```

There should be **no call** such as:

```python
update_binary_distillation_problem(
    total_flow=100,
    composition={...}
)
```

---

# 12. Acceptance Tests

Add tests specifically for READ/WRITE separation.

## Test 1 — Ask Feed Composition

Established state:

```text
Methanol = 30 kmol/hr
Water = 90 kmol/hr
```

User:

```text
What is the feed composition?
```

Expected:

```text
READ operation only
```

State before and after must be identical.

Expected answer:

```text
Methanol = 0.25
Water = 0.75
```

---

## Test 2 — Ask Flow and Composition

User:

```text
What is the flow rate and composition of the feed?
```

Expected:

```text
READ operation only
```

Answer:

```text
Total flow = 120 kmol/hr

Methanol = 30 kmol/hr, x = 0.25
Water = 90 kmol/hr, x = 0.75
```

No new engineering values may be created.

---

## Test 3 — Ask Component Flows

User:

```text
What component flow rates did I give you?
```

Expected:

```text
READ operation
```

Return:

```text
Methanol = 30 kmol/hr
Water = 90 kmol/hr
```

Do not resubmit these values through the update tool.

---

## Test 4 — Ask Pressure

User:

```text
What pressure did I specify?
```

Expected:

```text
READ operation
```

Return:

```text
101325 Pa
```

State unchanged.

---

## Test 5 — Ask Missing Information

User:

```text
What information is still missing?
```

Expected:

```text
READ operation
```

Return the missing Wankat case information.

Do not call the update tool.

---

## Test 6 — Ask Current Case

User:

```text
Which Wankat case am I in?
```

If no case-defining specifications have been supplied:

```text
case = None
case_candidates = ["A", "B", "C", "D"]
```

Do not choose a case.

---

## Test 7 — Mixed Turn

Existing:

```text
Methanol = 30 kmol/hr
```

User:

```text
Water is 90 kmol/hr. What is the feed composition now?
```

Expected update:

```python
component_flows={"Water": 90}
```

No other new input.

Normalization derives:

```text
total flow = 120
composition = 0.25 / 0.75
```

Answer using the updated state.

---

## Test 8 — Pressure Update Plus Question

User:

```text
Pressure is 202650 Pa. What is still missing?
```

Expected:

```text
WRITE:
pressure_Pa = 202650
```

Then answer missing information from the updated workflow state.

---

## Test 9 — Read Operations Are Idempotent

Store the complete serialized state before:

```text
What is the feed composition?
```

Call the read operation.

Store the state afterward.

Assert:

```python
state_before == state_after
```

---

## Test 10 — Assistant-Reported Values Never Become User Explicit

If:

```text
total_flow = 120
source = derived
```

and the assistant tells the user:

```text
Your total flow is 120 kmol/hr.
```

then a later state inspection must still show:

```text
source = derived
```

It must never become:

```text
source = user_explicit
```

unless the user subsequently explicitly confirms or supplies that value.

---

## Test 11 — No Invented Values on Read Turns

For every read-only question, assert that the agent cannot introduce any new numerical engineering value.

For example:

```text
What is the feed flow rate?
```

must never generate:

```text
100 kmol/hr
```

or any other value that is not already stored or deterministically derived.

---

## Test 12 — Consistency Checker Remains Active

If the user explicitly says:

```text
Actually, the total feed is 100 kmol/hr.
```

while the component flows remain:

```text
30 + 90 = 120 kmol/hr
```

then this **is** a genuine new engineering update.

The update should be accepted as an attempted new input, after which the deterministic validator should return:

```text
status = inconsistent_input
```

This confirms the consistency checker still functions correctly.

---

# 13. Recommended Internal Separation of Responsibilities

The architecture should ultimately distinguish the following operations:

```text
LLM EXTRACTION
"What new facts did the user explicitly state?"

        ↓

STATE UPDATE
"Merge those facts into the engineering state."

        ↓

NORMALIZATION
"What quantities follow mathematically?"

        ↓

CONSISTENCY CHECK
"Do the supplied and derived quantities agree?"

        ↓

WORKFLOW ASSESSMENT
"Is the Wankat problem definition complete?"

        ↓

STATE READ
"What is currently known, derived, or missing?"

        ↓

LLM EXPLANATION
"Communicate that information to the user."
```

Qwen should not be responsible for reconstructing the engineering state or recalculating stored values.

---

# 14. Updated Overall Binary-Distillation Architecture

The complete workflow should now be:

```text
Natural-language user message
            ↓
Qwen determines whether message contains:
    - new information
    - a state question
    - or both
            ↓
     ┌──────┴───────┐
     │              │
 NEW INFO?       READ ONLY?
     │              │
     ▼              ▼
update state     read state
     │              │
     ▼              │
normalize           │
     │              │
     ▼              │
validate            │
     │              │
     ▼              │
workflow check      │
     │              │
     └───────┬──────┘
             ▼
    authoritative state
             ↓
        Qwen response
```

The authoritative state, not Qwen's conversation memory, should determine all engineering values.

---

# 15. Definition of Done

This refactor is complete when:

- A clear READ operation exists.
- A clear WRITE/update operation exists.
- State questions never call the mutation tool.
- New engineering information still updates state correctly.
- Mixed information-plus-question turns update first and answer second.
- Existing or derived values are never resubmitted as new user inputs.
- Assistant responses do not alter engineering provenance.
- Read operations are guaranteed not to mutate state.
- Conversation history is not treated as the authoritative engineering database.
- The deterministic state remains the single source of truth.
- The existing inconsistency checker remains active.
- Questions such as “What is the composition and flow rate?” return the stored values without fabricating new ones.
- No BioSTEAM calculation or optimization is introduced by this refactor.
- All existing workflow tests continue to pass.
- All new READ/WRITE separation acceptance tests pass.

The core rule for this implementation is:

> **New engineering facts update the state. Questions about existing engineering facts read the state. Never turn a question into a new engineering input.**