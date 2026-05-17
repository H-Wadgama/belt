# atj_saf/atj_bst/CLAUDE.md

Context for the BioSTEAM-native Ethanol-to-Jet (ETJ) system.

## System Overview

Three-step catalytic conversion of bioethanol to sustainable aviation fuel (SAF):

```
Bioethanol → [Dehydration, R201] → Ethylene → [Oligomerization, R202] → C4–C18 Olefins → [Hydrogenation, R203] → SAF + RN + RD
```

**Design basis (standalone mode only):** `calculate_ethanol_flow()` provides an approximate ethanol feed for a target SAF output; used only when `ins=None`. When integrated with the cellulosic ethanol system (2,000 DMT/day poplar), `ins=F.ethanol` is passed and the feed flow is entirely determined upstream — `req_saf` is ignored.  
**CEPCI basis:** 800.8 (2023 USD).

```python
etj_sys = bst.System('atj_sys',
    path=(etoh_storage, pump_1, furnace_1, mixer_1, furnace_2, dehyd_1, splitter_1, flash_1, comp_1,
          distillation_1, comp_2, distillation_2, cooler_3, mixer_2,
          olig_1, splitter_2, h2_storage, mixer_4, furnace_3, hydgn_1, cooler_5,
          flash_2, psa_splitter, distillation_3, distillation_4, cooler_6, cooler_7, cooler_8,
          rn_storage, saf_storage, rd_storage, WW_mixer, WW_cooler, catalyst_replacement_unit),
    facilities=[WWT, BT],
    recycle=(dehyd_recycle, ethylene_recycle, h2_recycle))
```

## Input Streams

| Stream | Contents | Conditions | Price |
|---|---|---|---|
| `Ethanol_In` | 99.5% pure bioethanol | Liquid, 20°C, 1 atm | `price_data['ethanol']` — set on the stream by `create_etj_system()`. Only created internally when `ins=None`; otherwise the caller-supplied stream is used directly as `etoh_in`. |
| `Hydrogen_In` | Fresh H₂ makeup; flow set by `h2_flow` spec | Gas, 30 bar | `price_data['hydrogen']` — $8.46/kg (PEM electrolysis, full value chain) |

## Unit Operations

### Area 100 — Feed Storage

| Unit ID | Variable Name | Type | Function | Key Parameters |
|---|---|---|---|---|
| T101 | `etoh_storage` | `EthanolStorageTank` (custom) | Store bioethanol feed | 7-day storage, 2 × 750,000 gal tanks; Mueller vendor basis (2009 USD, ASTM A285 Grade C steel) |
| T102 | `h2_storage` | `HydrogenStorageTank` (custom) | Store fresh H₂; flow set by `h2_flow` spec | 7-day storage at 20 MPa; Amos 1999 NREL basis, scaled at 0.75 exp |

### Area 200 — Catalytic Upgrading

**Dehydration block:**

| Unit ID | Variable Name | Type | Function | Key Parameters |
|---|---|---|---|---|
| P201 | `pump_1` | Pump | Pressurize ethanol feed | P = 1.373 MPa |
| H201 | `furnace_1` | HXutility | Preheat feed | T = 500 K, rigorous VLE |
| M201 | `mixer_1` | Mixer | Mix fresh feed + `dehyd_recycle` | rigorous |
| H202 | `furnace_2` | HXutility | Heat to reaction temp | T = 754 K (481°C), rigorous |
| R201 | `dehyd_1` | `AdiabaticReactor` (custom) | Dehydration: Ethanol → Ethylene + Water | 99.5% conv, 754 K, 1.063 MPa, WHSV=0.3 kg/hr/kg_cat, Syndol catalyst |
| S201 | `splitter_1` | Splitter | Split reactor outlet; 70% → `dehyd_recycle`, 30% → flash | split=0.3 to flash |
| T201 | `flash_1` | Flash | Separate ethylene/water from liquid | T=420 K, P=1.063 MPa |
| K201 | `comp_1` | IsentropicCompressor | Compress ethylene/water vapor | P=2 MPa, η=0.72 |
| D201 | `distillation_1` | BinaryDistillation | Purify ethylene; remove water | LHK=(Ethylene, Water), y_top=0.999, x_bot=0.001, P=2 MPa |
| K202 | `comp_2` | IsentropicCompressor | Compress to oligomerization pressure | P=3.5 MPa, η=0.72 |
| D202 | `distillation_2` | BinaryDistillation | Remove trace ethanol from ethylene | LHK=(Ethylene, Ethanol), y_top=0.9999, x_bot=0.0001, P=3.5 MPa |

