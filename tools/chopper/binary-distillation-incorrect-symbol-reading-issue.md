I want you to fix a presentation-grounding problem in the binary-distillation assistant.

The immediate symptom is that Qwen incorrectly interprets:

```text
QR
```

as:

```text
reflux flow rate
```

even though in this workflow it means:

```text
reboiler duty
```

The broader issue is that the deterministic tool currently returns bare engineering symbols such as:

```python
["D", "B", "QR", "Qc", "N", "Nfeed (optimum feed stage)", "column diameter"]
```

and Qwen then expands those symbols using its own model knowledge.

That must stop.

The architecture should make deterministic Python the authoritative source not only for case selection and routing, but also for engineering labels and meanings.

Do NOT solve this by only adding a prompt sentence saying:

```text
QR means reboiler duty
```

That would patch one symptom while leaving Qwen free to reinterpret other symbols later.

---

# Goal

Change the deterministic output so engineering quantities are returned with explicit semantic metadata.

Instead of:

```python
"would_calculate": [
    "D",
    "B",
    "QR",
    "Qc",
    "N",
    "Nfeed (optimum feed stage)",
    "column diameter",
]
```

return structured data conceptually like:

```python
"would_calculate": [
    {
        "field": "distillate_flow",
        "symbol": "D",
        "label": "distillate flow rate",
    },
    {
        "field": "bottoms_flow",
        "symbol": "B",
        "label": "bottoms flow rate",
    },
    {
        "field": "reboiler_duty",
        "symbol": "QR",
        "label": "reboiler duty",
    },
    {
        "field": "condenser_duty",
        "symbol": "Qc",
        "label": "condenser duty",
    },
    {
        "field": "number_of_stages",
        "symbol": "N",
        "label": "number of stages",
    },
    {
        "field": "optimum_feed_stage",
        "symbol": "Nfeed",
        "label": "optimum feed stage",
    },
    {
        "field": "column_diameter",
        "symbol": None,
        "label": "column diameter",
    },
]
```

Use names consistent with the existing codebase.

The exact schema may differ, but the meaning must be deterministic and explicit.

---

# Step 1 — Inspect every place where engineering symbols are defined or rendered

Before changing anything, inspect:

- `tools/chopper/binary_distillation_workflow.py`
- `tools/chopper/binary_distillation_workflow_agent.py`
- case-definition structures
- any Wankat case metadata
- anywhere `would_calculate` is constructed
- anywhere `D`, `B`, `QR`, `Qc`, `N`, or `Nfeed` are converted into natural-language descriptions
- tests that assert `would_calculate`
- prompt/tool docstrings that mention these quantities

Search specifically for:

```text
would_calculate
QR
Qc
Nfeed
reflux flow
reboiler duty
condenser duty
```

Determine whether the semantic meaning already exists somewhere in deterministic Python.

If it already exists, reuse that source rather than duplicating definitions.

---

# Step 2 — Establish one authoritative engineering quantity registry

Create or reuse a single deterministic mapping for supported binary-distillation quantities.

Conceptually:

```python
BINARY_DISTILLATION_QUANTITIES = {
    "D": {
        "field": "distillate_flow",
        "symbol": "D",
        "label": "distillate flow rate",
    },
    "B": {
        "field": "bottoms_flow",
        "symbol": "B",
        "label": "bottoms flow rate",
    },
    "QR": {
        "field": "reboiler_duty",
        "symbol": "QR",
        "label": "reboiler duty",
    },
    "Qc": {
        "field": "condenser_duty",
        "symbol": "Qc",
        "label": "condenser duty",
    },
    "N": {
        "field": "number_of_stages",
        "symbol": "N",
        "label": "number of stages",
    },
    "Nfeed": {
        "field": "optimum_feed_stage",
        "symbol": "Nfeed",
        "label": "optimum feed stage",
    },
    "column_diameter": {
        "field": "column_diameter",
        "symbol": None,
        "label": "column diameter",
    },
}
```

Use terminology already established by the project's Wankat implementation.

Do not ask Qwen to define any of these fields.

Do not duplicate the same symbol-to-meaning mapping independently in multiple modules.

---

# Step 3 — Verify the authoritative meaning against the existing project source

Before finalizing the registry, inspect the existing Wankat-derived case definitions and current project documentation.

The registry must reflect the meaning already used by this project.

For the currently observed issue, verify that:

```text
QR = reboiler duty
Qc = condenser duty
```

according to the existing deterministic/project source.

Do not change notation based on generic model knowledge.

If the project source uses a more precise term such as:

```text
reboiler heat duty
```

then use that exact terminology consistently.

---

# Step 4 — Refactor `would_calculate` to use structured metadata

Replace bare strings with structured quantity objects.

Current:

```python
"would_calculate": [
    "D",
    "B",
    "QR",
    "Qc",
    "N",
    "Nfeed (optimum feed stage)",
    "column diameter",
]
```

