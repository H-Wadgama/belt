# kay_separations.md

Context notes for the ethanol/water separation work in `kay_testing.py`. Companion file — read alongside the script, not a replacement for it.

## 1. Reference pattern: BioSTEAM's shortcut → rigorous handoff (Glacial Acetic Acid tutorial)

Source: `https://biosteam.readthedocs.io/en/latest/tutorial/Glacial_acetic_acid_separation.html` (actual notebook lives in the `How2STEAM` repo, `case_studies/Glacial_acetic_acid_separation.ipynb`, linked via an `.nblink` from the docs page).

**Problem:** separate glacial acetic acid from dilute fermentation broth (1000 kg/hr acetic acid, 9000 kg/hr water). Water/acetic acid form a near-azeotrope, so an ethyl acetate LLE extraction step precedes distillation.

**Why shortcut first:**
- `ShortcutColumn` (Fenske-Underwood-Gilliland-type) solves algebraically from `Lr`/`Hr` or `y_top`/`x_bot` — no stage-by-stage MESH equations — so the whole flowsheet (including recycles) can be roughed out and converged fast, and CAPEX/OPEX sanity-checked early.
- Shortcut columns assume a single feed and an internal condenser/reboiler. They cannot represent multiple feeds at different stages or an externally-supplied reflux stream with no internal condenser.

**Why rigorous (MESH) second:**
- The full design needed a second feed (external reflux from a shared decanter) entering at the top stage, with `full_condenser=True` (no internal condenser on the column at all) — only `bst.MESHDistillation` supports that topology.
- MESH (Mass, Equilibrium, Summation, entHalpy) solves the nonlinear stage-by-stage equations and is much more sensitive to initial guesses than shortcut methods.

**The handoff — shortcut results seed the rigorous column, not thrown away:**
```python
print(ED.results())
outlet = ED.reboiler.outs[0]
boilup = outlet['g'].F_mol / outlet['l'].F_mol
distillate, condensate = ED.top_split.outs
split = condensate.F_mol / ED.condenser.outs[0].F_mol   # reflux ratio equivalent
N_stages = int(ED.design_results['Theoretical stages'])       # 10
feed_stage = int(ED.design_results['Theoretical feed stage'])  # 7
```
These (`N_stages`, `feed_stage`, `boilup`, `split`) are then passed straight into the `MESHDistillation` constructor:
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
Rationale: MESH's nonlinear solve converges reliably when started near the shortcut solution instead of from scratch.

**Result comparison (shortcut vs. rigorous), for calibration on what to expect when we do the same here:**

| Metric | Shortcut | Rigorous (MESH) |
|---|---|---|
| CAPEX | $1.99 MM | $2.04 MM |
| OPEX | $0.881 MM/yr | $0.96 MM/yr |
| Light key recovery | 13.9 kmol/hr | 14.2 kmol/hr |
| Residual water in product | 0.000126 kmol/hr | 0.0000168 kmol/hr |

Rigorous gave slightly better recovery/purity for a modest (~5%) cost increase — shortcut is a good first-pass estimate, rigorous confirms/refines rather than overturns it.

**Key API note learned from this exercise:** `ShortcutColumn`/`BinaryDistillation` accept either `(Lr, Hr)` (recovery-based) or `(y_top, x_bot)` (composition-based, **mole fraction**, not mass fraction) — mixing spec styles across columns in the same flowsheet is fine.

## 2. Current work: ethanol/water shortcut columns in `kay_testing.py`

Two `bst.units.ShortcutColumn`s in series, purifying ethanol from a cellulosic-ethanol fermentation broth. Both `LHK=('Ethanol', 'Water')`, `P=3*101325` Pa (3 atm), `k=8` (reflux = 8× minimum reflux).

**Feed — `ethanol_in_beer`:** fermentation broth at 115°C, 6 atm (flashes on entry to the 3 atm column). Composition (kg/hr): Ethanol 21507, Water 391023, Xylose 315.697, Extract 12208.3, AceticAcid 3663.85, LacticAcid 2135.35, Cellulose 3504.6, Xylan 1952.77, Lignin 13131.8, Protein 2635.1, Ash 4107.85, Cellulase 1681.7.

