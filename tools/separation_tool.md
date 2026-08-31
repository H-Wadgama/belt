# `tools/chopper/` — distillation sizing & optimization toolkit

This folder is a self-contained toolkit for scoping out a single BioSTEAM
`BinaryDistillation` column against a purity/recovery target, sweeping that
column over a range of reflux ratios, costing each point in the sweep, and
picking the cheapest one that actually hits the target. Each layer is a thin
wrapper around the one below it — nothing here re-implements BioSTEAM's
shortcut method; it only drives it and organizes the results.

**Scope: strictly binary feeds only, for now.** Every entry point in this
folder (`run_separation`, `sweep_reflux_ratio`, `optimize_reflux_ratio`,
`optimize_separation`, and the merged `separation_rag_agent.py`) requires
the feed to have exactly 2 components with nonzero flow —
`separation_trial.check_binary_feed()` raises `ValueError` otherwise.
Ternary/multicomponent feed support is planned as a later extension (see
`tools/binary-distillation-context.md`, "Scope: Binary Feeds Only, For
Now") but is not implemented yet.

## Hierarchy

```
run_separation()            separation_trial.py
    builds + simulates ONE BinaryDistillation column for a given
    reflux_ratio_k, reports feasible/not + cost + stream data
        │
        ▼
sweep_reflux_ratio()        sweep_separation.py
    calls run_separation() once per reflux_ratio_k in a list,
    collects the per-run results dicts into one DataFrame
        │
        ▼
annualize_sweep()           sep_economic_analysis.py
    adds $/yr columns to that DataFrame: annualized CAPEX
    (CAPEX_USD / lifetime_years) + annualized utility cost
        │
        ▼
find_best_design()          best_design.py
    filters the annualized DataFrame to feasible==True rows,
    returns whichever has the lowest total annualized cost
        │
        ▼
optimize_reflux_ratio()     optimizer.py
    ties all four steps above together behind one call:
    feed + spec + reflux range + economic assumptions in,
    {best_design, sweep_results, sweep_df, n_feasible, key_selection, ...} out
```

`optimize_reflux_ratio()` is the intended entry point for most uses — call
it once and read `result['best_design']`. The lower layers (`run_separation`,
`sweep_reflux_ratio`, `annualize_sweep`, `find_best_design`) exist to be
composed that way, but each is also usable standalone (e.g. to scope a
single column, or to re-cost an existing sweep DataFrame with a different
`lifetime_years`).

Before running the sweep, `optimize_reflux_ratio()` also calls
`validate_key_selection()` (same module) as a sanity check on the
`LHK` pair itself, independent of reflux ratio — see
[`validate_key_selection()`](#validate_key_selection-key-selection-sanity-check)
in the `optimizer.py` section below.

## Files in this folder

| File | Role |
|---|---|
| `separation_trial.py` | `run_separation()` — single-column build + simulate + feasibility check. |
| `sweep_separation.py` | `sweep_reflux_ratio()` — runs `run_separation()` across a list of reflux ratios into a DataFrame. |
| `sep_economic_analysis.py` | `annualize_capex()`, `annualize_utilities()`, `annualize_results()`, `annualize_sweep()` — turn CAPEX + hourly utility cost into $/yr figures, for one run or a whole sweep. |
| `best_design.py` | `find_best_design()` — picks the lowest-annualized-cost feasible row out of an annualized sweep. |
| `optimizer.py` | `optimize_reflux_ratio()` — the high-level function that chains all of the above. |
| `problem_spec.py` | `validate_problem()`, `check_essential_inputs()`, `identify_case()` — deterministic, LLM-free implementation of the Wankat Table 3-1/3-2 structured input check from `tools/binary-distillation-context.md`. |
| `case_design.py` | `design_binary_distillation()` — executes one already-identified Wankat Case A/B design as a single deterministic run (not a cost sweep); reports Case C/D as recognized-but-not-implemented. |
| `separation_plots.py` | `plot_purity_vs_reflux()`, `plot_utility_cost_vs_reflux()`, `plot_reflux_sweep()` — matplotlib plots of a sweep DataFrame (achieved-vs-target performance, utility cost) against `reflux_ratio_k`. |
| `separation_tool.py` | `design_separation_case()` and `optimize_separation()` — JSON-in/JSON-out wrappers around `case_design.design_binary_distillation()` and `optimizer.optimize_reflux_ratio()` respectively, built to be handed to Ollama as tools. |
| `separation_agent.py` | Natural-language chat front end (Ollama + `qwen3:8b`) that calls `design_separation_case()`/`optimize_separation()` on the model's behalf. |
| `feed_state.py` | `apply_user_update()`, `normalize_feed_state()`, `assess_feed_state()` — feed identity/quantity state layer with provenance tracking; sits ahead of the binary-scope gate in `binary_distillation_workflow.py`. |
| `binary_distillation_workflow.py` | `assess_binary_distillation_problem()` — deterministic, LLM-free workflow/case-routing checker; never performs a calculation. |
| `binary_distillation_workflow_agent.py` | Ollama tool-calling front end exposing `assess_binary_distillation_problem()` (WRITE/READ) plus `calculate_current_binary_distillation_problem()` (CALCULATE); the latter can only ever perform the deterministic feed-phase check, never Wankat Case A-D sizing, by construction. |
| `biosteam_feed.py` | `build_biosteam_feed()` — converts a `ready_for_calculation` workflow assessment into one canonical `bst.Stream`; no LLM involvement. |
| `feed_phase.py` | `evaluate_feed_phase()` — deterministic VLE feed-phase evaluation (T/P, V/P, or H/P) and liquid/vapor/vapor_liquid classification. |
| `feed_partial_condensation.py` | `evaluate_vapor_feed_at_reference_temperature()` — deterministic rigorous-BioSTEAM screen conditioning the overall feed to a fixed 313.15 K reference temperature; runs whenever `evaluate_feed_phase()` reports any vapor fraction (`vapor` or `vapor_liquid`), never for a `liquid` feed. |
| `binary_distillation_calculation.py` | `calculate_binary_distillation_problem()` — the calculation-layer entry point downstream of the workflow checker; chains `assess_binary_distillation_problem()` → `build_biosteam_feed()` → `evaluate_feed_phase()` → (for `vapor`/`vapor_liquid`) `evaluate_vapor_feed_at_reference_temperature()` → deterministic routing. |
| `sample_request.py` | Minimal standalone Ollama connectivity smoke test (`client.generate(...)`) — not part of the tool-calling pipeline; predates and is unrelated to `separation_agent.py`. |
| `testing_caes.ipynb` | Scratch/interactive notebook for ad hoc testing — not a maintained module; nothing else in this folder imports it. |

The runnable end-to-end example living outside this folder is
`atj_saf/demo_separation.py`, which calls `optimize_reflux_ratio()` on a
toy Water/Methanol feed and plots the resulting sweep.

## A note on imports within this folder

Every module here imports its neighbors with a bare same-directory import
(e.g. `sweep_separation.py` does `from separation_trial import run_separation`,
`optimizer.py` does `from sweep_separation import sweep_reflux_ratio`, etc.),
not a package-relative import. That only resolves when this directory is on
`sys.path` — true automatically when you `cd` here and run one of these
files directly (`python optimizer.py`), but **not** when importing this
folder from elsewhere (e.g. from a script in `atj_saf/`). Callers outside
this folder need to add it to `sys.path` first, then import bare (not as a
package):

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'tools' / 'chopper'))

from optimizer import optimize_reflux_ratio
```

`atj_saf/demo_separation.py` does exactly this — see that file for a working
example.

---

# `separation_trial.py`

A trial/scoping helper for running a single BioSTEAM `BinaryDistillation`
column to a user-defined separation target. It is **not an optimizer** — it
builds the column exactly as specified, simulates it once, and reports
whether the target was actually met, along with cost and stream data.

The module exposes one function: `run_separation(...)`.

## A note on reflux ratio terminology: `k` vs. absolute L/D

Every function in this file and in `sweep_separation.py`/`separation_plots.py`
takes a reflux ratio *input* named **`reflux_ratio_k`** (or, in the sweep,
`reflux_ratios_k`). This is **not** an absolute reflux ratio — it is
BioSTEAM's shortcut (Fenske-Underwood-Gilliland) multiplier `k`, defined as:

```
k = actual_reflux_ratio_LD / minimum_reflux_ratio_LD
```

You supply `k`; BioSTEAM works out the column's minimum reflux ratio for the
given separation and multiplies it by `k` internally to get the absolute
reflux ratio (L/D) actually used. The two absolute quantities that come out
of that calculation are always named with an `_LD` suffix and only ever
appear in *outputs*, never as something you pass in:

- **`actual_reflux_ratio_LD`** — the absolute L/D the column actually runs at.
- **`minimum_reflux_ratio_LD`** — the absolute L/D minimum reflux for that separation.

So `reflux_ratio_k=2` does **not** mean "L/D = 2" — it means "run at 2x the
minimum reflux," whatever absolute L/D that works out to. Keep an eye on the
`_k` vs. `_LD` suffixes throughout the tables below; they are the only thing
distinguishing the input multiplier from the two absolute values it produces.

## What you need to provide (inputs)

| Argument | Required? | Description |
|---|---|---|
| `feed` | Yes | A `bst.Stream` feed to the column. `bst.settings.set_thermo(...)` must already be called before building it. Must have exactly 2 components with nonzero flow — `run_separation` raises `ValueError` (via `check_binary_feed`) for 3+ nonzero-flow components; see the "Scope" note above. |
| `LHK` | Yes | `(light_key, heavy_key)` — the two component IDs the column is designed around (with a binary feed, this is just the feed's two components, in either order). |
| `reflux_ratio_k` | Yes | `k` — see [A note on reflux ratio terminology](#a-note-on-reflux-ratio-terminology-k-vs-absolute-ld) above. **Not the absolute L/D itself** — that's reported back in the output as `actual_reflux_ratio_LD` and `minimum_reflux_ratio_LD`. |
| `P` | No (default `101325`) | Column pressure in Pa. |
| `spec` | No (default `'purity'`) | `'purity'` or `'recovery'` — which kind of target to check feasibility against. |
| `target` | No (default `'top'`) | `'top'` or `'bottom'` — which outlet is the product you care about. `'top'` checks the light key in the distillate; `'bottom'` checks the heavy key in the bottoms. The other outlet is reported as `waste`. |
| `y_top`, `x_bot` | Needed together if `spec='purity'` | Target light-key molar fraction (light-key/heavy-key basis) in the distillate and bottoms, respectively. Both are required to fully specify the shortcut method, even though only the end named by `target` is checked as "the target." |
| `Lr`, `Hr` | Needed together if `spec='recovery'` | Target fractional recovery of the light key to the distillate (`Lr`) and the heavy key to the bottoms (`Hr`). Both required, same reasoning as above. |
| `is_divided` | No (default `True`) | Passed straight to `BinaryDistillation` (divided vs. non-divided column). |
| `tol` | No (default `1e-3`) | Absolute tolerance used when checking achieved vs. target. |
| `ID` | No (default `'D1'`) | Unit ID for the column. Also names the two outlet streams (`{ID}_distillate`, `{ID}_bottoms`), so repeated calls with different IDs (e.g. a parameter sweep) don't collide in BioSTEAM's flowsheet registry. |
| `**design_kwargs` | No | Any other `BinaryDistillation` keyword arguments (e.g. `vessel_material`, `tray_type`, `stage_efficiency`), passed through unchanged. |

**Note on `y_top`/`x_bot`/`Lr`/`Hr`:** BioSTEAM's shortcut method needs
*both* ends of a spec pair to fully define the separation — you cannot give
only a top purity with no bottoms spec, or vice versa. This function keeps
that requirement, but lets you designate (via `target`) which end is the one
whose result actually gets checked and reported as "met" or not.

## What you get back (output)

A single `results` dictionary:

| Key | Contents |
|---|---|
| `feasible` | `bool`. `True` only if the column simulated successfully **and** the target (purity or recovery, whichever `spec` selects) was met within `tol`. |
| `error` | `None`, or a string with the exception message if the column failed to build/converge (e.g. spec unreachable in under 100 stages). |
| `purity` | `{'target', 'achieved', 'met'}`. `achieved` is the *overall* molar fraction of the target key actually present in the product stream (all components counted) — this can legitimately read lower than the LHK-basis `target` if non-key components end up in that stream. `target`/`met` are only populated when `spec='purity'`. |
| `recovery` | `{'target', 'achieved', 'met'}`. `achieved` = moles of target key in the product ÷ moles of target key in the feed. `target`/`met` are only populated when `spec='recovery'`. |
| `capex_usd` | Column installed cost (`float`). |
| `utilities` | `{'heating_duty_kJ_per_hr', 'heating_cost_USD_per_hr', 'cooling_duty_kJ_per_hr', 'cooling_cost_USD_per_hr'}`. |
| `streams` | `{'feed', 'product', 'waste'}`. Each is a dict: `{'stream': <bst.Stream>, 'flow_kg_per_hr': {component: kg/hr, ...}, 'total_kg_per_hr': float}`. `product` and `waste` are `None` if the simulation failed. |
| `operating_conditions` | `{'pressure_Pa', 'reflux_ratio_k', 'actual_reflux_ratio_LD', 'minimum_reflux_ratio_LD', 'theoretical_stages', 'feed_stage'}`. `reflux_ratio_k` echoes back the *input* multiplier k; `actual_reflux_ratio_LD` and `minimum_reflux_ratio_LD` are the *absolute* (L/D) reflux ratios BioSTEAM computed from it — do not confuse k with an L/D value. |
| `unit` | The simulated `BinaryDistillation` instance, or `None` if construction/simulation failed. |

## Example

```python
import biosteam as bst
from separation_trial import run_separation

bst.settings.set_thermo(['Water', 'Methanol'], cache=True)
feed = bst.Stream('feed', flow=(80, 100))
feed.T = feed.bubble_point_at_P().T

results = run_separation(
    feed, LHK=('Methanol', 'Water'), reflux_ratio_k=2, P=101325,
    spec='purity', target='top', y_top=0.99, x_bot=0.01,
)

results['feasible']                                  # True
results['purity']['achieved']                         # ~0.99
results['capex_usd']                                   # ~215,100
results['streams']['product']['flow_kg_per_hr']        # {'Water': ..., 'Methanol': ...}
```

Running `python separation_trial.py` directly executes two demo cases (one
`spec='purity'`, one `spec='recovery'`) and prints a summary of each.

---

# `sweep_separation.py`

A parameter-sweep helper built on top of `run_separation`. It runs the same
separation spec across a list of reflux ratios and collects the results into
a single `pandas.DataFrame` (optionally written to CSV). It is not an
optimizer either — just a way to scope out how a separation responds to
reflux ratio before you look at any specific design in detail.

The module exposes one function: `sweep_reflux_ratio(...)`.

## What you need to provide (inputs)

| Argument | Required? | Description |
|---|---|---|
| `feed` | Yes | A `bst.Stream` feed. A separate copy of this stream is made for every run in the sweep, so the original `feed` is never mutated or consumed. Must have exactly 2 nonzero-flow components — same `check_binary_feed` restriction as `run_separation`; see the "Scope" note above. |
| `LHK` | Yes | `(light_key, heavy_key)` — same meaning as in `run_separation`. |
| `reflux_ratios_k` | Yes | A sequence of `k` values — see [A note on reflux ratio terminology](#a-note-on-reflux-ratio-terminology-k-vs-absolute-ld) above. **Not** absolute L/D values. One column is built and simulated per value. |
| `P`, `spec`, `target`, `y_top`, `x_bot`, `Lr`, `Hr`, `is_divided`, `tol` | No | Passed straight through to `run_separation` unchanged on every run in the sweep — see `run_separation` above for what each one means. Only `reflux_ratio_k` (and the per-run `feed` copy/unit `ID`) vary across rows; sweeping separation specs (e.g. varying `y_top` too) is a future extension, not handled here. |
| `csv_path` | No (default `None`) | If given, the resulting DataFrame is written here via `df.to_csv(csv_path, index=False)`. |
| `**design_kwargs` | No | Any other `BinaryDistillation` keyword arguments, passed through to `run_separation` on every run. |

Each run gets its own feed copy (`f'{feed.ID}_sweep{i}'`) and its own unit
`ID` (`f'D_sweep{i}'`), so the sweep doesn't hit the flowsheet-registry
collisions that reusing one feed/ID across a loop would cause.

## What you get back (output)

A single `pandas.DataFrame`, one row per reflux ratio, with columns:

| Column | Contents |
|---|---|
| `reflux_ratio_k` | The *input* `k` multiplier for that row — not an absolute L/D value. |
| `actual_reflux_ratio_LD` | The resulting *absolute* reflux ratio (L/D) BioSTEAM computed from `reflux_ratio_k`. |
| `minimum_reflux_ratio_LD` | The *absolute* minimum reflux ratio (L/D) for that separation — `reflux_ratio_k = actual_reflux_ratio_LD / minimum_reflux_ratio_LD`. |
| `theoretical_stages` | Theoretical stage count for that column. |
| `purity` | Achieved purity, from `results['purity']['achieved']`. |
| `purity_target` | Target purity, from `results['purity']['target']` — `None` unless `spec='purity'`. |
| `recovery` | Achieved recovery, from `results['recovery']['achieved']`. |
| `recovery_target` | Target recovery, from `results['recovery']['target']` — `None` unless `spec='recovery'`. |
| `feasible` | Whether that row's run met its target, from `results['feasible']`. |
| `CAPEX_USD` | Column installed cost for that row. |
| `heating_cost_USD_hr` | Reboiler heating cost for that row. |
| `cooling_cost_USD_hr` | Condenser cooling cost for that row. |
| `error` | `None`, or the exception message if that row's run failed to converge. |

## Example

```python
import biosteam as bst
from sweep_separation import sweep_reflux_ratio

bst.settings.set_thermo(['Water', 'Methanol'], cache=True)
feed = bst.Stream('feed', flow=(80, 100), units='kmol/hr')
feed.T = feed.bubble_point_at_P().T

