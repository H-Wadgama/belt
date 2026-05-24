# Alcohol-to-Jet SAF biorefinery

![ATJ Biorefinery](atj%20biorefinery.png)

## Overview

This module models the catalytic upgrading of ethanol to sustainable aviation fuel (SAF) via the **Alcohol-to-Jet (ATJ)** pathway. Corn-stover-derived ethanol undergoes three sequential heterogeneous catalytic reactions to yield a slate of renewable hydrocarbon fuels.

**Baseline Plant capacity:** 9 MM gal/yr SAF (similar to LanzaJet's Soperton, GA facility)

---

## Process Description

The ATJ pathway converts ethanol to jet-range hydrocarbons in three steps:

### Step 1 — Dehydration
Ethanol is vaporised and passed over a solid-acid catalyst to produce ethylene via intramolecular dehydration.

| Parameter | Value |
|-----------|-------|
| Temperature | 481 °C |
| Pressure | 10.6 bar |
| Conversion | 99.5 % |
| Catalyst lifetime | 2 yr |

### Step 2 — Oligomerization
Ethylene undergoes chain-growth oligomerization over a nickel-based catalyst, producing a distribution of linear α-olefins.

| Parameter | Value |
|-----------|-------|
| Temperature | 120 °C |
| Pressure | 35 bar |
| Conversion | 99.3 % |
| Catalyst lifetime | 1 yr |

**Product selectivity (mol basis):**

| Cut | Carbon number | Selectivity |
|-----|---------------|-------------|
| Renewable naphtha | C4, C6 | 35 % |
| **Jet fuel (SAF)** | **C10** | **62 %** |
| Renewable diesel | C18 | 3 % |

### Step 3 — Hydrogenation
Olefins are fully hydrogenated over a supported metal catalyst to produce the final alkane products. Unreacted hydrogen is recovered and recycled.

| Parameter | Value |
|-----------|-------|
| Temperature | 350 °C |
| Pressure | 35 bar |
| Conversion | 100 % |
| Catalyst lifetime | 3 yr |

---

## Feedstocks & Products

| Stream | Price |
|--------|-------|
| Ethanol (99.5 wt%, feedstock) | $2.67 / gal |
| Hydrogen — ATR + CCS (feedstock) | $4.45 / kg |
| Renewable naphtha (co-product) | $0.71 / kg |
| Renewable diesel (co-product) | $1.89 / kg |

**Key output:** Minimum Jet Selling Price (MJSP) in $/gal, solved at NPV = 0. Convenient economic metric to compare against petroluem jet fuel.

---

## Module Structure

```
atj_saf/
├── atj_qsd/          # QSDsan-based baseline model (no longer supported)
│   ├── systems.py                  # create_atj_system(), perform_tea()
│   ├── atj_chemicals.py            # Chemical property definitions
│   ├── tea_saf.py / tea_abstract.py
│   ├── units/
│   │   ├── catalytic_reactors.py   # AdiabaticReactor, IsothermalReactor
│   │   ├── PSA.py                  # H₂ pressure swing adsorption
│   │   └── storage_tanks.py
│   └── data/
│       ├── prices.py               # Feedstock & product prices
│       └── catalytic_reaction_data.py
├── atj_bst/          # BioSTEAM-based model (uncertainty & sensitivity analysis)
│   ├── etj_system.py / etj_settings.py
│   ├── etj_system.ipynb            # Main analysis notebook
│   └── breakdown_plot.py / uncertainty_plot.py / capacity_contour.py
├── main.py           # CLI entry point
└── requirements.txt
```

---

## Quick Start

Complete system file in .ipynb format
```
atj_saf/atj_bst/etj_system.ipynb
```

However, a .py file also available for the baseline process system (no TEA, uncertianty analysis, sensitivity analysis)
```
atj_saf/atj_bst/etj_system.py

```

---

Tested working on these versions: `biosteam=='2.51.19'`, `thermosteam==0.51.17'`, `biorefineries==2.34.10'`

