# lignin_saf/CLAUDE.md

Context for the RCF system and downstream purification system.

## rcf_system Overview

RCF (Reductive Catalytic Fractionation) loop that processes poplar biomass into crude lignin oil and a carbohydrate pulp. Two recycle streams: methanol solvent and hydrogen.

```python
rcf_system = bst.System('RCF_System',
    path=(meoh_h2o_mix, meoh_pump, meoh_heater, solvolysis_reactor, h2_mixer, h2_pre_heat,
          hydrogenolysis_reactor, R102, pre_psa_pump, pre_psa_flash, pre_psa_heater,
          psa_system, h2_pump, crude_distillation, meoh_purifier_col, meoh_mixer, cooler_2,
          water_remover, pulp_purifier, wastewater_mixer, catalyst_stream),
    recycle=(meoh_recycle, hydrogen_recycle))
```

## Input Streams

| Stream | Contents | Conditions | Price |
|---|---|---|---|
| `poplar_in` | 2,000 dry MT/day poplar + 20% moisture | Liquid, ambient | `prices['Feedstock']` — must be set on the stream by the caller when `ins` is passed; the `ins=None` branch of `create_rcf_system` sets it automatically but is never reached when `ins=poplar_in` |
| `meoh_in` | Fresh methanol only; flow set by `meoh_water_flow` spec | Liquid | `prices['Methanol']` — set inside `create_rcf_system()` |
| `water_in_meoh` | Fresh process water for MeOH solvent; flow set by `meoh_water_flow` spec | Liquid | No price (process water) |
| `hydrogen_in` | Fresh H₂, 0.054 kg/kg dry biomass (from PEM electrolysis) | Gas, 80°C, 30 bar | `prices['Hydrogen']` — set inside `create_rcf_system()` |

## Unit Operations

| Unit ID | Variable Name | Type | Function | Key Parameters |
|---|---|---|---|---|
| MIX100 | `meoh_h2o_mix` | Mixer | Mix fresh MeOH (`Meoh_in`) + fresh water (`Water_in_meoh`) + MeOH recycle | — |
| PUMP101 | `meoh_pump` | Pump | Pressurize MeOH | P = 60 bar |
| HX102 | `meoh_heater` | HXutility | Heat MeOH | T = 250°C, rigorous VLE |
| RCF103_S | `solvolysis_reactor` | `SolvolysisReactor` (custom) | Solvolysis: delignify biomass; produce pulp + liquor | T=250°C, P=60 bar, τ_s=3 hr, τ_0=1 hr, τ_res=18/60 hr (18 min), void_frac=0.5, V_max_limit=600 m³, LD_max=5.0; solvent loading derived from geometry |
| MIX104 | `h2_mixer` | Mixer | Mix fresh H₂ + H₂ recycle | — |
| HX105 | `h2_pre_heat` | HXutility | Heat H₂ | T = 250°C, rigorous |
| RCF106_H | `hydrogenolysis_reactor` | `HydrogenolysisReactor` (custom) | Hydrogenolyze lignin oil to C5–C15 monomers; continuous fixed-bed | T=250°C, P=60 bar, τ_res=1/3 hr (20 min), void_frac=0.7, free_frac=0.20, V_max_limit=100 m³, LD∈[3,10]; N_reactors derived from sizing; all product X values scaled by (1−1e−6) for numerical stability |
| — | `R102` | (flash/separator step inside hydrogenolysis path) | Phase separation after reactor | — |
| PUMP108 | `pre_psa_pump` | IsentropicCompressor | Compress vapor for PSA | P = 5 bar, vle=True |
| FLASH109 | `pre_psa_flash` | Flash | Cool/condense before PSA | T = 260 K, P = 5 bar |
| HX110 | `pre_psa_heater` | HXutility | Reheat gas to PSA inlet | T = 303 K (30°C), rigorous |
| PSA111 | `psa_system` | `PSA` (custom) | Recover H₂; purge light gases | — |
| PUMP112 | `h2_pump` | IsentropicCompressor | Recompress H₂ recycle | P = 30 bar, vle=True, gas phase enforced |
| DIST113 | `crude_distillation` | BinaryDistillation | Separate MeOH/water from hydrogenolysis liquids | LHK=(Methanol, Water), Lr=0.9995, Hr=0.033, P=1 atm |
| DIST114 | `meoh_purifier_col` | BinaryDistillation | Purify MeOH to spec | LHK=(Methanol, Water), y_top=0.9, x_bot=0.001, P=1 atm |
| MIX116 | `meoh_mixer` | Mixer | Combine purified MeOH + FLASH109 condensate | — |
| HX117 | `cooler_2` | HXutility (cooler) | Cool MeOH → `meoh_recycle` | V=0 (saturated liquid), rigorous |
| FLASH118 | `water_remover` | Flash | Separate water from crude RCF oil | T=400 K, P=1 atm |
| D601 | `pulp_purifier` | Flash | Flash-dry `Wet_Pulp`; remove residual MeOH/water before `Carbohydrate_Pulp` exits | T=400 K, P=1 atm; `outs[1]` = `Carbohydrate_Pulp`; `outs[0]` vapor currently unrecovered (future: route to WWT or solvent recovery) |
| — | `wastewater_mixer` | Mixer | Combine all wastewater → `RCF_WW` | — |
| — | `catalyst_stream` | `CatalystMixer` (custom) | Track NiC catalyst replacement cost | 0.1 kg/kg dry biomass, replaced 1×/year |

Note: FLASH107 (between `hydrogenolysis_reactor` and `pre_psa_pump`) performs the initial vapor-liquid split at T=320 K, P=5 bar — its variable name may be `R102` or an intermediate flash step.

## Recycle Loops

| Recycle Stream | Path |
|---|---|
| `meoh_recycle` | `cooler_2` (HX117) → `meoh_h2o_mix` (MIX100) |
| `hydrogen_recycle` | `h2_pump` (PUMP112) → `h2_mixer` (MIX104) |

Recycle specs: fresh feed in each mixer is adjusted so that `fresh + recycle = required total`. BioSTEAM iterates until both recycles converge.

## Output Streams

| Stream | Source Unit | Description | Downstream |
|---|---|---|---|
| `RCF_Oil` | `water_remover` (FLASH118) | Crude lignin oil: 50% monomers, 25% dimers, 25% oligomers; C5–C15 range | → `rcf_oil_purification_sys` (EtOAc LLE) |
| `Carbohydrate_Pulp` | `pulp_purifier` (D601) | Cellulose-rich pulp, 90% cellulose retention; residual MeOH/water removed | → `etoh_system` (cellulosic ethanol) |
| `RCF_WW` | `wastewater_mixer` | Combined wastewater (light organics, unconverted solvent) | → wastewater treatment |
| `Purge_Light_Gases` | `psa_system` (PSA111) | Non-H₂ light gases | purged / flared |

## Open implementation items

**`pulp_purifier` vapor outlet (D601, `outs[0]`):** The flash overhead contains evaporated MeOH and water stripped from the biomass pulp. It is currently unconnected — the solvent is not recovered. A future implementation should route this stream to `wastewater_mixer` (for WWT) or to a dedicated solvent recovery unit. When doing so, move `pulp_purifier` before `wastewater_mixer` in the path and add `pulp_purifier.outs[0]` to `wastewater_mixer.ins`.

**Hydrogenolysis reactions — `_X_scale = 1 − 1e−6` numerical guard (`systems/rcf.py`):** The six parallel reactions are set up so that ΣXi = Monomers + Dimers + Oligomers = 1.0 exactly (algebraic identity, holds for any `condensation_extent`). BioSTEAM's `ParallelReaction` captures each reactant's initial mass and subtracts Xi × SL0 in sequence; the residual `SL0 × (1 − ΣXi)` should be zero but floating-point arithmetic can produce a tiny negative value. At high delignification (large SL0), this absolute error can exceed BioSTEAM's −1e−12 threshold, raising `InfeasibleRegion`. All X values are therefore multiplied by `(1 − 1e−6)` so ~1 ppm of SolubleLignin passes through unconverted — negligible for the mass balance and TEA. If `condensation_extent` or `rcf_oil_yield` fractions are changed, the guard remains valid as long as the new fractions still sum to 1.0.

**`SolvolysisReactor._run()` solvent retention — hardcoded to `('Methanol', 'Water')`:** The loop that deposits a small fraction of solvent into the biomass stream is:
```python
for chem_id in ('Methanol', 'Water'):
    used_biomass.imass[chem_id] = used_solvent.imass[chem_id] * 0.005
```
This was restricted from a generic `for chem in solvent.chemicals` loop (which caused trace gases — CH4, CO, H2 — to accumulate in the pulp via the MeOH recycle) to explicitly name only the solvent components. If the solvent system is changed in the future (e.g. to ethanol/water, THF/water), this tuple must be updated to match the new solvent identity.

## Process Conditions (from ligsaf_settings.py)