**Oligomerization block:**

| Unit ID | Variable Name | Type | Function | Key Parameters |
|---|---|---|---|---|
| H203 | `cooler_3` | HXutility | Cool ethylene to reaction temp | T=393.15 K (120°C), rigorous |
| M202 | `mixer_2` | Mixer | Mix fresh ethylene + `ethylene_recycle` | rigorous |
| R202 | `olig_1` | `IsothermalReactor` (custom) | Oligomerization: Ethylene → C4–C18 olefins | 99.3% conv, 120°C, 3.5 MPa, WHSV=1.5, Ni/SiAl catalyst |
| S202 | `splitter_2` | Splitter | Route unreacted ethylene to `ethylene_recycle`; olefins to hydrogenation | split={'Ethylene':1.0} |

**Hydrogenation block:**

| Unit ID | Variable Name | Type | Function | Key Parameters |
|---|---|---|---|---|
| M203 | `mixer_4` | Mixer | Mix fresh H₂ + olefins + `h2_recycle` | rigorous |
| H204 | `furnace_3` | HXutility | Heat to reaction temp | T=623 K (350°C), rigorous |
| R203 | `hydgn_1` | `AdiabaticReactor` (custom) | Hydrogenation: Olefins + H₂ → Alkanes | 100% conv, 3.5 MPa, WHSV=3, CoMo catalyst |
| H205 | `cooler_5` | HXutility | Cool reactor outlet | T=250 K, rigorous |
| T202 | `flash_2` | Flash | Gas–liquid separation | T=250 K, P=0.5 MPa |
| S203 | `psa_splitter` | Splitter | PSA H₂ recovery | split={'Hydrogen': 0.85}; recovered → `h2_recycle`, reject → `BT_feed` |

### Area 300 — Product Fractionation

| Unit ID | Variable Name | Type | Function | Key Parameters |
|---|---|---|---|---|
| D301 | `distillation_3` | BinaryDistillation | Separate RN (C4–C6) from heavier products | LHK=(Hexane, Decane), y_top=0.99, x_bot=0.01, divided wall |
| D302 | `distillation_4` | BinaryDistillation | Separate SAF (C10) from RD (C18) | LHK=(Decane, Octadecane), y_top=0.99, x_bot=0.01, divided wall |
| H301 | `cooler_6` | HXutility | Condense RN distillate | V=0, rigorous |
| H302 | `cooler_7` | HXutility | Cool SAF distillate to 15°C | T=288 K, rigorous; `add_specification(run=False)` sets `outs[0].phase='l'` after each run to override trace VLE gas fraction |
| H303 | `cooler_8` | HXutility | Cool RD bottoms to 15°C | T=288 K, rigorous; same phase-fix spec as H302 |

### Area 400 — Boiler Turbogenerator

| Variable Name | Type | Function | Key Parameters |
|---|---|---|---|
| `BT` | `bst.facilities.BoilerTurbogenerator` | Burn PSA reject gas; generate steam and electricity | `fuel_price=price_data['NG']`; `BT.ins[1] = F.BT_feed` (PSA reject) |

### Area 500 — Product Storage

