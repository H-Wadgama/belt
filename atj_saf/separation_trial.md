# `separation_trial.py`

A trial/scoping helper for running a single BioSTEAM `BinaryDistillation`
column to a user-defined separation target. It is **not an optimizer** — it
builds the column exactly as specified, simulates it once, and reports
whether the target was actually met, along with cost and stream data.

The module exposes one function: `run_separation(...)`.

## What you need to provide (inputs)

| Argument | Required? | Description |
|---|---|---|
| `feed` | Yes | A `bst.Stream` feed to the column. `bst.settings.set_thermo(...)` must already be called before building it. |
| `LHK` | Yes | `(light_key, heavy_key)` — the two component IDs the column is designed around. |
| `reflux_ratio` | Yes | `k`: ratio of the actual reflux ratio to the *minimum* reflux ratio (BioSTEAM's shortcut Fenske-Underwood-Gilliland input). Not the absolute L/D — that's reported back in the output. |
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
| `capex_usd` | Column purchase cost (`float`). |
| `utilities` | `{'heating_duty_kJ_per_hr', 'heating_cost_USD_per_hr', 'cooling_duty_kJ_per_hr', 'cooling_cost_USD_per_hr'}`. |
| `streams` | `{'feed', 'product', 'waste'}`. Each is a dict: `{'stream': <bst.Stream>, 'flow_kg_per_hr': {component: kg/hr, ...}, 'total_kg_per_hr': float}`. `product` and `waste` are `None` if the simulation failed. |
| `operating_conditions` | `{'pressure_Pa', 'reflux_ratio_input_k', 'actual_reflux_ratio', 'minimum_reflux_ratio', 'theoretical_stages', 'feed_stage'}`. |
| `unit` | The simulated `BinaryDistillation` instance, or `None` if construction/simulation failed. |

## Example

```python
import biosteam as bst
from separation_trial import run_separation

bst.settings.set_thermo(['Water', 'Methanol', 'Glycerol'], cache=True)
feed = bst.Stream('feed', flow=(80, 100, 25))
feed.T = feed.bubble_point_at_P().T

results = run_separation(
    feed, LHK=('Methanol', 'Water'), reflux_ratio=2, P=101325,
    spec='purity', target='top', y_top=0.99, x_bot=0.01,
)

results['feasible']                                  # True
results['purity']['achieved']                         # ~0.99
results['capex_usd']                                   # ~215,100
results['streams']['product']['flow_kg_per_hr']        # {'Water': ..., 'Methanol': ...}
```

Running `python separation_trial.py` directly executes two demo cases (one
`spec='purity'`, one `spec='recovery'`) and prints a summary of each.
