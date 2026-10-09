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

## History / notes

- Moved out of `lignin_saf/` on 2026-10-09 along with creating `scn_params.py`.
- Dropped unused imports (`create_rcf_system`, `create_rcf_oil_purification_system`,
  `create_monomer_purification_system`, `create_hdo_system`, `additional_rcf`,
  `operating_days`/`labor` from `tea_params`) that were leftover from copying
  `rcf_etoh_etj.py` but never actually used in this no-RCF script.
- A comment claiming "no pretreatment_wastewater" was stale — the code correctly includes
  `F.pretreatment_wastewater` in the WWT feed, and it should stay included.

## TODO / open items

- Confirm `CEPCI = 840` (2026 basis) is the intended basis for this manuscript (differs
  from `541.7`/`800.8` used elsewhere in the repo).
- Build out the actual feedstock-price-vs-demand sweep (currently only a single baseline
  MJSP point is computed).