| Unit ID | Variable Name | Type | Outlet Stream | Basis |
|---|---|---|---|---|
| T501 | `rn_storage` | `HydrocarbonProductTank` (custom) | `RN` — renewable naphtha (C4–C6) | Dutta 2015 PNNL; 500,000 gal tank, 14-day storage, 0.7 exp, 2013 USD, CS |
| T502 | `saf_storage` | `HydrocarbonProductTank` (custom) | `SAF` — sustainable aviation fuel (C10) | Same basis |
| T503 | `rd_storage` | `HydrocarbonProductTank` (custom) | `RD` — renewable diesel (C18) | Same basis |

### Area 600 — Wastewater Treatment

| Variable Name | Type | Function |
|---|---|---|
| `WW_mixer` (ETJ_WW_MIX) | Mixer | Combine aqueous streams from T201, D201, D202 |
| `WW_cooler` (H602) | HXutility | Cool combined WW to liquid (V=0, rigorous) |
| `WWT` | `bst.create_conventional_wastewater_treatment_system` | Humbird 2011 WWT |

### Catalyst Tracking

| Variable Name | Type | Function |
|---|---|---|
| `catalyst_replacement_unit` | `CatalystMixer` (custom) | Track annual catalyst OPEX via three replacement streams |

## Recycle Streams

| Stream | Path | Notes |
|---|---|---|
| `dehyd_recycle` | S201 (70% split) → M201 | Non-selective split — recycles all effluent components (ethylene, water, unreacted ethanol) at 70%. Intentional design: recycled mass increases thermal mass in the adiabatic catalyst bed, moderating the temperature drop across R201. At steady state ~70% of R201 inlet mass is recycled ethylene + water. `MultiStream(phases=('g','l'))` |
| `ethylene_recycle` | S202 (split={'Ethylene':1.0}) → M202 | Unreacted ethylene; `MultiStream(phases=('g','l'))` |
| `h2_recycle` | S203 (85 mol% H₂ recovery) → M203 | Excess hydrogen; `Stream(P=3e6, phase='g')` |

## Output Streams

| Stream | Source | Description |
|---|---|---|
| `RN` | T501 | Renewable naphtha: butane (C4) + hexane (C6) |
| `SAF` | T502 | Sustainable aviation fuel: decane (C10); **MSP target stream** |
| `RD` | T503 | Renewable diesel: octadecane (C18) |
| `BT_feed` | S203 (PSA reject) | Non-H₂ light gases → BT combustion |
| WW streams | T201 bottoms, D201 bottoms, D202 bottoms | Aqueous waste → WWT |

## Reactions

### Dehydration (R201 — Adiabatic)
```
Ethanol,g → Water,g + Ethylene,g       X = 0.995
```

### Oligomerization (R202 — Isothermal, ParallelReaction)
```
2 Ethylene,g → Butene,g                X = 0.993 × 0.20   (C4, 20% selectivity)
3 Ethylene,g → Hex-1-ene,g            X = 0.993 × 0.15   (C6, 15% selectivity)
5 Ethylene,g → Dec-1-ene,l            X = 0.993 × 0.62   (C10, 62% selectivity — SAF precursor)
9 Ethylene,g → Octadec-1-ene,l        X = 0.993 × 0.03   (C18, 3% selectivity)
```

### Hydrogenation (R203 — Adiabatic, ParallelReaction)
```
Butene + H₂ → Butane                   X = 1.0  (both g and l phase)
Hex-1-ene + H₂ → Hexane               X = 1.0  (both g and l phase)
Dec-1-ene + H₂ → Decane               X = 1.0  (both g and l phase)
Octadec-1-ene + H₂ → Octadecane       X = 1.0  (both g and l phase)
```

## Process Conditions (from `etj_settings.py`)