**Column 1 — `beer_shortcut` (beer/stripping column):**
```python
beer_shortcut = bst.units.ShortcutColumn(
    ins=ethanol_in_beer,
    outs=('shortcut_beer_top', 'shortcut_beer_bottom'),
    P=3*101325,
    LHK=('Ethanol', 'Water'),
    Lr=0.9913,      # 99.13% of ethanol recovered overhead
    Hr=0.90717,     # 90.7% of water rejected to bottoms
    k=8,
    partial_condenser=True,
)
```
Recovery-based spec. Takes the full broth including all non-volatile solids (Lignin, Ash, Cellulase, Cellulose, Xylan, Protein) and other dilute organics — shortcut model treats these as heavy non-keys, routed to the bottoms/stillage.

**Column 2 — `rectification_shortcut`:**
```python
rectification_shortcut = bst.units.ShortcutColumn(
    ins=beer_shortcut-0,
    outs=('shortcut_rectif_top', 'shortcut_rectif_bottom'),
    P=3*101325,
    LHK=('Ethanol', 'Water'),
    y_top=0.925/1.11,    # = 0.8333 mol frac ethanol overhead
    x_bot=0.0005/2.55,   # = 0.000196 mol frac ethanol in bottoms
    k=8,
)
```
Feeds off column 1's distillate. Composition-based spec.

**Azeotrope correction (why the `/1.11` and `/2.55` divisors are there):** `y_top`/`x_bot` on `ShortcutColumn` are mole fractions, but the original design targets were mass-fraction based (36.8 wt% overhead / 0.05 wt% bottoms, per the initial hand spec). Entering the mass-fraction numbers directly as mole fractions was wrong on two counts:
1. `y_top = 0.925` mol fraction ethanol is *above* the ethanol/water azeotrope (~0.894 mol frac / ~95.6 wt%) — infeasible for a simple VLE-based shortcut column, same azeotrope issue the acetic acid tutorial worked around with an LLE extraction step.
2. `x_bot = 0.0005` mol fraction converts to ~0.128 wt% ethanol, not the intended 0.05 wt%.

Dividing by 1.11 and 2.55 (mass↔mole conversion factors for this composition, MW: ethanol 46.07, water 18.02) corrects both: `y_top=0.8333` mol frac ≈ 92.7 wt% ethanol (below the azeotrope, feasible), and `x_bot=0.000196` mol frac ≈ 0.050 wt% ethanol (matches the original bottoms target).

## 3. Rigorous (MESH) columns — implemented

Both `beer_mesh` and `rectif_mesh` (`bst.MESHDistillation`) are now built in `kay_testing.py`, seeded from the shortcut columns' `design_results` per the handoff pattern in Section 1 — though the rectification column's `reflux`/`boilup` have since been hand-tuned away from the literal shortcut values (see Section 5).

### 3.1 Column 1 — `beer_mesh`

