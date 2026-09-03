# Multicomponent Distillation Model Context

## Purpose

This context file defines the input/output information, domain vocabulary,
and rules that govern **multicomponent distillation** (3+ nonzero-flow
components) work in this repo. It is the sibling document to
`tools/binary-distillation-context.md`, which governs the existing binary
(`tools/chopper/`) toolkit and is strictly out of scope for 3+ component
feeds by design (`check_binary_feed()` rejects them).

Nothing described here is implemented yet. `tools/chopper/multicomponent_distillation_agent.py`
is currently a bare Ollama chat stub (`TOOLS = []`, `TOOL_FUNCTIONS = {}`) —
it can talk, but it cannot design or size anything. This document exists so
that when tools and an engineering layer are eventually added to that
agent, the scope, vocabulary, and rules are already settled rather than
invented ad hoc mid-implementation — both for whoever writes that code and
for the model calling the eventual tools.

---

## 0. Scope: What "Multicomponent" Means Here

A feed with **3 or more nonzero-flow components**. The binary chopper
toolkit's `check_binary_feed()` gate exists specifically to keep such feeds
out of the binary tools; this agent is the intended home for them instead.

Multicomponent distillation introduces one problem that binary distillation
does not have at all: **which two components are the light key and heavy
key**, and whether any other component is "distributed" between them. See
section 2 below — this is the central new decision the model must never
make silently.

---

## 1. Relationship to the Binary Chopper Toolkit

### Inherited concepts (carry over unchanged)

- **Wankat (2022) Table 3-1 essential-inputs discipline** — column
  pressure, feed flow rate, feed composition, feed thermal condition
  (temperature OR enthalpy OR quality, never defaulted to bubble point),
  and reflux thermal condition (saturated liquid is usual but must be
  stated, never assumed). See `binary-distillation-context.md` section 1.
  Feed composition is simply n-dimensional now instead of a single mole
  fraction pair.
- **`k` vs. external reflux ratio (`L0/D`) terminology** —
  `k = actual_reflux_ratio_LD / minimum_reflux_ratio_LD`. These are not the
  same quantity and must never be conflated. See
  `binary-distillation-context.md` section 4.
- **`validate_key_selection()`** (`tools/chopper/optimizer.py`) — currently
  described in `tools/separation_tool.md` as "dormant in practice" for the
  binary toolkit, since `check_binary_feed()` never lets it see a feed with
  a distributed component. This new agent is exactly the place where that
  function stops being dormant: every LHK choice on a genuinely
  multicomponent feed must be checked with it (or an equivalent) before a
  design is attempted.
