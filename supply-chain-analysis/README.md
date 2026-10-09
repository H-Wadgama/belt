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
| `x-chain-analysis.py` | Entry-point script: builds and simulates the integrated system, solves MJSP |
| `x-chain-analysis.ipynb` | Same analysis as an interactive notebook |
| `scn_params.py` | Local, editable copy of `feed_parameters` (flow/moisture/poplar_density) and feedstock price; everything else (chemical/utility prices) is reused from `lignin_saf.settings.prices` |

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

## TODO / open items

- Confirm `CEPCI = 840` (2026 basis) is the intended basis for this manuscript (differs
  from `541.7`/`800.8` used elsewhere in the repo).
- Build out the actual feedstock-price-vs-demand sweep (currently only a single baseline
  MJSP point is computed).