No condenser: `reflux=0` (passing `reflux=0` explicitly, not omitting it — see bug #1 below). `N_stages`, `feed_stages` (single feed), and `boilup` all pulled directly from `beer_shortcut.design_results` / `beer_shortcut.reboiler`. Overhead leaves fully vaporized and feeds `rectif_mesh` directly — no intermediate condensation.

### 3.2 Column 2 — `rectif_mesh`

Two feeds: `ins=(beer_mesh-0, reflux_recycle)`. Current working config:
```python
rectif_mesh = bst.MESHDistillation(
    'rectif_mesh',
    ins=(beer_mesh-0, reflux_recycle),
    outs=('rectif_mesh_vapor', 'rectif_mesh_bottoms'),
    N_stages=N_stages_rectif,   # 11
    feed_stages=[9, 8],         # beer_mesh vapor at 9, reflux_recycle at 8
    reflux=3,
    boilup=0.5,
    LHK=('Ethanol', 'Water'),
    P=3*101325,
)
```
`reflux=3` means this column now has a **real internal partial condenser** (`rectif_mesh.condenser`/`.reflux_drum` are populated, with real utility cost) — a departure from the original "no condenser, external heat recovery only" design intent (see Section 5, open item on possible double-condensing). `boilup=0.5` is hand-set, not the shortcut-derived `boilup_rectif` (3.395, still computed but currently unused).

`reflux_recycle` is *not* the column's internal reflux mechanism — it's a second external feed, entering low in the column (stage 8) alongside the column-1 vapor (stage 9), coming from the molecular-sieve loop below. Same conceptual pattern as the acetic acid tutorial's externally-supplied reflux feed, but here it re-enters mid/low in the column rather than at the very top.

### 3.3 Heat recovery + molecular sieve recycle loop

```
rectif_mesh.outs[0] (raw vapor)
  -> HX_sieve (HXprocess: condenses vapor against process water, 33 C -> 100 C)
  -> molecular_sieve (Splitter: dehydration, modeled as a component split)
       -> sieve_product  (final ethanol product, leaves the loop)
       -> sieve_reject   -> reflux_mixer (+ makeup_water) -> cooler_reflux (71 C, 3 atm) -> reflux_recycle
```

- **`HX_sieve`**: an `HXprocess` (no utility cost — process-to-process). A per-pass spec (`set_sieve_water_flow`) sizes the water inlet flow by direct enthalpy balance: duty released condensing the vapor to saturated liquid, divided by the enthalpy needed to heat 1 kmol of water 33→100 °C.
- **`molecular_sieve`**: models the sieve as a component `Splitter`. AceticAcid/LacticAcid are routed 100% to product (not water-selective — see bug #2 below). Ethanol/Water split fractions are set by a per-pass spec (`set_molecular_sieve_split`) targeting **fixed absolute reject flows** — `target_reflux_ethanol=5331.9 kg/hr`, `target_reflux_water=2043 kg/hr` — capped at whatever is actually available that pass (see bug #3 below for why this must be dynamic, not a one-time fraction).
- **`makeup_water`**: tops up the reject's water only if the column's real overhead can't supply the full 2043 kg/hr on its own (also a per-pass spec, `set_makeup_water_flow`). In practice the column has been supplying more than enough, so this has converged to 0 kg/hr.
- **`cooler_reflux`**: brings the combined reject + makeup water to 71 °C. No pump — pressure is assumed to already be 3 atm on both `sieve_reject` and `makeup_water`, so no pressure change is needed to re-enter the column.
- System assembly: `bst.System('rectif_loop_sys', path=(beer_mesh, rectif_mesh, HX_sieve, molecular_sieve, reflux_mixer, cooler_reflux), recycle=reflux_recycle)`.

`reflux_recycle` converges to exactly the target composition: **5331.9 kg/hr ethanol / 2043 kg/hr water = 72.3 wt% / 27.7 wt%, 7374.9 kg/hr total, 71 °C / 3 atm.**

## 4. Bugs found and fixed while converging this system

1. **`ZeroDivisionError` in MESHDistillation's internal solver** (`get_energy_balance_phase_ratio_departures`) when using `reflux=None` (the "no condenser" default) in certain feed-stage configurations. Root cause: an under-determined top-stage energy balance when no explicit reflux spec closes the degrees of freedom at stage 0. Passing **`reflux=0` explicitly** (rather than omitting it / `None`) fixed the single-feed `beer_mesh` case, since it gives the solver a real (if zero-valued) spec at stage 0. A later two-feed `rectif_mesh` config with feed stages far apart still hit the same error even with `reflux=0`; that was worked around with `algorithm='sequential', method='fixed-point'` (a different iterative solver that doesn't hit the singular calculation), and has since become moot because `rectif_mesh` now uses a genuine nonzero `reflux=3`.
2. **Runaway trace-component accumulation.** `molecular_sieve`'s `split` dict originally only specified `Ethanol`/`Water`; leaving `AceticAcid`/`LacticAcid` unspecified defaulted them to 100% reject with no purge path, so they built up unboundedly across recycle iterations (observed: 164 kmol/hr AceticAcid in the column vapor vs. ~61 kmol/hr in the *entire* feed). Fixed by explicitly routing both 100% to product.
3. **Static split-fraction / makeup-water drift.** The molecular sieve's split fraction and the makeup water flow were originally computed **once**, from the static `rectification_shortcut` shortcut-column snapshot — not from what `rectif_mesh` actually converges to. As soon as the MESH column's real behavior diverged from that snapshot (different `N_stages`/`reflux`/`feed_stages`), the fixed `Water=0.0` split (100% of whatever water arrives → reject) dumped far more water into the recycle than intended, **inverting** the recycle composition to 29.6 wt% ethanol / 70.4 wt% water instead of the intended 72.3/27.7. Fixed by making both the splitter fractions and the makeup water flow **per-pass specs** driven off absolute target flows (Section 3.3), recomputed from the actual current-pass stream every iteration.
4. **Azeotrope-violating (non-physical) converged solution.** With `feed_stages=[10, 8]` on an `N_stages=11` column, the column-1 vapor feed landed on stage 10 — the terminal stage, which is also where `MESHDistillation` pins the default `boilup` specification (`stage_specifications[-1]`). This produced a solution that closed mass balance exactly (0.0000% imbalance on every component) but was thermodynamically impossible: raw column overhead vapor at **98.84 wt% ethanol**, above the ~95.6 wt% ethanol/water azeotrope. This is not achievable by any plain VLE equilibrium-stage column with no entrainer — relative volatility inverts (alpha < 1) past the azeotrope, so no liquid composition can produce vapor richer than the azeotropic vapor composition. (Verified against the alpha-vs-composition sweep from Section 1's shortcut work, at this column's actual 3 atm — the azeotrope location is essentially unchanged from the 1 atm value.) Global mass balance closing is *not* sufficient evidence of a valid stage-by-stage equilibrium solution. **Fixed by moving the feed off the terminal stage** (`feed_stages=[9, 8]`), after which raw overhead purity dropped to a physically valid 90.76 wt% ethanol.

## 5. Current state / open items

- **`reflux=3`, `boilup=0.5`, `feed_stages=[9, 8]`, `N_stages_rectif=11`** are the current working values — hand-tuned to get a physically valid, converged solution, not a literal transfer of the shortcut's own `boilup_rectif` (3.395, still computed but unused) as Section 1's handoff pattern originally intended. The shortcut→rigorous handoff held up cleanly for `beer_mesh` (single feed, values pulled straight from `beer_shortcut`) but not for `rectif_mesh`, given the added complexity of a second feed and the molecular-sieve recycle loop.
- **Purity:** raw `rectif_mesh` overhead is ~90.76 wt% ethanol (~79.3 mol%) — physically valid, and in the right ballpark versus (but not exactly matching) the original shortcut target of 92.7 wt% / 83.3 mol%. After the molecular sieve step, final product purity is ~99.6 wt% ethanol — realistic for fuel-grade anhydrous ethanol, and legitimately allowed to exceed the azeotrope since that step models adsorption, not VLE.
- **Feed-stage placement is sensitive** — avoid ever placing a feed on the terminal (reboiler) stage of a MESH column; see bug #4. Any future changes to `N_stages`/`feed_stages` should re-check the raw column overhead against the ~95.6 wt% azeotrope ceiling as a sanity check.
- **Not yet resolved: possible double-condensing.** `rectif_mesh`'s `reflux=3` now builds a real internal partial condenser (with real cooling-water utility cost) that condenses vapor to generate reflux internally — and then `HX_sieve` condenses the *resulting net overhead product* a second time, against process water. Worth checking whether `HX_sieve`'s duty is now small/redundant given the internal condenser already does most of the condensing work, or whether this hybrid (some real reflux + external heat recovery on the net product) is the intended final design.