- **The general shape of the layered toolkit** — trial/single-run →
  sweep → economics → best-design → optimizer, one file per layer (see
  `tools/separation_tool.md`'s "Hierarchy" section). New multicomponent
  modules should mirror this pattern rather than growing one large file,
  unless there's a concrete reason not to.

### NOT inherited

- `check_binary_feed()`'s hard 2-component gate. The entire point of this
  agent is feeds that gate rejects.
- Wankat's Case A-D framework (Table 3-2) as a literal binary-only artifact
  — but see section 4 below: its vocabulary (composition-basis vs.
  recovery-basis specification) maps directly onto the multicomponent
  shortcut column's own two specification modes, so it is more "renamed"
  than "discarded."

---

## 2. Key Domain Concept: Light Key, Heavy Key, and Distributed Components

In a binary feed there is no choice to make — the two components *are* the
light key (LK) and heavy key (HK). In a multicomponent feed, the LK and HK
are a **choice**, and that choice determines whether the shortcut
(Fenske-Underwood-Gilliland, "FUG") method gives a meaningful answer at
all:

- Every feed component **lighter** than the LK is assumed to end up
  entirely in the distillate.
- Every feed component **heavier** than the HK is assumed to end up
  entirely in the bottoms.
- A component whose volatility falls **between** the LK and HK is a
  **distributed component** — the FUG shortcut method cannot resolve how it
  splits, because the method's sharp-split assumption is only valid for the
  two keys and everything strictly outside them.

`validate_key_selection(feed, LHK)` (see `tools/separation_tool.md`'s
`optimizer.py` section) already implements this check by comparing normal
boiling points (`chemicals[ID].Tb`) — any feed component whose `Tb` falls
strictly between the LK's and HK's is flagged as `distributed`, and the
function returns `valid=False` with a `warning` naming the offending
component(s). **This agent must run that check (or equivalent) on every
LHK choice before attempting a design**, and must never pick LK/HK on the
user's behalf — see the rules in section 6.

---

## 3. The Underlying Engineering Layer: `biosteam.units.ShortcutColumn`

BioSTEAM already ships a multicomponent counterpart to the
`BinaryDistillation` unit the existing chopper toolkit wraps:
`biosteam.units.distillation.ShortcutColumn`. It implements the same
Fenske-Underwood-Gilliland shortcut method, generalized to N≥2 components,
and is the natural drop-in engineering layer for this agent — analogous to
how `separation_trial.run_separation()` wraps `BinaryDistillation` today.

**Constructor parameters** (from the installed BioSTEAM source,
`biosteam/units/distillation.py`):

| Parameter | Meaning |
|---|---|
| `LHK` | `(light_key, heavy_key)` — same meaning as the binary toolkit. |
| `y_top` | Mole fraction of the light key, relative to LK+HK only, in the distillate. |
| `x_bot` | Mole fraction of the light key, relative to LK+HK only, in the bottoms. |
| `Lr` | Recovery of the light key to the distillate. |
| `Hr` | Recovery of the heavy key to the bottoms. |
| `k` | Ratio of actual reflux to minimum reflux — same `k = R/Rmin` as the binary toolkit. |
| `Rmin` | Optional user-enforced floor on minimum reflux (default 0.6); the computed minimum is used unless it's below this floor. |
| `specification` | `'Composition'` (use `y_top`/`x_bot`) or `'Recovery'` (use `Lr`/`Hr`) — mirrors `spec='purity'`/`spec='recovery'` in `separation_trial.run_separation()`. |
| `P` | Operating pressure, Pa. |
| `is_divided` | Same meaning as in the binary toolkit. |
| `vessel_material`, `tray_material`, `tray_type`, `tray_spacing`, `stage_efficiency`, `velocity_fraction`, `foaming_factor`, `open_tray_area`, `downcomer_area_fraction` | Costing/design knobs, same role as `BinaryDistillation`'s. |

**What actually differs from the binary shortcut method internally** —
the FUG helper functions in the same module
(`compute_minimum_theoretical_stages_Fenske`,
`objective_function_Underwood_constant` /
`compute_minimum_reflux_ratio_Underwood`, `compute_theoretical_stages_Gilliland`,
`compute_feed_stage_Kirkbride`) generalize each binary step:

- **Fenske** (minimum stages, total reflux) is computed from the LK/HK
  split alone, same as binary.
- **Underwood** (minimum reflux) requires solving for a constant `theta`
  by root-finding across **every** component's relative volatility and
  feed composition, not just the two keys — this is the genuinely new step
  multicomponent feeds require, and it's why non-key components' identity
  and composition matter even though they're not "in" the LK/HK spec.
- **Gilliland** (actual stages from `R`/`Rmin`) is the same correlation as
  binary.
- **Kirkbride** (optimum feed stage) is a correlation over the LK/HK split
  and component flows — the multicomponent analog of the binary feed-stage
  placement; it replaces "optimum feed plate" as a design output rather
  than a spec.

**Rigorous alternatives exist in the same module** if shortcut-method
accuracy is ever insufficient: `MESHDistillation` (converges the full
Mass/Equilibrium/Summation/Enthalpy stage-by-stage equations; takes
`N_stages`, `feed_stages`, `reflux`, `boilup` directly rather than `k`) and
`AdiabaticMultiStageVLEColumn`. These are **not** in scope for this agent's
first implementation — `ShortcutColumn` is the direct analog of what the
binary toolkit already does and should be the starting point.

---

## 4. Essential Inputs (Table 3-1 Analog, Multicomponent)

Same five categories as binary (`binary-distillation-context.md` section
1), with composition and key selection now genuinely multi-way:

1. **Column pressure.**
2. **Full feed flow rate and composition** — every component with nonzero
   flow, not just two.
3. **Feed thermal condition** — temperature OR enthalpy OR quality,
   explicitly stated, never defaulted to bubble point.
4. **Reflux thermal condition** — same "state it, don't assume it" rule as
   binary; saturated liquid is usual but must be confirmed.
5. **Light key and heavy key** — new relative to binary, where this choice
   is forced by there being exactly two components. Here it is a genuine
   engineering decision that must be explicitly stated (or explicitly
   confirmed if proposed) and validated for distributed components
   (section 2) before any design proceeds.

## 5. Design Specification (Table 3-2 Analog / `ShortcutColumn` Modes)

`ShortcutColumn`'s two `specification` modes map directly onto Wankat's
binary Cases A and B:

- **Composition-basis** (`y_top`/`x_bot` + external reflux ratio + optimum
  feed plate implicit via Kirkbride) — analog of **Case A**.
- **Recovery-basis** (`Lr`/`Hr` + external reflux ratio) — analog of
  **Case B**.

**Cases C and D have no analog here either**, for the same reason they
aren't executable in the binary toolkit today
(`tools/chopper/case_design.py`, `IMPLEMENTED_CASES = ('A', 'B')`):
`ShortcutColumn` has no constructor parameter for a direct product-flow-rate
spec or a boilup-ratio spec, just like `BinaryDistillation`. If this ever
changes, it should be re-derived from BioSTEAM's actual API, not assumed.

---

## 6. Rules the Model/Tool Layer Must Obey

These apply once tools exist on `multicomponent_distillation_agent.py` —
they are written now so implementation doesn't have to relitigate them:

1. **Never treat a 3+ component feed as binary, and never silently drop a
   component** to force it through the binary toolkit instead. If a user's
   request turns out to be genuinely binary, that's `separation_agent.py`'s
   job, not this agent's.
2. **Never pick LK/HK on the user's behalf.** If not stated, ask. If
   stated, validate adjacency (section 2) before proceeding, and report any
   distributed component found rather than silently running the design
   anyway or silently dropping/reassigning the offending component.
3. **Never silently assume feed thermal condition or reflux condition** —
   same rule as binary (`binary-distillation-context.md` section 1/6).
4. **Distinguish external reflux ratio (`L0/D`) from the internal
   multiplier `k`** — same rule as binary (`binary-distillation-context.md`
   section 4); never convert one to the other without measuring the
   column's actual minimum reflux first.
5. **No functionality is implemented yet.** Until real tools are wired into
   `multicomponent_distillation_agent.py`, it must say so plainly if asked
   to design or size a separation, rather than attempting one.
6. **New multicomponent modules should mirror the existing chopper
   layering** (single-run trial → sweep → economics → best-design →
   optimizer, one concern per file) rather than being bolted directly onto
   the binary files.

---

## 7. Implementation Status

- `tools/chopper/multicomponent_distillation_agent.py` — bare Ollama
  chat-loop stub, `TOOLS = []`, `TOOL_FUNCTIONS = {}`. No engineering
  layer, no `ShortcutColumn` wrapper, nothing beyond plain chat.
- No `multicomponent_*` engineering modules exist yet anywhere in
  `tools/chopper/`.
- This document should be kept up to date as multicomponent modules are
  built, the same way `binary-distillation-context.md` section 10 tracks
  the binary toolkit's implementation status against this file's earlier
  sections.

---

## 8. Provenance

- **Wankat, Phillip C. _Separation Process Engineering: Includes Mass
  Transfer Analysis_. Pearson, 2022.** — same source as the binary
  toolkit's Table 3-1/3-2 framework (section 1 above inherits from it
  directly). Wankat's own treatment of multicomponent shortcut design
  (key selection, FUG) has not been re-transcribed into specific
  table/section numbers here and should be verified against the text
  directly before being cited as such in code or docs.
- **BioSTEAM `distillation.py` module references** (see
  `biosteam/units/distillation.py`, module docstring), which
  `ShortcutColumn`'s design/costing correlations draw on:
  1. J.D. Seader, E.J. Henley, D.K. Roper (2011). *Separation Process
     Principles*, 3rd ed. John Wiley & Sons.
  2. M. Duss, R. Taylor (2018). *Predict Distillation Tray Efficiency*.
     AIChE.
  3. Green, D.W. *Distillation*. In *Perry's Chemical Engineers' Handbook*,
     9th ed. McGraw-Hill Education, 2018.
  4. Seider, W.D., Lewin, D.R., Seader, J.D., Widagdo, S., Gani, R., & Ng,
     M.K. (2017). *Product and Process Design Principles*. Wiley. (Chapter
     16, Cost Accounting and Capital Cost Estimation.)

This provenance should be retained if any of this document's content is
later incorporated into multicomponent tool code, prompts, or
documentation — same convention as `binary-distillation-context.md`
section 9.
