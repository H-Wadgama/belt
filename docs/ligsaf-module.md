# LigSAF Module

The LigSAF module models lignin valorization to Sustainable Aviation Fuel through Reductive Catalytic Fractionation (RCF). It is located in the `lignin_saf/` directory and is built on BioSTEAM.

The baseline configuration assumes a **poplar feedstock** (2,000 dry metric ton/day) with a methanol/water solvent, reflecting available experimental literature data.

The key output is the **Minimum Selling Price (MSP)** of the lignin monomer or SAF product in USD/kg.

---

## Pathway overview

RCF simultaneously fractionates lignocellulosic biomass and depolymerizes lignin into phenolic monomers. The purified monomers (propylguaiacol and propylsyringol) are then upgraded via hydrodeoxygenation (HDO) to propylcyclohexane, a cycloalkane SAF blendstock. The carbohydrate pulp co-product can be valorized via cellulosic ethanol fermentation.

---

## Process areas

| Area | Description | Status |
|---|---|---|
| 200 | RCF (solvolysis + hydrogenolysis + solvent recovery + pulp drying) | Implemented |
| 300 | Products recovery (EtOAc LLE → lignin oil; hexane LLE → purified monomers) | Implemented |
| 400 | Wastewater treatment | Implemented (shared utilities) |
| 500 | Combustor, boiler, and turbogenerator | Implemented (shared utilities) |
| HDO | Hydrodeoxygenation of purified monomers to propylcyclohexane | Implemented |
| 100, 600, 700 | Feed storage, product/chemical storage, utilities | Not yet modeled |

---

## Package structure

```
lignin_saf/
├── systems/
│   ├── rcf.py                     # Area 200: RCF factory
│   ├── rcf_oil_purification.py    # Area 300: EtOAc LLE
│   ├── monomer_purification.py    # Area 300: hexane LLE
│   ├── hdo.py                     # HDO upgrading factory
│   ├── cellulosic_ethanol.py      # Ethanol co-product (shared utilities)
│   └── ligsaf_utilities.py        # Area 400 + 500 shared utilities
├── ligsaf_units.py                # Custom unit operations
├── ligsaf_settings.py             # All process parameters and prices
├── ligsaf_chemicals.py            # Chemical property definitions
└── rcf_system.ipynb               # Main interactive notebook
```

---

## Entry-point scripts

Three pre-assembled configurations are available under `scripts/`:

| Script | Configuration |
|---|---|
| `scripts/rcf_etoh.py` | RCF + cellulosic ethanol co-product; full TEA and MSP solve |
| `scripts/rcf_hdo.py` | RCF + HDO upgrading to propylcyclohexane (SAF blendstock) |
| `scripts/rcf_etoh_etj.py` | RCF + cellulosic ethanol + ETJ catalytic upgrading to SAF/RN/RD |

Run any script from the repo root:

```bash
python scripts/rcf_etoh.py
```

---

## Interactive notebook

The main working environment is `lignin_saf/rcf_system.ipynb`. Open it in VS Code or Jupyter and run cells sequentially. The notebook assembles the full integrated system, runs the simulation, and computes the MSP.

---

## Building a custom system

Factory functions follow a consistent pattern — each returns a BioSTEAM `System` object and accepts an optional `ins` argument for wiring streams between areas:

```python
import biosteam as bst
from lignin_saf.systems.rcf import create_rcf_system
from lignin_saf.systems.rcf_oil_purification import create_rcf_oil_purification_system
from lignin_saf.systems.ligsaf_utilities import create_rcf_utilities_system

poplar_in = bst.Stream('Poplar_In', ...)

rcf_sys    = create_rcf_system(ins=poplar_in)
oil_pur    = create_rcf_oil_purification_system(ins=bst.F.RCF_Oil)
BT, WWT, gas_mixer = create_rcf_utilities_system()

combined = bst.System(
    'Combined_RCF_System',
    path=(rcf_sys, oil_pur, WWT),
    facilities=[gas_mixer, BT],
)
combined.simulate()
```

---

## TEA methodology

The techno-economic analysis uses `CellulosicEthanolTEA` (NREL 2011 methodology, 2016 USD basis) with a 10% IRR, 30-year plant life, and MACRS7 depreciation. Labor cost is estimated using the Seider method.

```python
msp = tea.solve_price(bst.F.RCF_Monomers)   # USD/kg
```

---

## Key assumptions

- Carbohydrate retention loss in pulp is due to solvent dissolution only (no reaction)
- Lignin extraction efficiency is 100% (delignification is reaction-limited)
- Solvolysis time on stream: 3 hours per batch; hydraulic residence time: 20 minutes
- Hydrogenolysis reactor: continuous fixed-bed, 20-minute hydraulic residence time
