# BELT

**Biorefinery Economic and Lifecycle Assessment Tool**

BELT is an open-source, modular framework for techno-economic analysis (TEA) of Sustainable Aviation Fuel (SAF) production. It is built on top of [BioSTEAM](https://biosteam.readthedocs.io/), a fast and flexible process simulation platform for early-stage biorefineries.

The package provides two independent modules that can be used separately or in combination:

| Module | Pathway | Key output |
|---|---|---|
| [**ATJ**](atj-module.md) | Alcohol-to-Jet from ethanol | Minimum jet fuel selling price (MJSP, USD/gal) |
| [**LigSAF**](ligsaf-module.md) | Lignin valorization via Reductive Catalytic Fractionation (RCF) | Minimum selling price (MSP, USD/kg) |

---

## Why BELT?

Techno-economic models for SAF are often closed-source, making it difficult to reproduce results or adapt assumptions to new feedstocks and process configurations. BELT is designed to be:

- **Modular** — process areas are independent factory functions that can be swapped or extended
- **Transparent** — all parameters, prices, and reaction specifications are in readable Python files
- **Reproducible** — simulations run from a single entry-point script or notebook

---

## Repository structure

```
ATJSPK/
├── atj_saf/          # ATJ module
│   └── atj_qsd/      # Process systems, units, and chemicals
├── lignin_saf/        # LigSAF module
│   └── systems/       # RCF, HDO, oil purification, utilities
├── scripts/           # Entry-point scripts for integrated simulations
└── consolidated_bp_kay/  # Supporting BioSTEAM configurations
```

---

## Citation

If you use BELT in your work, please cite the repository:

> Wadgama, H. (2025). BELT: Biorefinery Economic and Lifecycle Assessment Tool. GitHub. https://github.com/H-Wadgama/belt

---

## Contact

Questions or feedback? Reach out on [LinkedIn](https://www.linkedin.com/in/hafiwadgama/) or open an issue on [GitHub](https://github.com/H-Wadgama/belt/issues).