df = sweep_reflux_ratio(
    feed=feed,
    LHK=('Methanol', 'Water'),
    reflux_ratios_k=[1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5],
    spec='purity',
    target='top',
    y_top=0.99,
    x_bot=0.01,
    csv_path='reflux_ratio_sweep.csv',
)
```

Running `python sweep_separation.py` directly sweeps that same reflux ratio
list, prints the resulting DataFrame, and writes it to
`reflux_ratio_sweep.csv`.

---

# `sep_economic_analysis.py`

Turns the CAPEX and hourly utility cost that `run_separation`/
`sweep_reflux_ratio` report into annualized `$/yr` figures — straight-line
CAPEX annualization plus utility cost scaled up to a full operating year.
No optimization here either; it's pure unit conversion on top of numbers
that already exist.

Four functions, in increasing order of what they operate on:

| Function | Operates on | Returns |
|---|---|---|
| `annualize_capex(capex_usd, lifetime_years)` | A single CAPEX figure. | `capex_usd / lifetime_years`, or `None` if either input is `None`. |
| `annualize_utilities(heating_cost_usd_hr, cooling_cost_usd_hr, operating_days=330)` | A single run's hourly heating/cooling cost. | `(heating + cooling, $/hr) × (operating_days × 24 hr/day)`. |
| `annualize_results(results, operating_days=330, lifetime_years=None)` | One `run_separation(...)` output dict. | A dict of annualized figures for that one column (see below). |
| `annualize_sweep(df, operating_days=330)` | A whole `sweep_reflux_ratio(...)` DataFrame. | A copy of `df` with three new annualized columns added, one set of values per row. |

`DEFAULT_OPERATING_DAYS = 330` (0.9 operating factor) is the module-level
default used everywhere `operating_days` isn't given explicitly — it
matches the `lignin_saf` TEA convention.

## `annualize_results(results, ...)` — output

| Key | Contents |
|---|---|
| `lifetime_years` | Lifetime actually used (falls back to `results['lifetime_years']` if not passed in). |
| `operating_days` | Operating days/yr actually used. |
| `annualized_capex_usd_per_yr` | `capex_usd / lifetime_years`, or `None`. |
| `total_utility_cost_usd_per_yr` | `(heating_cost + cooling_cost) × operating_hours/yr`, or `None`. |
| `total_annual_cost_usd_per_yr` | `annualized_capex + total_utility_cost` — the headline $/yr figure for that column, or `None` if either input is missing (e.g. the run failed). |

## `annualize_sweep(df, ...)` — output

A copy of the input DataFrame with three columns appended, computed from
the existing `CAPEX_USD`, `lifetime_years`, `heating_cost_USD_hr`,
`cooling_cost_USD_hr` columns that `sweep_reflux_ratio` already produces:

| New column | Contents |
|---|---|
| `annualized_capex_usd_per_yr` | `CAPEX_USD / lifetime_years`, per row. |
| `total_utility_cost_usd_per_yr` | `(heating_cost_USD_hr + cooling_cost_USD_hr) × operating_hours/yr`, per row. |
| `total_annual_cost_usd_per_yr` | Sum of the two above — the column `find_best_design` (next section) minimizes over by default. |

## Example

```python
from sep_economic_analysis import annualize_sweep
from sweep_separation import sweep_reflux_ratio

df = sweep_reflux_ratio(feed=feed, LHK=('Methanol', 'Water'),
                         reflux_ratios_k=[1.5, 2.0, 2.5], spec='purity',
                         target='top', y_top=0.99, x_bot=0.01)
econ_df = annualize_sweep(df)
econ_df[['reflux_ratio_k', 'CAPEX_USD', 'total_annual_cost_usd_per_yr']]
```

Running `python sep_economic_analysis.py` directly demos both
`annualize_results` on a single `run_separation` call and `annualize_sweep`
on a full `sweep_reflux_ratio` sweep, printing each.

---

# `best_design.py`

Picks the lowest-annualized-cost **feasible** design out of a sweep. This
is the answer to "given the sweep, what's the best design?" — it runs no
new simulations; it just filters and sorts a DataFrame that already came
out of `annualize_sweep`.

The module exposes one function: `find_best_design(econ_df, cost_col='total_annual_cost_usd_per_yr')`.

## What you need to provide (inputs)

| Argument | Required? | Description |
|---|---|---|
| `econ_df` | Yes | Output of `sep_economic_analysis.annualize_sweep` (or any DataFrame with the same `feasible` and `cost_col` columns). |
| `cost_col` | No (default `'total_annual_cost_usd_per_yr'`) | Which column to minimize over among feasible rows. |

## What you get back (output)

A single `result` dictionary:

| Key | Contents |
|---|---|
| `found` | `bool` — `True` if at least one row in `econ_df` was feasible. |
| `design` | `dict` or `None` — the winning row (every column of `econ_df` for that reflux ratio) as a plain dict; `None` if nothing was feasible. |
| `message` | Human-readable one-line summary: either announcing the winning `reflux_ratio_k`/L-D/cost, or explaining that every row in the sweep failed or missed its target. |
| `n_feasible` | How many rows in `econ_df` were feasible. |
| `n_total` | How many rows `econ_df` had in total. |

If no row is feasible, `find_best_design` does **not** raise — it returns
`found=False`, `design=None`, and an explanatory `message`. Callers should
check `found` before reading `design`.

## Example

```python
from best_design import find_best_design

best = find_best_design(econ_df)
if best['found']:
    print(best['message'])
    best['design']['reflux_ratio_k']   # the winning k
```

Running `python best_design.py` directly runs the full
`sweep_reflux_ratio` → `annualize_sweep` → `find_best_design` chain on the
toy Water/Methanol/Glycerol feed and prints both the sweep table and the
winning design.

---

# `optimizer.py`

The high-level entry point for this whole folder: one function call that
chains `sweep_reflux_ratio()` → `annualize_sweep()` → `find_best_design()`
and hands back both the winner and the full sweep. It is still not a new
optimization method — same shortcut-method sweep as the layers below it,
just wired together so callers don't have to do it by hand.

The module exposes one function: `optimize_reflux_ratio(...)`.

## What you need to provide (inputs)

| Argument | Required? | Description |
|---|---|---|
| `feed` | Yes | Feed stream; a fresh copy is made per reflux ratio internally (via `sweep_reflux_ratio`) — `feed` itself is never mutated. Must have exactly 2 nonzero-flow components — same `check_binary_feed` restriction as `run_separation`; see the "Scope" note above. |
| `LHK` | Yes | `(light_key, heavy_key)` — same meaning as in `run_separation`. |
| `reflux_ratios_k` | Yes | The `k` values to sweep — see [the reflux ratio terminology note](#a-note-on-reflux-ratio-terminology-k-vs-absolute-ld) above. |
| `P` | No (default `101325`) | Column pressure in Pa. |
| `spec` | No (default `'purity'`) | `'purity'` or `'recovery'`. |
| `target` | No (default `'top'`) | `'top'` or `'bottom'`. |
| `purity_target` | Needed if `spec='purity'` and `y_top`/`x_bot` aren't given | Convenience shorthand: sets the symmetric pair `y_top=purity_target`, `x_bot=1-purity_target` (the 0.99/0.01 convention used everywhere else in this folder). |
| `recovery_target` | Needed if `spec='recovery'` and `Lr`/`Hr` aren't given | Convenience shorthand: sets `Lr=Hr=recovery_target`. |
| `y_top`, `x_bot` | No | Explicit purity spec — overrides `purity_target` if both given. |
| `Lr`, `Hr` | No | Explicit recovery spec — overrides `recovery_target` if both given. |
| `is_divided`, `tol` | No | Passed straight through to `run_separation` on every run — see `separation_trial.py` above. |
| `lifetime_years` | No (default `20`) | Column equipment lifetime, for CAPEX annualization. |
| `operating_days` | No (default `330`) | Plant operating days/yr, for utility cost annualization. |
| `cost_col` | No (default `'total_annual_cost_usd_per_yr'`) | Passed to `find_best_design` — which annualized column to minimize. |
| `csv_path` | No (default `None`) | If given, the raw (pre-annualized) sweep is written here (same as `sweep_reflux_ratio`'s own `csv_path`). |
| `**design_kwargs` | No | Any other `BinaryDistillation` keyword arguments, passed through to every run. |

Exactly one of (`purity_target`) or (`y_top` **and** `x_bot`) is required
when `spec='purity'`; exactly one of (`recovery_target`) or (`Lr` **and**
`Hr`) is required when `spec='recovery'`. Mixing (e.g. giving `y_top` but
not `x_bot`) raises `ValueError`.

## What you get back (output)

A single `result` dictionary:

| Key | Contents |
|---|---|
| `best_design` | `dict` or `None` — same as `find_best_design`'s `design`: the lowest-cost feasible row, or `None` if nothing was feasible. |
| `sweep_results` | `list[dict]` — the complete annualized sweep, one dict per reflux ratio (`econ_df.to_dict('records')`); JSON-friendly. |
| `sweep_df` | `pandas.DataFrame` — the same complete sweep, for direct use with `separation_plots.plot_reflux_sweep` or further analysis. |
| `n_feasible` | How many reflux ratios in the sweep were feasible. |
| `n_total` | How many reflux ratios were swept. |
| `found` | `bool` — whether at least one feasible design was found. |
| `message` | Human-readable summary from `find_best_design`. |
| `key_selection` | `dict` — output of `validate_key_selection(feed, LHK)`, run once before the sweep (see below). Present regardless of `found`/`n_feasible`; check `key_selection['warning']` before attributing an infeasible or unexpected result to reflux ratio. |

## `validate_key_selection()` — key-selection sanity check

**Currently dormant in practice.** Since `check_binary_feed()` now rejects
any feed with 3+ nonzero-flow components before `optimize_reflux_ratio()`
ever reaches this check, `validate_key_selection()` will always see a feed
with at most 2 nonzero-flow components in normal use — meaning
`distributed_components` is always empty and `valid` is always `True`
today. The function and its call site are kept as-is (rather than removed)
because they are exactly what ternary/multicomponent support will need
once that "Scope" restriction is lifted — see
`tools/binary-distillation-context.md`. The description below documents
what it does when given a genuinely ternary+ feed directly (i.e. called
standalone, bypassing the pipeline's binary check).

`optimize_reflux_ratio()` calls this automatically before sweeping reflux
ratios: `validate_key_selection(feed, LHK)`. It exists because the shortcut
(Fenske-Underwood-Gilliland) method only gives a meaningful answer when
`light_key` and `heavy_key` are **adjacent in relative volatility** — every
other feed component is expected to fall cleanly to one side of the split.
If a feed has 3+ components and some other component's boiling point falls
*between* the chosen keys, that component is a "distributed" component the
shortcut method can't resolve, and the resulting design — or its
infeasibility — may have nothing to do with reflux ratio at all. This is
exactly the failure mode that motivated the check: an agent (or a user)
picking the lightest and heaviest components in a ternary feed as `LHK`
while skipping over a middle-boiling component (e.g. `LHK=('Methanol',
'Glycerol')` in a Methanol/Water/Glycerol feed, skipping Water) will get an
infeasible sweep that has nothing to do with the reflux ratios tried.

This function only **checks and reports** — it never changes `LHK` or picks
keys on the caller's behalf.

**Inputs:** `feed` (`bst.Stream`, thermo already set — only components with
nonzero flow in `feed` are checked) and `LHK` (`(light_key, heavy_key)`,
same meaning as elsewhere in this folder).

**Output** — a single `dict`:

| Key | Contents |
|---|---|
| `valid` | `bool` — `True` if no other feed component's normal boiling point (`chemicals[ID].Tb`, K) falls strictly between the light key's and heavy key's. |
| `warning` | `str` or `None` — human-readable explanation naming the offending component(s), or `None` if `valid`. |
| `light_key`, `heavy_key` | Echoed back from `LHK`. |
| `light_key_Tb_K`, `heavy_key_Tb_K` | Normal boiling points (K) used for the comparison. |
| `distributed_components` | `list[dict]` — one `{'component', 'Tb_K'}` entry per feed component whose boiling point falls between the two keys'. Empty when `valid`. |

```python
from optimizer import validate_key_selection

check = validate_key_selection(feed, LHK=('Methanol', 'Glycerol'))
check['valid']       # False
check['warning']     # "...Water (Tb=373.1 K)... 'distributed' components the shortcut method cannot resolve..."
check['distributed_components']   # [{'component': 'Water', 'Tb_K': 373.1...}]
```

## Example

```python
from optimizer import optimize_reflux_ratio

result = optimize_reflux_ratio(
    feed=feed,
    LHK=('Methanol', 'Water'),
    reflux_ratios_k=[1.5, 1.75, 2.0, 2.25, 2.5],
    purity_target=0.99,
)

