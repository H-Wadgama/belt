# `atj_saf/atj_bst/Xseparation_agent/` — distillation sizing & optimization toolkit

This folder is a self-contained toolkit for scoping out a single BioSTEAM
`BinaryDistillation` column against a purity/recovery target, sweeping that
column over a range of reflux ratios, costing each point in the sweep, and
picking the cheapest one that actually hits the target. Each layer is a thin
wrapper around the one below it — nothing here re-implements BioSTEAM's
shortcut method; it only drives it and organizes the results.

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
| `separation_plots.py` | `plot_purity_vs_reflux()`, `plot_utility_cost_vs_reflux()`, `plot_reflux_sweep()` — matplotlib plots of a sweep DataFrame (achieved-vs-target performance, utility cost) against `reflux_ratio_k`. |
| `separation_tool.py` | `optimize_separation()` — JSON-in/JSON-out wrapper around `optimize_reflux_ratio()`, built to be handed to Ollama as a tool. |
| `separation_agent.py` | Natural-language chat front end (Ollama + `qwen3:8b`) that calls `optimize_separation()` on the model's behalf. |
| `sample_request.py` | Minimal standalone Ollama connectivity smoke test (`client.generate(...)`) — not part of the tool-calling pipeline; predates and is unrelated to `separation_agent.py`. |
| `testing_caes.ipynb` | Scratch/interactive notebook for ad hoc testing — not a maintained module; nothing else in this folder imports it. |

The runnable end-to-end example living outside this folder is
`atj_saf/demo_separation.py`, which calls `optimize_reflux_ratio()` on a
toy Water/Methanol/Glycerol feed and plots the resulting sweep.

## A note on imports within this folder

Every module here imports its neighbors with a bare same-directory import
(e.g. `sweep_separation.py` does `from separation_trial import run_separation`,
`optimizer.py` does `from sweep_separation import sweep_reflux_ratio`, etc.),
not a package-relative import. That only resolves when this directory is on
`sys.path` — true automatically when you `cd` here and run one of these
files directly (`python optimizer.py`), but **not** when importing this
folder as a package from elsewhere (e.g.
`from atj_saf.atj_bst.Xseparation_agent.optimizer import optimize_reflux_ratio`
from a script in `atj_saf/`). Callers outside this folder need to add it to
`sys.path` first:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'atj_bst' / 'Xseparation_agent'))

from atj_saf.atj_bst.Xseparation_agent.optimizer import optimize_reflux_ratio
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
| `feed` | Yes | A `bst.Stream` feed to the column. `bst.settings.set_thermo(...)` must already be called before building it. |
| `LHK` | Yes | `(light_key, heavy_key)` — the two component IDs the column is designed around. |
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

bst.settings.set_thermo(['Water', 'Methanol', 'Glycerol'], cache=True)
feed = bst.Stream('feed', flow=(80, 100, 25))
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
| `feed` | Yes | A `bst.Stream` feed. A separate copy of this stream is made for every run in the sweep, so the original `feed` is never mutated or consumed. |
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

bst.settings.set_thermo(['Water', 'Methanol', 'Glycerol'], cache=True)
feed = bst.Stream('feed', flow=(80, 100, 25), units='kmol/hr')
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
| `feed` | Yes | Feed stream; a fresh copy is made per reflux ratio internally (via `sweep_reflux_ratio`) — `feed` itself is never mutated. |
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
Water/Methanol/Glycerol feed and prints the feasibility count, summary
message, `key_selection` result, and full best-design breakdown — then runs
a second demo with `LHK=('Methanol', 'Glycerol')` on the same feed (skipping
over Water) to show `validate_key_selection()` flagging the ambiguous key
choice and the resulting sweep coming back with `n_feasible=0`.

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

