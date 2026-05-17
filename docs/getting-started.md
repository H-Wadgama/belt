# Getting Started

## Requirements

- Python 3.10
- conda (Anaconda or Miniconda)
- Git

---

## Installation

### 1. Create and activate a virtual environment

```bash
conda create -n belt python=3.10
conda activate belt
```

### 2. Clone the repository

```bash
git clone https://github.com/H-Wadgama/belt.git
cd belt
```

### 3. Install dependencies

Each module has its own requirements file. Install the one(s) you need:

**For LigSAF:**
```bash
pip install -r lignin_saf/requirements.txt
```

**For ATJ:**
```bash
pip install -r requirements.txt
```

### 4. Install the package in editable mode

```bash
pip install -e .
```

---

## Post-install patch (LigSAF only)

`flexsolve==0.5.9` has an import incompatibility with `scipy==1.11.4`. After installing, apply this one-time fix:

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

Then delete the compiled cache file:

```bash
rm <env>/lib/site-packages/flexsolve/__pycache__/numerical_analysis.cpython-310.pyc
```

Restart your Python kernel or terminal after applying the patch.

---

## Quick start

**Run the ATJ baseline simulation:**
```bash
python -m atj_saf.main
```
This simulates the full ATJ system and prints the Minimum Jet fuel Selling Price (MJSP) in USD/gal.

**Run the LigSAF baseline simulation:**

Open `lignin_saf/rcf_system.ipynb` in VS Code or Jupyter and run cells sequentially.

Alternatively, use one of the entry-point scripts under `scripts/`:

```bash
python scripts/rcf_etoh.py       # RCF + cellulosic ethanol co-product
python scripts/rcf_hdo.py        # RCF + HDO upgrading to propylcyclohexane
python scripts/rcf_etoh_etj.py   # RCF + ethanol + ETJ upgrading to SAF
```