Target:

```python
"would_calculate": [
    {
        "field": "distillate_flow",
        "symbol": "D",
        "label": "distillate flow rate",
    },
    ...
]
```

The deterministic tool result should now contain everything Qwen needs to present the quantity correctly.

Qwen must not have to infer:

```text
what does QR mean?
what does Qc mean?
what does N mean?
```

---

# Step 5 — Keep Wankat case definitions separate from labels

Case logic should continue to determine WHICH quantities are calculated.

Example:

```python
Case A -> D, B, QR, Qc, N, Nfeed, column diameter
```

The quantity registry should determine WHAT those quantities mean.

Conceptually:

```python
case_output_keys = [
    "D",
    "B",
    "QR",
    "Qc",
    "N",
    "Nfeed",
    "column_diameter",
]

would_calculate = [
    quantity_metadata[key]
    for key in case_output_keys
]
```

This keeps engineering case logic and display semantics cleanly separated.

---

# Step 6 — Update deterministic messages to use the same registry

If Python constructs messages such as:

```text
A full Case A design would also calculate: D, B, QR, Qc, N...
```

do not independently hard-code descriptions elsewhere.

Generate display wording from the same metadata if practical.

For example:

```text
D (distillate flow rate)
B (bottoms flow rate)
QR (reboiler duty)
Qc (condenser duty)
N (number of stages)
Nfeed (optimum feed stage)
column diameter
```

The deterministic raw result and deterministic message must agree.

---

# Step 7 — Update Qwen instructions: render, do not reinterpret

Add a concise rule to the agent prompt:

```text
ENGINEERING OUTPUT GROUNDING RULE

When a deterministic tool returns a quantity with explicit symbol and label,
use the returned label exactly for its engineering meaning.

Do not expand, reinterpret, rename, or redefine engineering symbols from
your own knowledge.

Example:
if the tool returns:
symbol="QR", label="reboiler duty"
then describe QR only as reboiler duty.

Never substitute another interpretation such as "reflux flow rate".
```

This is a secondary defense.

The primary fix must remain structured deterministic metadata.

---

# Step 8 — Tell Qwen not to enrich bare symbols

For backward compatibility, add a rule for any remaining old-style string output:

```text
If a tool returns a bare engineering symbol without a supplied definition,
do not invent a definition.

You may repeat the symbol as returned, but do not explain its meaning unless
the deterministic tool explicitly supplies that meaning.
```

Example:

If Python somehow returns:

```python
"would_calculate": ["QR"]
```

Qwen should say:

```text
QR
```

not:

```text
QR (reflux flow rate)
```

This prevents unsupported semantic enrichment.

---

# Step 9 — Consider backward compatibility carefully

Changing:

```python
would_calculate: list[str]
```

to:

```python
would_calculate: list[dict]
```

may affect existing tests or code.

Inspect all consumers first.

If a direct schema change creates excessive churn, introduce a compatibility field temporarily, for example:

```python
"would_calculate": ["D", "B", "QR", ...],
"would_calculate_details": [
    {...},
    {...},
]
```

Then migrate the agent to consume:

```python
would_calculate_details
```

Prefer the cleaner structured representation if existing code can be safely updated.

Do not break downstream logic merely for presentation.

---

# Step 10 — Use stable machine-readable fields

Do not rely only on natural-language labels.

Each quantity should ideally contain:

```python
{
    "field": "...",
    "symbol": "...",
    "label": "...",
}
```

The `field` value should be stable for Python logic.

The `symbol` is the engineering notation.

The `label` is the authoritative human-readable meaning.

This makes it possible later to add:

```python
"units": ...
"description": ...
"source": ...
```

without changing the basic architecture.

---

# Step 11 — Do not hard-code units prematurely

Only include units in the metadata if they are already deterministic and correct in the current architecture.

For example, reboiler duty may eventually have units such as:

```text
kJ/hr
```

but if units are not yet standardized, do not add guessed units just to improve presentation.

The current issue is semantic meaning, not unit implementation.

---

# Step 12 — Add a direct Case A regression test

Construct a fully specified Case A.

For example:

```python
xD = 0.9
xB = 0.1
external_reflux_ratio_LD = 2
use_optimum_feed_plate = True
```

Verify the deterministic result includes an entry where:

```python
symbol == "QR"
label == "reboiler duty"
```

and:

```python
symbol == "Qc"
label == "condenser duty"
```

The test should fail if QR is ever labeled:

```text
reflux flow rate
```

---

# Step 13 — Add tests for every currently supported output quantity

Test all mappings, not only QR.

At minimum verify:

```text
D -> distillate flow rate
B -> bottoms flow rate
QR -> reboiler duty
Qc -> condenser duty
N -> number of stages
Nfeed -> optimum feed stage
column diameter -> column diameter
```