| Parameter | Value |
|---|---|
| Solvolysis T / P / τ | 250°C / 60 bar / 3 hr (time on stream) + 18/60 hr (18 min) hydraulic RT |
| Hydrogenolysis T / P / τ_res | 250°C / 60 bar / 20 min (1/3 hr hydraulic RT); continuous, catalyst on-stream indefinitely |
| Solvent loading | derived from bed geometry (Q = V_solvent / τ_res); reported as `design_results['Solvent loading']` |
| Max vessel volume (`V_max_limit`) | 600 m³ — hard upper bound enforced by k-multiplier scaling of N_total |
| H₂:biomass ratio | 0.054 kg H₂/kg dry biomass |
| NiC catalyst loading | 0.1 kg/kg dry biomass |
| Lignin delignification | 92.8% → RCF oil |
| Condensation extent | 0.842 — fraction of the monomer fraction that re-polymerises into oligomers during hydrogenolysis |
| Cellulose retention in pulp | 90% |
| RCF oil composition | 50% monomers (before condensation) / 25% dimers / 25% oligomers; effective monomer yield = Monomers × (1 − condensation_extent) |
| Operating basis | 330 days/yr × 24 hr/day |
| CEPCI basis | 541.7 (2016 USD) |

## SolvolysisReactor Sizing Model

`_size_bed()` in `ligsaf_units.py` uses a three-stage **volume-first** approach. Bed geometry fully determines solvent volume; Q and loading are derived outputs.

**Stage 1 — Ideal stagger formula:**
```
N_total_base = round(cycle_time / tau_0)                       # = 4 at base case
N_working    = round(N_total_base × tau / cycle_time)          # = 3
N_offline    = N_total_base − N_working                        # = 1
batches/day  = 24 / tau_0  (independent of tau)
```

**Stage 2 — k-multiplier scaling to enforce V_max_limit:**
```
for k = 1, 2, 3, …:
    N_total = k × N_total_base,  N_working = k × N_working_base
    V_void          = void_frac × V_biomass            # interparticle voids
    V_excess_solvent = V_void × free_frac              # extra solvent for mass transfer
    V_solvent        = V_void × (1 + free_frac)        # total solvent volume per bed
    V_max            = V_solid + V_solvent             # vessel volume = wood + solvent
    Q_per_reactor    = V_solvent / tau_residence       # derived from geometry
    Q_total          = N_working × Q_per_reactor
    accept if V_max ≤ V_max_limit
```
k reduces V_max by increasing batches_per_day (smaller biomass_per_batch → smaller V_biomass).

**Stage 3 — L/D enforcement:**
If natural L/D > LD_max (default 5.0), superficial_velocity is reduced analytically:
```
A_new = (V_max × √π / (2 × LD_max))^(2/3)
u_adj = Q_per_reactor / (A_new × 3600)
```
`self.superficial_velocity` is updated so pressure drop uses the adjusted value.

**Base case results (tau=3, tau_0=1, tau_res=18/60 hr (18 min), void_frac=0.5, free_frac=0.10):**

Note: N_total, V_void, V_max, D/L/u are determined by bed geometry and do not change with τ_res. Q_total and derived loading scale with τ_res (shorter τ_res → faster flow → higher loading); recalculate by running the model after any τ_res change.

| Quantity | Value |
|---|---|
| N_total / N_working | 4 / 3 |
| Biomass per batch | 83,333 kg |
| V_void per bed | 85.9 m³ |
| V_solvent per bed | ~94.5 m³ (= V_void × 1.10) |
| V_max per vessel | ~180 m³ |
| Q_total / Q_per_reactor | recalculate — scales as V_solvent / τ_res |
| Derived loading | recalculate — scales as Q_total × 1000 × 24 / dry_biomass_kgday |
| D / L / L/D | ~3.58 m / ~17.9 m / 5.0 |
| Effective u (after L/D cap) | ~0.0078 m/s |

**`compute_Q_total()` method:** Returns Q_total [m³/hr] from geometry without side effects. Called by the `meoh_water_flow` spec in `systems/rcf.py` on every recycle iteration to set the methanol feed flow.

## HydrogenolysisReactor Sizing Model

`_size_bed()` in `ligsaf_units.py` uses a **continuous flow** approach. The catalyst is on-stream indefinitely; reactor volume is derived from the hydraulic residence time and total feed volumetric flow.

**Volume accounting:**
```
Q_total          = ins[0].F_vol + ins[1].F_vol          # liquid solvent/lignin + H₂ gas [m³/hr]
V_fluid          = Q_total × tau_residence               # fluid holdup in bed voids [m³]
V_bed            = V_fluid / void_frac                   # packed bed volume (voids + catalyst) [m³]
V_reactor_total  = V_bed / (1 − free_frac)               # add 20% free headspace above bed [m³]
N_reactors       = ceil(V_reactor_total / V_max_limit)   # integer parallel vessels
V_per_reactor    = V_reactor_total / N_reactors
Q_per_reactor    = Q_total / N_reactors
```

**L/D enforcement — [LD_min, LD_max]:**
Cross-section A and geometry are derived from `superficial_velocity`. If the natural L/D falls outside [3, 10], A is adjusted analytically to the nearest bound and `self.superficial_velocity` is updated:
```
A = (V_per_reactor × √π / (2 × LD_target))^(2/3)
u = Q_per_reactor / (A × 3600)
```

**Default parameters:**

| Parameter | Default | Meaning |
|---|---|---|
| `tau_residence` | 1/3 hr (20 min) | Hydraulic RT — determines V_fluid from Q |
| `void_frac` | 0.7 | Catalyst bed void fraction (fluid-occupied fraction) |
| `free_frac` | 0.20 | Free headspace as fraction of total reactor volume |
| `V_max_limit` | 100 m³ | Hard upper bound per vessel; N_reactors scales up to satisfy |
| `LD_min` / `LD_max` | 3.0 / 10.0 | L/D bounds; u adjusted analytically at either limit |

**Design results reported:** `Reactor volume`, `Total volume`, `Residence time`, `Number of reactors`, `Diameter`, `Length`, `Duty`, `Catalyst loading cost`.

## Downstream Systems (outside rcf_system)

- `rcf_oil_purification_sys` — built by `create_rcf_oil_purification_system()` in `systems/rcf_oil_purification.py`; EtOAc LLE on `RCF_Oil` → `Purified_RCF_Oil`
- `etoh_system` — cellulosic ethanol from `biorefineries.cellulosic`, fed by `Carbohydrate_Pulp`
- `monomer_purification_sys` — hexane LLE for monomer/dimer separation; built by `create_monomer_purification_system()` in `systems/monomer_purification.py`; K-values are placeholders (K=2.0 for all monomers) pending experimental hexane/water LLE data
- `combined_sys` — full integrated system wrapping all of the above (330 days/yr × 24 hr)
- `combined_sys_hx` — same with `HeatExchangerNetwork` (T_min_app=10°C)

## RCF Oil Purification System

Built by `create_rcf_oil_purification_system(ins=None)` in `systems/rcf_oil_purification.py`. Accepts the crude `RCF_Oil` stream from FLASH118 and recovers it as `Purified_RCF_Oil` via ethyl acetate liquid–liquid extraction.

**Import pattern:**
```python
from lignin_saf.systems.rcf_oil_purification import create_rcf_oil_purification_system
rcf_oil_purification_sys = create_rcf_oil_purification_system(ins=F.RCF_Oil)
rcf_oil_purification_sys.simulate()
```
If `ins=None`, `F.RCF_Oil` is grabbed from the main flowsheet — `rcf_system` must be simulated first.

**Unit operations:**

| Unit ID | Variable Name | Type | Function | Key Parameters |
|---|---|---|---|---|
| MIX200 | `solvent_mixer` | Mixer | Mix fresh EtOAc (`EthylAcetate_in`) + fresh water (`Water_in_etoac`) + solvent recycle | spec sets makeup = total required − recycle |
| LLE200 | `lle_column` | MultiStageMixerSettlers | 3-stage countercurrent EtOAc/water LLE | N_stages=3, feed_stages=(0, −1); lignin products partition to EtOAc extract |
| FLASH201 | `oil_flash` | Flash | Evaporate EtOAc overhead; **`Purified_RCF_Oil`** exits as bottoms | T=400 K, P=1 atm |
| HX202 | `solvent_cooler` | HXutility | Condense EtOAc vapor | V=0, rigorous |
| CENT203 | `solvent_decanter` | LiquidsSplitCentrifuge | Split EtOAc from water; EtOAc → `solvent_recycle` | EtOAc split = 0.95 |

**Recycle:** `solvent_recycle` (CENT203 → MIX200). Fresh EtOAc makeup computed by the `adjust_fresh_solvent_flow` spec on every iteration.

**Output streams:**

| Stream | Source | Description |
|---|---|---|
| `Purified_RCF_Oil` | FLASH201 bottoms | Concentrated lignin oil (monomers + dimers + oligomers), EtOAc removed |
| `WW_10` | LLE200 raffinate | Aqueous phase from LLE; to WWT |
| `WastePulp` | CENT203 second outlet | Water/EtOAc bleed from decanter; to WWT |

**Parameters (all in `ligsaf_settings.py` → `etoac_purification` dict):**

| Parameter | Value | Notes |
|---|---|---|
| `solvent_to_crude_ratio` | 1.1 L/kg | EtOAc volume per kg crude RCF oil; from 10.1039/D2RE00275B |
| `etoac_h2o_ratio` | 1.0 v/v | EtOAc : water ratio in solvent; from D2RE00275B |
| `N_stages` | 3 | Extraction stages; from ACS SCE 2024, 12, 12919 |
| `EtOAc_recycle_split` | 0.95 | Fraction of EtOAc recovered in centrifuge |
| `oil_flash_T` | 400 K | Flash temperature to evaporate EtOAc |
| `oil_flash_P` | 101325 Pa | Flash pressure |