| Parameter | Value | Notes |
|---|---|---|
| Ethanol feed purity | 99.5 wt% | `feed_parameters['purity']` |
| Dehydration T / P / X / WHSV | 754 K / 1.063 MPa / 99.5% / 0.3 kg/hr/kg_cat | Syndol catalyst, 2-yr lifetime |
| Oligomerization T / P / X / WHSV | 393 K / 3.5 MPa / 99.3% / 1.5 kg/hr/kg_cat | Ni/SiAl catalyst, 1-yr lifetime |
| Oligomerization selectivity | C4=20%, C6=15%, C10=62%, C18=3% | `prod_selectivity` dict |
| Hydrogenation T / P / X / WHSV | 623 K / 3.5 MPa / 100% / 3 kg/hr/kg_cat | CoMo catalyst, 3-yr lifetime |
| H₂:olefin molar ratio | 3:1 | Fresh H₂ = (3 × olefins) − recycled H₂ |
| H₂ PSA recovery | 85 mol% | `h2_recovery = 0.85` |
| Operating factor | 90% | Used in `calculate_ethanol_flow()` |

## Price Data (from `etj_settings.py` → `price_data`)

| Item | Value | Units |
|---|---|---|
| Ethanol feed | ~0.9 (from $2.67/gal) | USD/kg |
| Hydrogen (PEM) | 8.46 | USD/kg |
| Natural gas (BT fuel) | ~$3/MMBTU converted | USD/kg |
| Renewable naphtha | 0.71 | USD/kg |
| Renewable diesel | 1.888 | USD/kg |
| Dehydration catalyst (Syndol) | 36.81 | USD/kg |
| Oligomerization catalyst (Ni/SiAl) | 158.4 | USD/kg |
| Hydrogenation catalyst (CoMo) | 59.12 | USD/kg |
| Electricity | 0.0782 | USD/kWh |

## Catalyst Replacement Streams

Flows are set each simulation pass by `add_specification(run=True)` on each reactor — **not** read from `get_design_result()` after individual simulates. The formula `ins[0].F_mass / WHSV` is identical to the formula in `AdiabaticReactor._design()` / `IsothermalReactor._design()`.

| Stream | Component | Reactor | Formula |
|---|---|---|---|
| `Dehyd_cat_replacement` | `Syndol` | R201 | `dehyd_1.ins[0].F_mass / whsv / lifetime / 8760` kg/hr |
| `Olig_cat_replacement` | `Nickel_SiAl` | R202 | `olig_1.ins[0].F_mass / whsv / lifetime / 8760` kg/hr |
| `Hydgn_cat_replacement` | `CobaltMolybdenum` | R203 | `hydgn_1.ins[0].F_mass / whsv / lifetime / 8760` kg/hr |

All three feed into `catalyst_replacement_unit` (`CatalystMixer`) which tracks combined catalyst OPEX.

## Hydrogen Balance

Fresh H₂ is sized to maintain a 3:1 H₂:olefin molar ratio at the hydrogenation reactor inlet. The `h2_flow` spec on `h2_storage` runs before each `h2_storage._run()`:

```python
total_h2_req = 3 × Σ(olefin moles from olig_1.outs[0])
h2_storage.ins[0].imol['Hydrogen'] = total_h2_req - h2_recycle.imol['Hydrogen']
```

PSA (S203) recovers 85 mol% of the H₂ from the post-hydrogenation gas as `h2_recycle`. The remaining 15% exits as `BT_feed` along with light non-H₂ gases.

## Factory Pattern Notes

