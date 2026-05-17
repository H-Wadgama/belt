# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment Setup

This project uses a conda environment named `pyfuel` (Python 3.10):

```bash
conda activate pyfuel
pip install -r requirements.txt
pip install -e .   # install package in editable mode for development
```

Key pinned dependencies: `biosteam==2.47.0`, `qsdsan==1.4.1`, `numba==0.60.0`, `numpy==1.26.4`, `scipy==1.11.4`.

**Post-install patch required for flexsolve:** `flexsolve>=0.5.9` imports `scipy.differentiate.jacobian` which only exists in scipy>=1.14, conflicting with the pinned `scipy==1.11.4`. After installing, patch the installed file:

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
Then delete `<env>/lib/site-packages/flexsolve/__pycache__/numerical_analysis.cpython-310.pyc`.

**graphviz is required** for `system.diagram()` and `system.save_report()`. Install via conda (not pip):
```bash
conda install graphviz
```
Without graphviz, `save_report` will produce an empty Excel file with no stream or cost data.

Each sub-project also has its own `requirements.txt`:
- `lignin_saf/requirements.txt` — dependencies for the lignin SAF model only (excludes `qsdsan`)

## Running the Models

**ATJ baseline simulation (CLI):**
```bash
python -m atj_saf.main
```
This simulates the system and prints the Minimum Jet Selling Price (MJSP) in $/gal.

**Interactive analysis** is done primarily through Jupyter notebooks:
- `atj_saf/atj_bst/etj_system.ipynb` — BioSTEAM-native ATJ/ETJ system with uncertainty, sensitivity, and contour plot analysis
- `lignin_saf/rcf_system.ipynb` — Integrated RCF + cellulosic ethanol system (main active notebook)

**RCF system as a standalone script:**
- `scripts/rcf_etoh.py` — Builds and simulates the full integrated RCF + cellulosic ethanol system.
- `scripts/rcf_etoh_etj.py` — Extends the above with ETJ catalytic upgrading of the cellulosic ethanol co-product.

```python
# Entry-point pattern (scripts/rcf_etoh.py)
from lignin_saf.ligsaf_chemicals import create_chemicals
from lignin_saf.systems.rcf import create_rcf_system

chems = create_chemicals()
bst.settings.set_thermo(chems)
bst.settings.CEPCI = 541.7
chems.define_group('Poplar', ...)   # must be defined before creating Poplar stream
poplar_in = bst.Stream('Poplar_In', Poplar=..., Water=..., phase='l', units='kg/d')
rcf_system = create_rcf_system(ins=poplar_in)
rcf_system.simulate()
rcf_system.show()
```

## Architecture Overview

The repo contains two independent SAF process models, each with its own chemicals, units, systems, and TEA:

### 1. `atj_saf/` — Alcohol-to-Jet (ATJ) SAF

Three-step conversion: **ethanol → ethylene (dehydration) → olefins (oligomerization) → SAF (hydrogenation)**. Products are renewable naphtha (C4–C6), SAF (C10), and renewable diesel (C18).

Two sub-implementations exist:

| Sub-package | Framework | Entry point |
|---|---|---|
| `atj_baseline/` | QSDsan (`qs.SanStream`, `qs.System`) | `atj_saf/main.py` → `systems.py` |
| `atj_bst/` | Pure BioSTEAM (`bst.Stream`, `bst.System`) + `biorefineries` | `etj_system.ipynb` |

**Key files in `atj_saf/atj_baseline/`:**
- `systems.py` — `create_atj_system()` builds the full unit-by-unit flowsheet; `perform_tea()` sets up TEA
- `atj_chemicals.py` — chemical property definitions
- `units/catalytic_reactors.py` — custom `AdiabaticReactor` and `IsothermalReactor`
- `units/PSA.py` — pressure swing adsorption for H₂ recovery
- `units/storage_tanks.py` — ethanol, hydrogen, and hydrocarbon product tanks
- `data/prices.py` — all feedstock and product prices
- `data/catalytic_reaction_data.py` — reaction conversions and selectivities
- `tea_saf.py` / `tea_abstract.py` — `ConventionalEthanolTEA` class

**Key files in `atj_saf/atj_bst/`:**
- `etj_system.py` — `create_etj_system()` (BioSTEAM version)
- `etj_settings.py` — all process parameters and prices
- `atj_bst_units.py` — custom unit operations
- `atj_bst_tea_saf.py` / `atj_bst_tea_abstract.py` — TEA class
- `cellulosic_tea_etj.py` — TEA for cellulosic ethanol co-production variant
- Plot files: `breakdown_plot.py`, `uncertainty_plot.py`, `selectivity_plot.py`, `capacity_contour.py`

### 2. `lignin_saf/` — Lignin RCF to SAF

Two-reactor RCF process: **poplar → solvolysis + hydrogenolysis → lignin oil monomers**, co-producing cellulosic ethanol from the carbohydrate pulp. Feedstock: 2,000 dry MT/day poplar. CEPCI basis: 541.7 (2016 USD).

