# Binary Distillation Model Context

## Purpose

This context file defines the input and output information required when **binary distillation** is considered by the separations decision-support system.

The intent is to distinguish:

1. information that must be known for a binary distillation problem;
2. valid combinations of additional design specifications;
3. variables that should be calculated by the deterministic engineering layer; and
4. quantities that should not be silently assumed by the LLM.

## Source

The engineering specification framework in this document is based on:

**Wankat, Phillip C. _Separation Process Engineering: Includes Mass Transfer Analysis_. Pearson, 2022.**

In particular:

- **Table 3-1 — Usual specified variables for binary distillation**
- **Table 3-2 — Specifications and calculated variables for binary distillation for design problems**

The terminology and Case A–D organization below are retained from these tables.

---

## 0. Scope: Binary Feeds Only, For Now

The `chopper` toolkit (`tools/chopper/`) currently supports **strictly
binary feeds only** — a feed must have exactly 2 components with nonzero
flow. This is enforced in code: `separation_trial.check_binary_feed()`
raises `ValueError` for any feed with 3 or more nonzero-flow components,
and every entry point in the toolkit (`run_separation`,
`sweep_reflux_ratio`, `optimize_reflux_ratio`, the `optimize_separation`
LLM tool, and the merged `separation_rag_agent.py`) goes through that
check before building a column.

**Ternary and multicomponent feeds are explicitly out of scope for now.**
Supporting them — including a real key-selection/distributed-component
model beyond today's `validate_key_selection()` sanity check — is planned
as a **later** extension, not something this document should be read as
already covering. Until that work happens, a 3+ component feed should be
rejected with a clear error rather than silently run through the
LHK-based shortcut method as if it were properly handled.

---

## 1. Essential Inputs for Binary Distillation

According to **Wankat (2022), Table 3-1**, the usual specified variables for binary distillation are:

1. **Column pressure**
2. **Feed flow rate**
3. **Feed composition**
4. **Feed temperature or enthalpy or quality**
5. **Reflux temperature or enthalpy** — usually saturated liquid

These five variables form the essential input layer for a binary distillation problem.

### Modeling implication

The separations assistant should determine whether these variables are known before proceeding with detailed binary-distillation design.

The feed thermal condition should therefore be represented explicitly through a supplied **temperature, enthalpy, or quality**, rather than silently assuming that the feed is at its bubble point.

Likewise, the reflux thermal condition should be represented explicitly. Saturated-liquid reflux is usual according to the source, but this should be treated as an identified condition or stated assumption rather than an invisible LLM assumption.

---

## 2. Additional Design Specifications

Beyond the five usual specified variables in Table 3-1, **four additional specifications must be known** for the binary-distillation design problem.

Wankat (2022), **Table 3-2**, organizes the valid specification sets into Cases A–D.

### Case A — Distillate and Bottoms Compositions

#### Specified variables

1. Mole fraction of the more volatile component in the distillate, **xD**
2. Mole fraction of the more volatile component in the bottoms, **xB**
3. External reflux ratio, **L0/D**
4. Use optimum feed plate

#### Designer calculates

- Distillate flow rate, **D**
- Bottoms flow rate, **B**
- Heating load, **QR**
- Cooling load, **Qc**
- Number of stages, **N**
- Optimum feed plate
- Column diameter

---

### Case B — Component Recoveries

#### Specified variables

1–2. Fractional recoveries of components in the distillate and bottoms, **(FrA)dist** and **(FrB)bot**

3. External reflux ratio, **L0/D**

4. Use optimum feed plate

#### Designer calculates

- **xB**
- **xD**
- **D**
- **B**
- **QR**
- **Qc**
- **N**
- **Nfeed**
- Column diameter

---

### Case C — Product Flow Rate and Composition

#### Specified variables

1. **D or B**
2. **xD or xB**
3. External reflux ratio, **L0/D**
4. Use optimum feed plate

#### Designer calculates

- **B or D**, whichever was not specified
- **xB or xD**, whichever was not specified
- **QR**
- **Qc**
- **N**
- **Nfeed**
- Column diameter

---

### Case D — Product Compositions and Boilup Ratio

#### Specified variables

1–2. **xD and xB**

3. Boilup ratio, **V/B**

4. Use optimum feed plate

#### Designer calculates

- **D**
- **B**
- **QR**
- **Qc**
- **N**
- **Nfeed**
- Column diameter

---

## 3. Conceptual Input Structure for the Separations Assistant