**Partition coefficients (`etoac_partition_IDs` / `etoac_partition_K` in `ligsaf_settings.py`):**

K = c_extract (EtOAc-rich) / c_raffinate (water-rich). All values are placeholders pending experimental LLE data.

| Component | K |
|---|---|
| Water | 0.01 (strongly prefers aqueous phase) |
| Propylguaiacol | 200 |
| Propylsyringol | 200 |
| Syringaresinol | 500 |
| G_Dimer | 109 |
| S_Oligomer | 200 |
| G_Oligomer | 200 |

## Monomer Purification System

Built by `create_monomer_purification_system(ins=None)` in `systems/monomer_purification.py`. Accepts `Purified_RCF_Oil` (bottoms of FLASH201) and separates monomers/dimers from oligomers via hexane liquid–liquid extraction.

**Import pattern:**
```python
from lignin_saf.systems.monomer_purification import create_monomer_purification_system
monomer_purification_sys = create_monomer_purification_system(ins=F.Purified_RCF_Oil)
monomer_purification_sys.simulate()
```
If `ins=None`, `F.Purified_RCF_Oil` is taken from the main flowsheet — `rcf_oil_purification_sys` must be simulated first.

**Unit operations:**

| Unit ID | Variable Name | Type | Function | Key Parameters |
|---|---|---|---|---|
| MIX300 | `hexane_mixer` | Mixer | Mix fresh hexane (`Hexane_In`) + fresh water (`Water_in_hexane`) + hexane recycle | spec sets makeup = total required − recycle |
| LLE300 | `lle_column` | MultiStageMixerSettlers | 3-stage countercurrent hexane/water LLE | N_stages=3, feed_stages=(0, −1); true monomers (Propylguaiacol, Propylsyringol) partition to hexane extract; Syringaresinol (dimer), G_Dimer, S_Oligomer, G_Oligomer unlisted → stay in raffinate (`WW_12`) |
| FLASH301 | `monomer_flash` | Flash | Evaporate hexane overhead; **`RCF_Monomers`** exits as bottoms | T=400 K, P=1 atm |
| HX302 | `solvent_cooler` | HXutility | Condense hexane vapor | V=0, rigorous |
| CENT303 | `solvent_decanter` | LiquidsSplitCentrifuge | Split hexane from water; hexane → `hexane_recycle` | Hexane split = 0.95 |

**Recycle:** `hexane_recycle` (CENT303 → MIX300). Fresh hexane makeup computed by the `adjust_fresh_solvent_flow` spec on every iteration.

**Output streams:**

| Stream | Source | Description |
|---|---|---|
| `RCF_Monomers` | FLASH301 bottoms | True monomers only (Propylguaiacol, Propylsyringol); hexane removed |
| `WW_11` | CENT303 second outlet | Water bleed from hexane decanter; to WWT |
| `WW_12` | LLE300 raffinate (`lle_column.outs[1]`) | Aqueous raffinate containing Syringaresinol (dimer), G_Dimer, S_Oligomer, and G_Oligomer; routed directly to WWT. **Future:** if the system boundary expands to include dimer/oligomer upgrading, this stream should be cleaned (e.g. flashed to remove residual hexane) before being routed to WWT or fed to an upgrading unit. |

**Parameters (all in `ligsaf_settings.py` → `hexane_purification` dict):**

| Parameter | Value | Notes |
|---|---|---|
| `solvent_to_oil_ratio` | 5 kg/kg | Hexane mass per kg purified RCF oil |
| `water_hexane_ratio` | 1.0 v/v | Water : hexane volume ratio in solvent feed |
| `N_stages` | 3 | Extraction stages |
| `hexane_recycle_split` | 0.95 | Fraction of hexane recovered in centrifuge |
| `oil_flash_T` | 400 K | Flash T to evaporate hexane from monomer extract |

**Partition coefficients (`hexane_partition_IDs` / `hexane_partition_K` in `ligsaf_settings.py`):**

K = c_extract (hexane-rich) / c_raffinate (water-rich). All values are placeholders. `Syringaresinol`, `G_Dimer`, `S_Oligomer`, and `G_Oligomer` are not listed — unlisted components default to the aqueous raffinate in `MultiStageMixerSettlers`.

**Important:** `Syringaresinol` is a lignan DIMER (two sinapyl alcohol units linked via a β–β′ resinol linkage), not a monomer. It is intentionally excluded from the hexane partition data so it reports to `WW_12` alongside `G_Dimer`. Do not add it back as a listed component.

| Component | K | Note |
|---|---|---|
| Water | 0.01 (strongly prefers aqueous phase) | listed |
| Propylguaiacol | 2.0 (placeholder) | listed — true monomer |
| Propylsyringol | 2.0 (placeholder) | listed — true monomer |
| Syringaresinol | — | unlisted — dimer; stays in raffinate |
| G_Dimer | — | unlisted — dimer; stays in raffinate |
| S_Oligomer | — | unlisted — oligomer; stays in raffinate |
| G_Oligomer | — | unlisted — oligomer; stays in raffinate |

## HDO System

Built by `create_hdo_system(ins=None)` in `systems/hdo.py`. Accepts `RCF_Monomers` (Propylguaiacol + Propylsyringol from FLASH301) and converts them to propylcyclohexane (`SAF_CycloAlkane`) via catalytic hydrodeoxygenation over a Ni₂P/SiO₂ catalyst in dodecane solvent.

**Import pattern:**
```python
from lignin_saf.systems.hdo import create_hdo_system
hdo_system = create_hdo_system(ins=F.RCF_Monomers)
hdo_system.simulate()
```
If `ins=None`, `F.RCF_Monomers` is grabbed from the main flowsheet — `monomer_purification_sys` must be simulated first.

**Reactions:**
```
Propylguaiacol + 6 H₂  → propylcyclohexane + 2 H₂O + CH₄   (X = 1.0, mol basis)
Propylsyringol + 8 H₂  → propylcyclohexane + 3 H₂O + 2 CH₄  (X = 1.0, mol basis)
```

**Unit operations:**

| Unit ID | Variable Name | Type | Function | Key Parameters |
|---|---|---|---|---|
| HDO_MIX_H2 | `hdo_h2_mix` | Mixer | Mix fresh H₂ + H₂ recycle | spec: `fresh = (6×mol_PG + 8×mol_PS) × 1.5 − recycle`; outlet forced to gas |
| HDO_MIX_DOD | `hdo_dodecane_mix` | Mixer | Mix fresh dodecane + dodecane recycle; also updates catalyst flow | spec: `fresh = solvent_req × F_mass × ρ_dod − recycle`; catalyst = 0.8 kg/kg monomers |
| HDO_MIX1 | `hdo_mix_1` | Mixer | Mix H₂ feed + monomers + dodecane feed | rigorous=True |
| HDO_COMP1 | `hdo_comp_1` | IsentropicCompressor | Compress to HDO operating pressure | P=5 MPa, vle=True |
| HDO_HX1 | `hdo_hx_1` | HXutility | Heat to HDO operating temperature | T=573 K (300°C), rigorous |
| HDO_RXR1 | `hdo_rxr_1` | `HydrodeoxygenationReactor` (custom) | Batch HDO reaction | T=573 K, P=5 MPa, τ=5 hr, τ₀=1 hr, free_frac=0.10, V_max=600 m³, aspect_ratio=5 |
| HDO_HX2 | `hdo_hx_2` | HXutility | Cool reactor effluent before pressure let-down | T=400 K, rigorous |
| HDO_V1 | `hdo_v_1` | IsenthalpicValve | Depressurize to atmospheric | P=101325 Pa, vle=True |
| HDO_FLSH1 | `hdo_flsh_1` | Flash | Separate gas (H₂, CH₄) from liquid (product + solvent + water) | T=298 K, P=101325 Pa |
| HDO_FLSH2 | `hdo_flsh_2` | Flash | Dry gas before PSA; `HDO_wash_water` (liquid, near-pure water) → WWT | T=275 K, P=5 bar |
| HDO_HX3 | `hdo_hx_3` | HXutility | Reheat dried gas to PSA inlet temperature | T=303 K, rigorous |
| HDO_PSA1 | `hdo_psa_1` | `PSA` (custom) | Recover H₂ for recycle; purge light gases → BT | outs=(`HDO_h2_recycle` feed, `HDO_purge_gases`) |
| HDO_COMP_H2 | `hdo_h2_comp` | IsentropicCompressor | Recompress recovered H₂ to HDO pressure | P=5 MPa, vle=True; gas phase enforced by spec |
| HDO_COL1 | `hdo_col_1` | BinaryDistillation | Solvent recovery: propylcyclohexane (vapor tops) from dodecane (liquid bottoms) | LHK=(propylcyclohexane, Dodecane), Lr=0.99, Hr=0.9999, P=1 atm, partial_condenser=True |
| HDO_HX_DOD | `hdo_dodecane_cooler` | HXutility | Cool recovered dodecane to feed temperature for recycle | T=300 K, rigorous |
| HDO_COL2 | `hdo_col_2` | BinaryDistillation | Remove residual water (`HDO_WW`, tops) → WWT; isolate propylcyclohexane (`SAF_CycloAlkane`, bottoms) | LHK=(Water, Propylcyclohexane), y_top=0.9, x_bot=0.001, P=1 atm |

