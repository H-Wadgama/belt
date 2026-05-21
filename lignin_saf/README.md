# Lignin valorization to SAF through RCF

![Flow diagram](<flow diagram.png>)

This is a BioSTEAM model for lignin valorization to SAF currently under development

The baseline model assumes a poplar feedstock (2000 dry metric ton per day) and methanol water as a solvent for RCF. The choice of biomass and solvent primarily due to the availability of literature data

## Setup

**Requirements:** Python 3.10, conda

```bash
conda create -n lignin_saf python=3.10
conda activate lignin_saf
pip install -r lignin_saf/requirements.txt
pip install -e .   # install the local package in editable mode
```

**Post-install patch for flexsolve:** `flexsolve==0.5.9` imports `scipy.differentiate.jacobian`, which requires scipy >= 1.14 but this project pins `scipy==1.11.4`. After installing, patch the file manually:

In `<env>/lib/site-packages/flexsolve/numerical_analysis.py`, replace:
```python
from scipy.differentiate import jacobian
```
with:
```python
try:
    from scipy.differentiate import jacobian
except ImportError:
    jacobian = None
```
Then delete `<env>/lib/site-packages/flexsolve/__pycache__/numerical_analysis.cpython-310.pyc` and restart your kernel.

## Running the model

The main working notebook is `rcf_system.ipynb`. Open it in VS Code or Jupyter and run cells sequentially.

For standalone scripts, entry-point files are available under `scripts/`:

- `scripts/rcf_etoh.py` — RCF + cellulosic ethanol co-product; shared BT + WWT utilities; full TEA and MSP solve.
- `scripts/rcf_hdo.py` — RCF + HDO upgrading; converts purified lignin monomers to propylcyclohexane (`SAF_CycloAlkane`); shared BT + WWT utilities.
- `scripts/rcf_etoh_etj.py` — RCF + cellulosic ethanol + ETJ catalytic upgrading to SAF/RN/RD; fully integrated shared utilities.

All scripts follow the same pattern: set up thermodynamics, call the factory functions, assemble the combined system, simulate.

## Process areas

The proposed process areas are:
Area 100: Feed storage and handling
Area 200: RCF (reductive catalytic fractionation — solvolysis + hydrogenolysis + solvent recovery + pulp drying)
Area 300: Products recovery (EtOAc LLE → purified lignin oil; hexane LLE → purified monomers)
Area 400: Wastewater treatment
Area 500: Combustor, boiler and turbogenerator
Area 600: Product and feed chemical storage
Area 700: Utilities
HDO: Hydrodeoxygenation upgrading of purified monomers to propylcyclohexane (SAF precursor)

Current design includes Areas 200, 300, 400, and 500. The HDO upgrading step is implemented in `systems/hdo.py` and assembled in `scripts/rcf_hdo.py`. Areas 100, 600, and 700 are not yet modeled.

## Key source files

| File | Role |
|---|---|
| `systems/rcf.py` | `create_rcf_system(ins=None)` — Area 200 factory function |
| `systems/rcf_oil_purification.py` | `create_rcf_oil_purification_system(ins=None)` — Area 300 EtOAc LLE factory function |
| `systems/monomer_purification.py` | `create_monomer_purification_system(ins=None)` — Area 300 hexane LLE monomer/dimer separation factory function |
| `systems/hdo.py` | `create_hdo_system(ins=None)` — HDO upgrading factory; H₂ and dodecane recycles converged by BioSTEAM |
| `systems/cellulosic_ethanol.py` | `create_cellulosic_ethanol_system(ins=None, add_denaturant=True)` — `WWT=False, CHP=False`; shared RCF utilities serve the full biorefinery |
| `cellulosic_no_pretreatment.py` | `create_cellulosic_ethanol_system(ins=None)` — no-pretreatment variant; only hemicellulose reactions in `saccharification_rxns` (Xylan/Arabinan → monomers at R201 conversions; Galactan/Mannan → oligomers); Glucan omitted from `saccharification_rxns` — handled by R303 defaults to avoid double-application; hemicellulase cost not charged (documented assumption) |
| `systems/ligsaf_utilities.py` | `create_rcf_utilities_system()` — Area 400 + 500 factory function; returns `(BT, WWT, gas_mixer)` |
| `ligsaf_units.py` | Custom BioSTEAM unit classes: `SolvolysisReactor`, `HydrogenolysisReactor`, `HydrodeoxygenationReactor`, `PSA`, `CatalystMixer` |
| `ligsaf_settings.py` | All process parameters, prices, biomass composition, partition coefficients, `hdo_params` |
| `ligsaf_chemicals.py` | Chemical property definitions |
| `scripts/rcf_etoh.py` | Entry-point script: RCF + cellulosic ethanol co-product; full TEA and MSP solve |
| `scripts/rcf_hdo.py` | Entry-point script: RCF + HDO upgrading to propylcyclohexane (`SAF_CycloAlkane`) |
| `scripts/rcf_etoh_etj.py` | Entry-point script: RCF + cellulosic ethanol + ETJ catalytic upgrading to SAF/RN/RD |
| `rcf_system.ipynb` | Main interactive notebook for full integrated system analysis |