Use the project's exact preferred terminology.

This prevents the same problem from reappearing with another symbol.

---

# Step 14 — Add case-specific output tests

Verify each Wankat case returns the correct structured output set.

For example:

```text
Case A
Case B
Case C
Case D
```

should each return their existing expected output quantities, but now with deterministic metadata.

Do NOT modify which quantities belong to each case in this task unless you discover an existing deterministic bug.

This task is about representation, not case-definition logic.

---

# Step 15 — Add an agent-level anti-hallucination test

Script a tool result that contains:

```python
{
    "would_calculate": [
        {
            "field": "reboiler_duty",
            "symbol": "QR",
            "label": "reboiler duty",
        }
    ]
}
```

Then verify the assistant response contains:

```text
QR
reboiler duty
```

and does NOT contain:

```text
reflux flow rate
```

If exact natural-language response testing is brittle, assert the prohibited phrase is absent.

---

# Step 16 — Add a bare-symbol fallback test

Script a legacy tool result:

```python
{
    "would_calculate": ["QR"]
}
```

Verify Qwen is instructed to return something conceptually like:

```text
QR
```

rather than invent:

```text
QR (reflux flow rate)
```

This protects against partially migrated code paths.

---

# Step 17 — Check other deterministic fields for the same pattern

While implementing, inspect whether Qwen is currently asked to infer meanings for other compact codes such as:

```text
Lr
Hr
L0/D
V/B
xD
xB
```

Do NOT broadly refactor all of them unless required.

But document any similar presentation-risk locations you discover.

If the same metadata registry can include them with minimal churn, that is acceptable.

Do not expand into a general notation-system rewrite.

---

# Step 18 — Keep source provenance attached where practical

If the existing workflow already has Wankat provenance, keep it.

Do not have Qwen claim that a definition came from Wankat unless deterministic metadata/project source actually supports it.

If useful, structured quantity metadata may eventually support:

```python
"source": "Wankat Table ..."
```

but this is optional for this task.

---

# Step 19 — Re-run the exact conversation that exposed the bug

Use the same interaction:

```text
Separate water and ethanol at 355 K and 101325 Pa ...
...
xD = 0.9, xB = 0.1, external reflux ratio = 2,
use optimum feed plate
```

The raw tool result should now expose structured meanings.

The assistant should say conceptually:

```text
A full Case A design would calculate:

D — distillate flow rate
B — bottoms flow rate
QR — reboiler duty
Qc — condenser duty
N — number of stages
Nfeed — optimum feed stage
column diameter
```

It must NOT say:

```text
QR — reflux flow rate
```

---

# Step 20 — Run focused and full tests

Run:

1. quantity-registry tests,
2. workflow tests,
3. Wankat case-output tests,
4. agent presentation tests,
5. existing temperature tests,
6. full `tools/chopper` suite.

All existing functionality should remain intact.

---

# Important architectural rule

After this change, the responsibility split should be:

```text
Python:
- decides which quantities apply
- owns engineering symbols
- owns engineering meanings
- returns structured labels

Qwen:
- organizes the returned information
- turns it into readable prose
- does NOT redefine engineering notation
```

Qwen should never need to answer internally:

```text
"What does QR probably mean?"
```

That question should already be answered by deterministic Python.

---

# Do not expand scope

Do NOT modify:

- feed-screening readiness,
- Wankat case selection logic,
- BioSTEAM calculations,
- reference-temperature routing,
- feed-temperature extraction,
- product-flow unit handling,
- downstream separator implementation,
- full column calculations.

Do not implement QR or Qc calculations yet.

This task only fixes authoritative representation and response grounding.

---

# Definition of done

This task is complete when:

1. QR's meaning is defined deterministically in Python.
2. QR is returned as `reboiler duty` using the project's preferred terminology.
3. Qc is deterministically returned as `condenser duty`.
4. All currently exposed calculation-output symbols have explicit metadata.
5. Qwen does not independently reinterpret supplied engineering symbols.
6. A legacy bare symbol is repeated without invented explanation.
7. Case A no longer produces `QR (reflux flow rate)`.
8. Existing case membership is unchanged.
9. Temperature extraction remains unchanged.
10. BioSTEAM/routing behavior remains unchanged.
11. Focused tests pass.
12. Full `tools/chopper` test suite passes.

---

# Report back

After implementation, report:

- exact files changed,
- where the authoritative quantity registry now lives,
- final schema used for quantity metadata,
- exact QR/Qc definitions,
- whether `would_calculate` itself changed or a compatibility field was added,
- all tests added/updated,
- focused test results,
- full-suite result,
- exact raw `would_calculate` output for Case A,
- exact assistant response for Case A,
- confirmation that the phrase `QR (reflux flow rate)` can no longer be produced from authoritative tool output.

Do not continue into the readiness refactor after completing this task.