**Key files:**
- `rcf_system.ipynb` — main working notebook; builds and simulates the full integrated system
- `ligsaf_units.py` — custom units: `SolvolysisReactor`, `HydrogenolysisReactor`, `PSA`, `CatalystMixer`
- `ligsaf_settings.py` — all RCF process parameters (conditions, catalyst loading, biomass composition, oil composition)
- `ligsaf_chemicals.py` — chemical definitions for the RCF system
- `cellulosic_tea.py` — `CellulosicEthanolTEA` used for the integrated system TEA
- `ligsaf_plots.py` — reusable figure-generation functions (installed cost and operating cost breakdowns)
- `systems/rcf.py` — **`create_rcf_system(ins=None)`** — Area 200 RCF loop factory
- `systems/rcf_oil_purification.py` — **`create_rcf_oil_purification_system()`** — ethyl acetate LLE
- `systems/monomer_purification.py` — **`create_monomer_purification_system()`** — hexane LLE
- `systems/cellulosic_ethanol.py` — **`create_cellulosic_ethanol_system()`** — cellulosic ethanol co-product
- `systems/ligsaf_utilities.py` — **`create_rcf_utilities_system()`** — shared BT + WWT (returns `(BT, WWT, gas_mixer)`)

Import pattern:
  ```python
  from lignin_saf.systems.rcf import create_rcf_system
  rcf_system = create_rcf_system(ins=poplar_in)  # ins=None uses default feed from ligsaf_settings
  ```
  Note: `chems.define_group('Poplar', ...)` must be called before creating any stream with `Poplar` as a component — do this in the calling script after `bst.settings.set_thermo(chems)`, before passing `ins` to the factory.

**`SolvolysisReactor` sizing model (volume-first, semi-batch, ideal stagger):**

Reactor sizing in `_size_bed()` (`ligsaf_units.py`) follows a three-stage logic. Bed geometry fully determines the solvent volume; Q and loading are derived outputs, not inputs.

**Stage 1 — N_total from ideal stagger formula:**
```
N_total_base = round(cycle_time / tau_0)            # e.g. round(4/1) = 4
N_working    = round(N_total_base × tau/cycle_time) # e.g. round(4 × 3/4) = 3
N_offline    = N_total_base − N_working             # e.g. 1
```
This ensures exactly N_offline beds are always in their cleaning window (τ₀) — the ideal stagger condition. At least 1 cleaning slot and 1 active slot are guaranteed.

**Stage 2 — V_max_limit enforcement by k-multiplier scaling:**
If the base count gives vessel volumes above V_max_limit (600 m³), N_total is scaled by integer k = 1, 2, 3, … until V_max ≤ V_max_limit. Increasing k raises batches_per_day, which reduces biomass_per_batch and hence V_biomass and V_max. Stagger timing is preserved exactly because N_total = k × N_total_base and N_working = k × N_working_base.

**Stage 3 — Geometry with L/D cap:**
Cross-section A and diameter/length are derived from Q_per_reactor and superficial_velocity. If L/D > LD_max (default 5.0), superficial velocity is reduced analytically to hit L/D = LD_max exactly. `self.superficial_velocity` is updated so pressure drop uses the adjusted value.

**Key parameters:**

| Parameter | Default | Meaning |
|---|---|---|
| `V_max_limit` | 600 m³ | Hard upper bound per vessel; k-multiplier scales until satisfied. |
| `tau_s` | 3 hr | Time on stream per batch (biomass contact time) |
| `tau_s_res` | 1/3 hr (20 min) | Hydraulic residence time — sets Q via Q = V_solvent / tau_res |
| `void_frac` | 0.5 | Interparticle void fraction; V_void = void_frac × V_biomass |
| `poplar_density` | 485 kg/m³ | Bulk density of poplar chips |
| `free_frac` | 0.10 | Excess solvent fraction beyond interparticle voids; V_solvent = V_void × (1 + free_frac) |
| `LD_max` | 5.0 | Max L/D ratio; u reduced analytically if exceeded |

**Volume-first sizing (in `_size_bed()`):**
```
V_void            = void_frac × V_biomass                    # interparticle voids
V_excess_solvent  = V_void × free_frac                       # excess solvent for mass transfer
V_solvent         = V_void + V_excess_solvent                # = V_void × (1 + free_frac)
V_max             = V_solid + V_solvent                      # = V_biomass × (1 + void_frac × free_frac)
Q_per_reactor     = V_solvent / tau_residence                # derived from geometry
Q_total           = N_working × Q_per_reactor
loading           = Q_total × 1000 × 24 / dry_biomass_kgday # derived [L/kg], reported in design_results
```

**`meoh_water_flow` spec** calls `solvolysis_reactor.compute_Q_total()` on every recycle iteration to set the methanol feed flow. `compute_Q_total()` is a side-effect-free method that replicates the geometry calculation (including the free_frac excess solvent term) without requiring a prior simulate.