## Utilities system (Area 400 + 500)

`create_rcf_utilities_system()` in `ligsaf_utilities_system.py` returns a `(BT, WWT)` tuple. Call it after creating all upstream systems (so the named streams exist on the flowsheet) but before assembling the combined system.

```python
from lignin_saf.ligsaf_utilities_system import create_rcf_utilities_system

rcf_system               = create_rcf_system(ins=poplar_in)
rcf_oil_purification_sys = create_rcf_oil_purification_system(ins=F.RCF_Oil)
ethanol_system           = create_cellulosic_ethanol_system(ins=F.Carbohydrate_Pulp)
BT, WWT, gas_mixer       = create_rcf_utilities_system()

rcf_combined_system = bst.System(
    'Combined_RCF_System',
    path=(rcf_system, rcf_oil_purification_sys, ethanol_system, WWT),
    facilities=[gas_mixer, BT],   # gas_mixer must precede BT
)
rcf_combined_system.simulate()
```

**BT** (`bst.facilities.BoilerTurbogenerator`, `fuel_price=0.2612`) receives:
- `ins[0]` — WWT sludge (`WWT.outs[1]`, dewatered biological sludge from S603)
- `ins[1]` — `gas_mixer` outlet: PSA purge gas + WWT biogas combined
- `ins[2–6]` — makeup water, natural gas, lime, boiler chemicals, air (auto-set by BioSTEAM)

**WWT** (`bst.create_conventional_wastewater_treatment_system`, Humbird 2011 configuration) receives:
- `F.WW_10` — aqueous raffinate from EtOAc LLE (Area 300)
- `F.WastePulp` — decanter water bleed (Area 300); predominantly water, 5% EtOAc
- `F.RCF_WW` — combined RCF wastewater (Area 200)
- `F.WW_11` — water bleed from hexane decanter CENT303 (Area 300)
- `F.WW_12` — aqueous raffinate from hexane LLE300 (Area 300); contains S_Oligomer and G_Oligomer since these are not assigned hexane partition coefficients

The internal `SludgeCentrifuge` (S603) is patched after creation in `ligsaf_utilities_system.py`:

```python
for unit in WWT.units:
    if hasattr(unit, 'strict_moisture_content'):
        unit.strict_moisture_content = False   # ← change here to re-enable strict mode
    # To also change the target moisture fraction (default 0.79):
    # if hasattr(unit, 'moisture_content'):
    #     unit.moisture_content = 0.6
```

The Humbird 79% moisture target was calibrated for cellulosic-ethanol organic loadings. RCF wastewater has a different organic profile: `Acetate` is in `non_digestables` and passes through the bioreactors unreacted, accumulating in the S603 feed and reducing the available free water. `G_Dimer`, `S_Oligomer`, and `G_Oligomer` now have molecular formulas (added to `ligsaf_chemicals.py`) and are therefore included in `get_digestable_organic_chemicals`. All three, plus `Syringaresinol` (a lignan dimer — two sinapyl alcohol units linked via a β–β′ resinol linkage), are unlisted in the hexane LLE partition data and exit LLE300 as the aqueous raffinate `WW_12` — they reach WWT and are treated as digestable organics, contributing to biogas (`→ BT.ins[1]`) and sludge (`→ BT.ins[0]`). Only true monomers (Propylguaiacol, Propylsyringol) partition into the hexane extract and exit as `RCF_Monomers`. The primary remaining cause of the infeasibility is the Acetate accumulation. Set `strict_moisture_content=True` once WWT stream chemistry is validated against experimental RCF wastewater data.

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
| `S_Oligomer` | `C33H40O11` | `37.5 O2 + S_Oligomer → 33 CO2 + 20 Water` | resolved — explicit MW removed; MW now formula-derived (~612.67 Da) |
| `G_Oligomer` | `C31H40O8` | `37 O2 + G_Oligomer → 20 Water + 31 CO2` | correct |
| `Propylguaiacol` | `C10H14O2` | combusts correctly | correct |
| `Propylsyringol` | `C11H16O3` | combusts correctly | correct |
| `Syringaresinol` | `C22H26O8` | combusts correctly | correct |

