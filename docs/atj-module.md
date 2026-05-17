# ATJ Module

The ATJ (Alcohol-to-Jet) module models the catalytic upgrading of ethanol to Sustainable Aviation Fuel. It is located in the `atj_saf/` package and uses BioSTEAM for process simulation and techno-economic analysis.

The key output is the **Minimum Jet fuel Selling Price (MJSP)** in USD/gal.

---

## Pathway overview

Ethanol is dehydrated to ethylene, oligomerized to jet-range hydrocarbons, and hydrogenated to produce a SAF blendstock. The model follows the alcohol-to-jet-synthetic paraffinic kerosene (ATJ-SPK) pathway.

---

## Package structure

```
atj_saf/
├── main.py               # Entry point: simulate + compute MJSP
└── atj_qsd/
    ├── __init__.py
    ├── atj_chemicals.py  # Chemical property definitions
    ├── systems/          # Process system factory functions
    ├── units/            # Custom BioSTEAM unit operations
    └── data/             # Supporting data files
```

---

## Running the simulation

```bash
python -m atj_saf.main
```

This will:

1. Simulate the full ATJ flowsheet
2. Print a stream summary
3. Solve and print the MJSP in USD/gal

You can also import and run the system directly in Python:

```python
from atj_saf.atj_qsd.systems import atj_system, perform_tea

atj_system.simulate()
atj_system.show()

tea = perform_tea()
saf = atj_system.flowsheet.stream['SAF_product']
mjsp = tea.solve_price(saf) * saf.rho / 264.172   # USD/gal
print(f"MJSP: {mjsp:.2f} USD/gal")
```

---

## TEA methodology

The techno-economic analysis follows standard NREL methodology with a discounted cash flow rate of return (DCFROR) approach. Key assumptions include MACRS depreciation, a 30-year plant life, and a 10% internal rate of return (IRR).