**Recycle loops:**

| Recycle Stream | Path |
|---|---|
| `HDO_h2_recycle` | `hdo_h2_comp` (HDO_COMP_H2) → `hdo_h2_mix` (HDO_MIX_H2) |
| `HDO_dodecane_recycle` | `hdo_dodecane_cooler` (HDO_HX_DOD) → `hdo_dodecane_mix` (HDO_MIX_DOD) |

Recycle specs mirror the pattern in `systems/rcf.py`: fresh feed = required total − recycle, computed on every iteration. The `h2_flow` spec uses `ins.imol` to read monomer flows; `dodecane_flow` converts from volumetric (`solvent_req` in m³/kg) to mass using thermosteam's `Dodecane.rho()`.

**Input streams:**

| Stream | Contents | Conditions | Price |
|---|---|---|---|
| `ins` (`RCF_Monomers`) | Propylguaiacol + Propylsyringol | Liquid, ambient | No price — MSP target stream |
| `HDO_H2_IN` | Fresh H₂ makeup | Gas, 30 bar | `prices['Hydrogen']` |
| `HDO_DODECANE_IN` | Fresh dodecane makeup | Liquid, 300 K, 1 atm | No price set |
| `HDO_CAT_IN` | Ni₂P/SiO₂ catalyst | Solid | No price set |

**Output streams:**

| Stream | Source Unit | Description | Downstream |
|---|---|---|---|
| `SAF_CycloAlkane` | HDO_COL2 bottoms | Propylcyclohexane product | SAF blending / further upgrading |
| `HDO_purge_gases` | HDO_PSA1 outs[1] | H₂, CH₄, light gases | → `gas_mixer.ins.append(F.HDO_purge_gases)` → BT |
| `HDO_wash_water` | HDO_FLSH2 outs[1] | Near-pure water condensate from secondary flash | → `F.unit.M601.ins.extend([...])` → WWT |
| `HDO_WW` | HDO_COL2 outs[0] | Water-rich tops from product column | → `F.unit.M601.ins.extend([...])` → WWT |

**Stream routing in the calling script (`scripts/rcf_hdo.py`):**
```python
# Append HDO purge gases to gas_mixer — do NOT assign to BT.ins[1] directly,
# which would overwrite the gas_mixer connection and disconnect RCF PSA purge + WWT biogas.
gas_mixer.ins.append(F.HDO_purge_gases)

# Route HDO wastewater to WWT inlet mixer M601
F.unit.M601.ins.extend([F.HDO_wash_water, F.HDO_WW])
```

**No `solids_to_BT` mixer needed:** the HDO system produces no combustible solids. `BT.ins[0] = WWT.outs[1]` (the direct wire set inside `create_rcf_utilities_system()`) remains correct as-is.

**Process conditions (from `ligsaf_settings.py` → `hdo_params`):**

| Parameter | Value |
|---|---|
| T | 573 K (300°C) |
| P | 5 MPa (50 bar) |
| τ (time on stream per batch) | 5 hr |
| τ₀ (turnaround time per batch) | 1 hr |
| H₂ excess factor | 1.5 × stoichiometric |
| Dodecane solvent loading (`solvent_req`) | 0.04 m³/kg monomer feed |
| Catalyst loading (`catalyst_req`) | 0.8 kg/kg monomer feed |
| V_max per vessel | 600 m³ |
| Aspect ratio | 5 |

## Utilities System (Area 400 + 500)

Built by `create_rcf_utilities_system()` in `systems/ligsaf_utilities.py`. Returns `(BT, WWT, gas_mixer)`. Call after all upstream factory functions so the required named streams exist on the flowsheet.

**Assembly pattern:**
```python
rcf_system               = create_rcf_system(ins=poplar_in)
rcf_oil_purification_sys = create_rcf_oil_purification_system(ins=F.RCF_Oil)
BT, WWT, gas_mixer       = create_rcf_utilities_system()

rcf_combined_system = bst.System(
    'Combined_RCF_System',
    path=(rcf_system, rcf_oil_purification_sys, WWT),  # WWT is a System → path
    facilities=[gas_mixer, BT],                         # gas_mixer must precede BT
)
rcf_combined_system.simulate()
```

**BT** — `bst.facilities.BoilerTurbogenerator('BT', fuel_price=0.2612)`:

| Slot | Contents |
|---|---|
| `ins[0]` | WWT sludge (`WWT.outs[1]`) — dewatered biological sludge from S603 |
| `ins[1]` | `gas_mixer` outlet — PSA purge gas + WWT biogas combined |
| `ins[2–6]` | Makeup water, natural gas, lime, boiler chems, air (auto-set) |

**`gas_mixer`** — `bst.Mixer('MIX_BT_gas', ins=(F.Purge_Light_Gases, WWT.outs[0]))`:
Combines PSA purge gas and WWT biogas before the BT gas combustion slot. Listed before `BT` in `facilities` so its outlet is populated before BT consumes it.

**WWT** — `bst.create_conventional_wastewater_treatment_system('WWT', ...)` (Humbird 2011):

| Inlet stream | Source |
|---|---|
| `F.WW_10` | LLE200 raffinate (Area 300) — predominantly water |
| `F.WastePulp` | CENT203 decanter bleed (Area 300) — predominantly water + 5% EtOAc |
| `F.RCF_WW` | Combined RCF wastewater (Area 200) |
| `F.WW_11` | CENT303 hexane decanter bleed (Area 300) — water bleed from hexane recycle |
| `F.WW_12` | LLE300 aqueous raffinate (Area 300) — contains S_Oligomer and G_Oligomer; routed directly to WWT. Future: clean before WWT if oligomer upgrading is added. |

Note: `WastePulp` is predominantly water. In `CENT203`, `split={'EthylAcetate': 0.95}` means Water defaults to split=0.0 (all water → `outs[1]` = WastePulp). Only 5% of EtOAc ends up in WastePulp.

The internal `SludgeCentrifuge` (S603) is patched after WWT creation in `create_rcf_utilities_system()` (`systems/ligsaf_utilities.py`):

```python
for unit in WWT.units:
    if hasattr(unit, 'strict_moisture_content'):
        unit.strict_moisture_content = False   # ← toggle here
    # To adjust the target moisture fraction (default 0.79 from Humbird):
    # if hasattr(unit, 'moisture_content'):
    #     unit.moisture_content = 0.6
```

**Why this is needed:** The Humbird 79% moisture target was calibrated for cellulosic-ethanol organic loadings. RCF wastewater has a different organic profile:
- `Acetate` is in `non_digestables` → passes through the bioreactors unreacted and accumulates in the S603 feed, reducing available free water
- `G_Dimer`, `S_Oligomer`, `G_Oligomer` now have molecular formulas in `ligsaf_chemicals.py` and are included in `get_digestable_organic_chemicals`. All three, plus `Syringaresinol` (a dimer), are unlisted in the hexane LLE partition data — they exit LLE300 as `WW_12` and reach WWT, where they are treated as digestable organics (→ biogas → `BT.ins[1]`; sludge → `BT.ins[0]`)

The primary cause of the infeasibility is Acetate accumulation. `strict_moisture_content=False` lets the centrifuge use whatever water is available without raising `InfeasibleRegion`. Set it back to `True` once WWT stream chemistry is validated against experimental RCF wastewater data.

**WWT outputs:**

| Slot | Stream | Description | Routed to |
|---|---|---|---|
| `WWT.outs[0]` | biogas | CH4 + CO2 from anaerobic digestion | `gas_mixer` → `BT.ins[1]` |
| `WWT.outs[1]` | sludge | dewatered biological sludge from S603 | `BT.ins[0]` |
| `WWT.outs[2]` | RO treated water | clean permeate from reverse osmosis | `PWC.ins[0]` — wire after WWT creation via `F.unit.PWC.ins[0] = WWT.outs[2]` |
| `WWT.outs[3]` | brine | RO reject | unconnected |

**BT combustion reactions — current status:**

BioSTEAM's BT auto-derives combustion reactions from a chemical's elemental formula (`CₓHᵧOᵤ + O₂ → CO₂ + H₂O`). Formulas have been added to all six RCF lignin chemicals in `ligsaf_chemicals.py`; BT now generates combustion reactions for all of them:

| Chemical | Formula | BT combustion reaction | Status |
|---|---|---|---|
| `G_Dimer` | `C20H26O6` | `23.5 O2 + G_Dimer → 13 Water + 20 CO2` | correct |
| `S_Oligomer` | `C33H40O11` | `37.5 O2 + S_Oligomer → 33 CO2 + 20 Water` | resolved — explicit MW removed; MW formula-derived (~612.67 Da) |
| `G_Oligomer` | `C31H40O8` | `37 O2 + G_Oligomer → 20 Water + 31 CO2` | correct |
| `Propylguaiacol` | `C10H14O2` | combusts correctly | correct |
| `Propylsyringol` | `C11H16O3` | combusts correctly | correct |
| `Syringaresinol` | `C22H26O8` | combusts correctly | correct |

**`S_Oligomer` MW — resolved:** The explicit `MW=628.67` was removed; `S_Oligomer` is now defined with `formula='C33H40O11'` only, so thermosteam derives MW as ~612.67 Da and BT combustion produces no `Ash`. **Open question:** verify that `C33H40O11` is the correct structure against Bartling et al. Fig S8 — if the correct MW is 628.67, change the formula to `C33H40O12`.

