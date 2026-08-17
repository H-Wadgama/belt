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