The binary-distillation input problem can therefore be represented conceptually as:

```text
Binary Distillation Problem
│
├── Essential specifications — Wankat Table 3-1
│   ├── Column pressure
│   ├── Feed flow rate
│   ├── Feed composition
│   ├── Feed thermal condition
│   │   └── temperature OR enthalpy OR quality
│   └── Reflux thermal condition
│       └── temperature OR enthalpy
│
└── Design specifications — Wankat Table 3-2
    │
    ├── Case A
    │   ├── xD
    │   ├── xB
    │   ├── L0/D
    │   └── optimum feed plate
    │
    ├── Case B
    │   ├── fractional recovery in distillate
    │   ├── fractional recovery in bottoms
    │   ├── L0/D
    │   └── optimum feed plate
    │
    ├── Case C
    │   ├── D OR B
    │   ├── xD OR xB
    │   ├── L0/D
    │   └── optimum feed plate
    │
    └── Case D
        ├── xD
        ├── xB
        ├── V/B
        └── optimum feed plate
```

---

## 4. Important Distinction: User Specifications vs. Internal Model Parameters

The user-facing engineering specification should remain distinct from paramee\ters used internally by a particular simulator.

For example, Wankat Table 3-2 specifies the **external reflux ratio L0/D** for Cases A–C.

The existing BioSTEAM `chopper` prototype instead commonly uses a reflux-ratio multiplier:

```text
k = actual reflux ratio / minimum reflux ratio
```

or:

```text
k = R / Rmin
```

These quantities must not be treated as equivalent.

The system should distinguish explicitly between:

- **external/actual reflux ratio, L0/D or R**
- **minimum reflux ratio, Rmin**
- **reflux-ratio multiplier, k = R/Rmin**

A user specifying an actual reflux ratio is providing different information from a user specifying a multiplier of minimum reflux.

---

## 5. Implications for the Current Binary-Distillation Tool

The existing prototype should eventually be expanded so that its input schema reflects the engineering problem definition rather than forcing every problem into only a purity/recovery interface.

### Current prototype behavior to revisit

The current `optimize_separation()` workflow constructs the feed and sets it to its bubble point. This effectively imposes a saturated-liquid feed condition.

Under the Wankat Table 3-1 framework, **feed temperature, enthalpy, or quality is an essential specified variable**. The final tool should therefore not silently impose a bubble-point feed when the user's actual feed condition is unknown.

The existing prototype is also primarily organized around:

- purity specifications;
- recovery specifications; and
- a sweep over `k = R/Rmin`.

Those capabilities map most naturally onto portions of Cases A and B, but they do not yet represent the full Case A–D specification framework.

---

## 6. Recommended Problem-Definition Logic

Before running a binary-distillation design calculation, the system should perform a structured input check.

### Step 1 — Check Table 3-1 information

Determine whether the following are known:

```text
column pressure
feed flow rate
feed composition
feed temperature OR enthalpy OR quality
reflux temperature OR enthalpy
```

### Step 2 — Identify the Table 3-2 design case

Determine whether the remaining specifications correspond to:

```text
Case A
xD + xB + external reflux ratio + optimum feed plate

Case B
fractional recoveries + external reflux ratio + optimum feed plate

Case C
D or B + xD or xB + external reflux ratio + optimum feed plate

Case D
xD + xB + boilup ratio + optimum feed plate
```

### Step 3 — Check completeness

Do not proceed merely because some separation target was supplied.

The system should determine whether the combination of specifications constitutes one of the recognized design cases.

### Step 4 — Request genuinely missing information

If required information is absent, the LLM should identify the missing variable rather than silently inventing a value.

### Step 5 — Pass the complete problem to the deterministic engineering layer

Once the problem is sufficiently specified, Python/BioSTEAM or another deterministic calculation layer should calculate the remaining design variables.

---

## 7. Expected Binary-Distillation Outputs

Across the four design cases, the quantities calculated by the designer include combinations of:

- Distillate flow rate, **D**
- Bottoms flow rate, **B**
- Distillate composition, **xD**
- Bottoms composition, **xB**
- Reboiler/heating load, **QR**
- Condenser/cooling load, **Qc**
- Number of stages, **N**
- Optimum feed plate / **Nfeed**
- Column diameter

Which of these are outputs depends on which variables were supplied as inputs under Cases A–D.

Therefore, the tool should not rigidly classify every one of these variables as either always an input or always an output. Their role depends on the selected specification case.

---

## 8. Role of the LLM