**Base case (tau=3, tau_0=1, tau_res=1/3 hr, void_frac=0.5, free_frac=0.10):**

| Quantity | Value |
|---|---|
| N_total / N_working / N_offline | 4 / 3 / 1 |
| Biomass per batch | 83,333 kg |
| V_void per bed | 85.9 m³ |
| V_solvent per bed | ~94.5 m³ |
| V_max per vessel | ~180 m³ |
| Q_total / Q_per_reactor | ~851 / 284 m³/hr |
| Derived loading | ~10.2 L/kg |
| D / L / L/D | 3.58 m / 17.9 m / 5.0 |
| Effective u (after L/D cap) | ~0.0078 m/s |

**batches/day = 24/tau_0** regardless of tau — a consequence of the ideal stagger formula. Changing tau_residence changes Q (and hence loading) but not vessel size or count.

**Tests:** `lignin_saf/test_solvolysis_sizing.py` — pytest suite covering volume balance, batch arithmetic, Q correctness (Q = V_solvent / tau_res), L/D cap, derived loading, and all design result keys. Run with:
```bash
pytest lignin_saf/test_solvolysis_sizing.py -v
```

**Integrated systems built in `rcf_system.ipynb`:**
- `rcf_system` — RCF loop (MIX100 through FLASH118)
- `etoh_system` — cellulosic ethanol system from `biorefineries.cellulosic`
- `rcf_oil_purification_sys` — ethyl acetate LLE
- `monomer_purification_sys` — hexane LLE
- `combined_sys` — full integrated system (330 days/yr × 24 hrs)
- `combined_sys_hx` — same with `HeatExchangerNetwork` (T_min_app = 10°C)

## Git Workflow

After completing any meaningful unit of work, commit and push changes to GitHub so progress is never lost. Use clear, descriptive commit messages that explain what was done.

```bash
git add <specific-files>
git commit -m "short description of what changed and why"
git push origin main
```

Prefer staging specific files over `git add .` to avoid accidentally committing large outputs or temporary files. A `.gitignore` is in place that excludes `*.xlsx`, `*.png`, and `*.svg` output files — these are generated locally and should not be committed.

## Framework Conventions

- **BioSTEAM** (`import biosteam as bst`) is the primary process simulation framework. Systems are built by instantiating unit operations sequentially, connecting them via streams, then wrapping in `bst.System(path=(...), recycle=(...))`.
- **`atj_baseline`** additionally uses **QSDsan** (`import qsdsan as qs`) — units use `qs.SanStream` instead of `bst.Stream` and sanunits for standard operations.
- **`atj_bst`** and **`lignin_saf`** use pure BioSTEAM with the `biorefineries` package for the cellulosic ethanol sub-system.
- Custom reactor units subclass BioSTEAM's `Unit` and add OPEX via `add_OPEX` for catalyst replacement costs.
- TEA classes subclass BioSTEAM's `TEA`; MJSP/MSP is solved via `tea.solve_price(product_stream)`.
- CEPCI is set globally: `bst.settings.CEPCI = <value>` (541.7 for 2016, 800.8 for 2023).
- **Unit IDs** may only contain letters, numbers, and underscores — no hyphens or spaces (e.g. use `'RCF103_S'` not `'RCF103-S'`). Stream IDs follow the same rule.
- **Do not call `.simulate()` on individual units before assembling a `bst.System`.** Phase assignments that need to persist across recycle iterations should be placed inside `add_specification` decorators, not after standalone simulate calls.
## GitHub Pages site (BELT)

The repo has a documentation site built with MkDocs Material, deployed to `https://h-wadgama.github.io/belt/`.

- Site config: `mkdocs.yml` at the repo root
- Page content: `docs/` folder (Markdown files)
- Auto-deploy: `.github/workflows/docs.yml` triggers on every push to `main` — no manual deploy step needed
- The GitHub repo must be named `belt` (not `ATJ`) for the URL to resolve correctly

### Pages

| File | Page |
|---|---|
| `docs/index.md` | Landing page |
| `docs/getting-started.md` | Installation and quick start |
| `docs/atj-module.md` | ATJ module overview |
| `docs/ligsaf-module.md` | LigSAF module overview |

### Logo

The logo file is `belt-logo-updated.png` (repo root and `docs/`). It appears in:
- The README (GitHub repo main page)
- The MkDocs site header and favicon

`*.png` is globally ignored in `.gitignore`. Logo files need explicit exceptions — currently set as:
```
!belt-logo-updated.png
!docs/belt-logo-updated.png
```
If the logo file is ever renamed, update both the `.gitignore` exceptions and the references in `README.md` and `mkdocs.yml`.

### Local preview

```bash
pip install mkdocs-material
mkdocs serve
```
Then open `http://127.0.0.1:8000`.