**`S_Oligomer` MW — resolved:** The explicit `MW=628.67` parameter was removed; `S_Oligomer` is now defined with `formula='C33H40O11'` only, so thermosteam derives MW as ~612.67 Da and BT combustion is clean (no `Ash` term). **Open question:** confirm that `C33H40O11` (612.67 Da) is the correct molecular identity against Bartling et al. Fig S8 — if the correct structure has MW 628.67, change the formula to `C33H40O12`.

**Note on current process flows:** `Syringaresinol` (a dimer), `G_Dimer`, `S_Oligomer`, and `G_Oligomer` are all unlisted in the hexane LLE partition data and exit LLE300 as `WW_12` → WWT → biogas/sludge → BT; their combustion reactions are therefore active. Only true monomers (Propylguaiacol, Propylsyringol) partition to the hexane extract and exit as `RCF_Monomers`.

**Adding more wastewater or fuel streams in the future:**

For WWT, extend the `ins` tuple in `create_rcf_utilities_system()`:
```python
WWT = bst.create_conventional_wastewater_treatment_system(
    'WWT', ins=(F.WW_10, F.WastePulp, F.RCF_WW, F.WW_Etoh, ...)
)
```

For BT, each combustion slot accepts one stream. Combine multiple feeds with a `bst.Mixer` first, then wire the mixer outlet to `BT.ins[0]` or `BT.ins[1]`, and add the mixers to `facilities` before BT:
```python
solid_mixer = bst.Mixer('MIX_BT_solid', ins=(F.Stream1, F.Stream2))
BT.ins[0] = solid_mixer.outs[0]
# in combined system: facilities=[solid_mixer, BT]
```


## HDO System

`create_hdo_system(ins=None)` in `systems/hdo.py` converts the purified lignin monomers (Propylguaiacol + Propylsyringol from `RCF_Monomers`) to propylcyclohexane (`SAF_CycloAlkane`) via hydrodeoxygenation over Ni₂P/SiO₂ in dodecane solvent.

```python
from lignin_saf.systems.hdo import create_hdo_system
hdo_system = create_hdo_system(ins=F.RCF_Monomers)
hdo_system.simulate()
```

The system has two converged recycle loops:
- **H₂ recycle** — PSA (HDO_PSA1) recovers unreacted H₂, which is recompressed to 5 MPa (HDO_COMP_H2) and recycled to the H₂ mixer (HDO_MIX_H2). Fresh H₂ makeup is adjusted every iteration: `fresh = (6×mol_PG + 8×mol_PS) × 1.5 excess − recycle`.
- **Dodecane recycle** — the solvent-recovery column (HDO_COL1) separates propylcyclohexane (tops) from dodecane (bottoms). The dodecane bottoms are cooled to 300 K (HDO_HX_DOD) and recycled to the dodecane mixer (HDO_MIX_DOD). Fresh dodecane makeup is adjusted to maintain 0.04 m³/kg monomer feed.

**Named output streams for downstream wiring:**

| Stream | Description | Route in calling script |
|---|---|---|
| `SAF_CycloAlkane` | Propylcyclohexane product | product / further upgrading |
| `HDO_purge_gases` | PSA purge (H₂, CH₄, light gases) | `gas_mixer.ins.append(F.HDO_purge_gases)` |
| `HDO_wash_water` | Near-pure water from secondary flash | `F.unit.M601.ins.extend([F.HDO_wash_water, F.HDO_WW])` |
| `HDO_WW` | Water-rich tops from product column | same as above |

The HDO system produces no combustible solids, so no `solids_to_BT` mixer is needed — `BT.ins[0] = WWT.outs[1]` set inside `create_rcf_utilities_system()` remains correct.

## Unified utilities for the integrated biorefinery