result['n_feasible']            # 5
result['best_design']['reflux_ratio_k']   # winning k, e.g. 1.5
result['message']               # "Best feasible design: reflux_ratio_k=1.5 ..."
```

Running `python optimizer.py` directly runs this exact example on the toy
Water/Methanol feed and prints the feasibility count, summary message,
`key_selection` result, and full best-design breakdown — then runs a
second demo that calls `optimize_reflux_ratio()` on a Water/Methanol/
Glycerol feed to show `check_binary_feed()` rejecting it up front with a
clear "ternary/multicomponent feed support is planned for a future
release" `ValueError`, caught and printed rather than propagated.

---

# `problem_spec.py` + `case_design.py` — deterministic Wankat Case A-D layer

These two modules implement the structured input-check procedure from
`tools/binary-distillation-context.md` (itself based on Wankat, P.C.
*Separation Process Engineering*, 2022, Tables 3-1 and 3-2), so that
whether a binary-distillation request is completely and unambiguously
specified — and which of Wankat's four design cases it matches — is
determined by deterministic code, never by asking an LLM to infer it.

## `problem_spec.py`

Pure field-presence logic over a plain `dict` — no BioSTEAM or LLM calls.
Three functions:

| Function | Does |
|---|---|
| `check_essential_inputs(spec)` | Step 1: checks Wankat Table 3-1's "usual specified variables" are all present — `pressure_Pa`, `components` (feed flow + composition), a feed thermal condition (**exactly one** of `feed_temperature_K`, `feed_quality`, `feed_enthalpy_kJ_per_hr` — never defaulted, e.g. never silently set to bubble point), and `reflux_condition` (must be stated explicitly; today only the literal string `'saturated_liquid'` is supported, since that's the only condition the underlying shortcut column model implements). |
| `identify_case(spec)` | Steps 2-3: deterministically matches whichever of `xD`/`xB`, `Lr`/`Hr`, `distillate_flow`/`bottoms_flow`, `boilup_ratio_VB`, `external_reflux_ratio_LD`, `reflux_ratio_multiplier_k` are present against Wankat's Cases A-D (see `tools/binary-distillation-context.md` section 2). Detects genuine conflicts (e.g. both `external_reflux_ratio_LD` *and* `reflux_ratio_multiplier_k` given — these are explicitly **not** the same quantity, see that doc's section 4) as `ambiguous`, and reports, for every case still consistent with what's given so far, exactly which of its fields remain missing. **No default to Case A** — per `tools/binary-distillation-workflow.md` section 7, when nothing case-distinguishing has been given yet (none of `xD`/`xB`, `Lr`/`Hr`, a product flow, or a boilup ratio), `case_candidates` lists every case still consistent (typically all four, A-D), each with its own missing fields, rather than narrowing to Case A. As soon as something case-specific is actually given (most commonly `Lr`/`Hr`), the candidate set narrows to whichever case that information matches instead. |
| `validate_problem(spec)` | Runs both of the above and returns one report: `{'valid', 'case', 'case_candidates', 'missing_essential_inputs', 'missing_case_inputs_by_candidate', 'ambiguous', 'ambiguous_reason', 'message', 'provenance'}`. `provenance` always carries the Table 3-1/Table 3-2/full-citation strings (`TABLE_3_1_PROVENANCE`, `TABLE_3_2_PROVENANCE`, `FULL_CITATION` module constants), per that doc's section 9 ("this provenance should be retained ... in the ... binary-distillation tool documentation"). `valid` is `True` only when every Table 3-1 essential is present, unambiguous, and exactly one Case A-D is fully satisfied. |

`validate_problem()` never raises and never picks a value on the caller's
behalf — callers (`separation_tool.py`) are expected to check `valid`
before building any feed stream or BioSTEAM unit, and to surface
`message`/`missing_*`/`ambiguous_reason` back to the user/LLM instead of
guessing. Running `python problem_spec.py` directly prints eight demo
reports (nothing given; a complete Case A; Case A missing `xB`; an
ambiguous L0/D-and-k spec; a missing feed thermal condition; essentials +
L0/D only — candidates narrow to A/B/C, not D, since D has no reflux ratio;
essentials only, nothing case-specific — all four cases A-D are candidates;
only `Lr` given — narrows to Case B).

## `case_design.py`

`design_binary_distillation(feed, LHK, case, ...)` executes **one**
already-identified case as a single deterministic run — this is a
direct-design calculation (Wankat gives you one answer for one stated
reflux ratio), not a cost sweep like `optimizer.optimize_reflux_ratio()`.
It assumes the caller already ran `problem_spec.validate_problem()` and
that `feed`'s thermal condition was already set explicitly (it never calls
`feed.bubble_point_at_P()` or otherwise imposes a condition itself).

Only **Case A** (`xD`/`xB` + a reflux ratio) and **Case B** (`Lr`/`Hr` + a
reflux ratio) are actually executable today — the underlying BioSTEAM
shortcut `BinaryDistillation` model has no way to accept a direct
product-flow-rate spec (Case C) or a boilup-ratio spec (Case D) as an
input. `IMPLEMENTED_CASES = ('A', 'B')`; calling with `case='C'` or
`case='D'` returns `{'implemented': False, 'message': ...}` explaining
this rather than silently forcing the request through the Case A/B
machinery.

**Converting `external_reflux_ratio_LD` to the internal `k`:** Wankat's
Cases A-C specify the external/actual reflux ratio L0/D directly, but the
BioSTEAM shortcut column only accepts the multiplier `k = R/Rmin` (see
`separation_trial.py`'s note on `k` vs. absolute L/D). When the caller
supplies `external_reflux_ratio_LD` (rather than `reflux_ratio_multiplier_k`
directly), `design_binary_distillation()`:

1. Runs the column once at a trial `k` purely to read back
   `minimum_reflux_ratio_LD` from BioSTEAM's design results (this is
   computed via the Underwood equations independent of the `k` chosen, so
   any converged trial run reveals it).
2. Computes `k_actual = external_reflux_ratio_LD / minimum_reflux_ratio_LD`.
   If `external_reflux_ratio_LD <= minimum_reflux_ratio_LD`, the request is
   infeasible (would need infinite stages) and this is reported directly
   rather than attempting to simulate it.
3. Re-runs the column once more at `k_actual` for the real design.

The result's `'reflux'` dict always reports `external_reflux_ratio_LD`,
`reflux_ratio_multiplier_k`, and `minimum_reflux_ratio_LD` together with a
`'basis'` field (`'user_specified_external_LD'` vs.
`'user_specified_internal_k'`) so the two reflux quantities are never
conflated in the output either. Running `python case_design.py` directly
demos both conversion paths plus the Case C not-implemented message.

---

# `binary_distillation_workflow.py` + `binary_distillation_workflow_agent.py` — workflow-only checker

Implements `tools/binary-distillation-workflow.md` in full: a binary-
distillation **problem-definition and workflow-routing** layer that never
performs a distillation calculation, sizing, or optimization. It is a
separate, standalone alternative front end onto the same Wankat Table 3-1/
3-2 logic in `problem_spec.py` above — `case_design.py`/`optimizer.py`
(and BioSTEAM) are never imported or called from this pair of files.

## `feed_state.py` — feed identity/quantity separation

Implements `tools/binary-distillation-flow-rate-issue.md` in full: the
feed-state layer `binary_distillation_workflow.py` runs *before* its
binary-scope gate and Table 3-1/3-2 checks. No BioSTEAM or LLM calls.

The root problem it fixes: an earlier version of the workflow schema used
a single `components: dict[str, float]` field for both "which chemicals
are present" and "how much of each" — which meant a tool-calling model
either had to invent numbers just to name components, or risked treating
one component's stated flow as the total feed flow. `feed_state.py`
represents these as separate fields instead: `component_names` (identity,
`list[str]`), `component_flows` (per-component quantities actually
stated), `total_flow`, and `composition` — each quantity tagged with its
own provenance, `'user_explicit'` or `'derived'` (never `'assumed_by_llm'`
— there is no such state).

| Function | Does |
|---|---|
| `empty_feed_state()` | A feed state with no identity and no quantity information. |
| `apply_user_update(state, update)` | Non-destructive merge of a partial update into `state`. `component_names` in `update` REPLACES the feed's identity and clears any previously-known flows/total_flow/composition (a changed identity invalidates old quantities — e.g. naming a *different* separation after an unsupported 3-component request must not leave stale flows behind). `add_component_names` instead APPENDS to the existing identity without touching known quantities (e.g. answering "please specify the second component" with a bare name). `component_flows`/`composition` are merged key-by-key and marked `'user_explicit'`; naming a component's flow or composition also adds it to `component_names` if not already there — but never the reverse (naming a component never creates a flow). |
| `normalize_feed_state(state)` | Deterministically derives `total_flow`/`component_flows`/`composition` entries that are mathematically FORCED by what's already `user_explicit` (e.g. both component flows known → total + composition derived; total + all-but-one flow known → the missing flow derived; one of two binary mole fractions known → the complement derived). Never invents a value beyond what the math requires. Also cross-checks redundant explicit values for contradictions (e.g. component flows that don't sum to an explicitly-given total) and returns `(new_state, conflicts)` — a non-empty `conflicts` list means the caller should treat the feed as `inconsistent_input` rather than proceed. |
| `feed_completeness(state)` | `(feed_flow_complete, feed_composition_complete)` — `feed_flow_complete` is `total_flow is not None`; `feed_composition_complete` is a fraction known (explicit or derived) for every named component. |
| `assess_feed_state(state)` | Normalize + validate + completeness in one call; also returns the canonical `components` dict (`name -> flow`) the Table 3-1/3-2 layer below expects, populated only once both completeness flags are `True`. |

Running `python feed_state.py` directly prints seven demo reports covering
component-names-only, a single component flow, both component flows,
total-flow-plus-one-flow, a single mole fraction, and a deliberately
inconsistent case (flows summing to 100 vs. an explicit total of 120).
`tools/chopper/test_feed_state.py` is a pytest suite implementing all
twelve acceptance tests from the issue doc's section 17, plus merge/
replace/append and purity (non-mutation) checks. Run with:
```bash
pytest tools/chopper/test_feed_state.py -v
```

## `binary_distillation_workflow.py`

No BioSTEAM or LLM calls — pure field-presence logic, same spirit as
`problem_spec.py` (which it wraps and reuses `check_essential_inputs()`/
`identify_case()` from directly) and `feed_state.py` above (which it
inserts as a layer before everything else). One function:

`assess_binary_distillation_problem(spec)` — runs, in order:

0. **Feed-state normalization** (`feed_state.apply_user_update()` +
   `feed_state.assess_feed_state()`): builds a feed state from `spec`'s
   `component_names`/`add_component_names`/`component_flows`/
   `component_flow_units`/`total_flow`/`total_flow_units`/`composition`/
   `composition_basis` fields (see `feed_state.py` above), then derives
   whatever is mathematically determined. If the redundant information
   given conflicts, returns `status='inconsistent_input'` immediately,
   naming the specific contradiction.
1. **Binary-scope gate** (`check_binary_scope()`, workflow doc section 2,
   updated for the identity/quantity split): counts entries in the
   normalized state's `component_names` — identity alone, independent of
   whether a flow is known for each — and returns
   `status='need_components'` (0 or 1 named) or
   `status='unsupported_multicomponent'` (3+ named) before checking
   anything else. Never silently drops a component to force a feed into
   scope.
2. **Essential inputs**: the feed's `feed_flow_complete`/
   `feed_composition_complete` flags (from step 0) are checked directly —
   a component name is never enough on its own, and a single component's
   flow is never read as the total. Table 3-1's other three essentials
   (pressure, feed thermal condition, reflux condition) are still checked
   via `problem_spec.check_essential_inputs()`. Any of the four missing
   yields `status='need_essential_inputs'`; the message distinguishes
   "nothing about the feed quantity has been given yet" from "some feed
   quantity was given (e.g. one component's flow), but it's not enough" —
   see `_feed_quantity_message()`.
3. **Case identification** (`problem_spec.identify_case()`, Table 3-2):
   `status='ambiguous'` on a genuine conflict; `status='need_case_definition'`
   when nothing case-distinguishing has been given at all (`case_candidates`
   lists every case still open, typically all four — **no default to Case
   A**, workflow doc section 7); `status='need_case_inputs'` once the
   candidate set has narrowed but a candidate (or the optimum-feed-plate
   confirmation) is still incomplete.
4. **Optimum feed plate** (`use_optimum_feed_plate`, workflow doc section
   12): checked only once a single case is otherwise fully satisfied, and
   only after step 3 — it never influences case identification, since it's
   common to all four cases.
5. **Calculation-input readiness** (`check_calculation_inputs()`, added by
   `tools/binary-distillation-flow-units.md` — see the dedicated subsection
   right after this list): once Wankat's essentials + case + optimum-feed-
   plate are all satisfied, a **separate** check verifies the flow-rate
   units the downstream BioSTEAM feed adapter needs (`component_flow_units`
   or `total_flow_units`) are actually present. If not,
   `status='need_calculation_inputs'` — the engineering problem definition
   ("workflow definition complete") is NOT automatically the same thing as
   "calculation ready."
6. **Ready for calculation**: only once step 5 also passes,
   `status='ready_for_calculation'` and `would_calculate` lists exactly
   what a designer would compute for that case (workflow doc section 8;
   Case C's list depends on which of `distillate_flow`/`bottoms_flow` and
   `xD`/`xB` was actually given, since the other one is what gets
   calculated). `would_calculate_details` reports the same set of
   quantities with explicit engineering metadata — see "The
   `BINARY_DISTILLATION_QUANTITIES` registry" subsection right after this
   list. `calculation_performed` is **always `False`** — this
   function never builds a feed stream or calls BioSTEAM.

Return schema (workflow doc section 15, extended by
`tools/binary-distillation-flow-rate-issue.md` section 8/10,
`tools/binary-distillation-pending-truth.md` section 2/18,
`tools/binary-distillation-flow-units.md`, and
`tools/chopper/binary-distillation-incorrect-symbol-reading-issue.md`):
`{'valid_binary_scope', 'component_count', 'components',
'feed_flow_complete', 'feed_composition_complete', 'feed',
'essential_complete', 'missing_essential_inputs', 'case', 'case_candidates',
'case_complete', 'missing_case_inputs', 'optimum_feed_plate_confirmed',
'calculation_inputs_complete', 'missing_calculation_inputs', 'status',
'would_calculate', 'would_calculate_details', 'calculation_performed',
'message', 'provenance', 'pending_request'}`.
`feed` is the normalized `feed_state` dict (component flows/total flow/
composition, each with its provenance) — present on every result once the
scope gate passes, primarily for audit/debugging rather than for the
caller to reproduce logic from. `status` can also be `'inconsistent_input'`
when redundant feed information disagreed (e.g. component flows don't sum
to an explicitly-given total flow). Never raises. Running `python
binary_distillation_workflow.py` directly prints demo reports covering
the scope gate, component-names-only (no invented flows), a single
component flow (not treated as the total), missing essentials, an
inconsistent-input case, the no-case-signal state, boilup-ratio routing to
Case D, a complete Case D report blocked on missing calculation units, and
the same report once units are supplied.

### Calculation-input readiness — `check_calculation_inputs()` and `need_calculation_inputs`

Implements `tools/binary-distillation-flow-units.md` in full: a small
readiness layer that sits strictly AFTER Wankat completeness
(`essential_complete`/`case_complete`/`optimum_feed_plate_confirmed`) and
BEFORE `status='ready_for_calculation'` is ever returned. It fixes a real
inconsistency: without it, the workflow could report
`status == "ready_for_calculation"` while the downstream BioSTEAM
calculation (`biosteam_feed.build_biosteam_feed()`) still cannot run,
because it has no flow-rate units to build a `bst.Stream` with.

```text
workflow definition complete (essentials + case + optimum feed plate)
        ↓
calculation-specific inputs complete?      check_calculation_inputs()
        ↓
YES → ready_for_calculation
NO  → need_calculation_inputs
```

`check_calculation_inputs(feed_state)` takes the already-normalized
`feed_state` (the output of `feed_state.assess_feed_state()`, i.e. what
ends up in `assessment['feed']`) and returns `{'complete': bool,
'missing': list[str]}`. It never defaults a unit, never reads one from
conversation history, and never re-derives Wankat Table 3-1 — this is
purely a calculation-adapter requirement, checked separately so
`essential_complete` keeps meaning exactly what it always meant.

The subtlety it handles: `feed_state.normalize_feed_state()` derives
`component_flows` for BOTH representations once the feed is complete —
per-component flows given directly, or `total_flow` + `composition` given
instead — so a plain "is `component_flows` non-empty?" check can't tell
which representation the user actually used (it would basically always be
true). `check_calculation_inputs()` looks at PROVENANCE instead: whichever
of `component_flows`/`total_flow` carries `'user_explicit'` entries is the
representation actually supplied, and that is the one whose units field
(`component_flow_units` or `total_flow_units` respectively) is required.
`biosteam_feed.build_biosteam_feed()` itself only ever needs ONE of the two
units fields (it accepts either), so at most one field is ever reported
missing.

When incomplete, `assess_binary_distillation_problem()` returns
`status='need_calculation_inputs'` instead of `'ready_for_calculation'`,
with `calculation_inputs_complete=False` and `missing_calculation_inputs`
naming the single missing field (e.g. `['component_flow_units']`). A
matching `pending_request` (`{'field': ..., 'request_type': 'flow_units',
'prompt': ...}`) is generated by `_calculation_pending_request()` whenever
exactly one field is missing — the same never-guess-between-genuinely-
ambiguous-fields discipline as `_case_pending_request()`/
`_essential_pending_request()` above.

**Deterministic unit normalization and WRITE resolution
(`binary_distillation_workflow_agent.py`):** `normalize_units_reply()`
maps a small, fixed set of common phrasings (case/spacing-insensitive) to
the canonical unit string, e.g. `"KMOL/HR"`, `"kmol per hour"`,
`"kilomoles per hour"` all → `"kmol/hr"`; `"kg per hour"`,
`"kilograms per hour"` → `"kg/hr"` — via the `_FLOW_UNIT_ALIASES` table.
Unlike `normalize_short_reply()` (used for boolean/numeric pending
replies), it deliberately preserves `/`, since that's meaningful in a unit
string. `resolve_pending_reply()` was extended with a
`request_type == 'flow_units'` branch that calls it on the RAW reply text
(not the slash-stripped `normalized` variable used by the other branches)
and, on a match, returns `{field: normalized_unit}` — the same
`ask()`-level pending-reply short-circuit described above then turns this
directly into a real `update_binary_distillation_problem(...)` WRITE
before the model ever sees the message, so a bare `"KMOL/HR"` reply to a
live `component_flow_units` pending request is never misread as a request
to just look up state (`get_binary_distillation_problem`) and never left
for the model to (possibly) get right on its own. An unrecognized
phrasing resolves to `None` and falls through to normal model-driven tool
selection rather than being forced through with a guessed unit.

`SYSTEM_PROMPT`'s FLOW-UNIT EXTRACTION RULE tells the model to preserve
units in the SAME `update_binary_distillation_problem` call whenever the
user states a flow rate together with its units (e.g. "50 kmol per hour
methanol and 50 kmol per hour water" → `component_flows={...}` AND
`component_flow_units="kmol/hr"` together) — this reduces how often the
deterministic units fallback above is needed, but the workflow still
rejects `ready_for_calculation` if the model fails to extract them; the
`NEED_CALCULATION_INPUTS` prompt block tells the model never to claim
`ready_for_calculation` while this status shows, and never to infer or
default the missing unit (e.g. never assume `"kmol/hr"` just because it's
the usual choice).

`SYSTEM_PROMPT` carries an analogous **FEED TEMPERATURE EXTRACTION RULE**
for `feed_temperature_K` — see "Deterministic feed-temperature extraction"
further below, under the `pending_request` section.

`biosteam_feed.py` remains strict regardless: it never silently defaults
or converts a unit (`units = units or "kmol/hr"` is exactly what this
layer exists to make unreachable), so a `BiosteamFeedError` there stays a
defensive backstop rather than the normal path.

`tools/chopper/test_binary_distillation_workflow.py` covers
`check_calculation_inputs()`/`need_calculation_inputs` directly (missing
`component_flow_units` on the `component_flows` path, present → ready,
missing `total_flow_units` on the `total_flow`+`composition` path, and
that earlier statuses never surface a premature
`need_calculation_inputs`). `tools/chopper/test_binary_distillation_pending_truth.py`
covers the `pending_request`/`normalize_units_reply`/`resolve_pending_reply`
side. `tools/chopper/test_binary_distillation_workflow_agent_calculation.py`
covers the full agent-level replay: a complete Case D spec missing only
`component_flow_units` reports `need_calculation_inputs`; a `"KMOL/HR"`
reply performs a real WRITE (never a READ) and reaches
`ready_for_calculation`; and a subsequent feed-phase question then runs the
real calculation without asking for units again.

### The `BINARY_DISTILLATION_QUANTITIES` registry — deterministic engineering labels

Implements `tools/chopper/binary-distillation-incorrect-symbol-reading-issue.md`:
a single authoritative mapping, in `binary_distillation_workflow.py`, from
every engineering symbol this workflow can report in `would_calculate` to
its field name and human-readable meaning. It exists because Qwen was
observed reinterpreting a bare returned symbol from its own model
knowledge — most concretely, reading `QR` as "reflux flow rate" when this
workflow means "reboiler duty." The fix keeps Python, not the LLM,
authoritative for what a symbol *means*, not just which symbols apply.

```python
BINARY_DISTILLATION_QUANTITIES = {
    'D':               {'field': 'distillate_flow',        'symbol': 'D',     'label': 'distillate flow rate'},
    'B':               {'field': 'bottoms_flow',            'symbol': 'B',     'label': 'bottoms flow rate'},
    'xD':              {'field': 'distillate_composition',  'symbol': 'xD',    'label': 'distillate composition'},
    'xB':              {'field': 'bottoms_composition',     'symbol': 'xB',    'label': 'bottoms composition'},
    'QR':              {'field': 'reboiler_duty',           'symbol': 'QR',    'label': 'reboiler duty'},
    'Qc':              {'field': 'condenser_duty',          'symbol': 'Qc',    'label': 'condenser duty'},
    'N':               {'field': 'number_of_stages',        'symbol': 'N',     'label': 'number of stages'},
    'Nfeed':           {'field': 'optimum_feed_stage',      'symbol': 'Nfeed', 'label': 'optimum feed stage'},
    'column_diameter': {'field': 'column_diameter',         'symbol': None,    'label': 'column diameter'},
}
```

`label` wording is taken from this project's own established terminology —
`tools/binary-distillation-context.md` section 7 ("Reboiler/heating load,
QR" / "Condenser/cooling load, Qc") and this agent's own prompt text
("reboiler/condenser duty") — not from generic model knowledge, and not
invented for this task.

**`would_calculate_details`** is the structured counterpart to the
pre-existing `would_calculate` (bare strings, e.g. `'QR'`): once `status`
is `ready_for_calculation`, it's a list of `{'field', 'symbol', 'label'}`
dicts, one per quantity, built by `_would_calculate_details(case, spec)`
from `WOULD_CALCULATE_KEYS_BY_CASE`/`BINARY_DISTILLATION_QUANTITIES` — the
same case-A/B/D membership as the legacy `WOULD_CALCULATE_BY_CASE`, and the
same Case C give-one/get-the-other-back logic as `_would_calculate`, just
expressed as registry keys instead of display strings. For example, a
complete Case A returns:

```python
[
    {'field': 'distillate_flow', 'symbol': 'D', 'label': 'distillate flow rate'},
    {'field': 'bottoms_flow', 'symbol': 'B', 'label': 'bottoms flow rate'},
    {'field': 'reboiler_duty', 'symbol': 'QR', 'label': 'reboiler duty'},
    {'field': 'condenser_duty', 'symbol': 'Qc', 'label': 'condenser duty'},
    {'field': 'number_of_stages', 'symbol': 'N', 'label': 'number of stages'},
    {'field': 'optimum_feed_stage', 'symbol': 'Nfeed', 'label': 'optimum feed stage'},
    {'field': 'column_diameter', 'symbol': None, 'label': 'column diameter'},
]
```

`would_calculate` itself is kept byte-for-byte unchanged (same strings, same
case membership) purely for backward compatibility with existing callers/
tests; new code — and the agent prompt — should read `would_calculate_details`
for engineering meaning. The deterministic `ready_for_calculation` message
was also updated to render from this registry (`"QR (reboiler duty)"`
instead of a bare `"QR"`), so the human-readable summary can no longer omit
a symbol's meaning either.

`binary_distillation_workflow_agent.py`'s `SYSTEM_PROMPT` carries a matching
**ENGINEERING OUTPUT GROUNDING RULE**: when a tool result supplies a
quantity's `symbol` and `label`, Qwen must use that `label` verbatim and
must never expand, reinterpret, or redefine the symbol from its own
knowledge — with the QR/reboiler-duty case given as the explicit worked
example, and "reflux flow rate" named as the specific wrong answer to never
substitute. A companion rule covers the legacy bare-string path: if
`would_calculate` ever contains a symbol with no matching
`would_calculate_details` entry, Qwen repeats the bare symbol rather than
inventing a definition for it.

`tools/chopper/test_binary_distillation_workflow.py` covers the registry
directly: every currently supported symbol has the correct label (using
this project's own terminology, not a generic one), Case A/B/C/D each
return the correct structured set, and `would_calculate`'s legacy strings/
case membership are unaffected by the new field.
`tools/chopper/test_binary_distillation_workflow_agent.py` covers the
agent-level grounding: `SYSTEM_PROMPT` contains the grounding rule and its
QR/reboiler-duty example (verified via the actual scripted-client harness,
not just a string search), and — most importantly — the raw JSON tool
result actually appended to `messages` for a completed Case A carries
`"symbol": "QR"` / `"label": "reboiler duty"` and never contains the phrase
"reflux flow rate."

### `pending_request` — deterministic "what is being asked right now"

Per `tools/binary-distillation-pending-truth.md`, this fixes a failure mode
where the agent could verbally claim a field was confirmed (e.g. from a
user's "Of course!") even though the corresponding
`update_binary_distillation_problem` WRITE never actually happened — the
authoritative state stayed `None` while the assistant's prose said
"confirmed." The fix is to never let the model decide what a short,
contextual reply means; instead, the deterministic checker itself names
the exact field (or ordered field group) it is currently waiting on, and a
short reply is matched against *that* before the model gets a turn.

`pending_request` is `None` whenever nothing specific is unambiguously
outstanding, or one of:

```python
{'field': 'use_optimum_feed_plate', 'request_type': 'boolean_confirmation',
 'prompt': '...', 'allowed_values': [True, False]}

