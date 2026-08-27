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
5. **Ready for calculation**: once all of the above are satisfied,
   `status='ready_for_calculation'` and `would_calculate` lists exactly
   what a designer would compute for that case (workflow doc section 8;
   Case C's list depends on which of `distillate_flow`/`bottoms_flow` and
   `xD`/`xB` was actually given, since the other one is what gets
   calculated). `calculation_performed` is **always `False`** — this
   function never builds a feed stream or calls BioSTEAM.

Return schema (workflow doc section 15, extended by
`tools/binary-distillation-flow-rate-issue.md` section 8/10 and
`tools/binary-distillation-pending-truth.md` section 2/18): `{'valid_binary_scope',
'component_count', 'components', 'feed_flow_complete',
'feed_composition_complete', 'feed', 'essential_complete',
'missing_essential_inputs', 'case', 'case_candidates', 'case_complete',
'missing_case_inputs', 'optimum_feed_plate_confirmed', 'status',
'would_calculate', 'calculation_performed', 'message', 'provenance',
'pending_request'}`.
`feed` is the normalized `feed_state` dict (component flows/total flow/
composition, each with its provenance) — present on every result once the
scope gate passes, primarily for audit/debugging rather than for the
caller to reproduce logic from. `status` can also be `'inconsistent_input'`
when redundant feed information disagreed (e.g. component flows don't sum
to an explicitly-given total flow). Never raises. Running `python
binary_distillation_workflow.py` directly prints ten demo reports covering
the scope gate, component-names-only (no invented flows), a single
component flow (not treated as the total), missing essentials, an
inconsistent-input case, the no-case-signal state, boilup-ratio routing to
Case D, and a complete Case D report.

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
```

It is generated by `_essential_pending_request()` (a single missing
`pressure_Pa` or `reflux_condition`) and `_case_pending_request()` (once
`case_candidates` has narrowed to exactly one candidate whose still-missing
fields are all plain scalars — never an "X or Y" choice like `xD or xB` or
`external_reflux_ratio_LD (or reflux_ratio_multiplier_k)`, since guessing
which of two the user means is exactly what section 8 of that doc forbids),
plus the `use_optimum_feed_plate` boolean once a case is otherwise
complete. It is deliberately **not** stored as separate mutable state —
every call recomputes it fresh from whatever `spec` currently holds, so a
reset or a replaced problem (e.g. a new `component_names` list) automatically
leaves no stale pending request behind, with no separate invalidation logic
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
operations, and per `tools/binary-distillation-read-loop-fix-plan.md` to
enforce a bounded per-turn tool-call policy in Python rather than relying
on the model to stop on its own. Deliberately does **not** import
`separation_tool.py`, `case_design.py`, `optimizer.py`, or BioSTEAM at
all — importing this module alone pulls in only `ollama` and
`binary_distillation_workflow.py`, so no distillation calculation can
happen through it, by construction rather than by convention.

Three tools are registered:

| Tool | Kind | Does |
|---|---|---|
| `update_binary_distillation_problem` | WRITE | Merges newly-stated engineering facts into the accumulated state, then returns `assess_binary_distillation_problem()`'s full assessment of that state. Call only when the current turn states new information. |
| `get_binary_distillation_problem` | READ | Takes no arguments, mutates nothing, and returns the identical assessment schema computed from whatever is already accumulated. Call when the user asks about existing/derived/missing state. |
| `reset_workflow_session` | housekeeping | Clears accumulated state, same discipline as `reset_separation_session()` in `separation_tool.py`. |

Both `update_binary_distillation_problem` and `get_binary_distillation_problem`
wrap the same underlying deterministic checker and return the same schema —
WRITE returns it post-merge, READ returns it as-is.

### The per-turn tool-call controller (loop fix)

`ask()` no longer offers the full tool list to the model after every tool
result — doing so let the model re-select `get_binary_distillation_problem`
indefinitely, since a READ result changes nothing about which tools are on
offer next (see `tools/binary-distillation-read-loop-fix-plan.md` for the
failure mode this caused). Termination is now enforced by Python, not the
prompt, via a small per-turn policy:

- At most **one engineering-state operation** (`update_binary_distillation_problem`
  or `get_binary_distillation_problem`) runs per user turn. If a model
  response requests both, WRITE is preferred and READ is suppressed
  (WRITE's return value already reflects the merge, so a READ afterward
  cannot add information).
- `reset_workflow_session` may run once, before the one engineering
  operation, permitting the sequence `RESET -> WRITE/READ`. RESET does not
  itself count as "using" the turn's one engineering operation.
- After the engineering operation (or the `RESET -> engineering` pair)
  executes, the next model call is made **without exposing any tools**
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
message is an exact match against a small "proceed" phrase set (`yes`,
`go ahead`, `proceed`, `calculate it`, `yes boss`, ...), `ask()` returns a
fixed boundary message —
`"The problem is ready for calculation, but this workflow-only agent is
intentionally limited to problem specification. The calculation layer is
not enabled here."` — **without calling the model at all**. This is what
keeps a "go ahead" after the problem is fully specified from producing an
unsupported invitation to calculate or falling back to a generic "what can
I help you with?" (section 14/15 of the pending-truth doc).

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
ordered-group cases, and the ready-state boundary using a client that
raises if `chat()` is ever called, proving the boundary response never
touches the model). No running Ollama server is required. Run with:
```bash
pytest tools/chopper/test_binary_distillation_pending_truth.py -v
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
`would_calculate` — once `status` comes back `ready_for_calculation`.
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
| `binary_distillation_workflow_agent.py` (this section) | **Never** — both engineering tools' `calculation_performed` is always `False`. Use this to test problem-definition/case-routing behavior (scope gate, essential inputs, Case A-D identification, `would_calculate` reporting) in isolation. | No — never did, by design (workflow doc section 7/18). | Ollama + `qwen3:8b` only. Does **not** need `biosteam` importable. |
| `separation_agent.py` | Yes, once `design_separation_case`/`optimize_separation` gets a complete spec. Use this to test the full calculation pipeline (or the same Case-A-default fix, without the RAG/Chroma overhead below). | No — `problem_spec.identify_case()` no longer defaults to Case A (fixed; previously it did). | Ollama + `qwen3:8b`, `biosteam`. |
| `separation_rag_agent.py` | Yes, same pipeline as `separation_agent.py`, plus `retrieve_separation_heuristics`. Use this to test the calculation pipeline together with heuristic retrieval, or the merged agent specifically. | No — same fix as above (shared `problem_spec.py`). | Ollama + `qwen3:8b`, `biosteam`, `chromadb` + a seeded Chroma collection (`python tools/chopperRAG/seed_heuristics.py`). |
| `chopperRAG/query.py` | No BioSTEAM at all — retrieval + heuristic Q&A only, unrelated to binary-distillation case logic. | N/A | Ollama + `qwen3:8b`, `chromadb` + seeded collection. |

If you're specifically verifying "does it still silently pick Case A when
nothing case-specific was said" or "does it stop before calculating and
just report what it would calculate", use
`binary_distillation_workflow_agent.py` — it's the lightest to run and the
only one of the four that can never perform a calculation, so there's no
ambiguity about which behavior you're seeing. Use `separation_agent.py` or
`separation_rag_agent.py` when you actually want the sized/costed column
back.

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