Lets a user describe a separation in plain English (e.g. "separate 80
kmol/hr methanol and 100 kmol/hr water, 99% pure methanol overhead") and
get back a costed column design, via a local Ollama model (default:
`qwen3:8b`) that decides when to call `optimize_reflux_ratio()` as a tool.
Nothing new is computed here — it's a natural-language wrapper around the
same `optimize_reflux_ratio()` pipeline described above.

```
User types a request in plain English
        │
        ▼
separation_agent.py          qwen3:8b (via Ollama) decides whether to
    call optimize_separation()
        │
        ▼
separation_tool.py           optimize_separation() builds a bst.Stream
    from the model's {component: flow} dict, calls optimize_reflux_ratio(),
    returns a plain JSON-safe dict
        │
        ▼
separation_agent.py           feeds the tool result back to the model,
    which explains it in plain English
```

## `separation_tool.py`

Exposes one function, `optimize_separation(...)`, meant to be passed
directly to Ollama's `tools=[...]` argument (not called by hand). Ollama's
client introspects the function's type hints and Google-style docstring
(via `convert_function_to_tool`) to build the JSON schema the model sees —
so the signature and each `Args:` line *are* the model's documentation of
the tool; keep them accurate if the signature changes.

| Argument | Meaning |
|---|---|
| `components` | `{component_name: flow}` dict, e.g. `{"Methanol": 80, "Water": 100}`. Keys must be valid chemical names in the `chemicals`/BioSTEAM database. |
| `light_key`, `heavy_key` | Same as `LHK` elsewhere in this folder. |
| `units` | `'kmol/hr'` or `'kg/hr'` for the `components` values. |
| `spec`, `target`, `purity_target`, `recovery_target`, `pressure_Pa` | Same meaning as the corresponding arguments in `optimize_reflux_ratio()` (`purity_target`/`recovery_target` use the same convenience-shorthand convention). |
| `reflux_ratios_k` | Optional; defaults to `DEFAULT_REFLUX_RATIOS_K = [1.2, 1.5, 1.75, 2.0, 2.5, 3.0, 3.5]` if omitted. |

Internally, each call: (1) switches to a fresh `bst.main_flowsheet` (named
`sep_agent_{n}`, incrementing per call) so repeated calls in one chat
session don't collide on stream/unit IDs in BioSTEAM's flowsheet registry;
(2) calls `bst.settings.set_thermo()` on the union of `components`,
`light_key`, and `heavy_key`; (3) builds the feed stream and sets it to
its bubble point; (4) calls `optimize_reflux_ratio()`; (5) returns
`{'found', 'message', 'n_feasible', 'n_total', 'best_design', 'key_selection'}`,
recursively converted from numpy/pandas scalars to plain Python types via
the internal `_jsonify()` helper so the result is safely JSON-serializable.
`key_selection` is `optimize_reflux_ratio()`'s `validate_key_selection()`
output passed straight through (see the `optimizer.py` section above) —
its inclusion here is what actually gets the key-selection warning in
front of the model; the docstring's `Returns:` line explicitly tells the
model to check `key_selection['warning']` before attributing an infeasible
result to reflux ratio or purity/recovery target.

`TOOLS = [optimize_separation]` and `TOOL_FUNCTIONS = {'optimize_separation': optimize_separation}`
are the two names `separation_agent.py` imports — the former goes straight
into Ollama's `tools=` argument, the latter is used to dispatch a tool
call by name back to the actual Python function.

## `separation_agent.py`

The runnable chat agent. Talks to a **local Ollama server** running
`qwen3:8b` via the `ollama` Python client, with `separation_tool.TOOLS`
registered as its one available tool. Two modes:

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

### Two safeguards against wrong light_key/heavy_key choices

For feeds with 3+ components, `qwen3:8b` picking `light_key`/`heavy_key`
that aren't adjacent in volatility (e.g. lightest + heaviest, skipping a
middle-boiling component) produces an infeasible or nonsensical design that
has nothing to do with reflux ratio — see
[`validate_key_selection()`](#validate_key_selection-key-selection-sanity-check)
above for the mechanism. Two independent safeguards address this, layered
on top of each other:

1. **Prevention** — `SYSTEM_PROMPT` in `separation_agent.py` instructs the
   model to order feed components by boiling point and choose
   `light_key`/`heavy_key` as neighbors in that ordering *before* calling
   the tool, rather than just picking the lightest and heaviest components
   present.
2. **Detection** — regardless of what the model chose, `optimize_separation`
   always returns `key_selection` (see the `separation_tool.py` section
   above). `SYSTEM_PROMPT` also instructs the model to check
   `key_selection['warning']` after every tool call, *especially* on an
   infeasible result, and to attribute the failure to the flagged
   distributed component rather than to reflux ratio or the purity/recovery
   target when a warning is present.

Safeguard 2 is the backstop for when safeguard 1 doesn't work — the model
can still call the tool with a bad `LHK` (as it did before either safeguard
existed), but it now has the means to correctly diagnose why the sweep came
back infeasible instead of guessing "reflux ratio might be too low."

### How to run it

From an Anaconda Prompt (or any terminal with `conda` on `PATH`):

```bash
conda activate pyfuel
cd "atj_saf/atj_bst/Xseparation_agent"    # bare-import convention -- see note above

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

**Getting good results:** state real chemical names (e.g. Water,
Methanol, Ethanol, Glycerol) with explicit flow rates and units
(kmol/hr or kg/hr), and an explicit purity or recovery target — the model
will usually ask a follow-up rather than guess if these are missing,
since the tool has no default feed composition to fall back on.

---

# `atj_saf/atj_bst/XSeps_RAG/` — separation-heuristics RAG (separate toolkit)

A **different, unconnected** proof-of-concept living alongside
`Xseparation_agent/` in the same `atj_bst/` folder. Where `Xseparation_agent`
*runs* BioSTEAM columns, `XSeps_RAG` *mines a separations textbook* for
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
| `schema.py` | `Heuristic` / `ExtractionResult` pydantic models — the shape of one extracted rule (`category`, `condition`, `principle`, `design_implication`). |
| `ingest.py` | PDF → paragraph-aware chunks → LLM extraction → dual storage in Chroma. |
| `query.py` | Embeds a question, retrieves heuristics + hydrated raw chunks, asks the LLM to answer grounded in that context. `--test` runs three canned PoC questions. |
| `seed_heuristics.py` | Hand-seeds 2 manually-verified ground-truth heuristics directly into Chroma, bypassing LLM extraction — see below. |
| `requirements.txt` | `chromadb`, `openai` (client, used against any OpenAI-compatible local server), `sentence-transformers`, `pymupdf`, `pydantic`. |

## `seed_heuristics.py` — ground-truth retrieval validation

Before trusting `ingest.py`'s LLM-driven extraction across a whole
textbook, `seed_heuristics.py` plants two known-good heuristics (from
Seader's *Separation Process Principles*, ch. 9) straight into the Chroma
collection, so retrieval quality can be checked independently of
extraction quality:

1. **Vapor feed** → don't default to ordinary distillation; consider
   partial condensation, cryogenic distillation, gas absorption/adsorption,
   membrane gas permeation, or desublimation instead.
2. **Liquid feed** → a much broader toolkit applies: flash, ordinary
   distillation, stripping, extractive/azeotropic distillation, LLE,
   crystallization, liquid adsorption, membrane processes (dialysis/RO/UF/
   pervaporation), or supercritical extraction.

Each is rendered to the same `"When {condition}: {principle}. Design
implication: {design_implication}"` sentence `ingest.py` uses, embedded
with `config.EMBED_MODEL`, and `upsert`ed with `parent_chunk_id=""` (no
source chunk on file, since it was typed by hand).

**Run it:**
```bash
conda activate pyfuel
cd "atj_saf/atj_bst/XSeps_RAG"
pip install -r requirements.txt   # one-time
python seed_heuristics.py         # no Ollama needed — embedding-only
```

**Then validate retrieval with `query.py`** (this step needs a local Ollama
server running the model named in `config.py`'s `LLM_MODEL`):
```bash
python query.py "What separation technique should I use for a vapor feed?"
python query.py "What separation options exist if my feed is a liquid?"
```
Check that the printed heuristics block ranks the *matching* seed entry
first (not just "both come back," which is trivial with only 2 rows in the
store) and that the `ANSWER:` text is actually grounded in that entry
rather than the other one.

**Validated 2026-08-18/19** against `qwen3:8b` (config's `LLM_MODEL`
updated from the default `qwen2.5:14b-instruct` to match): both directions
passed — the vapor question ranked the vapor heuristic first and answered
from it exclusively; the liquid question ranked the liquid heuristic first
and answered from it exclusively. Confirms the embedding model
(`BAAI/bge-small-en-v1.5`) can tell the two heuristics apart despite their
near-identical boilerplate phrasing ("feed is a X, or is readily converted
to a X..."), and that the answer-generation prompt grounds itself in the
correct retrieved entry rather than defaulting to whichever is listed
first.

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