{'field': 'xD', 'request_type': 'float', 'prompt': '...', 'constraints': {'min': 0, 'max': 1}}

{'fields': ['xD', 'xB'], 'request_type': 'ordered_float_group', 'prompt': '...'}

{'field': 'feed_temperature_K', 'request_type': 'temperature_K', 'prompt': '...'}
```

It is generated by `_essential_pending_request()` (a single missing
`pressure_Pa` or `reflux_condition` — plus, per
`tools/binary-distillation-temperature-issue.md`, a single missing feed
thermal condition, reported as `request_type: 'temperature_K'` — see
"Deterministic feed-temperature extraction" below) and
`_case_pending_request()` (once `case_candidates` has narrowed to exactly
one candidate whose still-missing fields are all plain scalars — never an
"X or Y" choice like `xD or xB` or `external_reflux_ratio_LD (or
reflux_ratio_multiplier_k)`, since guessing which of two the user means is
exactly what section 8 of that doc forbids), plus the
`use_optimum_feed_plate` boolean once a case is otherwise complete. It is
deliberately **not** stored as separate mutable state — every call
recomputes it fresh from whatever `spec` currently holds, so a reset or a
replaced problem (e.g. a new `component_names` list) automatically leaves
no stale pending request behind, with no separate invalidation logic
needed.

`binary_distillation_workflow_agent.py`'s `resolve_pending_reply()` (see
below) is what actually turns a short reply into a real WRITE; this module
only ever describes what is being asked, never interprets an answer.

`tools/chopper/test_binary_distillation_workflow.py` is a pytest suite
implementing all twelve acceptance tests from the workflow doc's section
19 (updated for the separated feed-identity/quantity fields), plus checks
for no-default-to-Case-A, `calculation_performed` always `False`, the
inconsistent-input/conflicting-composition cases, and the two worked
examples from `tools/binary-distillation-flow-rate-issue.md` sections
15-16. Run with:
```bash
pytest tools/chopper/test_binary_distillation_workflow.py -v
```

## `binary_distillation_workflow_agent.py`

The isolated tool-calling agent from workflow doc section 18, Option C
("Expose only `assess_binary_distillation_problem()` to Qwen in a
dedicated workflow-testing agent"), refactored per
`tools/binary-distillation-read-vs-append.md` into separate READ and WRITE
operations, per `tools/binary-distillation-read-loop-fix-plan.md` to
enforce a bounded per-turn tool-call policy in Python rather than relying
on the model to stop on its own, and per
`tools/binary-distillation-connecting-feed-calculation.md` to connect the
deterministic feed-phase calculation layer below as a fourth,
CALCULATION-kind tool. It deliberately still does **not** import
`separation_tool.py`, `case_design.py`, or `optimizer.py` — the sizing/
optimization sweep layer remains out of scope here. It now **does** import
`binary_distillation_calculation.py` (and, transitively, BioSTEAM via
`biosteam_feed.py`/`feed_phase.py`/`feed_partial_condensation.py`) for that
one CALCULATION tool — see "Four capabilities" below.

Four tools are registered:

| Tool | Kind | Does |
|---|---|---|
| `update_binary_distillation_problem` | WRITE | Merges newly-stated engineering facts into the accumulated state, then returns `assess_binary_distillation_problem()`'s full assessment of that state. Call only when the current turn states new information. |
| `get_binary_distillation_problem` | READ | Takes no arguments, mutates nothing, and returns the identical assessment schema computed from whatever is already accumulated. Call when the user asks about existing/derived/missing state. |
| `calculate_current_binary_distillation_problem` | CALCULATION | Takes no arguments; reads the accumulated state via the same `_effective_spec()` WRITE/READ use, and calls `binary_distillation_calculation.calculate_binary_distillation_problem()` on it — only actually running BioSTEAM once the state is `ready_for_calculation`. See "Four capabilities" below. |
| `reset_workflow_session` | housekeeping | Clears accumulated state, same discipline as `reset_separation_session()` in `separation_tool.py`. |

`update_binary_distillation_problem` and `get_binary_distillation_problem`
wrap the same underlying deterministic checker and return the same schema —
WRITE returns it post-merge, READ returns it as-is.
`calculate_current_binary_distillation_problem` wraps a second, downstream
deterministic layer (the calculation pipeline below) and is documented in
full in the "Four capabilities" subsection after the controller.

### The per-turn tool-call controller (loop fix)

`ask()` no longer offers the full tool list to the model after every tool
result — doing so let the model re-select `get_binary_distillation_problem`
indefinitely, since a READ result changes nothing about which tools are on
offer next (see `tools/binary-distillation-read-loop-fix-plan.md` for the
failure mode this caused). Termination is now enforced by Python, not the
prompt, via a small per-turn policy:

- At most **one "primary operation"** — `update_binary_distillation_problem`,
  `get_binary_distillation_problem`, or (per
  `tools/binary-distillation-connecting-feed-calculation.md` Step 5)
  `calculate_current_binary_distillation_problem` — runs per user turn. If
  a model response requests more than one, WRITE is preferred over READ,
  and READ over CALCULATION (WRITE's/READ's return value already reflects
  the full state, so a further op afterward cannot add information). This
  is what prevents an uncontrolled `READ -> CALCULATION -> READ ->
  CALCULATION -> ...` loop within one turn.
- `reset_workflow_session` may run once, before the one primary operation,
  permitting the sequence `RESET -> WRITE/READ/CALCULATION`. RESET does not
  itself count as "using" the turn's one primary operation.
- After the primary operation (or the `RESET -> primary` pair) executes,
  the next model call is made **without exposing any tools**
  (`_chat_without_tools`), forcing a prose answer from the tool result
  instead of another tool call.
- `MAX_TOOL_CALLS_PER_TURN = 2` is a hard ceiling on how many tool calls
  `ask()` will ever execute in one turn, regardless of what the model
  requests — a defensive backstop independent of the policy above.
- A `(tool_name, canonicalized_args)` fingerprint set suppresses exact
  duplicate calls within a turn (`_fingerprint`, `_select_allowed_calls`).

This logic lives in `_select_allowed_calls()` (decides which of a
response's requested tool calls may run this round) and `ask()` (the state
machine driving execution and the with-tools/without-tools model calls).
`tools/chopper/test_binary_distillation_workflow_agent.py` is a pytest
suite exercising this controller against a fake/scripted Ollama client —
WRITE-only finalization, READ-only finalization, a model that always
requests READ, a mixed update+question turn, `RESET -> WRITE`, WRITE+READ
in one response (READ suppressed), duplicate-fingerprint suppression, and
the hard call budget under a pathological client that never stops
requesting tool calls. No running Ollama server is required. Run with:
```bash
pytest tools/chopper/test_binary_distillation_workflow_agent.py -v
```
`tools/chopper/test_binary_distillation_workflow_agent_calculation.py`
extends this coverage to the CALCULATION tool specifically — see "Four
capabilities" below.

### Raw tool result debug printing (diagnostic only)

Per `tools/chopper/binary-distillation-debugging-prints.md`, the tool-call
loop inside `ask()` prints the complete raw result of every tool call to
the terminal, immediately after `_run_tool_call(call)` returns and before
that result is JSON-serialized into `messages` for Qwen — the exact point
between steps 3 and 4 of "receive the tool call → invoke the tool → receive
the return value → pass it back to Qwen." Implemented at
`binary_distillation_workflow_agent.py:1170-1173`:

```python
result = _run_tool_call(call)
print("\n========== RAW TOOL RESULT ==========")
pprint.pprint(result, width=100)
print("=====================================\n")
```

`pprint` is imported at the top of the file (`binary_distillation_workflow_agent.py:52`).
This is temporary diagnostic logging only — it doesn't touch workflow
state, tool schemas, prompts, calculation behavior, case-selection logic,
or the model's own behavior; it only makes the literal dict/JSON a tool
returns visible in the terminal before it's stringified for Qwen.

### Deterministic pending-request resolution and the state-truth rule

`tools/binary-distillation-pending-truth.md` fixes an observed failure
where the model would answer "Optimum feed plate: Confirmed" after a user
said "Of course!" without ever having issued the WRITE that changes
`use_optimum_feed_plate` — a later `get_binary_distillation_problem` call
still showed it as `None`. The model had used conversational context to
claim a state transition that never happened in the deterministic state.

`ask()` now gives `resolve_pending_reply()` first refusal on every turn,
**before** the model is even asked to pick a tool (section 4/17 of that
doc):

1. Read the current authoritative state via `get_binary_distillation_problem()`
   (not conversation history) and look at its `pending_request` (see the
   `binary_distillation_workflow.py` section above for how that field is
   generated).
2. `normalize_short_reply(text)` strips casing/punctuation noise (`"Ofcourse!@"`
   → `"ofcourse"`, `"YES!!!"` → `"yes"`, `"nope."` → `"nope"`) while
   preserving digits/`.`/`-` so numeric replies survive intact.
3. `resolve_pending_reply(pending_request, text)` matches the normalized
   text against `pending_request['request_type']`:
   - `boolean_confirmation` — a fixed affirmative/negative phrase list
     (`yes`, `of course`, `do it`, ... / `no`, `dont`, `not necessary`, ...),
     matched as an exact match or `"<phrase> ..."` prefix.
   - `float` — the ENTIRE normalized text must parse as one float (a
     message with any extra words is left unresolved rather than guessed).
   - `ordered_float_group` — the normalized text must contain exactly as
     many numbers as `pending_request['fields']`; they're mapped in order
     (`"0.99 and 0.01"` → `{'xD': 0.99, 'xB': 0.01}`).
   - `string_choice` (e.g. `reflux_condition`) is deliberately never
     auto-resolved from a bare "yes" — left to normal model-driven routing.
   - A reply longer than `_MAX_SHORT_REPLY_WORDS` (6) is never resolved,
     even if it happens to start with a matching word — this is what keeps
     "No, actually let's start over with ethanol and water" (which starts
     with a negative word) from being misread as a `False` answer to an
     unrelated pending field.
4. If it resolves, `ask()` calls `update_binary_distillation_problem(**resolved)`
   directly — a real WRITE, in Python, before the model ever produces a
   token — appends the synthetic assistant-tool-call/tool-result pair to
   `messages` for conversation-history consistency, then finalizes with
   `_chat_without_tools` so the model can only describe the (now-updated)
   returned state, never mutate it further. If it doesn't resolve, `ask()`
   falls through unchanged to the per-turn controller described above.

Separately, once `status == 'ready_for_calculation'` and the (normalized)
message is either an exact match against a small "proceed" phrase set
(`yes`, `go ahead`, `proceed`, `calculate it`, `yes boss`, ...) or an
explicit feed-phase/vapor-fraction question (`is_feed_phase_question` —
see "Four capabilities" below), `ask()` now runs
`calculate_current_binary_distillation_problem()` directly and finalizes
from its result — **without ever giving the model a tool-selection turn**.
This supersedes the pending-truth doc's original fixed-refusal boundary
message (kept only as a historical note: before
`tools/binary-distillation-connecting-feed-calculation.md` connected the
calculation layer, this same "go ahead" trigger returned a fixed
`"...the calculation layer is not enabled here."` string instead, since no
calculation tool existed yet). The goal is unchanged — a "go ahead" (or an
explicit phase question) after the problem is fully specified must never
fall through to a generic "what can I help you with?" response or an
unsupported invitation to calculate (section 14/15 of the pending-truth
doc) — only the mechanics of what happens once that trigger fires changed.

`SYSTEM_PROMPT` also carries this doc's **state-truth rule** verbatim in
spirit: the deterministic tool state is the sole authority for engineering
facts, and the model must never say a field was "confirmed", "updated",
"stored", or "specified" unless the latest tool result actually shows that
value — conversation context may help it understand what the user means,
but never itself changes engineering state.

`tools/chopper/test_binary_distillation_pending_truth.py` is a pytest
suite covering both halves: `binary_distillation_workflow.py`'s
`pending_request` generation directly (optimum-feed-plate, a single
numeric field, an ordered field group, the "never guess an X-or-Y choice"
and "never guess across multiple case candidates" cases, essential-input
`pressure_Pa`, and invalidation on reset/problem-replacement), and the
agent's `normalize_short_reply`/`resolve_pending_reply`/`ask()` wiring
(affirmative and noisy-affirmative confirmation, negative confirmation, a
longer unrelated message that must NOT be hijacked, the numeric and
ordered-group cases, and the ready-state "go ahead" trigger — now
asserted to run `calculate_current_binary_distillation_problem` and
finalize with exactly one no-tools model call, per
`tools/binary-distillation-connecting-feed-calculation.md` Step 13). No
running Ollama server is required. Run with:
```bash
pytest tools/chopper/test_binary_distillation_pending_truth.py -v
```

### Deterministic feed-temperature extraction

Per `tools/binary-distillation-temperature-issue.md`, this fixes a
reproducible failure where a message like "Separate water and ethanol at
355 K and 101325 Pa pressure..." could reach Qwen and have the model omit
`feed_temperature_K` from its `update_binary_distillation_problem` call
(capturing `pressure_Pa` but silently dropping the co-stated temperature),
and where a later corrective message — "I think I specified the feed
temperature as 355 K" — could be misrouted to a READ
(`get_binary_distillation_problem`) instead of the WRITE that actually
supplies the missing value.

**Root cause of the corrective-reply bug:** `_essential_pending_request()`
(`binary_distillation_workflow.py`) previously never generated a
`pending_request` for a missing feed thermal condition at all — only for
`pressure_Pa`/`reflux_condition` — on the reasoning that it's a three-way
choice (`feed_temperature_K`/`feed_quality`/`feed_enthalpy_kJ_per_hr`) and
guessing which of the three a bare short reply answers is exactly what
section 8 of `tools/binary-distillation-pending-truth.md` forbids. With
`pending_request` always `None` in that state, `ask()`'s pending-reply
short-circuit (see above) never had anything to resolve the corrective
message against, so it fell through to normal model-driven tool selection,
where Qwen could pick READ.

**Fix — two deterministic layers, plus a prompt-level reinforcement:**

1. `_essential_pending_request()` now also generates a pending_request when
   the feed thermal condition is the *sole* missing essential (same
   single-missing-item discipline as the pressure/reflux-condition cases):
   `{'field': 'feed_temperature_K', 'request_type': 'temperature_K', 'prompt': ...}`.
   This does **not** weaken the three-way-choice guard — the `field` names
   `feed_temperature_K`, but the corresponding resolver (next point) only
   ever matches an explicitly Kelvin-suffixed reply, never a bare number —
   so a reply that actually means `feed_quality` (e.g. a bare `"0.5"`) still
   falls through to normal model-driven routing rather than being
   misresolved as a temperature.
2. `binary_distillation_workflow_agent.py` gained two new deterministic
   helpers:
   - `resolve_pending_reply()` grew a `request_type == 'temperature_K'`
     branch that regex-matches an explicit Kelvin-suffixed number (`355 K`,
     `355K`) on the **raw** reply text — checked *before* the general
     `_MAX_SHORT_REPLY_WORDS` (6-word) cap the other branches use, since a
     corrective restatement ("I think I specified the feed temperature as
     355 K") legitimately runs longer than a bare confirmation, and the `K`
     suffix is itself an unambiguous signal.
   - `extract_explicit_feed_temperature_K(user_text)` recognizes a short,
     standalone statement that *names* the feed's thermal condition
     together with a Kelvin value (`"feed temperature is 355 K"`, `"the
     feed enters at 400 K"`) even when nothing is formally pending yet —
     wired into `ask()` right after the pending-reply check, gated on
     `_feed_thermal_condition_missing(current_state)` so it only fires
     while the field is genuinely still open. Both helpers exclude a value
     explicitly tied to a *different* apparatus (`condenser`, `reboiler`,
     `bottoms`, `distillate`, `overhead`, `column` — e.g. "the condenser
     operates at 355 K" must never be misread as the feed temperature), and
     `extract_explicit_feed_temperature_K` is additionally capped at 12
     words specifically so it can never hijack the long, multi-fact initial
     problem statement — that one is still left to the model to extract in
     full, in one WRITE (see point 3).
   Either path, once resolved, goes through the same synthetic
   assistant-tool-call/tool-result injection as the existing pending-reply
   short-circuit: a real `update_binary_distillation_problem(feed_temperature_K=...)`
   call happens in Python before the model gets a turn, and the
   finalization call is made with `_chat_without_tools` so the model can
   only describe the result, never call `get_binary_distillation_problem`
   instead.
3. `SYSTEM_PROMPT` gained a **FEED TEMPERATURE EXTRACTION RULE** section
   (mirroring the existing FLOW-UNIT EXTRACTION RULE above it), and the
   `feed_temperature_K` parameter in `update_binary_distillation_problem`'s
   docstring gained worked examples — both teach the model to extract
   `feed_temperature_K` into the SAME call as any other explicit fact from
   the same message (e.g. "at 355 K and 101325 Pa" → `feed_temperature_K=355`
   **and** `pressure_Pa=101325` together, not just one of the two). This is
   the fix for the *first*-mention extraction miss; the deterministic
   helpers in point 2 are deliberately scoped to short corrective/standalone
   restatements, not the rich initial problem statement, precisely so they
   never substitute for full model-driven extraction there.

`tools/chopper/test_binary_distillation_temperature_issue.py` is a pytest
suite covering all of the above: `pending_request` generation for the
feed-thermal-condition case (including that it stays `None` when another
essential is *also* missing, same as before); `resolve_pending_reply`
against every corrective phrasing from the issue doc ("I think I specified
the feed temperature as 355 K", "Feed temperature is 355 K", "It was 355
K"/"It is 355 K", bare "355 K"/"355K", "I already said 355 K"), plus the
condenser-context negative case and the bare-unitless-number negative case
(preserving the exactly-one-thermal-spec rule); `extract_explicit_feed_temperature_K`
positive/negative cases, including that it does *not* fire on the long
composite initial statement; full `ask()`-level scripted-client tests
proving the corrective reply performs a real WRITE (never a READ), a
standalone restatement WRITEs even with no pending_request, a genuine
question about stored temperature still falls through to the model
unintercepted, and the rich initial statement passes through to the model
untouched; conflicting-thermal-spec and feed_quality-still-works checks
(Steps 15-16 of the issue doc); and content guards asserting the
SYSTEM_PROMPT/docstring reinforcement text is present. No running Ollama
server is required. Run with:
```bash
pytest tools/chopper/test_binary_distillation_temperature_issue.py -v
```

**Cross-call accumulation** works the same way as `separation_tool.py`'s
`_spec_state` (see that section above): every call merges its non-`None`
arguments into a module-level `_workflow_state` dict, clearing a stale
feed-thermal-condition or reflux-quantity field left over from an earlier
call when a new one of that group is given this call. Simpler than
`separation_tool.py`'s accumulator in one respect — it has no
`_STABLE_FIELDS`/`ConflictingResend` check, since Option C's goal is a
clean, isolated experiment rather than production hardening against a
drifting feed across turns.

Feed identity/quantity (`component_names`, `add_component_names`,
`component_flows`, `component_flow_units`, `total_flow`,
`total_flow_units`, `composition`, `composition_basis`) is accumulated
separately, in a nested `feed_state`-shaped dict under
`_workflow_state['feed']`, via `feed_state.apply_user_update()` (see the
`feed_state.py` section above) rather than the flat non-`None` overwrite
used for every other field — this is what gives `component_names` its
REPLACE semantics and `add_component_names` its APPEND semantics (issue
doc section 12). Only ever-`'user_explicit'` values are kept in this
accumulator; `_effective_spec()` strips out anything already `'derived'`
before building the flat spec passed to
`assess_binary_distillation_problem()`, so that function — the sole place
derivation actually happens — always sees fresh, correctly-provenanced
explicit inputs, even though it's called once per turn on the full
accumulated history.

**No more collapsed `components: dict[str, float]`.** An earlier version
of this tool accepted feed composition as either `components` (component
→ flow rate directly) or `total_flow` + `composition` (component →
mole/mass fraction), normalized by a Form 1/Form 2 helper. That collapsed
schema is exactly what `tools/binary-distillation-flow-rate-issue.md`
identifies as the root cause of two failure modes: a model forced to
invent numbers just to name components (since the dict's values had to be
numeric even for an identity-only statement), and a single component's
stated flow silently read as the whole feed. `component_names` (identity)
and `component_flows`/`total_flow`/`composition` (quantity) are now
separate tool arguments — see `update_binary_distillation_problem`'s docstring —
so naming components never requires a number, and a single component's
flow is never conflated with the total (workflow doc section 19 Test 11
still holds: giving both binary component flows is enough to derive the
total and composition without the model asking for them separately —
`feed_state.normalize_feed_state()` does this now, not a Form 1/2
normalizer).

`SYSTEM_PROMPT` implements workflow doc section 17 verbatim in spirit: it
tells the model it is "not the binary-distillation decision engine",
instructs it to extract information and pass it to the checker rather than
inferring a case itself, to never invent pressure/feed condition/reflux
condition/purity/recovery/reflux ratio/boilup ratio/product flow/optimum-
feed-plate use, to never claim a calculation was performed (there is no
calculation tool available to this agent), and to stop — reporting
`would_calculate_details` (see "The `BINARY_DISTILLATION_QUANTITIES`
registry" above) — once `status` comes back `ready_for_calculation`. An
**ENGINEERING OUTPUT GROUNDING RULE** block tells the model to use each
`would_calculate_details` entry's `label` verbatim for its `symbol`'s
meaning and never redefine it from its own knowledge (the QR ≠ "reflux flow
rate" fix).
Separate guidance blocks cover each `status` value the checker can return
(`need_components`/`unsupported_multicomponent`/`inconsistent_input`/
`need_essential_inputs`/`need_case_definition`/`need_case_inputs`/
`ambiguous`/`ready_for_calculation`), plus a block distinguishing
`component_names` (full replace) from `add_component_names` (append) and
one distinguishing `component_flows` from `total_flow`+`composition`.

**Prerequisites:** same as `separation_agent.py` — a local Ollama server
running `qwen3:8b` — but does **not** need `biosteam` to be importable, since
this module never imports it.

**Run it:**
```bash
conda activate pyfuel
cd "tools/chopper"

python binary_distillation_workflow_agent.py                 # interactive REPL
python binary_distillation_workflow_agent.py "I want to separate methanol and water."   # one-shot
```

## Which agent to test against

Four different chat entry points exist across this folder and
`tools/separation_rag_agent.py`. They are not interchangeable — pick based
on what you're trying to observe:

| Agent | Performs a real BioSTEAM calculation? | Case A ever defaulted? | Needs |
|---|---|---|---|
| `binary_distillation_workflow_agent.py` (this section) | **Only a feed-phase check**, and only via the one `calculate_current_binary_distillation_problem` CALCULATION tool once `ready_for_calculation` — `update_binary_distillation_problem`/`get_binary_distillation_problem`'s `calculation_performed` is always `False`; no Wankat Case A-D sizing (reflux ratio, stage count, column diameter, etc.) happens through this agent at all. Use this to test problem-definition/case-routing behavior (scope gate, essential inputs, Case A-D identification, `would_calculate` reporting) or the feed-phase calculation connection specifically, in isolation from the full sizing pipeline below. | No — never did, by design (workflow doc section 7/18). | Ollama + `qwen3:8b`, plus `biosteam` (now needed transitively, for the CALCULATION tool only — see `biosteam_feed.py`/`feed_phase.py` below). |
| `separation_agent.py` | Yes, full Wankat-case sizing/costing, once `design_separation_case`/`optimize_separation` gets a complete spec. Use this to test the full calculation pipeline (or the same Case-A-default fix, without the RAG/Chroma overhead below). | No — `problem_spec.identify_case()` no longer defaults to Case A (fixed; previously it did). | Ollama + `qwen3:8b`, `biosteam`. |
| `separation_rag_agent.py` | Yes, same pipeline as `separation_agent.py`, plus `retrieve_separation_heuristics`. Use this to test the calculation pipeline together with heuristic retrieval, or the merged agent specifically. | No — same fix as above (shared `problem_spec.py`). | Ollama + `qwen3:8b`, `biosteam`, `chromadb` + a seeded Chroma collection (`python tools/chopperRAG/seed_heuristics.py`). |
| `chopperRAG/query.py` | No BioSTEAM at all — retrieval + heuristic Q&A only, unrelated to binary-distillation case logic. | N/A | Ollama + `qwen3:8b`, `chromadb` + seeded collection. |

If you're specifically verifying "does it still silently pick Case A when
nothing case-specific was said" or "does it stop before sizing and just
report what a full Case design would calculate", use
`binary_distillation_workflow_agent.py` — it's the lightest to run and the
only one of the four that can never perform Wankat Case A-D sizing, so
there's no ambiguity about which behavior you're seeing (its one
CALCULATION tool is deliberately scoped to feed phase only — see "Four
capabilities" below). Use `separation_agent.py` or `separation_rag_agent.py`
when you actually want the sized/costed column back.

---

# `biosteam_feed.py` + `feed_phase.py` + `feed_partial_condensation.py` + `binary_distillation_calculation.py` — deterministic feed-phase calculation layer

Implements `tools/binary-distillation-feed-phase-evaluation.md`,
`tools/binary-distillation-feed-vapor-liquid.md`,
`tools/binary-distillation-vapor-liquid-dead-end.md`, and
`tools/binary-distillation-condensation-edge-case.md` in full: the first
deterministic **calculation** layer downstream of the workflow-only checker
above. It only ever runs once `assess_binary_distillation_problem()` reports
`status == 'ready_for_calculation'` — the LLM never generates BioSTEAM
code, invents a missing value, decides the feed phase itself, or decides
routing; every number that goes into the BioSTEAM stream and every branch of
the VLE/conditioning calculation comes from the already-normalized,
already-validated workflow state.

```text
assess_binary_distillation_problem(spec)
        │
        ▼
status != ready_for_calculation → no calculation (checks == {})
status == ready_for_calculation
        │
        ▼
build_biosteam_feed(spec, assessment)      biosteam_feed.py
    canonical bst.Stream from the normalized feed state
        │
        ▼
evaluate_feed_phase(feed, ...)             feed_phase.py
    exactly one VLE branch (T/P, V/P, or H/P), deterministic
    liquid / vapor / vapor_liquid classification
        │
        ▼
                phase
     /            |            \
liquid      vapor_liquid      vapor
   │              └─────┬──────┘
   ▼                    ▼
stop /          evaluate_vapor_feed_at_reference_temperature(...)
future                             feed_partial_condensation.py
liquid              condition the OVERALL feed to 313.15 K via a
route               rigorous BioSTEAM HXutility VLE flash
                                    │
                                    ▼
                    conditioned vapor_fraction <= PHASE_FRACTION_TOLERANCE ?
                          /                          \
                        yes                           no
                         │                             │
                         ▼                   conditioned liquid_fraction >= 0.50 ?
              liquid-phase separation              /            \
              only (no vapor pathway)            yes             no
                         │                         │               │
                         │                         ▼               ▼
                         │              liquid + vapor future  vapor-phase separation
                         │              separation routes      advisable (not implemented)
        │                │                         │               │
        ▼                ▼                         ▼               ▼
calculate_binary_distillation_problem(spec)   binary_distillation_calculation.py
    {'calculation_performed', 'workflow',
     'checks': {'feed_phase': {...}, 'routing': {...},
                'vapor_condensation_screen': {...} (vapor/vapor_liquid only)},
     'calculation_progress': {...}}
```

**A feed that starts out already a vapor-liquid mixture is not a dead end.**
Earlier, `phase == 'vapor_liquid'` stopped immediately with an
`implemented: False` `two_phase_feed` route and no further BioSTEAM call.
`tools/binary-distillation-vapor-liquid-dead-end.md` replaced that: any feed
containing a vapor fraction — entirely vapor, or already a vapor-liquid
mixture — now runs the identical reference-temperature conditioning screen
and the identical complete-condensation/>=50%-liquid routing classification
described below. The
feed's ORIGINAL phase result (at its stated feed conditions) and its
CONDITIONED result (after cooling/heating to 313.15 K) are kept as two
separate, independently inspectable dict entries — `checks['feed_phase']`
and `checks['vapor_condensation_screen']` — never overwritten into one.

## `biosteam_feed.py`

`build_biosteam_feed(spec, assessment, *, stream_id='feed')` — raises
`BiosteamFeedError` unless `assessment['status'] == 'ready_for_calculation'`,
the normalized `assessment['feed']['component_names']` has exactly 2
entries, every one of those components has a known flow in
`assessment['feed']['component_flows']`, flow units are available (from
`component_flow_units` or `total_flow_units`), and `spec['pressure_Pa']` is
present. On success it calls `bst.settings.set_thermo(component_names,
cache=True)` and returns a `bst.Stream` built from the actual component
flows — never inferring or inventing a value beyond what
`feed_state.normalize_feed_state()` already derived upstream. It never sets
`feed.T` or otherwise imposes a thermal condition (no silent default to
bubble point) — thermal state is handled entirely by `feed_phase.py`.

## `feed_phase.py`

`evaluate_feed_phase(feed, *, pressure_Pa, feed_temperature_K=None,
feed_quality=None, feed_enthalpy_kJ_per_hr=None, phase_tolerance=1e-6)` —
requires exactly one of the three thermal-condition arguments (returns
`valid=False, error='invalid_thermal_specification'` otherwise — it never
guesses which one applies or defaults to bubble point), defensively
re-checks the feed has exactly 2 nonzero-flow components
(`error='unsupported_component_count'` if not — a backstop independent of
the workflow's own binary-scope gate), then runs the one matching VLE call
on a **copy** of `feed` (`feed.vle(T=..., P=...)`, `feed.vle(V=..., P=...)`,
or `feed.vle(H=..., P=...)`) — the input stream is never mutated. The
resulting `vapor_fraction` is classified in plain Python (never by the
model): `liquid` if `V <= phase_tolerance`, `vapor` if
`V >= 1 - phase_tolerance`, else `vapor_liquid`. Per-component vapor/liquid
molar flows are read from `imol['g', ID]`/`imol['l', ID]` and returned
alongside the classification. Any exception during the VLE calculation is
caught and reported as `{'valid': False, 'error':
'phase_calculation_failed', 'message': str(err)}` rather than left to
propagate or reinterpreted by the model.

**Output schema** (JSON-friendly; never returns the raw `bst.Stream`):

```python
{
    'check': 'feed_phase', 'valid': True,
    'phase': 'vapor_liquid',            # 'liquid' | 'vapor' | 'vapor_liquid'
    'vapor_fraction': 0.37, 'liquid_fraction': 0.63,
    'temperature_K': 405.0, 'pressure_Pa': 101325.0,
    'components': ['Butane', 'Acetaldehyde'],
    'vapor_mol': {'Butane': ..., 'Acetaldehyde': ...},
    'liquid_mol': {'Butane': ..., 'Acetaldehyde': ...},
    'calculation': {'type': 'VLE', 'specification': 'T_P'},  # or 'V_P' / 'H_P'
    'message': 'Feed is a vapor-liquid mixture at the specified feed conditions.',
}
```

`tools/chopper/test_feed_phase.py` covers all eight acceptance tests from
the spec doc's Step 11 (TP binary feed, liquid/vapor/two-phase
classification via bubble/dew-point-bracketed temperatures, quality-based
state, invalid/missing thermal specification, defensive
unsupported-component-count), plus an enthalpy-pressure (`H_P`) test. Run
with:
```bash
pytest tools/chopper/test_feed_phase.py -v
```

## `feed_partial_condensation.py`

`evaluate_vapor_feed_at_reference_temperature(feed, *, pressure_Pa,
initial_temperature_K, reference_temperature_K=313.15)` — the deterministic
reference-temperature screen `binary_distillation_calculation.py` runs
whenever `evaluate_feed_phase()` reports the feed has any vapor fraction
(`phase in ('vapor', 'vapor_liquid')`). It never runs for a `liquid` feed.

On a **copy** of `feed` (the canonical feed itself is never mutated), it
runs a rigorous BioSTEAM VLE flash to the feed's actual equilibrium state at
`initial_temperature_K`/`pressure_Pa` (`feed_copy.vle(T=..., P=...)` —
reproducing a pure-vapor state exactly when the feed is entirely vapor, and
the true mixed-phase state when the feed is already vapor-liquid), then
passes that **whole** copy — never only its initial vapor portion — through
a `bst.units.HXutility(ins=feed_copy, T=reference_temperature_K,
rigorous=True)` conditioned to `REFERENCE_TEMPERATURE_K` (313.15 K / ~40°C,
a common heat-exchanger utility-water screening point). BioSTEAM's rigorous
VLE flash is the sole source of the resulting liquid/vapor split — this
module never estimates, assumes complete condensation, or infers the split
itself.

The resulting `liquid_fraction`/`vapor_fraction` are classified in a fixed
order, per `tools/binary-distillation-condensation-edge-case.md` — complete
(or numerically-complete) condensation is checked **before** the 50%
threshold, since a `liquid_fraction` of `1.0` would otherwise still satisfy
`>= 0.50` and incorrectly route to the mixed-phase branch as well:

| Condition | `route` |
|---|---|
| `vapor_fraction <= PHASE_FRACTION_TOLERANCE` | `liquid_phase_separation` — no meaningful vapor phase remains; only a future liquid-phase separation pathway is reported, not implemented. **Checked first.** |
| `liquid_fraction >= LIQUEFACTION_THRESHOLD` (and vapor is above tolerance) | `liquid_and_vapor_separation_future` — both a future liquid-phase and a future vapor-phase separation pathway are reported, neither implemented. Exactly 50% liquid falls in this branch. |
| otherwise | `vapor_separation_advisable` — a vapor-phase separation method is advisable, not implemented. |

`PHASE_FRACTION_TOLERANCE = 1e-9` (module-level constant) is used instead of
exact equality against `0.0`, since a rigorous VLE flash can return a tiny
nonzero residual (e.g. `2.4e-12`) for a phase that is effectively absent.
The same constant governs both the routing decision here and the tests
below — never a second, independently-chosen tolerance.

`operation` reports `'cooling'`/`'heating'`/`'none'` from comparing
`initial_temperature_K` to `reference_temperature_K` — a two-phase feed is
never assumed to always be cooled. Any BioSTEAM/HX failure is caught and
reported as `{'valid': False, 'error':
'reference_temperature_flash_failed', 'message': str(err)}` rather than
fabricating a route.

**Output schema** (JSON-friendly) — complete condensation, e.g. the real
Water/Ethanol 355 K worked example, which conditions to `liquid_fraction ==
1.0`/`vapor_fraction == 0.0` at 313.15 K:

```python
{
    'valid': True, 'check': 'vapor_feed_reference_temperature',
    'target_temperature_K': 313.15, 'initial_temperature_K': 355.0,
    'pressure_Pa': 101325.0, 'operation': 'cooling',
    'components': ['Water', 'Ethanol'],
    'vapor_mol': {...}, 'liquid_mol': {...},
    'liquid_fraction': 1.0, 'vapor_fraction': 0.0,
    'liquid_percent': 100.0, 'vapor_percent': 0.0,
    'route': 'liquid_phase_separation',
    'implemented': False,
    'message': (
        'At 313.15 K, the conditioned feed is effectively fully liquid '
        '(cooling from 355.00 K). No meaningful vapor phase remains. '
        'Liquid-phase separation is the next future pathway, but it is '
        'not yet implemented.'
    ),
}
```

A genuinely mixed-phase result (`vapor_fraction` above tolerance and
`liquid_fraction >= 0.50`) still returns `route: 'liquid_and_vapor_separation_future'`
with the original "substantial partial condensation" wording — the message
above is used only for the complete-condensation branch.

`tools/chopper/test_feed_partial_condensation.py` covers the module-level
HX-screen behavior: cooling vs. heating direction, the exactly-50%/
above-50%/below-50% routing thresholds, original-feed immutability,
liquid+vapor fraction conservation, deterministic BioSTEAM-failure
reporting, defensive component-count/zero-flow checks, and — per
`tools/binary-distillation-vapor-liquid-dead-end.md` — that this all holds
equally for a feed that is already vapor_liquid (not just entirely vapor)
at its initial conditions, including that the *whole* feed's molar flow
(not just its initial vapor portion) reaches the exchanger. Per
`tools/binary-distillation-condensation-edge-case.md`, it additionally
covers the complete-condensation edge case: exact `vapor_fraction == 0.0`,
a near-zero vapor fraction within `PHASE_FRACTION_TOLERANCE` (`1e-12`)
routing identically to exact zero, a just-above-tolerance vapor fraction
(`1e-6` overall) still routing to `liquid_and_vapor_separation_future`, and
`PHASE_FRACTION_TOLERANCE == 1e-9` as a fixed constant. Run with:
```bash
pytest tools/chopper/test_feed_partial_condensation.py -v
```

## `binary_distillation_calculation.py`

`calculate_binary_distillation_problem(spec)` — calls
`assess_binary_distillation_problem(spec)`; if `status !=
'ready_for_calculation'`, returns `{'calculation_performed': False,
'workflow': assessment, 'checks': {}, 'calculation_progress': {...}}`
immediately (no BioSTEAM call at all). Otherwise builds the feed and
evaluates its phase (`checks['feed_phase']`) — a `BiosteamFeedError` from
the feed-build step is caught and reported as `checks['feed_phase']` with
`error='feed_build_failed'` rather than propagating (still with a populated
`calculation_progress`).

Once `checks['feed_phase']['valid']` is `True`, deterministic routing (never
model-decided) runs from `phase_result['phase']` alone:

| `phase` | Behavior |
|---|---|
| `liquid` | Stops immediately. `checks['routing']` = `{'route': 'liquid_phase_separation', 'implemented': False, ...}`. `evaluate_vapor_feed_at_reference_temperature()` is never called. |
| `vapor` or `vapor_liquid` | Both run `evaluate_vapor_feed_at_reference_temperature()` on the SAME overall feed — the vapor/vapor_liquid distinction only matters for the ORIGINAL feed-phase result, never for which conditioning pathway runs. The result is stored as `checks['vapor_condensation_screen']`, and — if valid — echoed into `checks['routing']` (`route`, `liquid_fraction`/`vapor_fraction`, `liquid_percent`/`vapor_percent`, `message`) per the complete-condensation/>=50%-liquid/otherwise classification table above (complete condensation checked first — see `tools/binary-distillation-condensation-edge-case.md`). |

The full return shape is `{'calculation_performed': True, 'workflow':
assessment, 'checks': {'feed_phase': {...}, 'routing': {...},
'vapor_condensation_screen': {...} (vapor/vapor_liquid only)},
'calculation_progress': {...}}`. The `checks` dict is deliberately shaped to
hold future deterministic checks alongside these (`relative_volatility`,
`azeotrope`, `thermal_stability`, `condensability`,
`critical_temperature_margin`, ...) without changing this function's return
shape — none of those are implemented yet, and neither is any actual
liquid- or vapor-phase separator design (`STEP_LIQUID_PHASE_SEPARATION`/
`STEP_VAPOR_PHASE_SEPARATION` below are recognized-but-unimplemented
endpoints this pipeline intentionally stops at). See "Calculation-progress
state" below for `calculation_progress` itself.

`tools/chopper/test_binary_distillation_calculation.py` covers the
incomplete-workflow → no-calculation and complete-workflow →
feed-phase-calculation transitions, plus a ternary spec being rejected by
the binary-scope gate before any BioSTEAM code runs.
`tools/chopper/test_binary_distillation_feed_vapor_liquid.py` covers the
phase-based routing end to end: a liquid feed skips the HX screen entirely;
a vapor feed with <50% conditioned liquid routes to
`vapor_separation_advisable`; and — per
`tools/binary-distillation-vapor-liquid-dead-end.md` — a genuinely
vapor_liquid feed (a real Water/Ethanol 355 K/101325 Pa case, ~25.5 mol%
liquid/~74.5 mol% vapor at feed conditions) no longer stops, actually runs
the reference-temperature screen, and preserves its original feed-phase
result distinctly from the conditioned one. That same Water/Ethanol case
fully condenses at 313.15 K (conditioned `liquid_fraction == 1.0`), so —
per `tools/binary-distillation-condensation-edge-case.md` — it now serves
as the real-BioSTEAM regression case for the complete-condensation edge
case: `route == 'liquid_phase_separation'`, `remaining_steps ==
['liquid_phase_separation']`, and `'vapor_phase_separation'` is absent from
`remaining_steps`. A separate fake-HX-driven test covers genuine (non-
complete) partial condensation at a >=50%-liquid mixed split, still routing
to `liquid_and_vapor_separation_future` with both future pathways reported.
Conditioning failures are still reported deterministically, and a follow-up
"what next?" is still answered from the stored conditioned result rather
than rerunning BioSTEAM or falling back to the old dead-end message. Run
with:
```bash
pytest tools/chopper/test_binary_distillation_calculation.py -v
pytest tools/chopper/test_binary_distillation_feed_vapor_liquid.py -v
```

**One-directional boundary:** none of these four modules import `ollama`
or `openai` — this calculation layer remains structurally incapable of LLM
involvement, regardless of what imports it. The reverse is no longer true:
`tools/binary-distillation-connecting-feed-calculation.md` connects
`binary_distillation_workflow_agent.py` to this layer (see "Four
capabilities" right below) via one narrow entry point,
`calculate_current_binary_distillation_problem()` — the workflow agent
still never imports `separation_tool.py`/`case_design.py`/`optimizer.py`,
so no Wankat Case A-D sizing is reachable through it, only the feed-phase
evaluation, reference-temperature conditioning screen, and the
deterministic post-feed-phase routing between them. RAG heuristic retrieval
(`tools/chopperRAG/`) is not connected to either layer yet — see
`tools/binary-distillation-feed-phase-evaluation.md` Step 16.

## Four capabilities: connecting the calculation layer to the agent

`tools/binary-distillation-connecting-feed-calculation.md` gives
`binary_distillation_workflow_agent.py` a fourth conceptual capability
alongside WRITE/READ/RESET, and
`tools/binary-distillation-whats-next.md` adds a fifth (see
"Calculation-progress state" below):

```text
WRITE              update_binary_distillation_problem
READ               get_binary_distillation_problem
CALCULATE          calculate_current_binary_distillation_problem
CALCULATION READ   get_binary_distillation_calculation_status
RESET              reset_workflow_session
```

`calculate_current_binary_distillation_problem()` is a **zero-argument**
wrapper — Qwen cannot pass, restate, or otherwise influence any engineering
value through it. It reads the same accumulated authoritative state as the
WRITE/READ tools (`_effective_spec()`) and calls
`binary_distillation_calculation.calculate_binary_distillation_problem()`
on it directly:

```python
def calculate_current_binary_distillation_problem() -> dict:
    return calculate_binary_distillation_problem(_effective_spec())
```

Two deterministic (non-model) routing layers decide when this tool runs
without waiting for the model to choose it, in `ask()`, both gated on
`status == 'ready_for_calculation'`:

- **The existing "proceed" trigger** (`yes`, `go ahead`, `proceed`,
  `calculate it`, ...) — previously a fixed refusal message (see the
  pending-truth section above), now runs the calculation and finalizes
  from its result instead.
- **`is_feed_phase_question(text)`** — a narrow substring match against a
  small, explicit set of phrasings ("what is the feed phase", "is the feed
  vapor", "what is the vapor fraction", "how much of the feed is liquid",
  ...). An explicit feed-phase/vapor-fraction question is a calculation
  question, never something answered from the workflow state alone or from
  the model's general chemical knowledge — the `CALCULATED ENGINEERING
  STATE RULE` and `FEED-PHASE ROUTING RULE` blocks in `SYSTEM_PROMPT` state
  this explicitly (e.g. forbidding reasoning like "400 K is above
  methanol's boiling point, so the feed is probably vapor"), and this
  deterministic router makes it structural rather than advisory whenever
  the phrasing is unambiguous. A feed-phase question asked while the
  problem is **not yet** `ready_for_calculation` deliberately does NOT
  trigger this router — it falls through to normal model-driven tool
  selection, where the tool itself (if the model calls it) reports
  `calculation_performed: False` and the missing inputs, without ever
  touching BioSTEAM.

Both routes call a shared `_run_calculation_and_finalize()` helper: it runs
the calculation, appends a synthetic assistant-tool-call/tool-result pair
to `messages` (matching the pending-reply resolver's own pattern), then
finalizes with `_chat_without_tools` so the model can only explain the
already-fixed result, never call another tool that turn. When neither
router fires, the model may still choose
`calculate_current_binary_distillation_problem` itself through normal
tool selection (e.g. "please calculate the feed phase" doesn't match the
narrow phrase list) — it participates in the same per-turn controller as
WRITE/READ described above, so it is still capped at one calculation per
turn and still forces a no-tools finalization call afterward.

**Scope stays explicit at every layer.** Because
`calculate_binary_distillation_problem()` only ever populates
`checks['feed_phase']`, `checks['routing']`, and — for a `vapor`/
`vapor_liquid` feed — `checks['vapor_condensation_screen']`,
`SYSTEM_PROMPT`'s `ready_for_calculation` guidance tells the model to report
exactly those checks and to explicitly note that `would_calculate_details`'s
other quantities (distillate/bottoms flow, reflux ratio, reboiler/condenser duty,
stage count, feed stage, column diameter) are still not computed, and that
no liquid- or vapor-phase separator has actually been designed or sized —
never implying the full Wankat Case design was performed.

`tools/chopper/test_binary_distillation_workflow_agent_calculation.py` is
the pytest suite for this connection (fakes/scripted clients throughout,
except its final test, which is a real end-to-end BioSTEAM integration
test): a ready problem's feed-phase/vapor-fraction/liquid-vapor questions
routing to the calculation tool without an intervening
`get_binary_distillation_problem` call; the calculation result standing
already-fixed in `messages` before the model's finalization turn runs (so
a model attempting qualitative boiling-point reasoning cannot make that the
authoritative answer); an incomplete problem's calculation call reporting
`calculation_performed: False` with the missing inputs, never touching
BioSTEAM; a pending confirmation (e.g. "yes" answering an
optimum-feed-plate prompt) still winning over calculation routing; the
tool's zero-argument schema; no repeated calculation within one turn under
a pathological client; and a real `calculate_current_binary_distillation_problem()`
call against a complete Case D spec (Methanol/Water, 50/50 kmol/hr, 400 K,
101325 Pa, saturated-liquid reflux, `boilup_ratio_VB=1.2`, `xD=0.95`,
`xB=0.01`, optimum feed plate) asserting `calculation_performed is True`
and `checks['feed_phase']['phase']` is one of `liquid`/`vapor`/
`vapor_liquid`. Run with:
```bash
pytest tools/chopper/test_binary_distillation_workflow_agent_calculation.py -v
```

## Calculation-progress state: `calculation_progress`, `_last_calculation_result`, and `get_binary_distillation_calculation_status`

`tools/binary-distillation-whats-next.md` adds a distinct third kind of
truth, on top of the two the sections above already establish:

```text
Problem state       = what inputs are known                (assess_binary_distillation_problem)
Calculation state    = what deterministic calculations have
                        actually been performed              (calculate_binary_distillation_problem)
Calculation progress = what is complete, what is next, and
                        what remains                          (calculation_progress / this section)
```

Without this layer, a question like "what next?" or "continue" had no
deterministic answer — it either fell through to generic LLM reasoning (which
could invent a completed step, or re-ask for inputs already on file) or was
answered by re-deriving problem-definition state, which does not know
whether a calculation has actually run. This layer exists so those questions
are answered the same way engineering facts already are: from Python state,
never from conversation history.

**`calculation_progress` (`binary_distillation_calculation.py`).** Every
`calculate_binary_distillation_problem()` result — success, feed-build
failure, or workflow-not-ready — now includes a `calculation_progress` dict:

| Key | Contents |
|---|---|
| `completed_steps` | `list[str]` of stable step IDs that actually completed, derived only from `checks` — `[STEP_FEED_PHASE]` once `checks['feed_phase']['valid'] is True`; `[STEP_FEED_PHASE, STEP_VAPOR_CONDENSATION_SCREEN]` once the reference-temperature screen also completed (for a `vapor`/`vapor_liquid` feed). Never includes a step whose check is missing or `valid: False`. |
| `next_step` / `next_step_available` | The next EXECUTABLE step, or `None`/`False`. Always `None`/`False` today — no downstream separator design step is implemented yet (see the step IDs below); reserved for when one ships. |
| `remaining_steps` | Deterministic, from `phase`: `[STEP_LIQUID_PHASE_SEPARATION]` for `liquid`. For `vapor`/`vapor_liquid`, derived from the screen's `route` (never re-derived independently from `liquid_fraction` — see `tools/binary-distillation-condensation-edge-case.md`): `[STEP_LIQUID_PHASE_SEPARATION]` when the conditioned feed is effectively fully liquid (`route == 'liquid_phase_separation'`, i.e. `vapor_fraction <= PHASE_FRACTION_TOLERANCE`); `[STEP_LIQUID_PHASE_SEPARATION, STEP_VAPOR_PHASE_SEPARATION]` for genuine partial condensation with `liquid_fraction >= 0.50`; `[STEP_VAPOR_PHASE_SEPARATION]` once it's `< 0.50`; `[]` if the screen itself failed. |
| `remaining_outputs` | No `would_calculate`-equivalent output list exists yet for any of these separation pathways, so this is always `[]` even when `remaining_steps` is non-empty. |
| `blocked_reason` | `None` once nothing remains; `'not_implemented'` once feed-phase (and, for `vapor`/`vapor_liquid`, the conditioning screen) succeeded but the separation-pathway step hasn't shipped; `'calculation_failed'` if the feed-phase check OR the reference-temperature screen itself errored despite the workflow being ready — **never** reported as a missing-input situation; `'workflow_not_ready'` when `calculate_binary_distillation_problem` never even reached the calculation layer. |
| `message` | Human-readable summary matching whichever branch above applies — for `vapor`/`vapor_liquid`, this is the screen's own message (percentages, cooling/heating direction). |

Stable step IDs (module-level constants in `binary_distillation_calculation.py`):
`STEP_FEED_PHASE` and `STEP_VAPOR_CONDENSATION_SCREEN` (the two actually
executable today — the latter runs for any feed with a vapor fraction, per
`tools/binary-distillation-vapor-liquid-dead-end.md`),
`STEP_LIQUID_PHASE_SEPARATION`, `STEP_VAPOR_PHASE_SEPARATION` (recognized
downstream endpoints this pipeline intentionally stops at, not yet
implemented), and `STEP_CASE_A_DESIGN`..`STEP_CASE_D_DESIGN` (reserved for
once a Wankat Case A-D design step is wired into this pipeline — not
reachable today, since post-feed-phase routing always stops at a
separation-pathway step first). The old `STEP_TWO_PHASE_ROUTING` step ID
and its `two_phase_feed` route no longer exist — an initially vapor_liquid
feed is no longer a dead end (see above).
`build_calculation_progress(*, assessment, checks)` derives all of this
purely from the already-computed `assessment`/`checks` — it is never asked
of the LLM.

**`_last_calculation_result` (`binary_distillation_workflow_agent.py`).**
A module-level variable holding the most recent
`calculate_current_binary_distillation_problem()` result for the CURRENT
problem, or `None`. It is written to in exactly three places:

- `calculate_current_binary_distillation_problem()` — sets it to whatever it
  computed and returns, every time it runs.
- `reset_workflow_session()` — clears it back to `None`, alongside the rest
  of the accumulated state.
- `update_binary_distillation_problem()` — clears it back to `None`
  whenever the call actually writes something (any non-`None` argument),
  since a calculation result computed against the OLD engineering state must
  never remain authoritative once that state changes. This is deliberately
  the simplest safe rule ("any successful non-empty engineering WRITE
  invalidates it") rather than a narrower field-by-field dependency check —
  it can invalidate more than strictly necessary, but it can never leave a
  stale result standing.

Conversation history is never consulted for any of this — `_last_calculation_result`
is calculation-progress TRUTH the same way `_workflow_state` is
problem-definition TRUTH.

**`get_binary_distillation_calculation_status()`** — the CALCULATION READ
tool (fifth capability in the table above). Takes no arguments, never
mutates anything, never runs BioSTEAM:

```python
# No calculation yet (or invalidated by reset/WRITE):
{'calculation_available': False, 'latest_calculation': None, 'message': '...'}

# A calculation has run:
{'calculation_available': True, 'latest_calculation': <full calculate_current_binary_distillation_problem() result>, 'message': <its calculation_progress['message']>}
```

**`get_precalculation_progress()`** — an internal helper, not registered as
an Ollama tool, used only by the deterministic "what next?" router below to
give that question a meaningful answer even BEFORE the first calculation has
run: if the workflow is already `ready_for_calculation`, it reports
`next_step='feed_phase'`/`next_step_available=True` directly from the
workflow assessment (no BioSTEAM call); otherwise it reports
`blocked_reason='workflow_not_ready'` with the workflow's own `message`.

**Deterministic "what next?"/"continue"/"what remains?" routing.**
`is_calculation_progress_question(text)` matches a small, fixed phrase set
(`normalize_short_reply`'d first, same normalization the pending-reply
resolver uses) — multi-word phrases like `"what remains"`/`"where are we"`
by substring, and the two bare single-word phrases `"next"`/`"continue"`
only as the ENTIRE normalized message (so "what's the next component?" is
not misrouted). In `ask()`, this check runs after pending-reply resolution
and the "proceed" trigger, before feed-phase-question routing and before any
model-driven tool selection:

```text
is_calculation_progress_question(user_text)
        │
        ▼
_last_calculation_result is not None?
    YES → get_binary_distillation_calculation_status()
    NO  → get_precalculation_progress()
        │
        ▼
synthetic assistant-tool-call/tool-result pair appended to `messages`
        │
        ▼
_chat_without_tools()  -- model can only explain the fixed result
```

This reuses the same synthetic-message pattern as
`_run_calculation_and_finalize`/the pending-reply resolver — the model never
gets a tool-selection turn for a progress question, so it cannot invent a
completed step or re-ask for stored inputs.

**Controller precedence (`_select_allowed_calls`).** The per-turn policy
described above now orders model-selected primary operations as
`WRITE > CALCULATION EXECUTE > CALCULATION READ > (state) READ` (RESET
still runs first, once, if requested), and `get_binary_distillation_calculation_status`
counts toward the same one-primary-operation-per-turn budget as
WRITE/READ/CALCULATE — so a model cannot loop READ ↔ CALCULATION READ
within one turn any more than it could loop READ ↔ CALCULATE before.

**`SYSTEM_PROMPT` additions.** A `CALCULATION-PROGRESS TRUTH RULE` block
states that the deterministic calculation state is the sole authority for
completed steps, available next steps, and remaining steps — the model must
never infer any of this from conversation history. A `DO NOT RE-ASK STORED
INPUTS` block states that a question like "what next?" is never itself
evidence the user is starting a new problem, and stored inputs must not be
re-requested unless the deterministic checker actually reports them
missing/inconsistent/invalidated.

`tools/chopper/test_binary_distillation_calculation_progress.py` covers all
of this: `calculation_progress` schema correctness (feed-phase and
vapor-condensation-screen completed, a fully-condensed Case D feed's
`next_step_available=False`/`remaining_steps=[STEP_LIQUID_PHASE_SEPARATION]`
with `STEP_VAPOR_PHASE_SEPARATION` absent/`blocked_reason='not_implemented'`
— per `tools/binary-distillation-condensation-edge-case.md`, this real
Methanol/Water 400 K worked example also conditions to complete
condensation at 313.15 K, so its `route` is `'liquid_phase_separation'`,
not `'liquid_and_vapor_separation_future'` — a not-ready workflow's
`blocked_reason='workflow_not_ready'`, `remaining_outputs` staying `[]`
even though `remaining_steps` is non-empty), the
`get_binary_distillation_calculation_status` READ before/after a
calculation, reset and WRITE invalidation, and the exact worked
regression from that doc (complete Case D → "yes" runs the calculation →
"okay what next" routes to `get_binary_distillation_calculation_status`
without any `update_binary_distillation_problem` call, never re-asking for
components/flow/temperature/pressure/xD/xB/boilup ratio/reflux
condition/optimum feed plate) — plus a "what next?" asked BEFORE any
calculation has run (routes to `get_precalculation_progress`, reporting
`next_step='feed_phase'`) and a post-calculation "continue" (reporting
`next_step_available=False`, never silently performing Case D design). Run
with:
```bash
pytest tools/chopper/test_binary_distillation_calculation_progress.py -v
```

---

# `separation_plots.py`

Matplotlib plots of a `sweep_reflux_ratio` (or `annualize_sweep`/
`optimize_reflux_ratio`) DataFrame, always against `reflux_ratio_k` on the
x-axis. Pure visualization — no new computation beyond what's already in
the DataFrame's columns.

| Function | Plots | Notes |
|---|---|---|
| `plot_purity_vs_reflux(df, spec=None, ...)` | Achieved purity or recovery (whichever `spec` picks) vs. `reflux_ratio_k`, with the target drawn as a reference line. | If `spec=None`, it's inferred from whichever of `purity_target`/`recovery_target` is actually populated in `df`. |
| `plot_utility_cost_vs_reflux(df, ...)` | Reboiler heating cost and condenser cooling cost (`$/hr`) vs. `reflux_ratio_k`. | Two lines, one legend. |
| `plot_reflux_sweep(df, spec=None, save_dir=None, show=True)` | Convenience wrapper: draws both plots above in one call. | If `save_dir` is given, saves `{save_dir}/{purity or recovery}_vs_reflux.png` and `{save_dir}/utility_cost_vs_reflux.png`. |

All three take an optional `ax`/`save_path` (or `save_dir`) and `show`
argument, following standard matplotlib-wrapper conventions — pass `ax` to
draw onto an existing axes instead of creating a new figure, `save_path`/
`save_dir` to write PNGs, `show=False` to suppress the interactive
`plt.show()` call (needed in headless/non-interactive runs, e.g. with
`matplotlib.use('Agg')`).

## Example

```python
from separation_plots import plot_reflux_sweep

plot_reflux_sweep(result['sweep_df'], save_dir='.', show=False)
```

Running `python separation_plots.py` directly reads `reflux_ratio_sweep.csv`
(as written by `sweep_separation.py`'s own demo run) and plots it.

---

# `separation_tool.py` + `separation_agent.py` — Ollama tool-calling agent

Lets a user describe a separation in plain English and get back a column
design, via a local Ollama model (default: `qwen3:8b`) that decides when
to call one of two tools: `design_separation_case()` (a single
deterministic Wankat-case design) or `optimize_separation()` (a
cost-optimized sweep over an internal reflux multiplier). Neither tool
silently completes a missing input — both run the `problem_spec`/
`case_design` machinery described above before doing anything
BioSTEAM-related, and refuse to proceed on an incomplete or ambiguous
request.

```
User types a request in plain English
        │
        ▼
separation_agent.py          qwen3:8b (via Ollama) decides whether to
    call design_separation_case() or optimize_separation()
        │
        ▼
separation_tool.py           validate_problem()/check_essential_inputs()
    check completeness FIRST (no feed/BioSTEAM built yet); only if valid,
    builds a bst.Stream with the feed's stated thermal condition, then
    calls case_design.design_binary_distillation() or
    optimizer.optimize_reflux_ratio(); returns a plain JSON-safe dict
        │
        ▼
separation_agent.py           feeds the tool result back to the model,
    which explains it in plain English (or relays the missing/ambiguous
    fields back to the user, per SYSTEM_PROMPT)
```

## `separation_tool.py`

Exposes three functions: `design_separation_case(...)`,
`optimize_separation(...)`, and `reset_separation_session()`, all meant to
be passed directly to Ollama's `tools=[...]` argument (not called by
hand). Ollama's client introspects each function's type hints and
Google-style docstring (via `convert_function_to_tool`) to build the JSON
schema the model sees — so the signature and each `Args:` line *are* the
model's documentation of the tool; keep them accurate if the signature
changes.

### Cross-call accumulation — why every argument is optional

Every argument on `design_separation_case`/`optimize_separation` defaults
to `None`. This is deliberate, not a relaxation of the "never assume"
requirement: a tool-calling model (especially a small local one like
`qwen3:8b`) cannot be relied on to restate the entire spec on every
follow-up call — in practice, after being asked for a missing field, it
will often call back with *only* that one new field. Making every
argument required (as an earlier version of this tool did) doesn't fix
that; it just means the follow-up call is either missing required
arguments (a `TypeError`) or the model reaches for a plausible-sounding
default to fill the gap itself, which is exactly the silent-assumption
behavior this whole layer exists to prevent.

Instead, both functions merge whatever they're given into a **module-level
accumulator**, `_spec_state`, and validate the *accumulated* state, not
just the current call's arguments:

- `_merge_into_state(new_fields)` copies every non-`None` field from this
  call into `_spec_state`. Two field groups are mutually exclusive
  (`_THERMAL_FIELDS` = the three feed-thermal-condition fields;
  `_REFLUX_QUANTITY_FIELDS` = `external_reflux_ratio_LD` /
  `reflux_ratio_multiplier_k`): if exactly one member of a group is given
  in *this* call, the merge clears any other member left over from an
  *earlier* call first, so a stale choice from a previous turn can never
  silently linger and create a false conflict against a new one. If more
  than one member of a group is given in the *same* call, nothing is
  cleared — both values are set, so `problem_spec.identify_case()`'s own
  conflict detection (e.g. both `external_reflux_ratio_LD` and
  `reflux_ratio_multiplier_k` present at once) still fires correctly.
- `_STABLE_FIELDS` = `components`, `light_key`, `heavy_key` — these
  identify *which* separation problem this is, not a parameter of it. If a
  call resends one of these with a value that differs from what's already
  in `_spec_state`, `_merge_into_state` raises `ConflictingResend` instead
  of overwriting it; both `design_separation_case` and `optimize_separation`
  catch this and return `{'valid': False, 'error': 'conflicting_resend',
  'field', 'previous_value', 'attempted_value', 'message'}` telling the
  caller to either omit the field (to keep the established feed) or call
  `reset_separation_session()` first if the feed genuinely changed. This
  guards against exactly the failure mode a small tool-calling model is
  prone to: being asked only for a missing field (e.g. pressure) and, on
  the very next call, fabricating a *different* feed composition instead of
  omitting `components` — before this check, that silently clobbered the
  correct accumulated feed with no indication anything had changed. A
  resend with the *same* value (or omitting the field entirely) is not a
  conflict and proceeds normally.
- Both functions then call `problem_spec.validate_problem()` /
  `check_essential_inputs()` on the full accumulated `_spec_state`, not on
  the current call's raw arguments — so a call that supplies only a
  `feed_temperature_K` the model was just asked for is validated against
  everything given in earlier calls too, and can complete the design even
  though this call's own arguments look completely partial in isolation.
- `_missing_keys_check(state)` additionally checks `light_key`/`heavy_key`
  are present (these identify which feed component is which for BioSTEAM,
  but aren't Table 3-1/3-2 Wankat variables themselves, so `problem_spec`
  doesn't check them) and folds any missing ones into the same
  `missing_essential_inputs` list/message.
- `reset_separation_session()` clears `_spec_state` entirely. Both
  system prompts instruct the model to call this only when the user
  switches to a genuinely different, unrelated separation problem — never
  between ordinary follow-up turns — since calling it mid-problem would
  discard information still needed.

`_spec_state` lives for the life of the Python process (one REPL session,
or one one-shot invocation) — it is not persisted to disk and is not
shared across separate `python separation_agent.py` invocations.

### `design_separation_case(...)` — single deterministic Wankat-case design

| Argument | Meaning |
|---|---|
| `components`, `light_key`, `heavy_key`, `units` | Same as below — feed composition/flow and key components. Omit on a later call if already given in an earlier one this conversation — the accumulated value is reused. |
| `pressure_Pa` | Column pressure (Pa). Never defaulted — reported as missing until given in some call. |
| `reflux_condition` | Must be the literal string `'saturated_liquid'` — the only reflux thermal condition the engineering layer implements; must be stated explicitly rather than assumed. |
| `feed_temperature_K`, `feed_quality`, `feed_enthalpy_kJ_per_hr` | The feed's thermal condition — give **exactly one** (across however many calls it takes). Never defaulted (no bubble-point fallback); omitting all three (in the accumulated state) is reported as a missing essential input, not silently resolved. |
| `xD`, `xB` | Case A/D — distillate/bottoms light-key mole fractions. |
| `Lr`, `Hr` | Case B — fractional recoveries of light key (distillate) and heavy key (bottoms). Giving either one narrows the accumulated case candidates to Case B. |
| `distillate_flow`, `bottoms_flow` | Case C — give at most one. |
| `boilup_ratio_VB` | Case D — boilup ratio V/B. |
| `external_reflux_ratio_LD` | Wankat's external/actual reflux ratio L0/D (Cases A-C). **Not the same quantity as** `reflux_ratio_multiplier_k` — see `problem_spec.py`/`case_design.py` above; giving both (in the accumulated state) is rejected as ambiguous. |
| `reflux_ratio_multiplier_k` | The internal BioSTEAM shortcut parameter k = R/Rmin (Cases A-C, alternative to `external_reflux_ratio_LD`). |
| `target` | `'top'` or `'bottom'` — which outlet is labeled `'product'`; doesn't affect case identification. |

Internally: merges all given arguments into `_spec_state` (see above),
then calls `problem_spec.validate_problem(_spec_state)` **before** touching
BioSTEAM at all. If `not valid`, the function returns that report directly
(`{'valid': False, 'case', 'missing_essential_inputs',
'case_candidates', 'missing_case_inputs_by_candidate', 'ambiguous',
'ambiguous_reason', 'message', 'provenance'}`) — no flowsheet switch, no
feed stream, no column. Only if valid does it switch to a fresh
`bst.main_flowsheet` (`sep_agent_{n}`), build the feed with its stated
thermal condition via `feed.vle(...)` (never `.bubble_point_at_P()`), and
call `case_design.design_binary_distillation()`, merging that result with
the `validate_problem()` report (so `case`/`provenance` are always present
alongside the design/`implemented`/`reflux` fields described in the
`case_design.py` section above).

**No default to Case A.** `problem_spec.identify_case()` (see above) never
picks a case on its own — whenever nothing case-distinguishing has been
given yet (no `xD`/`xB`, `Lr`/`Hr`, product flow, or boilup ratio), `case`
is `null` and `case_candidates` lists every case still consistent
(typically all four, A-D), each with its own `missing_case_inputs_by_candidate`
entry. This means the tool (or the model consuming its output) must ask
which kind of specification the user wants to give, rather than silently
assuming Case A or asking the user to pick a case letter out of four. As
soon as the accumulated state contains something case-specific — most
commonly `Lr`/`Hr` — the candidate set narrows to whichever case that
information actually matches (Case B for recoveries) instead.

### `optimize_separation(...)` — cost-optimized reflux sweep

Same purpose as before (sweep `reflux_ratios_k` and return the cheapest
feasible design), and shares the same cross-call accumulation, `_spec_state`,
described above with `design_separation_case` (giving a pressure or feed
condition to one carries over to the other):

| Argument | Meaning |
|---|---|
| `components`, `light_key`, `heavy_key`, `units` | Same as `design_separation_case`. |
| `pressure_Pa`, `reflux_condition` | Never defaulted — same meaning as `design_separation_case`. |
| `feed_temperature_K`, `feed_quality`, `feed_enthalpy_kJ_per_hr` | Feed thermal condition — give exactly one (across however many calls); never defaulted. Replaces the old hardcoded `feed.T = feed.bubble_point_at_P().T`. |
| `spec`, `target`, `purity_target`, `recovery_target` | Unchanged — same meaning as `optimize_reflux_ratio()`. `spec`/`target` fall back to `'purity'`/`'top'` only if never given in any call. |
| `reflux_ratios_k` | Unchanged; the **internal** multiplier sweep, explicitly documented in the docstring as not the external/actual reflux ratio. Defaults to `DEFAULT_REFLUX_RATIOS_K = [1.2, 1.5, 1.75, 2.0, 2.5, 3.0, 3.5]` if omitted. Not accumulated across calls (always taken from the current call, since re-sweeping with the same list every time would be redundant). |

Internally: merges given arguments into `_spec_state`, then calls
`problem_spec.check_essential_inputs()` on the accumulated state (Table 3-1
only — this tool isn't organized around a single Wankat case, so
`identify_case()` doesn't apply); also runs the same `light_key`/`heavy_key`
presence check as `design_separation_case`. If anything essential is
missing or the feed thermal condition is ambiguous/the reflux condition
unsupported, returns `{'valid': False, 'missing_essential_inputs', ...,
'message', 'provenance'}` without building anything. Otherwise builds the
feed (same `feed.vle(...)` pattern, no bubble-point default), calls
`optimize_reflux_ratio()`, and returns
`{'valid': True, 'found', 'message', 'n_feasible', 'n_total', 'best_design', 'key_selection'}`,
recursively converted from numpy/pandas scalars to plain Python types via
the internal `_jsonify()` helper. `key_selection` is
`optimize_reflux_ratio()`'s `validate_key_selection()` output passed
straight through (see the `optimizer.py` section above) — its inclusion
here is what gets the key-selection warning in front of the model; the
docstring's `Returns:` line explicitly tells the model to check
`key_selection['warning']` before attributing an infeasible result to
reflux ratio or purity/recovery target.

### `reset_separation_session()` — clear the accumulator

Clears `_spec_state` entirely and returns `{'reset': True, 'message': ...}`.
Both `SYSTEM_PROMPT`s instruct the model to call this only when the user
is clearly switching to a different, unrelated separation problem, never
between ordinary follow-up turns refining the same one — calling it
mid-problem would discard fields still needed and reintroduce the exact
restate-everything burden the accumulation above exists to remove.

`TOOLS = [design_separation_case, optimize_separation, reset_separation_session]`
and
`TOOL_FUNCTIONS = {'design_separation_case': design_separation_case, 'optimize_separation': optimize_separation, 'reset_separation_session': reset_separation_session}`
are the two names `separation_agent.py` imports — the former goes straight
into Ollama's `tools=` argument, the latter is used to dispatch a tool
call by name back to the actual Python function.

## `separation_agent.py`

The runnable chat agent. Talks to a **local Ollama server** running
`qwen3:8b` via the `ollama` Python client, with `separation_tool.TOOLS`
(both `design_separation_case` and `optimize_separation`) registered.
`SYSTEM_PROMPT` tells the model: use `design_separation_case` when the
user has stated (or has been asked for and given) a specific reflux
ratio; use `optimize_separation` for a cost search; **once one of those two
tools has been used for the current problem, keep calling that same tool on
every follow-up turn — supplying a previously-missing field or tweaking a
parameter is never itself a reason to switch tools; only switch when the
user explicitly changes what kind of answer they want** (a specific design
vs. a cost search); never assume pressure, feed thermal condition, or
reflux condition — ask instead; treat `external_reflux_ratio_LD` and
`reflux_ratio_multiplier_k` as different quantities and never convert one
into the other itself; read `missing_essential_inputs`/`case_candidates`/
`ambiguous_reason` back to the user verbatim when a call returns
`valid: false` rather than retrying with a guess; and if a call returns
`error: "conflicting_resend"` (see `_STABLE_FIELDS` above), don't retry
with another guessed feed — either omit the conflicting field or call
`reset_separation_session()` if the feed genuinely changed. Two modes:

- **Interactive REPL** — `python separation_agent.py`, then type requests
  at the `You:` prompt; `exit`/`quit`/Ctrl+C to leave. Conversation
  history (`messages`) persists for the life of the process, so follow-ups
  like "now try 99.5% instead" have context from earlier turns.
- **One-shot** — `python separation_agent.py "<prompt>"`: runs a single
  prompt, prints the reply, exits. Useful for scripting/testing.

`ask(client, messages)` is the core loop: send `messages` to the model
with `tools=TOOLS`; while the model's response includes `tool_calls`,
look each one up in `TOOL_FUNCTIONS` by name, call it with
`**call.function.arguments`, append the JSON-serialized result back onto
`messages` as a `{'role': 'tool', ...}` message, and re-query the model —
until it responds with plain text instead of another tool call. Each
resolved tool call is echoed to stdout as
`[calling optimize_separation({...})]` before the result comes back, so
you can see what arguments the model actually chose.

Both `client.chat(...)` calls in `ask()` pass `think=False`. `qwen3:8b` is a
hybrid thinking model that otherwise emits a `<think>...</think>` reasoning
block before every response and before every tool call; `think=False` turns
that off via Ollama's chat API. This was switched off deliberately — it made
the agent noticeably faster, since the model no longer spends tokens
reasoning through each tool-call decision and each final summary.

### Guarding against non-binary feeds (and the now-dormant key-selection safeguard)

Since the toolkit-wide binary-only restriction was added (see the
top-level "Scope" note), a 3+ nonzero-component feed can no longer reach
the shortcut method at all — `check_binary_feed()` rejects it with a
`ValueError` before any column is built, independent of anything the model
does. `SYSTEM_PROMPT` in `separation_agent.py` is written to cooperate
with this: it instructs the model, when a user describes a feed with three
or more components, *not* to work around the limit by calling the tool
with only two of them and silently dropping the rest, but to tell the user
ternary/multicomponent feed support isn't available yet and ask them to
narrow the request to a true two-component feed.

Before this restriction existed, the risk was different: `qwen3:8b`
picking `light_key`/`heavy_key` that weren't adjacent in volatility (e.g.
lightest + heaviest, skipping a middle-boiling component) would produce an
infeasible or nonsensical design that had nothing to do with reflux ratio
— see
[`validate_key_selection()`](#validate_key_selection-key-selection-sanity-check)
above for the mechanism, and its "currently dormant in practice" note.
Two safeguards addressed that risk (prompt instructions to order
components by boiling point before choosing keys, plus a `key_selection`
field in every tool result for the model to check). Both remain in the
code for when ternary support returns, but neither can currently be
exercised through the normal pipeline, since `check_binary_feed()` now
rejects the ternary feed outright before key selection is ever relevant.

### How to run it

From an Anaconda Prompt (or any terminal with `conda` on `PATH`):

```bash
conda activate pyfuel
cd "tools/chopper"    # bare-import convention -- see note above

python separation_agent.py                 # interactive REPL
python separation_agent.py "Separate 80 kmol/hr methanol and 100 kmol/hr water, 99% pure methanol overhead"   # one-shot
```

**Prerequisites:**
- A local Ollama server must be running (normally automatic once Ollama
  is installed — a tray app/service; `ollama serve` in a separate terminal
  if it isn't).
- The model must be pulled once: `ollama pull qwen3:8b`.
- Run with the `pyfuel` environment's Python — that's where `ollama` and
  `biosteam` are both installed (`ollama` is not in the repo's base
  `requirements.txt`; it was added ad hoc via `pip install ollama` for
  this agent).

**Getting good results:** state real chemical names for exactly **two**
components (e.g. Water, Methanol, Ethanol, Glycerol — any two of these,
not three or more) with explicit flow rates and units (kmol/hr or kg/hr),
a column pressure, the feed's thermal condition (temperature, vapor
fraction, or enthalpy), confirmation that reflux is saturated liquid, and
either a specific reflux ratio (for `design_separation_case`) or a purity/
recovery target (for `optimize_separation`). None of these are ever
defaulted for you — expect the model to ask a follow-up for any of them
it wasn't given, per `problem_spec.py`'s Table 3-1 essential-input check
(see the `problem_spec.py`/`case_design.py` section above), rather than
silently assuming bubble point, 1 atm, or saturated-liquid reflux. A
three-or-more-component feed is not supported yet (see the top-level
"Scope" note); the model should say so rather than guessing which two
components to keep.

You do not need to repeat earlier answers when responding to a follow-up
question — `separation_tool.py` remembers everything already given about
the current separation problem (see "Cross-call accumulation" in the
`separation_tool.py` section above), so answering just "350 K" to a
feed-temperature question is enough; the tool merges it with the pressure,
components, etc. already established. If you want to start a *different*
separation problem in the same session, say so explicitly (e.g. "let's do
a different separation") — the model is instructed to call
`reset_separation_session()` in that case, but not on ordinary follow-ups.

---

# `tools/chopperRAG/` — separation-heuristics RAG (separate toolkit)

A **different, unconnected** proof-of-concept living alongside
`chopper/` in the same top-level `tools/` folder. Where `chopper`
*runs* BioSTEAM columns, `chopperRAG` *mines a separations textbook* for
engineering design heuristics (rules of thumb like "if the compound is
heat-sensitive, do X") and makes them queryable via a local LLM + vector
search. The two are not wired together yet — per the folder's own README,
turning a retrieved heuristic's `design_implication` into an actual
`optimize_reflux_ratio()` call is future work, not something either tool
does today.

**Dual-storage RAG design:** every textbook chunk is stored raw in Chroma,
and any heuristics an LLM extracts from it are stored as separate, linked
records in the same collection (`parent_chunk_id` ties a heuristic back to
its source chunk). One query returns a mix of both; heuristic hits get
their parent chunk hydrated automatically.

| File | Role |
|---|---|
| `config.py` | Local LLM endpoint/model, embedding model, Chroma path, chunking/retrieval knobs. |
| `schema.py` | `Heuristic` / `ExtractionResult` pydantic models — the shape of one extracted rule (`category`, `condition`, `principle`, `design_implication`, plus `heuristic_type`/`equation`/`required_variables` for calculation-based heuristics — see below). |
| `ingest.py` | PDF → paragraph-aware chunks → LLM extraction → dual storage in Chroma. |
| `query.py` | Embeds a question, retrieves heuristics + hydrated raw chunks, asks the LLM to answer grounded in that context. `--test` runs three canned PoC questions. |
| `seed_heuristics.py` | Hand-seeds a set of manually-verified ground-truth heuristics directly into Chroma, bypassing LLM extraction — see below. |
| `requirements.txt` | `chromadb`, `openai` (client, used against any OpenAI-compatible local server), `sentence-transformers`, `pymupdf`, `pydantic`. |
| `SETUP.md` | Step-by-step run checklist (activate `pyfuel`, `cd` here, confirm Ollama's up with the model pulled, seed, query) — a cheat sheet for re-running the tool, not design notes. |

## `schema.py` — heuristic shape, including calculation-based heuristics

`Heuristic` (and the `ExtractionResult` list it lives in) has two kinds of
rows, distinguished by `heuristic_type`:

- **`"rule"`** (default) — a qualitative judgment call: `category`,
  `condition`, `principle`, `design_implication` only. This is the original
  shape and covers most extracted/seeded heuristics today.
- **`"equation"`** — a calculation-based heuristic. Adds `equation` (the
  formula as a plain string, e.g. `"SF = alpha_1,2 = Ps_1 / Ps_2"`) and
  `required_variables` (`List[str]` of the variable names on the
  right-hand side, e.g. `["Ps_1", "Ps_2"]`). `ingest.py`'s extraction prompt
  asks the LLM to classify each extracted heuristic this way, and
  `seed_heuristics.py` has one hand-seeded example (separation-factor ≈
  relative volatility, from Seader ch. 9).

`equation` is currently opaque text — nothing parses or evaluates it; a
human (or the answering LLM in `query.py`) reads it and applies it by hand.
Chroma metadata values must be scalars, so `required_variables` is stored as
a comma-joined string (`ingest.py`/`seed_heuristics.py`) and split back into
a list wherever it's read for display (`query.py`).

**Future work (not started):** wire `heuristic_type="equation"` heuristics
into an actual BioSTEAM calculation instead of just surfacing the formula as
text — e.g. a small registry mapping `required_variables` names to how to
pull/compute them from a live BioSTEAM stream or chemical (`Ps_1` →
`chemicals['X'].Psat(T)`), plus a generic evaluator that plugs those into
`equation`. This is a distinct, later step from the `chopper`↔`chopperRAG`
wiring already flagged as future work below (turning a `design_implication`
into an `optimize_reflux_ratio()` call) — both are on the roadmap, neither
is built yet.

## `seed_heuristics.py` — ground-truth retrieval validation

Before trusting `ingest.py`'s LLM-driven extraction across a whole
textbook, `seed_heuristics.py` plants a set of known-good heuristics
straight into the Chroma collection, so retrieval quality can be checked
independently of extraction quality. `SEED_HEURISTICS` is a list of
**`(source_tag, Heuristic)`** tuples, not a flat list of `Heuristic` —
two different textbooks are both cited as "ch. 9" here (Seader's
*Separation Process Principles* vs. Seider et al.'s *Product and Process
Design Principles* — easy to confuse given the near-identical author
names), so each entry carries its own `source_tag` explicitly rather than
relying on one module-level constant. `DEFAULT_SOURCE_TAG = "seader_ch9"`
covers most entries; a couple are tagged `"seider_ch9"` instead.

Twelve heuristics are currently seeded, spanning two qualitatively
different categories:

- **`separation_technique_selection`** (2 entries, Seader ch. 9) — *what
  class of separation technique to even consider*, based on feed phase:
  vapor feed → don't default to ordinary distillation, consider partial
  condensation, cryogenic distillation, gas absorption/adsorption,
  membrane gas permeation, or desublimation instead; liquid feed → a much
  broader toolkit applies (flash, ordinary distillation, stripping,
  extractive/azeotropic distillation, LLE, crystallization, liquid
  adsorption, membrane processes, supercritical extraction).
- **`separation_factor_estimation`** (1 entry, Seader ch. 9) — the
  equation-type heuristic (separation factor ≈ relative volatility); see
  the `schema.py` section above.
- **`separation_sequence_selection`** (2 entries) — *where in a
  multi-step sequence a given separation belongs*, not which technique to
  use. Qualitatively distinct from `separation_technique_selection` above:
  (1, Seider ch. 9) remove thermally unstable/corrosive/reactive
  components early in the sequence; (2, Seader ch. 9 sec. 9.4) for a
  nearly-ideal multicomponent feed (e.g. a hydrocarbon mixture or a
  homologous series like alcohols), an all-ordinary-distillation sequence
  is often economical, provided each column's feasibility conditions hold.
- **`distillation_feasibility`** (7 entries, Seader ch. 9 sec. 9.4) — the
  per-column feasibility checks that back up the sequencing heuristic
  above: relative volatility between keys > 1.05, reboiler duty not
  excessive, tower pressure not near the critical temperature, overhead
  vapor condensable without excessive refrigeration, bottoms temperature
  below the point of thermal decomposition, no azeotrope blocking the
  split, and tolerable column pressure drop (especially under vacuum).

Each heuristic is rendered to the same `"When {condition}: {principle}.
Design implication: {design_implication}"` sentence `ingest.py` uses,
embedded with `config.EMBED_MODEL`, and `upsert`ed with
`parent_chunk_id=""` (no source chunk on file, since it was typed by
hand) and `source_file=<its own source_tag>`.

**Run it** — see `SETUP.md` for the full walkthrough (env activation,
Ollama check, troubleshooting); short version:
```bash
conda activate pyfuel
cd "tools/chopperRAG"
pip install -r requirements.txt   # one-time
python seed_heuristics.py         # no Ollama needed — embedding-only; upserts by ID, safe to re-run
```

**Then validate retrieval with `query.py`** (this step needs a local Ollama
server running the model named in `config.py`'s `LLM_MODEL`):
```bash
python query.py "What separation technique should I use for a vapor feed?"
python query.py "What separation options exist if my feed is a liquid?"
python query.py "My feed has a corrosive component - where in the separation sequence should I remove it?"
python query.py "Can I use a plain sequence of distillation columns for a nearly ideal hydrocarbon mixture?"
```
Check that the printed heuristics block ranks the *matching* seed entry
first, and — now that `retrieve()`/`format_heuristics()` attach each
result's raw Chroma distance as a `distance` field (added after the
initial 2-entry validation below; **lower = more similar**, results are
already ordered nearest-first) — that its `distance` is meaningfully
lower than the next entry's, not just "first by luck." Also confirm the
`ANSWER:` text is grounded in the matching entry rather than a different
one.

**Validated 2026-08-18/19** against `qwen3:8b` (config's `LLM_MODEL`
updated from the default `qwen2.5:14b-instruct` to match), when the store
held only the original 2 technique-selection heuristics: both directions
passed — the vapor question ranked the vapor heuristic first and answered
from it exclusively; the liquid question ranked the liquid heuristic first
and answered from it exclusively. Confirms the embedding model
(`BAAI/bge-small-en-v1.5`) can tell the two heuristics apart despite their
near-identical boilerplate phrasing ("feed is a X, or is readily converted
to a X..."), and that the answer-generation prompt grounds itself in the
correct retrieved entry rather than defaulting to whichever is listed
first. Not yet re-validated against the full 12-entry set above.

**Caveat:** `query.py`'s `answer()` call does not pass a `think=False`
equivalent, unlike `separation_agent.py`'s `ask()` (see above) — since
`qwen3:8b` is a hybrid thinking model, expect a `<think>...</think>` block
ahead of the answer text in `query.py`'s output.

## Where the similarity comparison actually happens

`sentence-transformers` only *produces* vectors (`embedder.encode(text)` —
text in, a fixed-length embedding out); it has no notion of "similar to
what." The nearest-neighbor comparison itself happens inside **`chromadb`**,
in `collection.query(query_embeddings=[q_emb], n_results=top_k)`
(`query.py`'s `retrieve()`) — Chroma walks its internal HNSW index and
returns the stored vectors closest to the query vector, ranked
nearest-first. That ranking is what determined "vapor heuristic ranks
first for a vapor question" in the validation above; the LLM never
re-judges relevance itself, it only sees results Chroma already ranked.
`retrieve()` also pulls `results["distances"][0]` alongside the documents/
metadatas and attaches it to each heuristic dict; `format_heuristics()`
prints it as a `distance` field, so the raw per-result score is visible
in `query.py`'s output, not just the (already-sorted) print order.

**Distance metric caveat (unverified against a larger corpus):** none of
`ingest.py`/`query.py`/`seed_heuristics.py` pass `metadata={"hnsw:space":
...}` to `get_or_create_collection`, so the collection runs Chroma's
default distance metric (squared L2), and `embedder.encode(...)` is never
called with `normalize_embeddings=True` either. `bge-small-en-v1.5` is
trained/benchmarked for cosine similarity, not raw L2 — on 2 seed entries
the ranking still came out correct, but this is worth revisiting (set
`hnsw:space="cosine"` and/or `normalize_embeddings=True`) before trusting
retrieval precision at full-textbook scale, per the README's own
"precision on the structured side" checklist item.

## Library roles at a glance

| Library | Job in this pipeline |
|---|---|
| `pymupdf` (`fitz`) | Reads the source PDF, extracts raw page text. |
| `sentence-transformers` | Text → embedding vector. The engine behind both storage-time and query-time embedding; does not compare vectors itself. |
| `chromadb` | Stores (text, vector, metadata) records and performs the actual nearest-neighbor similarity search + plain ID lookups (for parent-chunk hydration). |
| `pydantic` | Validates that any `Heuristic` (hand-seeded or LLM-extracted) has all four required string fields before it's stored — schema enforcement, not content judgment. |
| `openai` (client) | Generic OpenAI-compatible HTTP client, pointed at the local Ollama server — carries both the extraction request (`ingest.py`) and the answer-generation request (`query.py`) to `qwen3:8b`. |

---

# `tools/separation_rag_agent.py` — the merged agent

The chopper↔chopperRAG wiring flagged as future work above (now built, in a
first, prompt-guided form): one Ollama tool-calling agent, `TOOLS =
[design_separation_case, optimize_separation, reset_separation_session, retrieve_separation_heuristics]`,
that decides per turn which tool(s) to call. `design_separation_case`,
`optimize_separation`, and `reset_separation_session` are imported
unchanged from `chopper/separation_tool.py` (see the `problem_spec.py`/
`case_design.py` and `separation_tool.py` sections above — neither sizing
tool silently completes a missing pressure, feed thermal condition, or
reflux condition, neither conflates the external reflux ratio L0/D with
the internal k = R/Rmin multiplier, and both share the same cross-call
`_spec_state` accumulator so a follow-up only needs to supply what's new).
`retrieve_separation_heuristics` is new — a thin wrapper around
`chopperRAG/query.py`'s `retrieve()` that returns raw matched heuristics +
hydrated textbook chunks (not a pre-synthesized answer, to avoid a
redundant second LLM call inside the tool — the outer chat model already
gets a turn to read and summarize tool output).

Neither `chopper/separation_agent.py` nor `chopperRAG/query.py` is changed
or superseded — both remain independently runnable exactly as documented
above, for standalone testing of each half.

**Tool continuity, and rejecting a drifted feed.** Same as
`chopper/separation_agent.py`'s `SYSTEM_PROMPT` (see above): once
`optimize_separation` or `design_separation_case` has been used for the
current problem, `SYSTEM_PROMPT` here instructs the model to keep calling
that same tool on every follow-up turn — answering a question the model
itself asked (a missing pressure, feed condition, etc.) is never grounds to
switch tools; only an explicit user request to switch between "a specific
design" and "a cost search" is. This was added after an observed failure
where a follow-up turn that only supplied pressure and feed temperature
caused the model to both switch from `optimize_separation` to
`design_separation_case` *and* resend `components` with a fabricated flow
rate different from the one established two turns earlier. The second half
is now also caught in code, not just prompted against: `_STABLE_FIELDS`
(`components`/`light_key`/`heavy_key`) in `separation_tool.py` reject a
resend that conflicts with the accumulated value (`ConflictingResend` →
`{'valid': False, 'error': 'conflicting_resend', ...}`) instead of silently
overwriting it — see the `_merge_into_state` bullet in the
`separation_tool.py` section above.

**Heuristic checking is model-decided, not auto-triggered.** `SYSTEM_PROMPT`
nudges the model to call `retrieve_separation_heuristics` before/alongside a
sizing call when the situation looks unusual (vapor feed, heat-sensitive/
corrosive/reactive component, azeotrope, or a qualitative "what should I
use" question) and to fold any resulting caveat into the same summary as the
costed design — e.g. a vapor-feed sizing request gets back one answer noting
both the column cost *and* that ordinary distillation isn't the default
choice for a vapor feed — rather than two disconnected outputs. It is not
required on plain, ordinary-distillation-appropriate requests. Equation-type
heuristics (`heuristic_type='equation'`) are explicitly called out as
non-evaluated reference text, same as `query.py` treats them today —
building an evaluator for those is a separate, still-unstarted piece of
future work.

**Retrieved heuristics are filtered and tiered before being summarized, not
just relayed.** Because `retrieve_separation_heuristics` returns up to
`top_k` (default 8) nearest-neighbor hits out of a small (~12-entry) pool,
most calls come back with several heuristics that aren't actually relevant to
the question — `SYSTEM_PROMPT` explicitly instructs the model not to mention
a heuristic merely because it was retrieved, and to ignore anything that
doesn't help answer the specific question even if it ranked highly. For the
heuristics that are kept, it classifies each into one of two tiers:
**directly triggered** (the heuristic's `condition` is explicitly established
by the facts given — state its `principle`/`design_implication` as an active
finding) vs. **conditionally relevant** (the heuristic bears on the situation
but its own `condition` hasn't been established yet — phrase it as a check
still to be performed, not a conclusion already reached; e.g. a
bottoms-temperature-decomposition heuristic surfaced by a heat-sensitivity
question, when no bottoms temperature has actually been given or computed).
A single question can trigger heuristics at multiple levels at once —
technique/key selection, sequencing, feasibility — and the prompt explicitly
tells the model to synthesize across all of them into one coherent answer
rather than collapsing to a single "winning" heuristic. `chopperRAG/query.py`'s
`ANSWER_PROMPT` carries the same filtering/tiering/synthesis instructions,
independently, for standalone testing of the chopperRAG half.

**Prerequisites** (all already present in the `pyfuel` conda env as of this
writing): everything `chopper/separation_agent.py` needs (`biosteam`,
`ollama`) *and* everything `chopperRAG` needs (`chromadb`, `openai`,
`sentence-transformers`, `pymupdf`, `pydantic`), plus a local Ollama server
running `qwen3:8b`, plus a seeded Chroma collection:
```bash
conda activate pyfuel
python tools/chopperRAG/seed_heuristics.py   # once, if not already seeded
```

**Run it** (from anywhere — unlike the two standalones, `sys.path` wiring at
the top of the script makes cwd irrelevant):
```bash
python tools/separation_rag_agent.py                 # interactive REPL
python tools/separation_rag_agent.py "I have a vapor feed of 80 kmol/hr methanol and 100 kmol/hr water at 1 atm. Should I use ordinary distillation, and if so what would a 99% pure methanol column cost?"
```

`tools/chopperRAG/config.py`'s `CHROMA_DIR` was changed from the relative
`"./chroma_db"` to an absolute path (`Path(__file__).parent / "chroma_db"`)
so it resolves correctly regardless of the caller's cwd — this is what lets
the merged agent (which does not run from `tools/chopperRAG`) find the same
Chroma collection `query.py`/`ingest.py`/`seed_heuristics.py` use. The two
paths are identical when those three are run the documented way (cwd already
`tools/chopperRAG`), so this is a pure robustness fix with no behavior
change for their existing documented usage.