**Note on current process flows:** `Syringaresinol` (a dimer), `G_Dimer`, `S_Oligomer`, and `G_Oligomer` are all unlisted in the hexane LLE partition data and exit LLE300 as `WW_12` → WWT → biogas/sludge → BT; their combustion reactions are therefore active. Only true monomers (Propylguaiacol, Propylsyringol) partition to the hexane extract and exit as `RCF_Monomers`.

**Extending BT and WWT with more streams:**
- WWT: add streams to the `ins` tuple inside `create_rcf_utilities_system()`.
- BT: each combustion slot takes one stream; use a `bst.Mixer` to combine multiple feeds, add the mixer to `facilities` before BT, and wire `BT.ins[0]` or `BT.ins[1]` to the mixer outlet.

## Unified utilities for the integrated biorefinery

`scripts/rcf_etoh.py` integrates the cellulosic ethanol co-product using the shared RCF utilities (BT, WWT) as the biorefinery-wide utilities. The local `systems/cellulosic_ethanol.py` provides `create_cellulosic_ethanol_system` with `WWT=False, CHP=False` passed to `bst.create_all_facilities`, so the ethanol system never creates its own BT or WWT. This eliminates the ID-conflict problem entirely — no post-hoc unit removal is needed.

**Stream routing — how ethanol streams reach the shared utilities:**

Streams are identified by explicit name, not by a `sink is None` heuristic. The heuristic was found to over-capture cooling tower evaporation (atmospheric), cooling water circulation streams, and the fermentation vent — none of which should be routed to BT or WWT. Verified by comparing `systems/cellulosic_ethanol.py` (with `WWT=False`) against the stock `biorefineries.cellulosic` factory stream-by-stream.

Correct routing (matches `cellulosic.create_cellulosic_ethanol_system`):

| Stream | Destination | Notes |
|---|---|---|
| `F.pretreatment_wastewater` | WWT via `M601.ins` | Named stream from dilute-acid pretreatment |
| `F.unit.S401.outs[1]` (stillage filtrate, ID `s48`) | WWT via `M601.ins` | Liquid fraction from pressure filter |
| `F.unit.S401.outs[0]` (filter cake, ID `s47`) | BT solids slot via `solids_to_BT` | |
| `WWT.outs[0]` (biogas) | BT gas slot via `gas_mixer` | Already in `gas_mixer` from `create_rcf_utilities_system()` |
| `WWT.outs[1]` (sludge) | BT solids slot via `solids_to_BT` | |
| `WWT.outs[2]` (RO treated water, ~479,000 kg/hr) | `PWC.ins[0]` directly | See PWC note below |
| Fermentation vent (`F.vent`) | **unconnected** — atmospheric | Stock system does not burn it in BT |
| CT evaporation | **unconnected** — atmospheric | |
| CT blowdown | → PWC via `blowdown_recycle=True` (hardcoded in `systems/cellulosic_ethanol.py`) | Not routed to WWT |

```python
# Explicit stream routing — do NOT use sink=None heuristic
etoh_ww     = [F.pretreatment_wastewater, F.unit.S401.outs[1]]
etoh_solids = [F.unit.S401.outs[0]]
```

After `create_rcf_utilities_system()`, wire into shared utilities:
```python
F.unit.M601.ins.extend(etoh_ww)
solids_to_BT = bst.Mixer('MIX_BT_solids', ins=[WWT.outs[1]] + etoh_solids)
BT.ins[0] = solids_to_BT.outs[0]
# Do NOT extend gas_mixer with etoh_gases — fermentation vent is atmospheric
```

**PWC ← WWT.outs[2] connection (critical):**

`create_all_facilities(WWT=False)` creates an empty placeholder mixer M2 that was intended to receive WWT treated water. Since WWT=False, M2 has no inlets and its outlet flows 0 kg/hr. Without wiring `WWT.outs[2]` to `PWC.ins[0]`, PWC must purchase ~480,000 kg/hr of fresh water that the stock system gets for free from WWT — adding ~$143/hr (~$1.1M/yr at 7,920 hr/yr) of spurious PWC cost.

In the stock `cellulosic.create_cellulosic_ethanol_system`, M4 (a single-inlet pass-through mixer from S604) feeds this stream to `PWC.ins[0]` automatically. The equivalent fix is to bypass M2 and connect directly:

```python
# Wire WWT RO-treated water to PWC — bypasses M2 (empty placeholder)
# Verified: M4 in the stock system has exactly one inlet (RO_treated_water from S604);
# our direct connection is structurally equivalent.
# The WWT→PWC feedback is weak; no explicit recycle specification is needed.
F.unit.PWC.ins[0] = WWT.outs[2]
```

**`fuel_price` and `utility_cost`:**

`BT.utility_cost` does not include natural gas cost — BioSTEAM treats natural gas as a raw material billed through the TEA's `material_cost` (via `BT.ins[2].price`), not through `utility_cost`. The `fuel_price` parameter therefore does not appear in `utility_cost` comparisons, but it will affect `tea.solve_price()`. The RCF system uses `fuel_price=0.2612`; the stock cellulosic factory uses `fuel_price=0.218`.

**`ethanol_system` is included directly in the combined system path:**

```python
rcf_combined_system = bst.System(
    'Combined_RCF_System',
    path=(rcf_system, rcf_oil_purification_sys, monomer_purification_sys, ethanol_system, WWT),
    facilities=[solids_to_BT, gas_mixer, BT],
)
```

An earlier version of this code kept `ethanol_system` out of the path and re-simulated it via `add_specification(simulate=True)`, based on a concern that `update_configuration` would pull LLE200 into the ethanol system's boundary. This was tested and found to be incorrect in BioSTEAM 2.47 — LLE200 does not leak regardless of assembly strategy, and all stream flows converge identically either way.

Keeping ethanol out of the path was actually wrong from a TEA standpoint: it caused the TEA to omit the ethanol system's CAPEX (~$85M installed) and the ethanol product revenue (~$124M/yr), artificially inflating the MSP by ~$1/kg. It also incorrectly scoped BT to only the RCF subsystem, leaving the ethanol system's ~80 MW of steam demand (M203 MPS, D402/D403/U401 LPS) served by market agents rather than the shared BT. Including `ethanol_system` in the path is the correct approach: BT serves all steam demand as a true integrated CHP, the TEA accounts for all CAPEX and co-product revenue, and the MSP reflects the full integrated biorefinery economics.

**No ordering constraint:** Because `systems/cellulosic_ethanol.py` never creates BT or WWT, the IDs `M601`, `WWTC`, `BT` etc. are never claimed by the ethanol system. `create_rcf_utilities_system()` can be called in any order relative to `create_cellulosic_ethanol_system`.

**Full implementation pattern (current `scripts/rcf_etoh.py`):**

```python
from lignin_saf.systems.cellulosic_ethanol import create_cellulosic_ethanol_system

# 1. Create and simulate process subsystems
rcf_system               = create_rcf_system(ins=poplar_in);  rcf_system.simulate()
rcf_oil_purification_sys = create_rcf_oil_purification_system(ins=F.RCF_Oil)
monomer_purification_sys = create_monomer_purification_system(ins=F.Purified_RCF_Oil)
rcf_oil_purification_sys.simulate(); monomer_purification_sys.simulate()

# 2. Ethanol system — BT and WWT absent (WWT=False, CHP=False in bst.create_all_facilities)
ethanol_system = create_cellulosic_ethanol_system(ins=F.Carbohydrate_Pulp)
ethanol_system.simulate()

# 3. Name ethanol streams explicitly — do NOT use sink=None heuristic.
# Verified against stock cellulosic.create_cellulosic_ethanol_system:
# - Fermentation vent is atmospheric (not burned in BT)
# - CT blowdown goes to PWC via blowdown_recycle=True (not to WWT)
# - Cooling tower evaporation and cooling water streams must not be captured
etoh_ww     = [F.pretreatment_wastewater, F.unit.S401.outs[1]]
etoh_solids = [F.unit.S401.outs[0]]

# 4. Create shared utilities and route ethanol streams
BT, WWT, gas_mixer = create_rcf_utilities_system()
F.unit.M601.ins.extend(etoh_ww)
solids_to_BT = bst.Mixer('MIX_BT_solids', ins=[WWT.outs[1]] + etoh_solids)
BT.ins[0] = solids_to_BT.outs[0]
# Do NOT extend gas_mixer with ethanol gases — fermentation vent is atmospheric

# Wire WWT RO-treated water back to PWC.
# create_all_facilities(WWT=False) leaves M2 (placeholder mixer for WWT water) empty.
# Without this line PWC purchases ~480,000 kg/hr of fresh water unnecessarily (~$1.1M/yr).
F.unit.PWC.ins[0] = WWT.outs[2]

# 5. Assemble combined system — ethanol_system in path for correct TEA and BT CHP scope
rcf_combined_system = bst.System(
    'Combined_RCF_System',
    path=(rcf_system, rcf_oil_purification_sys, monomer_purification_sys, ethanol_system, WWT),
    facilities=[solids_to_BT, gas_mixer, BT],
)

rcf_combined_system.simulate()
```

