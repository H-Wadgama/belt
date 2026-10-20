# Supply Chain Analysis

Manuscript-bound analysis of how biorefinery feedstock demand (plant scale) affects MJSP,
kept separate from the rest of the repo so it can be packaged independently.

## Purpose

This folder investigates the tradeoff between two opposing effects of increasing
biorefinery throughput (demand):

- **Larger demand → feedstock sourced from farther away → higher feedstock price.**
- **Larger demand → economies of scale → cheaper per-unit biorefinery operations**
  (lower CAPEX/OPEX contribution to MJSP).

The goal is to uncover the net relationship between plant scale and MJSP by trading off
these two effects, using external cost-vs-sourcing-distance data the user has, plus
related analyses to be added over time.

## Why this is a separate folder

`lignin_saf/settings/process_params.py` and `lignin_saf/settings/prices.py` are shared by
every other analysis in the repo. This manuscript needs to sweep `feed_parameters` (flow,
moisture, poplar density) and the feedstock price repeatedly and independently, without
risking changes to those shared parameter files. So this folder has its own local copy of
just the parameters it needs (`scn_params.py`) and does not touch `lignin_saf/settings/`.

## Files

| File | Purpose |
|---|---|
| `x-chain-analysis.py` | Entry-point script: builds and simulates the integrated system, solves baseline MJSP, runs the downtime-vs-feedstock-price-offset analysis (85% operating-factor scenario + breakeven feedstock-price search), and runs the rotary-dryer heat-utility-cost scenario + `energy_data.py` sensitivity sweep |
| `x-chain-analysis.ipynb` | ⚠️ **Stale.** Predates the downtime/breakeven addition above — does not mirror `x-chain-analysis.py`'s current content. Also scratch/exploratory as-is (leftover `break`/`BREAK` debug cells, duplicate prints). Needs a refresh pass before treating it as authoritative; see TODO. |
| `supply-chain-script.py` | Standalone demo script (not an entry point for this manuscript's results) showing the `MultiYearCellulosicEthanolTEA` array-`operating_days` pattern for safely running two TEA scenarios on one shared system. Reference implementation for the pattern used in `x-chain-analysis.py`'s downtime scenario — see Conventions section above. |
| `scn_params.py` | Local, editable copy of `feed_parameters` (flow/moisture/poplar_density) and feedstock price; everything else (chemical/utility prices) is reused from `lignin_saf.settings.prices` |
| `rotary_dryer.py` | `RotaryDryer(bst.Unit)` — standalone heat-utility-cost-only unit (zero ins/outs, no process-stream connections). Given a duty [kJ/hr] and process `T_in`/`T_out` [K], calls BioSTEAM's `Unit.add_heat_utility` in `_cost` to select/price a heating or cooling agent, the same mechanism `AdiabaticReactor` uses in `atj_saf/atj_bst/atj_bst_units.py`. Models no design/purchase cost — only a utility operating cost. |
| `energy_data.py` | `energy_data` dict of `[min, max]` rotary-dryer heat duties [kJ/hr] by biomass storage scenario (`Outdoor-open`, `Outdoor-tarped`, `Indoor`), consumed by the heating-cost sensitivity sweep at the end of `x-chain-analysis.py`. |

**To vary the analysis:** edit `feed_parameters` or `feedstock_price_dry_ton` in
`scn_params.py`. Do not edit `lignin_saf/settings/process_params.py` or `prices.py` for
this analysis — those are shared by other work in the repo.

## System modeled

This script builds a **simplified** integrated biorefinery — no RCF (lignin extraction)
step, unlike the main `lignin_saf` scripts:

```
poplar_in → cellulosic ethanol (with dilute-acid pretreatment) → NH3 splitter
          → ETJ upgrading (etj_ligfirst.create_etj_system_no_facilities)
          → SAF / renewable naphtha / renewable diesel
```

Shared utilities (WWT, BT, H2 storage) are assembled the same way as in
`lignin_saf/scripts/rcf_etoh_etj.py`, just without the RCF/HDO purge-gas or wastewater
streams (since there's no RCF/HDO here). Note the ETJ factory used is
`atj_saf.atj_bst.etj_ligfirst.create_etj_system_no_facilities`, which uses explicitly
prefixed stream names (`ETJ_WW_OUTS`, `ETJ_PSAWASTE_OUTS`, `ETJ_H2_IN`, `ETJ_SAF_OUT`,
etc.) rather than the generic names documented for `etj_no_facilities` in
`lignin_saf/CLAUDE.md`.

MJSP is solved via `tea.solve_price(F.ETJ_SAF_OUT)`, converted from USD/kg to USD/gal
using the stream's density and `264.172` gal/m³.

## Conventions / known gotchas

**Multiple TEA scenarios on one shared system:** `create_cellulosic_ethanol_tea()` returns
a plain `CellulosicEthanolTEA` when `operating_days` is a scalar, or a
`MultiYearCellulosicEthanolTEA` when it's an array (one entry per operating year). The
plain class reads/writes `operating_hours` **directly on the shared `bst.System` object**,
so if you ever need a second (or third) TEA instance wrapping the *same* system — to
compare operating-day scenarios, run a sensitivity sweep, etc. — build every TEA after the
first one as the array-based Multi-Year class, even for a constant schedule:

```python
import numpy as np
n_operating_years = duration[1] - duration[0]
constant_schedule = np.full(n_operating_years, operating_days_value)  # triggers Multi-Year class
scenario_tea = create_cellulosic_ethanol_tea(etoh_etj_system, operating_days=constant_schedule, duration=duration)
```

This is **fixed/resolved** as of 2026-10-09 in `x-chain-analysis.py`'s downtime scenario —
`downtime_tea` uses this pattern and the script self-checks it with
`assert baseline_tea.operating_days == 330` right after `downtime_tea` is built. No TEA in
this script currently needs a manual `tea.operating_days = <value>` reset. Keep using the
array-based pattern for any new scenario TEA added to this file so it stays that way. Full
background: `project_tea_shared_operating_hours_gotcha` memory, and the History/notes entry
below.

**Rotary dryer `add_heat_utility` T_in/T_out sign convention:** BioSTEAM's
`Unit.add_heat_utility(duty, T_in, T_out)` treats `T_in`/`T_out` as the pinch range of the
*heating or cooling requirement itself*, not the physical flow direction of whatever hot/cold
utility stream supplies it — the requirement always needs `T_in < T_out` for a heating duty
(positive `duty`) or `T_in > T_out` for a cooling duty (negative `duty`), regardless of how the
supplying stream itself warms or cools. `RotaryDryer` models a dryer heated by a hot flue-gas
stream that itself enters at 250 °C and leaves at 104 °C (i.e. the flue gas cools as it gives up
heat) — but since the *duty is a heating requirement* (positive, heat delivered to the biomass),
the call must be `add_heat_utility(duty, T_in=104 C, T_out=250 C)` (pinch range low→high), which
correctly makes BioSTEAM auto-select the `'natural_gas'` agent (BioSTEAM's built-in
combustion/flue-gas heating agent — a good match for an actual hot-flue-gas supply). The naive
literal reading — `T_in=250 C, T_out=104 C` with a *negative* duty, mirroring the flue gas's own
250→104 cooling direction — is a trap: BioSTEAM treats that as a *cooling* requirement and
auto-selects `'cooling_water'`, which is physically wrong (cooling water cannot operate at
250–377 °C, and this should be a heating cost, not refrigeration). `x-chain-analysis.py` pins the
agent explicitly to `'natural_gas'` rather than relying on auto-selection going forward.

## History / notes

- Moved out of `lignin_saf/` on 2026-10-09 along with creating `scn_params.py`.
- Dropped unused imports (`create_rcf_system`, `create_rcf_oil_purification_system`,
  `create_monomer_purification_system`, `create_hdo_system`, `additional_rcf`,
  `operating_days`/`labor` from `tea_params`) that were leftover from copying
  `rcf_etoh_etj.py` but never actually used in this no-RCF script.
- A comment claiming "no pretreatment_wastewater" was stale — the code correctly includes
  `F.pretreatment_wastewater` in the WWT feed, and it should stay included.
- 2026-10-09: added a downtime-vs-feedstock-price-offset analysis to the end of the
  script. Compares baseline MJSP (330 days/yr) against a degraded-uptime scenario
  (85% operating factor = 310.25 days/yr, same feedstock price), then solves for the
  feedstock price at 330 days/yr that would give the same MJSP as the degraded scenario
  — i.e. the maximum feedstock price premium the plant could pay (e.g. for a more
  reliable supply) while staying no worse off than running at reduced uptime. Baseline
  case: 68.2 USD/dry ton @ 330 days → 9.60 USD/gal MJSP; at 310.25 days → 9.91 USD/gal
  (+0.31, +3.2%); breakeven feedstock price at 330 days → 79.17 USD/dry ton (+16.1%).
  **Gotcha found and fixed:** `CellulosicEthanolTEA` (plain, scalar `operating_days`)
  reads/writes `operating_hours` directly on the shared `system` object rather than
  keeping a private copy, so a second plain instance on the same system (e.g. an
  earlier version of `downtime_tea`) silently overwrote `baseline_tea`'s schedule.
  Fixed by building `downtime_tea` as a `MultiYearCellulosicEthanolTEA` instead —
  pass operating_days as an *array* (one entry per operating year, here a constant
  310.25 repeated for all 30 years via `np.full`) rather than a scalar, which routes
  `create_cellulosic_ethanol_tea` to the Multi-Year class. That class keeps a fully
  private `operating_hours`/`sales`/`material_cost`/`utility_cost`/`solve_price`, so it
  never touches the shared system attribute and `baseline_tea` needs no manual reset
  anywhere in the script. A runtime `assert baseline_tea.operating_days == 330` right
  after `downtime_tea` is built self-checks this invariant on every run.
- 2026-10-20: `scn_params.py`'s `feedstock_price_dry_ton` had drifted to `119` USD/dry ton
  (uncommitted, likely leftover from separate `uptime_sweep.py` experimentation) — reverted
  to `68.2` USD/dry ton so `baseline_mjsp` matches the documented 9.60 USD/gal again. Note
  the last *committed* value was actually `79.17` (the downtime-breakeven price from the
  note above, committed on top of the original `68.2` in commit `8f9f0b9`) — worth deciding
  whether `scn_params.py` should be committed back at `68.2` (true baseline) or `79.17`
  before continuing other work in this file.
- 2026-10-20: Added `rotary_dryer.py` (`RotaryDryer`, standalone heat-utility-only cost
  unit) and wired it into `x-chain-analysis.py` as a new scenario. It is **not connected**
  to any process stream — wrapped around `etoh_etj_system` in a new `dryer_system`/
  `dryer_tea` (built via the Multi-Year TEA pattern above) rather than mutating
  `etoh_etj_system`'s own facilities, so `baseline_tea`/`downtime_tea` and their cached
  `cost_units` are untouched. See the T_in/T_out sign-convention note above for why the
  dryer's heating duty is passed as `add_heat_utility(duty, T_in=104 C, T_out=250 C)` with
  the `'natural_gas'` agent pinned explicitly.
  - First scenario: duty = 160,416,666.67 kJ/hr → heat utility cost 874.56 USD/hr →
    MJSP 9.87 USD/gal (+0.27 USD/gal vs. the 9.60 USD/gal baseline).
  - Sensitivity sweep over `energy_data.py`'s `[min, max]` duty pairs per biomass storage
    scenario, reusing `dryer_system`/`dryer_tea` rather than rebuilding/re-simulating
    `etoh_etj_system` per value: since `rotary_dryer` has no connected streams, each step
    just sets `rotary_dryer.duty` and calls `rotary_dryer.simulate()` (unit-level, not
    `dryer_system.simulate()`), then re-reads `dryer_tea.solve_price(...)`. Additional
    heating cost vs. the 9.60 USD/gal baseline, in USD/gal:

    | Storage scenario | Min | Max |
    |---|---|---|
    | Outdoor-open | 0.2687 | 0.3615 |
    | Outdoor-tarped | 0.1900 | 0.2558 |
    | Indoor | 0.1359 | 0.1831 |

    Wetter/less-protected biomass (outdoor, uncovered) requires the most drying energy and
    so carries the largest MJSP penalty; indoor-stored (driest) biomass the least.

## TODO / open items

- Confirm `CEPCI = 840` (2026 basis) is the intended basis for this manuscript (differs
  from `541.7`/`800.8` used elsewhere in the repo).
- Build out the actual feedstock-price-vs-demand sweep (currently only a single baseline
  MJSP point plus the downtime-vs-feedstock-price-offset scenario are computed).
- Refresh `x-chain-analysis.ipynb` to match `x-chain-analysis.py` (currently stale — see
  Files table above).
- `RotaryDryer` is still a standalone/unconnected cost placeholder (duty supplied by hand,
  not derived from an actual mass/energy balance on a connected biomass or flue-gas
  stream) — decide whether this manuscript needs it wired into the real flowsheet instead.
- Decide whether `scn_params.py`'s `feedstock_price_dry_ton` should be committed at `68.2`
  (true baseline) or `79.17` (last committed value, the downtime-breakeven price) — see
  2026-10-20 History/notes entry above.
