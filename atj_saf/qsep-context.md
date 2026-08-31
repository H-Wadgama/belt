# `qsep.py` — context notes

`qsep.py` is a standalone sandbox script (methanol/water binary system) for
comparing BioSTEAM's shortcut `BinaryDistillation` (McCabe-Thiele) column
against the rigorous `MESHDistillation` column, and for understanding what
each one needs as input. It is not part of any production model — it's a
scratch space for building intuition before touching the real ATJ/lignin
systems. This file is the accumulated Q&A/findings from working through it.

**Version note:** every `distillation.py` line number cited below refers to the
currently pinned `biosteam==2.47.0` / `thermosteam==0.46.0` install (per
`CLAUDE.md`), i.e. `<env>/Lib/site-packages/biosteam/units/distillation.py`.
See §11 for a newer release found nearby (`dist2.py`) that changes some of
these line numbers and a few behaviors.

## What's in the script

1. **D1** — `BinaryDistillation`, given `y_top=0.90`, `x_bot=0.10`, `k=2`
   (reflux/Rmin ratio). Solves stage count, feed stage, and reflux
   internally via McCabe-Thiele, and *directly targets* the given product
   purities through its mass balance.
2. **`compute_binary_feed_stage()`** — a standalone reimplementation of
   BioSTEAM's internal `BinaryDistillation._run_McCabeThiele` logic, using
   only public thermosteam/biosteam calls (`get_bubble_point`,
   `dew_point_at_P`, `bubble_point_at_P`) plus the public helper
   `compute_stages_McCabeThiele`. Verified to reproduce `D1.design_results`
   exactly. Returns `theoretical_stages`, `theoretical_feed_stage`, `Rmin`,
   `R`, `q`, `zf`, `x_m`, `y_m`.
3. **`solve_boilup_for_bottoms_purity()`** — builds `MESHDistillation`
   columns (this is where `MESHDistillation` actually appears — it's nested
   inside `build()`, called repeatedly by `brentq` via `bottoms_error()`,
   not a bare top-level assignment like D1) and root-finds the `boilup`
   value that reproduces D1's bottoms purity target, since MESHDistillation
   has no direct purity spec of its own.
4. **D2** — the `MESHDistillation` column returned by the solver above, using
   D1's `theoretical_stages`/`theoretical_feed_stage` and a converted
   reflux (see below).
5. **`build_mesh()` + `trials`** — a one-at-a-time sensitivity sweep. Swaps
   each of D1's "actual" design outputs (reflux, `N_stages`, `feed_stage`)
   into an otherwise-generic `MESHDistillation` column individually, holding
   the other two at fixed naive defaults (`N_default`, `feed_stage_default`,
   `reflux_default`) and `boilup` fixed at a constant (`boilup_default`,
   **not** root-found), to isolate which single parameter moves purity the
   most. See §10 below. To test a different stage count by hand, edit
   `N_default` — that's the one line that drives both the `'all defaults'`
   and `'actual reflux only'` rows.

## Required inputs, by column class — and what each is used to calculate