**Notes:**
- `blowdown_recycle=True` in `systems/cellulosic_ethanol.py` matches the stock factory: CT blowdown goes to PWC, not WWT. Setting it to `False` would leave CT blowdown with no sink and does not match the stock system's WWT loading.
- `solids_to_BT` must appear before `BT` in the facilities list so its outlet is populated before BT consumes it.
- The `strict_moisture_content=False` patch in `create_rcf_utilities_system()` applies to the shared WWT for both RCF and ethanol wastewater streams.

## RCF + ETJ Integrated Biorefinery (`scripts/rcf_etoh_etj.py`)

Extends the RCF + cellulosic ethanol assembly (described above) by routing the cellulosic ethanol product through the ETJ catalytic upgrading system rather than selling it. Products: RCF lignin monomers (MSP target), renewable naphtha (RN, C4–C6), sustainable aviation fuel (SAF, C10), and renewable diesel (RD, C18).

### Chemical set

`ligsaf_chemicals.create_chemicals()` is a strict superset of `etj_chemicals.create_chemicals()` — every ETJ-specific chemical (Ethylene, Butene, Hex-1-ene, Dec-1-ene, Octadec-1-ene, Butane, Hexane, Decane, Octadecane, Syndol, Nickel_SiAl, CobaltMolybdenum, Coal) is already present in the ligsaf chemical set. No separate merged chemical set is needed. `scripts/rcf_etoh_etj.py` calls `bst.settings.set_thermo(ligsaf_chems)` once and it serves both subsystems.

### Module-level side effects in `etj_no_facilities.py`

Importing `create_etj_system_no_facilities` immediately runs two module-level statements:
```python
bst.F.set_flowsheet('etj')          # switches active flowsheet to 'etj'
bst.settings.set_thermo(etj_chems)  # sets ETJ-only chemicals — overridden on the next line of scripts/rcf_etoh_etj.py
```
`scripts/rcf_etoh_etj.py` calls `bst.settings.set_thermo(ligsaf_chems)` right after the import, overriding the ETJ-only thermo with the complete ligsaf set. The `CEPCI = 800.8` line has been removed from `etj_no_facilities.py`; the combined system uses `CEPCI = 541.7` throughout.

**Future clean-up:** guard the two remaining module-level lines with `if ins is None:` so they only fire in standalone mode:
```python
if ins is None:
    bst.F.set_flowsheet('etj')
    bst.settings.set_thermo(etj_chems)
```

The `set_flowsheet('etj')` line is still present but not blocking. Because it runs before any units are created in `scripts/rcf_etoh_etj.py`, all RCF, ethanol, and ETJ units are consistently registered in the 'etj' flowsheet. `F` (from `from biosteam import main_flowsheet as F`) aliases this flowsheet, so all `F.xxx` stream and unit lookups work correctly.

### Ethanol feed routing to ETJ

The cellulosic ethanol product exits `T703` (the "Product tank", explicitly named in `systems/cellulosic_ethanol.py`). An NH3 splitter guards against trace ammonia before the ETJ feed:
```python
nh3_splitter = bst.units.Splitter(ins=F.T703.outs[0], split={'NH3': 1.0})
# outs[1] = ethanol product (NH3-free) → ETJ feed
etj_system = create_etj_system_no_facilities(ins=nh3_splitter.outs[1])
```
With `denaturant_fraction=0.0`, T703 outputs ~99.5 wt% ethanol and no octane. NH3 in practice exits with the beer column stillage, not T703, so the splitter is effectively a pass-through. It is retained as an explicit guard.

### ETJ wastewater routing

The ETJ system collects its aqueous streams (T201 bottoms, D201 bottoms, D202 bottoms) in `ETJ_WW_MIX`, cools them in `H602`, then routes the H602 outlet to the shared WWT:
```python
etoh_ww.append(F.H602.outs[0])          # add ETJ WW alongside ethanol WW streams
# ... after create_rcf_utilities_system():
F.unit.M601.ins.extend(etoh_ww)          # M601 is the WWT inlet mixer
```
The ETJ WW mixer was renamed from `M601` to `ETJ_WW_MIX` in `etj_no_facilities.py` to eliminate the ID conflict with the WWT's internal `M601`.

### ETJ waste gases routing

The ETJ PSA reject (`etj_waste_gases`, from S203) must be appended to the shared `gas_mixer`, not assigned to `BT.ins[1]`:
```python
gas_mixer.ins.append(F.etj_waste_gases)
# gas_mixer already holds: F.Purge_Light_Gases (RCF PSA purge) + WWT.outs[0] (biogas)
# BT.ins[1] remains = gas_mixer.outs[0] — do NOT overwrite it
```
Writing `BT.ins[1] = F.etj_waste_gases` would replace the gas_mixer connection, disconnecting RCF PSA purge gas and WWT biogas from BT.

### Combined system path

```python
rcf_combined_system = bst.System(
    'Combined_RCF_System',
    path=(rcf_system, rcf_oil_purification_sys, monomer_purification_sys,
          ethanol_system, nh3_splitter, etj_system, WWT),
    facilities=[solids_to_BT, gas_mixer, BT],
)
```

**Critical ordering:** `nh3_splitter` and `etj_system` must precede `WWT`. The ETJ WW (`F.H602.outs[0]`) is added to `M601.ins`, and the combined system has no outer recycle declared between the ETJ and WWT subsystems. If WWT runs before ETJ, it processes zero ETJ WW on that pass. Placing ETJ before WWT ensures H602 is populated when WWT executes.

**Solids to BT:** The ETJ system produces no combustible solids. Only WWT sludge and ethanol filter cake feed `solids_to_BT`:
```python
solids_to_BT = bst.Mixer('MIX_BT_solids', ins=[WWT.outs[1]] + etoh_solids)
BT.ins[0] = solids_to_BT.outs[0]
```

### CEPCI basis

The combined system uses `CEPCI = 541.7` (2016 USD) throughout. The ETJ unit cost parameters in `atj_bst_units.py` reference 2009–2015 literature (Amos 1999 NREL for H₂ storage, Mueller 2009 for ethanol tanks, Dutta 2015 PNNL for product tanks). At CEPCI=541.7, ETJ installed costs are evaluated on the same basis as the RCF and ethanol systems. Note: ETJ standalone results reported at CEPCI=800.8 (2023 USD) are approximately 48% higher — this gap should be acknowledged when comparing standalone vs. integrated ETJ capital costs.

### Open TEA items

The following ETJ streams require prices in `scripts/rcf_etoh_etj.py` **before calling `integrated_tea.solve_price()`**:

| Stream | Price to set | Value | Notes |
|---|---|---|---|
| `F.Hydrogen_In` | `price_data['hydrogen']` | 8.46 USD/kg | PEM H₂ — largest ETJ operating cost; omitting it understates VOC significantly |
| `F.RN` | `price_data['renewable_naphtha']` | 0.71 USD/kg | Co-product revenue; omitting it inflates the RCF monomer MSP |
| `F.RD` | `price_data['renewable_diesel']` | 1.888 USD/kg | Co-product revenue; same issue |
| `F.SAF` | market price (USD/kg) | no entry in `price_data` | Set to a literature market price when solving for RCF monomer MSP; leave at 0 and set `F.RCF_Monomers.price` if solving for SAF MJSP instead |

```python
from atj_saf.atj_bst.etj_settings import price_data
F.Hydrogen_In.price = price_data['hydrogen']           # 8.46 USD/kg
F.RN.price          = price_data['renewable_naphtha']  # 0.71 USD/kg
F.RD.price          = price_data['renewable_diesel']   # 1.888 USD/kg
F.SAF.price         = <market_price_USD_per_kg>        # no entry in etj_settings.py; choose from literature
```

Without these prices, the TEA computes zero H₂ cost and zero SAF/RN/RD revenue, making the `solve_price(F.RCF_Monomers)` result meaningless.

## TEA

`scripts/rcf_etoh.py` runs a full TEA using `CellulosicEthanolTEA` from `cellulosic_tea.py` (NREL 2011 methodology, 2016 USD, 10% IRR, 30-year plant life, MACRS7 depreciation for process equipment, MACRS20 for BT).

**Stream pricing — complete picture:**

| Stream | Variable | Price set where |
|---|---|---|
| `Poplar_In` | `poplar_in` | Caller sets `poplar_in.price = prices['Feedstock']` before passing to factory — the `ins=None` branch that sets it inside `create_rcf_system` is dead code when `ins` is provided |
| `Meoh_in` | `meoh_in` | Inside `create_rcf_system()` — methanol only, `price=prices['Methanol']`; water is in separate unpriced `Water_in_meoh` |
| `Hydrogen_In` | `hydrogen_in` | Inside `create_rcf_system()` — `price=prices['Hydrogen']` |
| `EthylAcetate_in` | EtOAc fresh makeup | Inside `create_rcf_oil_purification_system()` — EtOAc only, `price=prices['EthylAcetate']`; water is in separate unpriced `Water_in_etoac` |
| `Hexane_In` | Hexane fresh makeup | Inside `create_monomer_purification_system()` — hexane only, `price=prices['Hexane']`; water is in separate unpriced `Water_in_hexane` |
| `RCF_Catalyst` | `catalyst` stream in `CatalystMixer` | `price=prices['NiC_catalyst']` |
| `Carbohydrate_Pulp` | `F.Carbohydrate_Pulp` | Set in `scripts/rcf_etoh.py` to `prices['Feedstock']` as a conservative co-product credit; only relevant when cellulosic ethanol system is excluded |
| `RCF_Monomers` | `F.RCF_Monomers` | Not set — left at zero so `tea.solve_price(F.RCF_Monomers)` returns the MSP |
| WWT/BT utility chemicals | Internal WWT/BT streams | BioSTEAM defaults (H₂SO₄, lime, DAP, boiler chems, etc.) |

