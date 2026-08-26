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

The user-facing engineering specification should remain distinct from parameters used internally by a particular simulator.

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