The two column classes invert each other: in `BinaryDistillation` the
*separation target* (`y_top`/`x_bot` or `Lr`/`Hr`) is an **input**, and
everything else (flow split, `Rmin`, `R`, stage count, feed stage) is
*calculated* from it. In `MESHDistillation` the *equipment* (`N_stages`,
`feed_stages`, `reflux`, `boilup`) is the **input**, and product purity
is whatever the rigorous per-stage balance produces — it is never a
direct input (gotcha #4 below).

### `BinaryDistillation` (shortcut, McCabe-Thiele)

| Input | Feeds into | Produces |
|---|---|---|
| Feed flow `F` + composition `zf` | Overall mass balance | Combined with `y_top`/`x_bot`, gives **distillate flow `D`** and **bottoms flow `B`** via the lever rule `F·zf = D·y_top + B·x_bot` (`_run_binary_distillation_mass_balance`, `distillation.py`). |
| `y_top`, `x_bot` (or `Lr`, `Hr`) | Mass balance + staircase end-points | The `D`/`B` split above, and the two end-points the McCabe-Thiele staircase steps between. |
| Feed thermal condition (`T`, quality, or enthalpy) + declared `phase` | `get_feed_quality()` | **Feed quality `q`** — see gotcha #7: getting `phase` wrong silently flips `q`'s sign and cascades through everything below. |
| `zf`, `q` | q-line | Intersection of the q-line with the **equilibrium curve** → the McCabe-Thiele **pinch point**, per the `Rmin`/pinch-point section below. |
| `k` (reflux multiplier), `Rmin` (user floor) | `R = k * Rmin` | The **actual reflux ratio (L/D)** — full derivation in "Where `R` actually comes from" below. |
| *(derived)* `R`, `q`, `y_top`, `x_bot` | McCabe-Thiele staircase | **Theoretical stages `N`** and **theoretical feed stage** — see "Stage-count terminology" below. |
| *(derived)* `N`, `R`, plus viscosity/relative-volatility/L-V traffic (Murphree/O'Connell) | Stage efficiency correlation | **Actual (physical) stages** = `ceil(N/efficiency)`. |

Causal chain: `F, zf, y_top, x_bot → D, B` (mass balance, independent of
staging) in parallel with `q (from T/P/phase), zf → pinch point → Rmin →
R (via k) → N, feed stage (staircase) → actual stages (efficiency)`.

`ShortcutColumn` (multicomponent) follows the identical `k`×`Rmin`→`R`
philosophy with correlations (Fenske/Underwood/Gilliland/Kirkbride)
instead of the McCabe-Thiele graphical method — already tabulated above.

### `MESHDistillation` (rigorous)

| Input | Required? | Used to calculate |
|---|---|---|
| `N_stages` | Yes — **not computed**; typically read off a prior shortcut run (gotcha #6: these are theoretical, not physical, stages) | Size of the per-stage system being solved. |
| `feed_stages` | Yes — **not computed** | Where the feed's mass/energy enters the per-stage balance. |
| `reflux` (L/V at condenser) | Yes, unless `full_condenser=True` (then enforced externally via a `Splitter.split` — gotcha #8) | One boundary condition closing the equations at the top. **Not** the same quantity as `BinaryDistillation`'s `R` — conversion `L/V = R/(R+1)`, gotcha #1. |
| `boilup` (V/L at reboiler) | Yes (gotcha #3 — omitting it defaults to an adiabatic last stage, bottoms purity comes out wildly wrong) | The other boundary condition, at the bottom. Same convention as the textbook boilup ratio, no conversion needed (gotcha #2). |
| Feed stream (flow, composition, `T`/`P`/declared `phase`) | Yes | Real per-stage **enthalpy** balance — phase declaration matters even more here than in `BinaryDistillation` (gotcha #7 applies identically). |
| `P` | Yes | VLE at each stage. |
| `LHK` | For reporting only | Not used to constrain the solve — just labels the design-result output. |

Output: the solver marches the **M**ass/**E**quilibrium/**S**ummation/
**H**eat equations per stage and returns the converged composition and
flow of every stream — there is no purity input to satisfy (gotcha #4).
To hit a target purity, invert the problem: fix `N_stages`/`feed_stages`/
one of `reflux`/`boilup`, and **root-find** the other stage spec against
the desired product composition — `solve_boilup_for_bottoms_purity()`
does exactly this. Even then only the one purity root-found against is
guaranteed; the other end comes out however the rigorous energy balance
says it does (see "Residual, expected limitation" below), since MESH
doesn't share the shortcut method's constant-molal-overflow assumption.

**Connecting the two in practice** (`qsep.py`'s actual workflow): run
`BinaryDistillation` first (purity in → `N`, feed stage, `R` out), then
feed those into `MESHDistillation` as inputs, converting `reflux`
(gotcha #1) and root-finding `boilup` (gotcha #4) since there is no
direct purity-matching analog for it.

## How BioSTEAM determines the feed stage (general)

Three different mechanisms depending on the column class:

- **`BinaryDistillation`**: McCabe-Thiele graphical method. Steps off the
  staircase and finds which stage crosses the intersection of the q-line and
  rectifying operating line (`x_m`, `y_m`). Needs: feed quality `q`, feed
  light-key mole fraction `zf`, `y_top`/`x_bot`, reflux `R`, pressure `P`.
- **`ShortcutColumn`**: Fenske-Underwood-Gilliland + the empirical **Kirkbride
  equation** (`compute_feed_stage_Kirkbride` in `biosteam/units/distillation.py`).
  Needs aggregate quantities: total theoretical stages `N`, bottoms/distillate
  molar flows `B`/`D`, feed's heavy-key/light-key mole ratio, LK mole fraction
  in bottoms, HK mole fraction in distillate.
- **`MESHDistillation`**: `feed_stages` is a **required user input**, not
  computed. It's a rigorous MESH (Mass/Equilibrium/Summation/Enthalpy) solver
  — you tell it where the feed goes; it doesn't back-calculate an optimum.
  Typical workflow: get a stage count/feed location from a shortcut method
  first, then feed those numbers in here.

## Where `R` actually comes from: `k`, `Rmin`, and the pinch point

Both shortcut classes take `k` (ratio of actual reflux to minimum reflux) rather than `R`
directly, and both follow the same pattern: **compute `Rmin` → floor it against a user-set
minimum → `R = k * Rmin`.** Confirmed in `biosteam/units/distillation.py`.

**`BinaryDistillation._run_McCabeThiele` (lines 1312-1350):**

1. Build the q-line from feed quality `q` and light-key mole fraction `zf`.
2. Find where the q-line intersects the **equilibrium curve** (not an operating line) via
   `brentq` — this is the McCabe-Thiele **pinch point** `(x_Rmin, y_Rmin)`: the point where,
   at minimum reflux, the rectifying operating line would need infinite stages to reach.
3. Slope of the line from `y_top` (on the `y=x` diagonal, since total condenser) through the
   pinch point gives `m`; since a rectifying operating line's slope is always `R/(R+1)`,
   solving `m = R/(R+1)` for `R` gives `Rmin = m/(1-m)`.
4. `if Rmin < self._Rmin: Rmin = self._Rmin` — `self._Rmin` is the constructor's `Rmin=` kwarg
   (default 0.3), a **user-enforced floor**, not part of the calculation. It only kicks in
   when the geometric `Rmin` comes out unrealistically low (near-ideal separations).
5. `R = k * Rmin`. This actual `R` then builds the real rectifying operating line, whose
   intersection with the q-line (`x_m, y_m`) drives stage-stepping and feed-stage location —
   i.e. `compute_binary_feed_stage()` in `qsep.py` reproduces exactly this chain.

**`ShortcutColumn._run_FenskeUnderwoodGilliland` (lines 1871-1905)** — the third feed-stage
mechanism from the section above, spelled out in full — follows the identical `k`/`Rmin`
pattern but gets `Rmin` from a different (correlation-based, not graphical) route:

| Step | Function (`distillation.py`) | Computes |
|---|---|---|
| **Fenske** | `compute_minimum_theoretical_stages_Fenske` (1611) | `Nm` — minimum stages, from LK/HK ratios and mean relative volatility |
| **Underwood** | `objective_function_Underwood_constant` + `compute_minimum_reflux_ratio_Underwood` (1620, 1624) | Solves constant `theta`, then `Rm` (minimum reflux) from it |
| *(floor + scale)* | `if Rm < self.Rmin: Rm = self.Rmin; R = self.k * Rm` (1885-1886) | Same floor-then-`k`-multiply pattern as `BinaryDistillation` |
| **Gilliland** | `compute_theoretical_stages_Gilliland` (1629) | `N` — actual theoretical stage count at the real `R`, from `Nm`, `Rm`, `R` |
| **Kirkbride** | `compute_feed_stage_Kirkbride` (1636) | Feed stage location (already noted above) |

So `BinaryDistillation` and `ShortcutColumn` are two independent implementations of the same
design philosophy (`k` × minimum reflux → real reflux → real stage count), one graphical
(binary-only), one correlation-based (multicomponent).

## Stage-count terminology: minimum vs. theoretical vs. actual stages

Three distinct numbers, easy to conflate:

**1. Minimum stages (`Nm`, Fenske, line 1611).** Stage count at **total reflux** (`R → ∞`):
condenser returns 100% of condensate, reboiler returns 100% of boilup, zero net product
withdrawal. A purely geometric/algebraic lower bound driven only by the required split and
relative volatility — not a buildable design (infinite duty, zero product). Only computed
explicitly in `ShortcutColumn`; `BinaryDistillation` never calculates it since McCabe-Thiele
steps directly at the real `R`.

**2. Theoretical stages (`N`, `Design['Theoretical stages']`).** Stage count at the **actual,
finite** design reflux `R = k * Rmin` (see previous section) — i.e. already "at the actual
reflux," not the `R=∞` case. In `ShortcutColumn` this is `N = Gilliland(Nm, Rm, R)`:

```python
def compute_theoretical_stages_Gilliland(Nm, Rm, R):
    X = (R - Rm) / (R + 1.)
    Y = 1. - np.exp((1. + 54.4*X) / (11. + 117.2*X) * (X - 1.) / X**0.5)
    N = (Y + Nm) / (1. - Y)
    return np.ceil(N)
```

Sanity check on the limits: as `R → ∞`, `X → 1`, `Y → 0`, `N → Nm` (converges to the Fenske
minimum, as expected). As `R → Rmin` (minimum reflux, the pinch condition), `X → 0` and
`N → ∞` — matches the McCabe-Thiele pinch point in `BinaryDistillation` needing infinite
stages right at `Rmin`. Real designs sit strictly between these two infinities, and `k` is
the knob that picks where — a "theoretical stage" is still an idealized *equilibrium* stage
(perfect VLE between the liquid/vapor leaving it), just counted at the real reflux rather
than the `R=∞` limit.

**3. Actual stages (`Design['Actual stages']`).** A *separate*, later correction — **nothing
to do with where `R` sits relative to `Rmin`**. Real trays don't reach perfect equilibrium;
the Murphree stage efficiency `E` (modified O'Connell correlation, from viscosity, relative
volatility, and liquid/vapor molar flow) quantifies how close a real tray gets:

```
Actual stages = ceil(Theoretical stages / E)
```

(`distillation.py:2281`, `2327-2328` for `ShortcutColumn`; `BinaryDistillation` splits this
into rectifying/stripping sections with separate efficiencies `E_rectifier`/`E_stripper`,
lines 895-910, since liquid/vapor traffic differs above vs. below the feed — piecewise
version of the same formula, split at the theoretical feed stage). `R` does feed into the
efficiency calc indirectly (e.g. `V_Rmol = (R+1) * F_mol_distillate`, line 894) purely
because `R` sets the internal liquid/vapor traffic the correlation needs as input — **not**
because "actual stages" means "stages at actual reflux." That meaning belongs to
*theoretical* stages (point 2). Passing `stage_efficiency=` explicitly to the constructor
overrides the Murphree correlation entirely (lines 884-886).

**Full chain, disambiguated:**

```
Rmin (pinch point / Fenske-Underwood)
  → R = k * Rmin                              "actual" reflux ratio (finite, buildable)
    → N = Theoretical stages                   stage count AT that actual R (idealized/equilibrium stages)
      → Actual stages = ceil(N / efficiency)   physical tray count (separate correction for imperfect trays)
```

`MESHDistillation` doesn't compute an `Actual stages` at all in `distillation.py` — a MESH
solve is already per real stage as specified via `N_stages`/`feed_stages`, so there's no
lumped theoretical→actual efficiency correction the way there is for `BinaryDistillation`/
`ShortcutColumn`. (Not yet independently re-verified beyond a code read — flag if this
matters for a real design and it should be checked more carefully.)

## Key gotchas found while wiring D1's design into D2

### 1. `reflux` means different things in the two classes

- `BinaryDistillation`'s `R` (and McCabe-Thiele generally) is the classic
  **L/D** ratio — reflux liquid vs. distillate product.
- `MESHDistillation`'s `reflux` parameter is **L/V** — "liquid to vapor flow
  rate at the condenser" (confirmed in `biosteam/units/stage.py`:
  `_get_specification` sets `B = 1/reflux` for the `'Reflux'` spec, where `B`
  is the internal vapor/liquid ratio).
- Conversion: `L/V = R/(R+1)`. Do **not** plug D1's `R` straight into
  MESHDistillation's `reflux` — it silently means something else (much more
  reflux than intended for `R` >= 1, since L/V saturates at 1 while L/D is
  unbounded).
- Intuition: L/D asks "reflux compared to what leaves as product"; L/V asks
  "what fraction of the vapor gets condensed and sent back down" (always
  0–1, since `V = L + D` and `D >= 0`).

### 2. `boilup`, by contrast, *is* the standard convention

`MESHDistillation`'s `boilup` = **V/L** at the reboiler ("vapor to liquid
flow rate at the reboiler") — this matches the textbook boilup ratio
directly; `_get_specification` sets `B = value` with no inversion. No
conversion needed, unlike `reflux`.

### 3. MESHDistillation needs *both* ends specified

Without a `boilup` spec, the last stage defaults to an adiabatic (`Q=0`)
equilibrium stage — i.e. no real reboil duty, so the stripping section barely
does anything. Confirmed empirically: same `N_stages`/`feed_stage`/`reflux`,
no `boilup` → bottoms purity ended up wildly off target (~0.46 vs. a 0.10
target). Always specify both `reflux` and `boilup` (or another equivalent
pair of specs).

### 4. MESHDistillation has no purity spec — use root-finding to match one

There's no "hit x_bot=0.10" option; only `Reflux`/`Boilup`/`Duty`/
`Temperature` per stage. To reproduce a shortcut design's target purity,
root-find `boilup` (or `reflux`) against the resulting product composition
— see `solve_boilup_for_bottoms_purity()`. Matching stage count + feed
location + reflux is not sufficient on its own.

### 5. Caching bug: mutating `.boilup`/`.reflux` on a live instance doesn't trigger a re-solve

`MESHDistillation._setup()` short-circuits when `stage_specifications` is
`==` to `self._last_args`'s copy — but the property setters (`reflux`/
`boilup`) mutate that same dict **in place**, so after the first simulate,
changing `.boilup` and re-simulating silently reuses the previous solve.
Confirmed by scanning boilup values on one persistent instance (result flat)
vs. building a fresh instance per trial (result changes as expected, and
non-monotonic-looking flat curve turned into a clean monotonic one). Any
root-finding loop over stage specs **must construct a fresh column per
trial value**.

### 6. `N_stages`/`feed_stages` are theoretical stages, not physical trays

Confirmed in `distillation.py:_actual_stages()` — the `Theoretical stages`
design result is `self.N_stages` passed straight through; `Actual stages` is
derived afterward via a per-stage Murphree efficiency
(`np.ceil(N_stages / eff)`). Same convention as `BinaryDistillation`'s
`Theoretical stages`/`Theoretical feed stage`. So feeding
`compute_binary_feed_stage()`'s output directly into `MESHDistillation` is
correct — no conversion needed here (unlike `reflux`).

### 7. Feed `phase` is declared, not auto-detected — it changes everything upstream

`bst.Stream.phase` selects which correlation branch (`liquid` vs `vapor`)
computes `H`, `Cp`, density, etc. — it does **not** run a flash to check
whether that phase is actually stable at the given `T`/`P`. If you don't set
it, a stream can end up with an internally-inconsistent "superheated liquid"
enthalpy at a `T` where the material is really vapor.

Concretely for this feed (50/50 methanol/water, 405 K, 1 atm — both pure
components boil below this temperature at 1 atm, so it's genuinely
superheated vapor): adding `phase='g'` changed the feed-quality calc from
`q=0.865` (looked like a nearly-saturated liquid feed) to `q=-0.051`
(correctly superheated vapor). Since `q` feeds directly into the q-line,
`Rmin`, `R`, stage count, and feed location, this one line changes the
entire downstream design:

| | phase unset (defaulted liquid) | `phase='g'` (correct) |
|---|---|---|
| `q` | 0.865 | -0.051 |
| Rmin | 0.433 (hit floor) | 1.180 (real value) |
| R (L/D) | 0.866 | 2.359 |
| Theoretical stages | 6 | 5 |
| Feed stage | 3 | 3 |
| D2 distillate x(MeOH) | 0.867 | 0.720 |
| D2 bottoms x(MeOH) | 0.100 (solved) | 0.100 (solved) |

**Always set `phase=` explicitly to match the real physical state at the
stream's `T`/`P`** (check with `dew_point_at_P()`/`bubble_point_at_P()` if
unsure) — don't rely on the default.

### 8. `full_condenser=True` removes the internal `reflux` spec — L/V gets enforced externally instead

Cross-checked against BioSTEAM's own tutorial (`Glacial_acetic_acid_separation.html`), which builds a
`MESHDistillation` column that never sets `reflux`:

```python
ED = bst.MESHDistillation(
    'extract_distiller',
    ins=(HX-0, reflux),
    outs=('distillate', 'acetic_acid'),
    feed_stages=[feed_stage-2, 1],
    N_stages=N_stages,
    full_condenser=True,
    boilup=boilup,
    LHK=('Water', 'AceticAcid'),
    use_cache=True,
)
```

With `full_condenser=True`, stage 0 condenses **100%** of the incoming vapor to liquid — there's no
vapor/liquid split left at that stage for a `reflux` (L/V) spec to control, so the spec is simply
absent. Reflux is instead recovered by physically feeding a `reflux` stream back into `ED`'s second
`ins` slot. That stream is produced by an external `Splitter` on the condenser's total liquid outlet:

```python
distillate, condensate = ED.top_split.outs
split = condensate.F_mol / ED.condenser.outs[0].F_mol   # == L / V

splitter = bst.Splitter(
    ins=settler-0,
    outs=(reflux, solvent_rich),
    split=split,
)
```

Since total condensation conserves molar flow across the phase change, `condenser.outs[0].F_mol == V`
(the vapor that rose into the condenser), and `condensate.F_mol` is the portion of that liquid sent
back down, `L`. So `split = L/V` — **the exact same ratio** `MESHDistillation.reflux` means on a
partial condenser (§1) — just enforced via an external `Splitter.split` and a real recycled stream
instead of an internal stage spec. Two equivalent mechanisms for the same L/V quantity:

| | Partial condenser (this script's D2) | `full_condenser=True` (tutorial) |
|---|---|---|
| Where L/V lives | `MESHDistillation.reflux` stage spec, solved internally | `Splitter.split` on the condensed distillate, external to the column |
| What's fed back | Nothing extra — split happens inside stage 0 | `condensate` outlet physically piped into `ED`'s second `ins` slot |

## Residual, expected limitation

Even with everything above fixed, D1 (shortcut, constant-molal-overflow
assumption, direct purity targets) and D2 (rigorous MESH, real energy
balances, no purity target) won't perfectly agree on *both* product
purities simultaneously. Root-finding `boilup` against the bottoms target
matches bottoms exactly, but the resulting distillate composition is
whatever the rigorous model produces — it can be noticeably off the
shortcut's `y_top` target, more so for non-ideal, genuinely vapor-fed cases
like this one. This is treated as informative, not a bug: it's the actual
gap between shortcut sizing and rigorous simulation for this system.

### 9. Tried borrowing D1's "actual" internal reflux/boilup instead of root-finding — doesn't work, and shows *why* the gap above exists

Prompted by comparing against BioSTEAM's
[Glacial acetic acid tutorial](https://biosteam.readthedocs.io/en/latest/tutorial/Glacial_acetic_acid_separation.html),
which builds its rigorous `MESHDistillation` column using `reflux`/`boilup` read
directly off the shortcut `ShortcutColumn`'s own simulated condenser/reboiler
streams (`boilup = outlet['g'].F_mol / outlet['l'].F_mol`, `split =
condensate.F_mol / condenser.outs[0].F_mol`) rather than root-finding against a
purity target. Tried the analogous thing here: read D1's real condensate/
distillate and reboiler-vapor/bottoms flow ratios instead of using
`compute_binary_feed_stage()`'s graphical `R` and the root-found `boilup`.

**Reflux: turns out to be a non-issue — the two are numerically identical.**
`BinaryDistillation._run_condenser_and_reboiler` (`distillation.py:839`)
*constructs* the condensate stream as `F_mol_condensate = R *
F_mol_distillate` — i.e. `R` isn't a target that the internal streams
independently verify, the streams are algebraically built from `R`. Confirmed:
`D1.condensate.F_mol / D1.outs[0].F_mol == 2.3594868149433963`, exactly
`results['R']` to full float precision. So `reflux_LV = R/(R+1)` was already
using the "real" value all along; there is no separate real reflux to borrow.

**Boilup: tried it, made things *worse*.** D1's implied boilup
(`D1.reboiler.outs[0]['g'].F_mol / D1.outs[1].F_mol`) is `1.3595`, vs. the
root-found `0.1003`. Feeding `1.3595` into `MESHDistillation` (same matched
reflux, `N_stages=5`, `feed_stages=[3]`):

| | root-found boilup (0.1003) | D1's implied boilup (1.3595) |
|---|---|---|
| distillate MeOH frac | 0.720 | 0.628 |
| bottoms MeOH frac (target 0.100) | 0.100 (by construction) | **0.022** |
| distillate/bottoms F_mol | 50 / 50 (matches D1) | 78.9 / 21.1 |

Both compositions got worse *and* the overall D/B mass split — which
`BinaryDistillation` just asserts from `y_top`/`x_bot` via a 100%-non-key-
separation algebraic mass balance, never checked against real stage-by-stage
equilibrium — came apart entirely.

**Root cause:** `BinaryDistillation`'s `R` and implied boilup are only
self-consistent *if* the constant-molal-overflow (CMO) assumption holds.
`MESHDistillation` doesn't assume CMO; it solves a real per-stage mass/energy
balance, so handing it CMO-derived reflux/boilup free to converge to a
completely different product split if CMO is a poor assumption for the actual
feed. Here it is — this is a superheated vapor feed (`q=-0.051`, see gotcha
#7) — so the borrowed numbers send D2 somewhere else entirely. The tutorial's
system (dilute acetic-acid recovery, Lr=Hr=0.95) is far more CMO-friendly, so
"borrow the shortcut's own numbers" happens to work well *there* — that's a
property of that system, not a generally valid technique. **Conclusion:**
root-finding `boilup` against one purity target (current approach) is not a
workaround to be replaced — it's about as good as it gets without abandoning
the shortcut method's CMO assumption altogether for feeds like this one.

### 10. One-at-a-time sensitivity — isolating which "actual" parameter drives the purity gap

Given the residual gap above (D2 hits `x_bot` exactly but lands at
`distillate=0.720` vs. the `y_top=0.90` target), the natural next question is
*which* of D1's actual design outputs — reflux, `N_stages`, or `feed_stage` —
is actually responsible for how close MESH gets to target, since D2 changes
all three simultaneously. Answered with `build_mesh()`/`trials` in `qsep.py`
(§ item 5 above): build a MESH column with a fixed, non-tuned `boilup`, and
swap in D1's actual value for exactly one of {reflux, `N_stages`,
`feed_stage`} at a time, holding the other two at generic defaults
(`N_default=8`, `feed_stage_default=4`, `reflux_default=0.5`). `boilup` is
deliberately **not** root-found here — the point is to see each parameter's
raw effect on purity, not to have `boilup` secretly compensate for whichever
one is being tested.

**Result — checked at three different fixed `boilup` values (0.1, 0.5, 1.0)
to make sure the ranking isn't an artifact of which constant was picked:**

| boilup fixed at | actual reflux only (dist, bot) | actual N_stages only (dist, bot) | actual feed_stage only (dist, bot) |
|---|---|---|---|
| 0.1 | 0.723, 0.093 | **0.901, 0.473** | 0.657, 0.093 |
| 0.5 | 0.701, 0.009 | **0.871, 0.374** | 0.642, 0.004 |
| 1.0 | 0.656, 0.002 | **0.828, 0.278** | 0.609, 0.001 |

(baseline "all defaults, no D1 info" for reference: 0.657/0.093, 0.641/0.009,
0.609/0.002 at boilup 0.1/0.5/1.0 respectively; target is distillate=0.90,
bottoms=0.10)

**Findings:**

- **`N_stages` is by far the dominant lever** on *both* purities — swapping
  only the generic `N_default=8` for D1's actual `N=5` moves distillate and
  bottoms far more than swapping either other parameter, at every boilup
  tested.
- **Reflux has a real but modest effect** on distillate, and essentially none
  on bottoms.
- **`feed_stage` alone does almost nothing** — the smallest individual effect
  of the three, consistently across all three boilup values.
- **Effects are not additive.** Combining all three actual values (with
  `boilup` still fixed, not root-found) does not simply stack the individual
  effects — e.g. at `boilup=1.0`, "all three actual" gives
  `distillate=0.648`, which is *worse* than "actual N_stages only" alone
  (`0.828`), even though actual reflux alone also pushed distillate up. The
  parameters interact strongly; purity is a joint function of
  (reflux, boilup, N_stages, feed_stage) at fixed structure, not a sum of
  independent per-parameter contributions.
- **The choice of fixed `boilup` constant doesn't change the ranking**, only
  the absolute numbers. It can look meaningful in a single snapshot — e.g. at
  `boilup=0.1`, "actual `N_stages` only" lands almost exactly on the
  distillate target (0.901 vs. 0.90) — but that is a coincidence of that one
  combination, not evidence that `boilup=0.1` is a more "correct" constant to
  fix than `0.5` or `1.0`. `0.1` is also not itself a meaningful default in
  its own right: it's D2's *root-found* boilup, solved specifically for the
  combination of actual reflux + actual `N_stages` + actual `feed_stage` (see
  §4/§9) — plugging that solved value in alongside generic reflux or
  `N_stages` doesn't carry over any of that meaning.

**Implication for closing the residual gap (§ above):** since `N_stages` is
the strongest lever and `feed_stage` the weakest, the more promising way to
hit both `y_top` and `x_bot` in MESH — instead of the single-variable
`boilup` root-find, or borrowing D1's CMO-derived numbers wholesale (§9) — is
likely a design-mode solve that **searches `N_stages` and root-finds
`boilup`** together, holding reflux pinned at D1's actual value. Not yet
implemented in `qsep.py`.

## 11. `dist2.py` — a newer BioSTEAM release found nearby, for comparison only

`atj_saf/dist2.py` is a full copy of `distillation.py` from a **newer**
BioSTEAM/thermosteam release, not something `qsep.py` imports or runs. Diffed
against the installed `biosteam==2.47.0` file this doc's line numbers refer
to:

**Bug fixes present in `dist2.py`, still live in the installed 2.47.0 file:**
- `'Rectifier platform and ladders'` / `'Stripper platform and ladders'` cost
  keys are swapped in `_cost()` for divided (`is_divided=True`) columns.
- `MESHDistillation`'s `full_condenser=True` branch wires `top_split` to the
  wrong outlet index (`self-2` instead of `self-0`).
- `Po = self.P * 0.000145078` (vacuum-pressure check) raises if `self.P` is
  an array of per-stage pressures rather than a scalar — no
  `isinstance(P, Iterable)` guard in 2.47.0.

**New features in `dist2.py`, not available in the installed version:**
`vlle=` threading `lle=` through every `bubble_point_at_P`/`dew_point_at_P`/
`solve_Ty` call (three-phase VLLE columns); `Distillation.to_rigorous_column()`
to auto-convert a solved `BinaryDistillation`/`ShortcutColumn` into an
equivalent `MESHDistillation` (would have been directly useful for D1→D2 in
this script, see §"Connecting the two in practice" above — not available at
`biosteam==2.47.0`); `MESHDistillation` gains `bottoms_product_to_feed`,
plural `algorithms`/`methods`, `max_attempts`, `specifications_by_weight`,
and an optional `LHK` (defaults `stage_efficiency=0.6` when omitted).

**Confirmed not a drop-in replacement:** installed `thermosteam==0.46.0`'s
`Stream.bubble_point_at_P` has no `lle` kwarg, and installed
`biosteam==2.47.0`'s `MultiStageEquilibrium._init` still uses the old
singular `algorithm`/`method`/`collapsed_init`/`inside_out` signature —
copying `dist2.py` over the installed file directly raises `TypeError` on
first VLE call. Using any of `dist2.py`'s new features would require bumping
`biosteam`/`thermosteam`/`flexsolve` together (untested here), not a
single-file swap.

**Relevance to this doc:** `dist2.py` also simplifies
`_run_condenser_and_reboiler`'s reboiler-temperature handling (drops a
redundant bubble-point recompute + pump re-simulate, just reuses the already
-computed boilup bubble point) — a legitimate simplification, not a change to
the fundamental CMO-vs-rigorous-MESH gap described in §9/§10 above.