**BioSTEAM stream pricing convention — IMPORTANT for future streams:**

`stream.price` is charged as `price × stream.F_mass` (price per kg of *total stream mass*). If a makeup stream contains both a priced solvent and free process water, they **must** be split into two separate streams:
- one stream carrying only the priced component (with `price` set)
- one stream carrying only water (no `price`, defaults to 0)

Both feed into the same downstream mixer. The `add_specification` spec adjusts each stream's flow independently.

Current streams that follow this pattern:

| Priced stream | Unpriced water stream | Mixer |
|---|---|---|
| `Meoh_in` (Methanol only) | `Water_in_meoh` | MIX100 (`meoh_h2o_mix`) |
| `EthylAcetate_in` (EtOAc only) | `Water_in_etoac` | MIX200 (`solvent_mixer`) |
| `Hexane_In` (Hexane only) | `Water_in_hexane` | MIX300 (`hexane_mixer`) |

When adding any new solvent makeup stream that co-feeds water, apply this same split. Do not combine priced solvent and free water into a single stream.

**Labor cost** — Seider-based estimate computed in `scripts/rcf_etoh.py`:
```python
# DWandB = (operators/shift) * shifts * hr/yr * $/hr
DWandB             = 1 * 3 * 5 * 2080 * 40          # 1 op/section, 3 sections, 5 shifts, $40/hr
Dsalaries_benefits = 0.15 * DWandB
O_supplies         = 0.06 * DWandB
technical_assistance = 5 * 75_000                    # 5 technical staff @ $75k/yr
control_lab          = 5 * 80_000                    # 5 lab staff @ $80k/yr
labor = DWandB + Dsalaries_benefits + O_supplies + technical_assistance + control_lab
```
Override the TEA default (`labor_cost=2.5e6`) after creating:
```python
integrated_tea = create_cellulosic_ethanol_tea(rcf_combined_system)
integrated_tea.labor_cost = labor
```

**MSP calculation:**
```python
msp = integrated_tea.solve_price(F.RCF_Monomers)   # [USD/kg]
```

**`Carbohydrate_Pulp` disposition (cellulosic system excluded):** When the cellulosic ethanol system is excluded, the pulp exits the combined system boundary unconnected. Setting `F.Carbohydrate_Pulp.price = prices['Feedstock']` gives it a revenue credit equal to the raw poplar cost (~0.088 USD/kg at 2016 prices). This is a lower-bound assumption — the processed, cellulose-rich pulp may command a higher market price. Update when better data are available.

## Plotting Utilities (`ligsaf_plots.py`)

All reusable figure-generation functions live in `ligsaf_plots.py`. Import and call them from any script or notebook after simulation is complete.

### `plot_installed_cost_breakdown(categories, values, ...)`

Generates a pie chart of installed cost by process area with percentage leader-line labels, a total cost annotation, and a bottom legend.

```python
from lignin_saf.ligsaf_plots import plot_installed_cost_breakdown

fig, ax = plot_installed_cost_breakdown(
    categories=["RCF Area", "Oil purification", "Monomer purification",
                "Boiler Turbogenerator", "WasteWater Treatment"],
    values=[rcf_area_ic, rcf_oil_purification_ic, rcf_monomer_purification_ic,
            BT_installed_cost, WWT_installed_cost],
    title="Installed Cost Breakdown",
    save_path="installed_cost_breakdown.svg",   # None to skip saving
)
```

**Parameters:**

| Parameter | Default | Notes |
|---|---|---|
| `categories` | — | List of area label strings, one per wedge |
| `values` | — | List of installed costs in USD, same order as `categories` |
| `title` | `"Installed Cost Breakdown"` | Chart title |
| `save_path` | `"installed_cost_breakdown.svg"` | Output path; extension sets format (`.svg`, `.png`, …). `None` skips saving. |
| `dpi` | 300 | Resolution for raster formats |
| `fig_w_px`, `fig_h_px` | 1500, 1260 | Figure dimensions in pixels |
| `fontsize` | 13 | Base font size for all text elements |

**Adding a new process area:** append to both `categories` and `values` before calling. The palette in `_OI_COLORS` has 10 slots; a `ValueError` is raised if more areas are passed. Add entries to `_OI_COLORS` in `ligsaf_plots.py` if you need to go beyond 10.

**Label placement logic:** percentage labels are placed at radii 1.14–1.38 from the pie center depending on wedge size (larger wedges get closer labels). Wedges below 5% are staggered alternately at r=1.36 and r=1.46 to avoid overlap. The total-cost annotation is placed at y=−1.72 below the pie.

**Font selection:** tries Arial → Liberation Sans → DejaVu Sans in that order; falls back to DejaVu Sans if none are available. SVG output uses `svg.fonttype='none'` so text remains editable in Inkscape/Illustrator.

### `plot_operating_cost_breakdown(categories, values, ...)`

Identical pie-chart layout as `plot_installed_cost_breakdown`, but defaults to `ncol=4` in the legend and a tighter bottom margin (`legend_bottom=0.10`) to fit the wider legend row.

```python
from lignin_saf.ligsaf_plots import plot_operating_cost_breakdown

fig, ax = plot_operating_cost_breakdown(
    categories=["Methanol", "Hydrogen", "Poplar", "Ethyl Acetate",
                "Hexane", "NiC catalyst", "Utilities", "Fixed Operating Cost"],
    values=[methanol_price, hydrogen_price, poplar_price, ethyl_acetate_price,
            hexane_price, catalyst_cost, integrated_tea.utility_cost, integrated_tea.FOC],
    title="Annual Operating Cost Breakdown",
    save_path="operating_breakdown.svg",   # None to skip saving
)
```

Parameters are identical to `plot_installed_cost_breakdown`; `values` should be annual costs in USD/yr.

### Shared color palette (`_OI_COLORS`)

Both functions draw from the same 10-entry palette in order:

| Slot | Hex | Color |
|---|---|---|
| 0 | `#E69F00` | orange |
| 1 | `#56B4E9` | sky blue |
| 2 | `#F0E442` | yellow |
| 3 | `#0072B2` | blue |
| 4 | `#D55E00` | vermillion |
| 5 | `#CC79A7` | reddish purple |
| 6 | `#476066` | dark teal |
| 7 | `#562C29` | dark brown |
| 8 | `#009E73` | bluish green |
| 9 | `#999999` | grey |

Slots 0–5 are colorblind-friendly (Wong 2011). Add new entries at the end if more than 10 areas are needed.

## Cellulosic Ethanol Without Pretreatment (`scripts/etoh.py`)

`scripts/etoh.py` is a standalone test script for the RCF + cellulosic ethanol pathway that **skips dilute-acid pretreatment**. The `Carbohydrate_Pulp` from RCF feeds directly into enzymatic saccharification and fermentation via `cellulosic_no_pretreatment.py` (root of `lignin_saf/`).

### Hemicellulose hydrolysis in saccharification

`cellulosic_no_pretreatment.py` passes a custom `saccharification_rxns` to `create_cellulosic_fermentation_system`. **Glucan reactions are intentionally excluded from `saccharification_rxns`.** The reason: in the default `kind='IB'` (Integrated Bioprocess) fermentation mode, `saccharification_reactions` is forwarded to R301 (`ContinuousPresaccharification`) but **not** to R303 (`SaccharificationAndCoFermentation`). R303 always runs its own default Glucan saccharification (90% Glucan → Glucose) regardless of what is passed. If Glucan reactions were included in `saccharification_rxns`, R301 would first convert 90% of all Glucan, then R303 would convert 90% of the residual 4.2% — inflating total Glucan→Glucose yield to ~95% vs. the ~91.5% of the pretreatment pathway. Keeping Glucan out of `saccharification_rxns` lets R303 handle it once on the full incoming Glucan, giving ~91.2% — matching the pretreatment pathway within 0.3%.

`saccharification_rxns` therefore contains only hemicellulose hydrolysis, replacing what dilute-acid pretreatment (R201) would have done:

```
Xylan    + H₂O → Xylose              (90%)   → co-fermented at 85% → Ethanol
Xylan    + H₂O → XyloseOligomer      (2.4%)  → WWT
Xylan           → Furfural + 2 H₂O   (5%)    → WWT
Arabinan + H₂O → Arabinose           (90%)   → co-fermented
Arabinan + H₂O → ArabinoseOligomer   (2.4%)  → WWT
Arabinan        → Furfural + 2 H₂O   (0.5%)  → WWT
Galactan + H₂O → GalactoseOligomer   (2.4%)  → WWT (no fermentation pathway)
Galactan        → HMF + 2 H₂O        (0.3%)  → WWT
Mannan   + H₂O → MannoseOligomer     (0.3%)  → WWT (no fermentation pathway)
Mannan          → HMF + 2 H₂O        (0.3%)  → WWT
```

Net conversions vs. the pretreatment pathway:

