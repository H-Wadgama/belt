## Round 2 Finalization — Make simple stored-field queries terminal

The Round 2 follow-up is now working correctly at the routing/state level.

Live successes:

```text
"boilup ratio is 2"
→ deterministic WRITE
```

```text
"What is the feed flow rate of ethanol?"
→ deterministic state query
→ correctly resolves 50 kmol/hr
```

```text
"Before I answer that, what is the temperature of the feed?"
→ deterministic state query
→ correctly resolves 355 K
```

Do NOT change the WRITE routing or field-alias architecture again.

The remaining bug occurs AFTER the deterministic state query has already produced the correct result.

Examples:

```text
The ethanol flow rate is 50 kmol/hr.
Please provide the flow rate for water...
```

Water is already stored as 50 kmol/hr.

Likewise:

```text
The feed temperature is 355 K.
...
Please provide feed composition...
```

Feed composition is already stored.

The first sentence is correct. The model-generated continuation is wrong.

---

# Goal

For simple single-field stored-state queries, the deterministic state-query result should be a TERMINAL response path.

Do not send it back through Qwen for additional free-form elaboration.

---

# Desired architecture

Current conceptual behavior:

```text
USER STATE QUESTION
        ↓
deterministic state-query resolver
        ↓
correct structured result
        ↓
Qwen
        ↓
correct answer + hallucinated extra advice
```

Replace with:

```text
USER STATE QUESTION
        ↓
deterministic state-query resolver
        ↓
correct structured result
        ↓
deterministic formatter
        ↓
RETURN TO USER
```

No additional Qwen generation for this narrow response type.

---

# Scope

Apply this ONLY when:

```python
query_result["query_type"] == "stored_field"
```

or the equivalent existing internal classification.

Do not convert all assistant responses into deterministic strings.

Broader questions such as:

```text
Summarize my current problem.
What am I still missing?
What should happen next?
Explain the feed-screen result.
```

may continue through their appropriate deterministic/controller/model paths.

This fix is specifically for simple field lookup questions.

---

# Deterministic formatting

Examples:

Input:

```python
{
    "field": "feed_temperature_K",
    "found": True,
    "value": 355,
    "units": "K",
    "provenance": "user_explicit"
}
```

Output:

```text
The feed temperature is 355 K.
```

Input:

```python
{
    "field": "pressure_Pa",
    "found": True,
    "value": 101325,
    "units": "Pa"
}
```

Output:

```text
The specified pressure is 101325 Pa.
```

Input:

```python
{
    "field": "component_flows.Ethanol",
    "found": True,
    "value": 50,
    "units": "kmol/hr"
}
```

Output:

```text
The ethanol feed flow rate is 50 kmol/hr.
```

Input:

```python
{
    "field": "xD",
    "found": False
}
```

Output:

```text
xD has not been specified yet.
```

For yes/no wording such as:

```text
Did I already specify the ethanol flow?
```

it is acceptable to produce:

```text
Yes. The ethanol feed flow rate is 50 kmol/hr.
```

If the existing resolver retains enough query metadata to distinguish "what is" versus "did I specify", use it.

If not, a neutral form is acceptable:

```text
The stored ethanol feed flow rate is 50 kmol/hr.
```

Do not over-engineer natural-language formatting.

---

# Critical behavior

After producing the field answer:

```python
return formatted_state_query_answer
```

Do NOT append:

- missing Design Option inputs;
- other stored variables;
- requests for already-known information;
- workflow guidance;
- "let me know if...";
- suggestions to proceed;
- generic chemical-engineering requirements.

The user asked a narrow question. Answer the narrow question.

---

# Preserve pending workflow state

A state-query interruption must NOT erase the existing `pending_request`.

Example:

```text
Assistant:
Should the design use the optimum feed plate?

User:
Before I answer that, what is the feed temperature?

Assistant:
The feed temperature is 355 K.
```

Internally, the existing optimum-feed-plate pending request should remain active.

Therefore, if the user's NEXT message is an appropriate short reply such as:

```text
yes
```

the existing pending-request resolver should still be able to resolve it.

Do not require the assistant to repeat the pending question after every state lookup.

Conversation output and workflow state should remain separate.

---

# Tests

Set up state:

```text
Water = 50 kmol/hr
Ethanol = 50 kmol/hr
T = 355 K
P = 101325 Pa
boilup ratio = 2
xB = 0.1
xD = 0.9
```

Test:

```text
What is the feed flow rate of ethanol?
```

Expected exactly or semantically:

```text
The ethanol feed flow rate is 50 kmol/hr.
```

Must NOT ask for Water flow.

---

Test:

```text
What is the temperature of the feed?
```

Expected:

```text
The feed temperature is 355 K.
```

Must NOT request feed composition, reflux ratio, product flows, recoveries, or Design Option information.

---

Test:

```text
What is the pressure?
```

Expected:

```text
The specified pressure is 101325 Pa.
```

No extra advice.

---

Test:

```text
What is the boilup ratio?
```

Expected:

```text
The boilup ratio is 2.
```

No extra advice.

---

Test unknown field:

```text
What is Lr?
```

when Lr has not been specified.

Expected:

```text
Lr has not been specified yet.
```

No Design Option dump.

---

# Pending-request continuity regression

Create a state where:

```python
pending_request.field == "use_optimum_feed_plate"
```

Then ask:

```text
Before I answer that, what is the temperature?
```

Expected response:

```text
The feed temperature is 355 K.
```

Verify internally that the optimum-feed-plate pending request remains active.

Then send:

```text
yes
```

Verify that it resolves the pending optimum-feed-plate request correctly.

---

# Do not change in this task

Do NOT modify:

- BioSTEAM calculations;
- feed-screen readiness;
- Design Option definitions;
- Design Option calculation logic;
- WRITE-first routing;
- phase routing;
- 313.15 K conditioning;
- calculation result presentation yet;
- model-facing full-state projection yet.

This task only closes the simple stored-field-query response path.

---

# Report back

Report:

1. exact files changed;
2. where the deterministic formatter lives;
3. where the early/terminal return occurs;
4. whether state-query results are still sent to Qwen;
5. how missing fields are formatted;
6. whether pending requests survive an intervening state query;
7. focused test results;
8. full `tools/chopper` test results.