- **No individual `.simulate()` calls** — all units are defined then assembled into `bst.System`; `etj_sys.simulate()` drives sequential-modular convergence over all three recycle loops.
- **S201 non-selective recycle (intentional):** S201 is a plain 70/30 splitter on the full R201 outlet, not a selective ethanol separator. All effluent components (ethylene, water, unreacted ethanol) are recycled at 70%. This increases the thermal mass through the adiabatic dehydration reactor, moderating the temperature drop across the catalyst bed. Consequence: at steady state ~70% of R201 inlet mass is non-reactive (ethylene + water), so WHSV-based catalyst weight and vessel sizing in `AdiabaticReactor._design()` use total `ins[0].F_mass` and are conservatively overestimated ~3.3× relative to an ethanol-only WHSV basis. This is a known bias — do not "fix" the recycle without understanding the thermal implication.
- **Phase assignments on H302 / H303:** `rigorous=True` VLE at 15°C can produce a trace gas fraction for decane and octadecane streams. Each cooler uses `add_specification(run=False)` to call `_run()`, `_design()`, `_cost()` explicitly and then override `outs[0].phase = 'l'`. This ensures `HydrocarbonProductTank` always receives a single-phase liquid stream.
- **Catalyst stream flows:** computed in `add_specification(run=True)` specs — these fire before each reactor's `_run()`, so the inlet flow from the current pass is used. This replicates what `_design()` would compute without requiring access to `design_results`.
- **`h2_recycle` ordering:** `h2_storage` is positioned after `splitter_2` in the system path so that `olig_1.outs[0]` (olefin flows) is current-pass data when the `h2_flow` spec fires.

## Ethanol Flow Utility (`etj_utils.py`)

Used only in standalone mode (`ins=None`). When integrated with the cellulosic ethanol system, `ins=F.ethanol` is passed and this function is never called — ethanol flow is set by the upstream system.

```python
etoh_flow = calculate_ethanol_flow(req_saf=9, operating_factor=0.9)
# Returns an approximate kg/hr ethanol feed for a target SAF output — rough sizing only.
# Formula: (1/0.56) × (1/0.8) × req_saf × 1e6 × (1/264.17) × 776 / (op_factor × 8760)
# 0.56 = ethanol-to-ethylene mass yield proxy; 0.8 = ethylene-to-C10 yield proxy (actual selectivity is 0.62);
# 776 kg/m³ = approximate ethanol density used as a density proxy.
# These are intentional approximations; the actual SAF output is determined by simulation.
```

## Key Source Files