| Sugar path | With pretreatment | No pretreatment |
|---|---|---|
| Glucan → Glucose | ~91.5% (R201 9.9% + R303 on 89.5%) | ~91.2% (R303 default on full Glucan) |
| Xylan → Xylose | 90% (R201) | 90% (R301 custom) |
| Arabinan → Arabinose | 90% (R201) | 90% (R301 custom) |
| Galactan/Mannan → oligomers | minor (R201) | minor (R301 custom) |

The residual 0.3% Glucan gap (91.5% vs 91.2%) reflects that acid pretreatment releases a small extra glucose fraction (9.9% Glucan→Glucose in R201) that enzymatic saccharification alone does not replicate. The remaining difference is that pretreatment charges sulfuric acid + ammonia as chemical costs; this pathway does not.

### Hemicellulase enzyme cost — documented assumption

The enzyme loading in `M301` is:
```python
M301.loading_basis = lambda: 1.2 * pretreated_biomass.imass['Glucan']
```
It scales only to Glucan mass. The Xylan/Arabinan hydrolysis reactions in saccharification are therefore catalyzed at **no additional enzyme cost** — no xylanase or arabinanase stream is added. In reality, a hemicellulase-supplemented enzyme cocktail (e.g. Cellic CTec3 which already contains xylanase activity) would be required. This is a known model simplification: the no-pretreatment case replaces acid cost (H₂SO₄ + NH₃) with implied hemicellulase activity that is not separately priced. The net effect on operating cost is uncertain in sign and magnitude until enzyme pricing data for a hemicellulase-augmented cocktail are available.

### Assembly pattern (`scripts/etoh.py`)

```python
rcf_system  = create_rcf_system(ins=poplar_in);  rcf_system.simulate()
etoh_system = create_cellulosic_ethanol_system(ins=F.Carbohydrate_Pulp)
etoh_system.simulate()

# No pretreatment_wastewater — only S401 stillage filtrate goes to WWT
etoh_ww     = [F.unit.S401.outs[1]]
etoh_solids = [F.unit.S401.outs[0]]

WWT = bst.create_conventional_wastewater_treatment_system('WWT', ins=[F.RCF_WW] + etoh_ww)
for unit in WWT.units:
    if hasattr(unit, 'strict_moisture_content'):
        unit.strict_moisture_content = False

F.unit.PWC.ins[0] = WWT.outs[2]

solids_to_BT = bst.Mixer('MIX_BT_solids', ins=[WWT.outs[1]] + etoh_solids)
gas_mixer    = bst.Mixer('MIX_BT_gas',    ins=[F.Purge_Light_Gases, WWT.outs[0]])

BT = bst.facilities.BoilerTurbogenerator('BT', fuel_price=0.2612)
BT.ins[0] = solids_to_BT.outs[0]
BT.ins[1] = gas_mixer.outs[0]

combined_system = bst.System('Combined_Ethanol_System',
    path=(rcf_system, etoh_system, WWT),
    facilities=[solids_to_BT, gas_mixer, BT])
combined_system.simulate()
```

**Differences from `scripts/rcf_etoh.py` (with pretreatment):**
- Uses `cellulosic_no_pretreatment.py` (root) instead of `systems/cellulosic_ethanol.py`
- No oil or monomer purification systems — only RCF and ethanol sections
- `etoh_ww` contains only `S401.outs[1]`; `F.pretreatment_wastewater` does not exist
- No sulfuric acid or ammonia chemical costs (pretreatment chemicals removed)
- Hemicellulose hydrolysis occurs in saccharification; hemicellulase cost not charged (see "Hemicellulase enzyme cost" note above)
- WWT inlets are `F.RCF_WW` + stillage filtrate only (no EtOAc/hexane LLE wastewater)
- `gas_mixer` receives `F.Purge_Light_Gases` (RCF PSA); no ETJ or HDO purge gases
- WWT is constructed inline rather than via `create_rcf_utilities_system()`, because that function expects `WW_10`, `WastePulp`, `WW_11`, `WW_12` (streams from oil/monomer purification that don't exist here)

## Key Source Files

| File | Contents |
|---|---|
| `ligsaf_units.py` | `SolvolysisReactor`, `HydrogenolysisReactor`, `PSA`, `CatalystMixer` class definitions |
| `ligsaf_settings.py` | All process parameters, reaction conditions, prices, biomass composition, EtOAc and hexane LLE partition data |
| `ligsaf_chemicals.py` | Chemical property definitions for the RCF system |
| `ligsaf_plots.py` | Reusable figure-generation functions: `plot_installed_cost_breakdown`, `plot_operating_cost_breakdown` |
| `cellulosic_tea.py` | `CellulosicEthanolTEA` class used for integrated system TEA |
| `systems/rcf.py` | `create_rcf_system(ins=None)` — Area 200 factory function |
| `systems/rcf_oil_purification.py` | `create_rcf_oil_purification_system(ins=None)` — Area 300 EtOAc LLE factory function |
| `systems/monomer_purification.py` | `create_monomer_purification_system(ins=None)` — Area 300 hexane LLE monomer/dimer separation factory function |
| `systems/cellulosic_ethanol.py` | `create_cellulosic_ethanol_system(ins=None, add_denaturant=True)` — includes dilute-acid pretreatment; `WWT=False, CHP=False` always; pass `add_denaturant=False` when ethanol routes to ETJ. |
| `cellulosic_no_pretreatment.py` | `create_cellulosic_ethanol_system(ins=None)` — **no pretreatment variant** (root of `lignin_saf/`); feeds `Carbohydrate_Pulp` directly into enzymatic saccharification. `saccharification_rxns` contains **only hemicellulose reactions** (Xylan/Arabinan → monomers; Galactan/Mannan → oligomers) — Glucan reactions deliberately omitted so R303's defaults handle Glucan once, avoiding double-application. Hemicellulase cost not charged — see "Cellulosic Ethanol Without Pretreatment" section. |
| `systems/hdo.py` | `create_hdo_system(ins=None)` — HDO upgrading factory; H₂ and dodecane recycles converged by BioSTEAM |
| `systems/ligsaf_utilities.py` | `create_rcf_utilities_system()` — Area 400 + 500; returns `(BT, WWT, gas_mixer)`; expects `WW_10`, `WastePulp`, `WW_11`, `WW_12` from oil/monomer purification — not suitable for the no-purification `scripts/etoh.py` assembly |
| `scripts/rcf_etoh.py` | Entry-point script: full integrated system (RCF + oil purification + monomer purification + ethanol **with** pretreatment) |
| `scripts/etoh.py` | Entry-point script: RCF + cellulosic ethanol **without** pretreatment. `Carbohydrate_Pulp` feeds directly to fermentation. WWT and BT assembled inline. Glucan→Glucose yield (~91.2%) matches the pretreatment pathway (~91.5%) within 0.3%. See "Cellulosic Ethanol Without Pretreatment" section. |
| `scripts/rcf_etoh_etj.py` | Entry-point script for the fully integrated RCF + cellulosic ethanol + ETJ biorefinery. Poplar → RCF lignin monomers co-produced with SAF/RN/RD from ETJ upgrading of cellulosic ethanol. Uses `systems/cellulosic_ethanol.create_cellulosic_ethanol_system(add_denaturant=False)` so all ethanol routes to ETJ. Shared utilities (BT, WWT) serve all three areas. See "RCF + ETJ Integrated Biorefinery" section for integration details and open TEA items. |
| `scripts/rcf_hdo.py` | Entry-point script: builds and simulates the RCF + HDO upgrading system. Poplar → RCF lignin monomers → propylcyclohexane (`SAF_CycloAlkane`). HDO purge gases routed to `gas_mixer` → BT; HDO wastewater routed to WWT via `M601.ins`. No cellulosic ethanol co-product in this script. |

## Repo Clean-up Status

### DONE

- **Merged duplicate ethanol factories** — `ethanol_production_no_denaturant.py` deleted; `systems/cellulosic_ethanol.py` accepts `add_denaturant=True/False`.
- **Deleted legacy/scratch files** — `combined_trial_1/2.py`, `cellulosic_ethanol_legacy.py`, `solo_ethanol.py`, `solo_ethanol_no_facilities.py`, `rcf_purification.py` all removed.
- **Moved entry-point scripts to `scripts/`** — `scripts/rcf_etoh.py` and `scripts/rcf_etoh_etj.py`.
- **Moved factory functions to `systems/`** — all five factory files now live under `lignin_saf/systems/`.
- **Added `systems/hdo.py`** — `create_hdo_system(ins=None)` factory with H₂ and dodecane recycle loops; H₂ bug fixed (was using Propylguaiacol for both terms); all unit IDs use underscores per convention. Entry-point script at `scripts/rcf_hdo.py`.

### TODO

- **Merge `etj_system.py` and `etj_no_facilities.py`** (`atj_saf/atj_bst/`) into one factory with a `facilities=True` bool parameter. The two module-level side effects in `etj_no_facilities.py` (`set_flowsheet`, `set_thermo`) should be guarded or removed so importing the merged file has no side effects.

- **Strip `ligsaf_` prefix from support files** (optional, low priority — only worthwhile before public release):

| Current name | Target name |
|---|---|
| `ligsaf_chemicals.py` | `chemicals.py` |
| `ligsaf_settings.py` | `settings.py` |
| `ligsaf_units.py` | `units.py` |
| `ligsaf_plots.py` | `plots.py` |
| `cellulosic_tea.py` | `tea.py` |

Requires updating all imports across the repo.