For this part of the separations assistant, the LLM should primarily:

1. extract the binary-distillation problem from natural language;
2. identify the Table 3-1 variables supplied by the user;
3. determine which Table 3-2 specification case the request matches;
4. identify missing required information;
5. distinguish actual reflux ratio from `R/Rmin`;
6. construct a structured input for the deterministic calculation tool; and
7. explain the calculated results.

The LLM should **not silently complete an underspecified distillation problem using unstated engineering assumptions**.

---

## 9. Provenance

The specification framework documented here comes from:

**Wankat, Phillip C. _Separation Process Engineering: Includes Mass Transfer Analysis_. Pearson, 2022.**

Specifically:

- **Table 3-1:** *Usual specified variables for binary distillation*
- **Table 3-2:** *Specifications and calculated variables for binary distillation for design problems*

This provenance should be retained if the information is later incorporated into the separations knowledge base, decision engine, prompt context, or binary-distillation tool documentation.

---

## 10. Implementation Status

The structured input-check procedure in section 6 above is implemented in
`tools/chopper/problem_spec.py`:

- **Step 1** (Table 3-1 essentials) → `check_essential_inputs()`. The feed
  thermal condition and reflux condition are both required as explicit
  fields (`feed_temperature_K`/`feed_quality`/`feed_enthalpy_kJ_per_hr`,
  and `reflux_condition`) with no default value anywhere in the code path
  — see `tools/chopper/separation_tool.py`, which no longer calls
  `feed.bubble_point_at_P()` on the caller's behalf.
- **Steps 2-3** (Table 3-2 case identification + completeness) →
  `identify_case()`. When the caller has given none of Case A/B/C/D's
  distinguishing fields (compositions, recoveries, a product flow, a
  boilup ratio), `identify_case()` returns every case still consistent
  (`case=None`, `candidates` = every case whose own fields aren't yet
  contradicted — typically all four) rather than defaulting to Case A; see
  `tools/binary-distillation-workflow.md` section 7. It narrows to
  whichever case the caller's fields actually indicate as soon as
  something case-specific is given.
- **Step 4** (request missing information, never invent it) →
  `validate_problem()`'s `message`/`missing_essential_inputs`/
  `case_candidates`/`missing_case_inputs_by_candidate`/`ambiguous_reason`
  fields, surfaced by `separation_tool.py`'s `design_separation_case()`
  and `optimize_separation()` and relayed to the user via each agent's
  `SYSTEM_PROMPT`. Because an LLM tool-calling loop (particularly a small
  local model) cannot be relied on to restate the full problem on every
  follow-up call, `separation_tool.py` also accumulates whatever fields
  have been given across calls in a session-scoped `_spec_state` dict and
  validates against that accumulated state, rather than requiring the
  caller to resupply everything already established every time.
- **Step 5** (pass to the deterministic engineering layer) →
  `tools/chopper/case_design.py`'s `design_binary_distillation()`, which
  also handles distinguishing external reflux ratio (L0/D) from the
  internal shortcut-method multiplier `k` (section 4 above) by measuring
  the column's actual minimum reflux ratio when L0/D is given. Only Cases
  A and B are executable by the current BioSTEAM shortcut engineering
  layer; Cases C and D are correctly identified but reported as
  recognized-but-not-yet-implemented (see section 5 above), since the
  shortcut column has no way to accept a direct product-flow-rate or
  boilup-ratio specification as an input.

See `tools/separation_tool.md` for the full function-level reference.

**Workflow-only checker layer (`tools/binary-distillation-workflow.md`):**
`tools/chopper/binary_distillation_workflow.py`'s
`assess_binary_distillation_problem()` wraps `check_essential_inputs()` and
`identify_case()` above with the component-count scope gate (section 2 of
that doc), the optimum-feed-plate confirmation gate (section 12), and a
`would_calculate` report — all without ever building a feed stream or
calling BioSTEAM. `tools/chopper/binary_distillation_workflow_agent.py` is
an isolated tool-calling agent (Option C, section 18) exposing only that
one function to the model; it does not import `separation_tool.py`,
`case_design.py`, `optimizer.py`, or BioSTEAM at all, so no distillation
calculation can happen through it. **Test this agent, not
`separation_agent.py`/`separation_rag_agent.py`, when checking
problem-definition/case-routing behavior specifically** — the other two
still perform real BioSTEAM sizing once a spec is complete. See
`tools/separation_tool.md`'s "Which agent to test against" table for the
full comparison.