| File | Contents |
|---|---|
| `etj_system.py` | `create_etj_system(ins=None, req_saf=9)` — full factory function; returns ready-to-simulate `bst.System`. `ins=None` creates the ethanol feed internally from `feed_parameters`; pass a pre-built stream when integrating downstream of cellulosic ethanol. `req_saf` sets the SAF production target in MM gal/yr (ignored when `ins` is provided). |
| `etj_no_facilities.py` | `create_etj_system_no_facilities(ins=None)` — facilities-free variant for RCF biorefinery integration. Omits BT and WWT. ETJ wastewater is collected in `ETJ_WW_MIX` (renamed from `M601` to avoid ID conflict with the shared WWT's internal `M601`) and cooled in `H602`; the `H602` outlet is wired into the shared WWT by the calling script. The ETJ PSA reject (`etj_waste_gases`) must be appended to the shared `gas_mixer` by the caller (`gas_mixer.ins.append(F.etj_waste_gases)`). Module-level `CEPCI` override removed; the calling script controls the basis. See `lignin_saf/CLAUDE.md` → "RCF + ETJ Integrated Biorefinery" for the full integration pattern. |
| `etj_run.py` | Thin standalone entry-point script; mirrors `scripts/rcf_etoh.py`. Calls `create_etj_system(req_saf=9)`, simulates, and prints results. |
| `etj_chemicals.py` | Chemical property definitions (Ethanol, Ethylene, olefins, alkanes, H₂, Syndol, Nickel_SiAl, CobaltMolybdenum, etc.) |
| `etj_settings.py` | All process parameters: `feed_parameters`, `dehyd_data`, `olig_data`, `prod_selectivity`, `hydgn_data`, `price_data`, `h2_recovery` |
| `etj_utils.py` | `calculate_ethanol_flow(req_saf, operating_factor)` — basis calculation utility |
| `atj_bst_units.py` | Custom unit classes: `AdiabaticReactor`, `IsothermalReactor`, `EthanolStorageTank`, `HydrogenStorageTank`, `HydrocarbonProductTank`, `CatalystMixer` |
| `atj_bst_tea_saf.py` | `ConventionalEthanolTEA` — TEA class for the ETJ system |
| `atj_bst_tea_abstract.py` | `AbstractTEA` base class |
| `cellulosic_tea_etj.py` | `create_cellulosic_ethanol_tea()` — TEA for cellulosic ethanol co-production variant |
| `etj_system.ipynb` | Main working notebook: uncertainty, sensitivity, and contour plot analysis |
| `breakdown_plot.py` | Cost breakdown pie charts |
| `uncertainty_plot.py` | Monte Carlo uncertainty visualization |
| `selectivity_plot.py` | Oligomerization selectivity sensitivity |
| `capacity_contour.py` | Capacity vs. MJSP contour plots |

## Usage Pattern

**Standalone (entry-point script or notebook):**
```python
from atj_saf.atj_bst.etj_system import create_etj_system

etj_sys = create_etj_system(req_saf=9)   # thermo, CEPCI, and feed stream set internally
etj_sys.simulate()
etj_sys.show()
```
Or run directly:
```bash
python -m atj_saf.atj_bst.etj_run
```

**Integrated into a combined biorefinery (e.g. RCF + ETJ):**
```python
from atj_saf.atj_bst.etj_no_facilities import create_etj_system_no_facilities

# Pass the ethanol stream produced upstream; req_saf is ignored when ins is provided.
etj_sys = create_etj_system_no_facilities(ins=F.ethanol)
```
WWT and BT are absent; the WW outlet of H602 (`WW_cooler.outs[0]`) should be wired into the combined system's central WWT mixer after the ETJ system is created.

**RCF biorefinery integration status (`scripts/rcf_etoh_etj.py`):**

The following changes were made to `etj_no_facilities.py` to enable integration:

| Issue | Status |
|---|---|
| `bst.settings.CEPCI = 800.8` at module level overwrote the RCF 2016 basis | **Resolved** — line removed; combined system uses `CEPCI = 541.7` throughout |
| `WW_mixer` ID `M601` conflicted with WWT's internal `M601` | **Resolved** — renamed to `ETJ_WW_MIX` |
| `bst.settings.set_thermo(etj_chems)` at module level overwrote RCF thermo | **Functional** — `scripts/rcf_etoh_etj.py` calls `set_thermo(ligsaf_chems)` immediately after the import; `ligsaf_chemicals` is a strict superset of `etj_chemicals`, so all ETJ chemicals are present |
| `bst.F.set_flowsheet('etj')` switched the active flowsheet | **Functional** — because this runs before any units are created in `scripts/rcf_etoh_etj.py`, all units (RCF + ETJ) consistently land in the 'etj' flowsheet; `F` aliases it; all `F.xxx` lookups work correctly |

**Clean-up (future):** Guard the two remaining module-level lines with `if ins is None:` so they only fire in standalone mode and have no effect when the module is imported by an integrated script:
```python
if ins is None:
    bst.F.set_flowsheet('etj')
    bst.settings.set_thermo(etj_chems)
```

**Open TEA item:** `Hydrogen_In`, `RN`, `RD`, and `SAF` stream prices are not set in `etj_no_facilities.py`. The calling script (`scripts/rcf_etoh_etj.py`) must assign them before `tea.solve_price()`. See `lignin_saf/CLAUDE.md` → "RCF + ETJ Integrated Biorefinery" → "Open TEA items" for the required price assignments.

TEA setup (after simulation):
```python
from atj_saf.atj_bst.atj_bst_tea_saf import ConventionalEthanolTEA
tea = ConventionalEthanolTEA(etj_sys, ...)
mjsp = tea.solve_price(F.SAF)   # USD/kg — convert to USD/gal for reporting
```