The cellulosic ethanol co-product uses the shared RCF utilities (BT, WWT) rather than its own. `ethanol_production.py` provides a local `create_cellulosic_ethanol_system` that passes `WWT=False, CHP=False` to `bst.create_all_facilities`, so no BT or WWT is ever created inside the ethanol system. This avoids all ID conflicts without post-hoc unit removal.

`ethanol_system` is included **directly in the combined system path**. This is required for a correct TEA (so that ethanol CAPEX and revenue are included) and for correct BT CHP scope (so that the ethanol system's ~80 MW of steam demand is served by the shared BT rather than billed as market utilities).

After creating the ethanol system, streams are routed into the shared utilities by explicit name. **Do not use a `sink is None` heuristic** — it over-captures cooling tower evaporation, cooling water circulation, and the fermentation vent, none of which should go to BT or WWT.

Correct stream destinations:

| Stream | Destination | Notes |
|---|---|---|
| `F.pretreatment_wastewater` | WWT via `M601.ins` | |
| `F.unit.S401.outs[1]` (stillage filtrate) | WWT via `M601.ins` | |
| `F.unit.S401.outs[0]` (filter cake) | BT solids via `solids_to_BT` | |
| `WWT.outs[2]` (RO treated water, ~479,000 kg/hr) | `PWC.ins[0]` directly | Without this, PWC purchases ~480,000 kg/hr fresh water unnecessarily (~$1.1M/yr) |
| Fermentation vent | **unconnected** — atmospheric | Stock system does not burn it in BT |
| CT blowdown | → PWC via `blowdown_recycle=True` | Set in `ethanol_production.py` |

```python
from lignin_saf.ethanol_production import create_cellulosic_ethanol_system

ethanol_system = create_cellulosic_ethanol_system(ins=F.Carbohydrate_Pulp)
ethanol_system.simulate()

# Explicit stream routing — verified against stock cellulosic factory
etoh_ww     = [F.pretreatment_wastewater, F.unit.S401.outs[1]]
etoh_solids = [F.unit.S401.outs[0]]

BT, WWT, gas_mixer = create_rcf_utilities_system()
F.unit.M601.ins.extend(etoh_ww)
solids_to_BT = bst.Mixer('MIX_BT_solids', ins=[WWT.outs[1]] + etoh_solids)
BT.ins[0] = solids_to_BT.outs[0]
# Do NOT extend gas_mixer with ethanol gases — fermentation vent is atmospheric

# Wire WWT RO-treated water to PWC.
# create_all_facilities(WWT=False) leaves placeholder mixer M2 empty.
# This line prevents PWC from purchasing ~480,000 kg/hr unnecessary fresh water.
F.unit.PWC.ins[0] = WWT.outs[2]

rcf_combined_system = bst.System(
    'Combined_RCF_System',
    path=(rcf_system, rcf_oil_purification_sys, monomer_purification_sys, ethanol_system, WWT),
    facilities=[solids_to_BT, gas_mixer, BT],
)

rcf_combined_system.simulate()
```

**Note on `fuel_price`:** `BT.utility_cost` does not include natural gas cost — BioSTEAM bills it as a raw material through the TEA's `material_cost` (via `BT.ins[2].price`). The `fuel_price` parameter therefore does not affect utility cost comparisons but will surface in `tea.solve_price()`. The RCF system uses `fuel_price=0.2612`; verify this matches your natural gas price assumption.


## TEA (Techno-Economic Analysis)

`rcf_4_21_2026` runs a full TEA using `CellulosicEthanolTEA` (NREL 2011 methodology, 2016 USD, 10% IRR, 30-year plant life, MACRS7 depreciation).

**Stream prices** — set in two places:

| Stream | Set where |
|---|---|
| `Meoh_in` (methanol only) | Inside `create_rcf_system()` in `ligsaf_system.py`; process water is in separate unpriced `Water_in_meoh` |
| `Hydrogen_In` | Inside `create_rcf_system()` in `ligsaf_system.py` |
| `Poplar_In` (feedstock) | On the stream object in `rcf_4_21_2026` before calling `create_rcf_system(ins=poplar_in)` — the price inside the `ins=None` branch of the factory is dead code when `ins` is passed |
| `EthylAcetate_in` (EtOAc only) | Inside `create_rcf_oil_purification_system()`; process water is in separate unpriced `Water_in_etoac` |
| `Hexane_In` (hexane only) | Inside `create_monomer_purification_system()`; process water is in separate unpriced `Water_in_hexane` |
| NiC catalyst | OPEX via `CatalystMixer`; `price=prices['NiC_catalyst']` on the catalyst stream |

**Stream pricing convention:** BioSTEAM charges `price × F_mass` for the *entire* stream. Whenever a solvent makeup stream co-feeds both a priced solvent and free water, they must be two separate streams — priced solvent only on the first, unpriced water on the second — both entering the same mixer. See CLAUDE.md TEA section for the full convention and the table of existing split stream pairs.

**`Carbohydrate_Pulp` co-product credit:** When the cellulosic ethanol system is excluded, `Carbohydrate_Pulp` exits the combined system boundary with no downstream. A co-product credit is assigned at the feedstock price as a conservative lower-bound:
```python
F.Carbohydrate_Pulp.price = prices['Feedstock']
```
Update this value when a better market price for cellulosic pulp is available.

**Labor cost** — Seider-based estimate computed in `rcf_4_21_2026`, then used to override the TEA default:
```python
# 1 operator/section × 3 sections × 5 shifts × 2080 hr/yr × $40/hr
DWandB = 1 * 3 * 5 * 2080 * 40
labor  = DWandB + 0.15*DWandB + 0.06*DWandB + 5*75_000 + 5*80_000

integrated_tea = create_cellulosic_ethanol_tea(rcf_combined_system)
integrated_tea.labor_cost = labor   # overrides default 2.5e6
```

**Minimum selling price (MSP):**
```python
msp = integrated_tea.solve_price(F.RCF_Monomers)   # [USD/kg]
```

_Hemicellulose hydrolysis in the no-pretreatment pathway is catalyzed at no additional enzyme cost_: In `cellulosic_no_pretreatment.py`, Xylan → Xylose (90%) and Arabinan → Arabinose (90%) are added to the saccharification step using the same conversions as dilute-acid pretreatment (R201). The enzyme loading formula in M301 scales only to Glucan mass (`1.2 × Glucan kg`), so no hemicellulase cost is charged for the additional hemicellulose reactions. In reality a xylanase/arabinanase-supplemented cocktail would be required. The no-pretreatment case therefore removes acid + ammonia cost (from pretreatment) without adding an equivalent hemicellulase cost — the net operating cost impact is uncertain until enzyme pricing for a hemicellulase-augmented cocktail is available.

## Open implementation items

**Pulp purifier vapor recovery (D601):** `pulp_purifier` (Flash D601, T=400 K, P=1 atm) strips residual methanol and water from the `Wet_Pulp` before the `Carbohydrate_Pulp` stream exits Area 200. The vapor overhead (`outs[0]`) is currently unrecovered — it represents lost solvent not yet accounted for in WWT. A future implementation should route this stream to wastewater treatment or to a dedicated solvent recovery step.

**Solvolysis reactor solvent retention — hardcoded to methanol/water:** `SolvolysisReactor._run()` in `ligsaf_units.py` deposits 0.5% of the solvent flow into the biomass outlet for MeOH and Water only:
```python
for chem_id in ('Methanol', 'Water'):
    used_biomass.imass[chem_id] = used_solvent.imass[chem_id] * 0.005
```
The original generic loop (iterating over all chemicals) caused trace gases — CH4, CO, H2 — accumulated in the MeOH recycle to appear in the carbohydrate pulp. The explicit tuple is the current fix. If the solvent is changed from methanol/water in the future, this tuple must be updated to match the new solvent identity.

## The main process assumptions:
_The loss of carbohydrate retention in biomass pulp post RCF is due to solvent dissolution_: Carbohydrate retention can decrease due to solvent dissolution or  reaction within the solvent [1](https://pubs.rsc.org/en/content/articlelanding/2021/ee/d0ee02870c). Here we assume that the carbohydrates are only solubilized and are not reacting with the solvent. 


_The extraction efficiency of lignin is 100%_: We assume that delignification (i.e. solvolysis + extraction) is only dependent on the solvolysis reaction, and that the extraction efficiency is always 100%.


_Delignification extent is constant throughout residence time of solvolysis_: This assumption can be false since as the reaction proceeds, the content of lignin in biomass reduces and this could lead to concentration hotspots of lignin in the poplar bed. However, we assume that delignication stays constant throughout the biomass bed because the continuous flow of fresh solvent allows for a maximum diffusive flux between the solvent and the biomass [2](https://pubs.acs.org/doi/10.1021/acssuschemeng.8b01256). 


_Total RCF solvolysis time on stream is 3 hours_: The solvolysis bed operates as a semi-batch unit: each bed is on-stream for 3 hours (time on stream, TOS) — the period during which biomass is loaded and solvent flows through continuously — then taken offline for 1 hour of cleaning/turnaround. Note that "time on stream" (3 hr, a property of the biomass batch) is distinct from the hydraulic residence time of the solvent (20 min, a property of the solvent flow rate through the bed). This gives a 4-hour cycle per solvolysis bed and 6 batches per reactor per day. The kinetic basis for the 3-hour solvolysis time follows from Beckham and Roman-Leshkov's group showing solvolysis is the rate-limiting step [2](https://pubs.acs.org/doi/10.1021/acssuschemeng.8b01256). The hydrogenolysis reactor is modelled as a fully continuous fixed-bed reactor; it is sized from a 20-minute (1/3 hr) hydraulic residence time applied to the combined liquid + hydrogen feed volumetric flow.

_Solvolysis reactor hydraulic residence time is 20 minutes (experimentally derived)_: The 20-minute hydraulic residence time (`tau_residence`) comes from experimental RCF data. It determines the solvent flow rate through each active bed. The total solvent volume per bed is V_solvent = V_void × (1 + free_frac), where V_void = void_frac × V_biomass is the interparticle void volume and the free_frac term adds excess solvent beyond the voids to satisfy mass transfer considerations. The flow rate follows directly — Q_per_reactor = V_solvent / tau_residence. The BioSTEAM model treats the solvolysis reactor as single-pass flow-through; internal recirculation is not modeled. Mass balances and TEA results are valid because delignification conversion (70%) is held fixed in the reaction specification.

_Solvolysis reactor sizing uses a volume-first model with ideal stagger scheduling_: Bed geometry drives the design — the solvent loading [L/kg] is a derived output, not a user input. The reactor volume is set by how much biomass fits per batch (from the ideal stagger schedule and bulk density), and the solvent flow rate follows from the solvent volume and residence time (Q = V_solvent / tau_res, where V_solvent = V_void × (1 + free_frac)). The number of reactors is determined in three stages: (1) **Ideal stagger**: N_total = round(cycle_time / tau_0), N_working = round(N_total × tau / cycle_time) — this gives perfectly staggered scheduling with exactly N_offline beds always cleaning. (2) **V_max enforcement**: V_max = V_solid + V_solvent; if this exceeds V_max_limit (600 m³), N_total is scaled by integer multiples (k = 1, 2, …) — each step increases batches_per_day and reduces biomass_per_batch, shrinking V_max until it fits. (3) **L/D cap**: if L/D > LD_max (default 5.0, targeting the ideal packed-bed range of 3–5), the superficial velocity is reduced analytically to hit L/D = 5 exactly; pressure drop is recomputed at the adjusted velocity.

At the base case (tau=3 hr, tau_0=1 hr, tau_res=20 min, void_frac=0.5, free_frac=0.10), this gives N_total=4, N_working=3, V_max ≈ 180 m³ per vessel, D ≈ 3.58 m, L ≈ 17.9 m, Q_total ≈ 851 m³/hr, and a derived solvent loading of ~10.2 L/kg. The vessel cost is extrapolated outside BioSTEAM's built-in correlation range (L ≤ 40 ft / 12 m) — this is expected for large custom pressure vessels of this scale.


_Hydrogenolysis reactor is a continuous fixed-bed reactor sized from hydraulic residence time_: The hydrogenolysis reactor is fully continuous — the NiC catalyst is on-stream indefinitely with no batch cycles. Reactor volume is derived from the total feed volumetric flow (liquid solvent + dissolved lignin + hydrogen gas) and a 20-minute (1/3 hr) hydraulic residence time: V_fluid = Q_total × τ_res, with V_bed = V_fluid / void_frac (void_frac = 0.7) and V_reactor = V_bed / (1 − free_frac) where free_frac = 0.20 is the headspace fraction above the packed bed. The number of parallel reactors is derived automatically as N = ceil(V_reactor / 100 m³). Reactor geometry (D, L) is computed from superficial velocity with L/D enforced within [3, 10]: if the natural L/D falls outside this range the superficial velocity is adjusted analytically to the nearest bound.





