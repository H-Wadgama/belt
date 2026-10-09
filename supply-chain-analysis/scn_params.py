"""Local, editable feedstock & process parameters for the supply-chain-analysis manuscript.

Kept separate from lignin_saf/settings/process_params.py and lignin_saf/settings/prices.py
so varying flow, moisture, poplar density, and feedstock price here never touches the
parameters other analyses in the repo rely on. Everything else (chemical/utility prices,
RCF/HDO/TEA parameters, etc.) is reused as-is from lignin_saf.settings.
"""

from lignin_saf.settings.prices import prices as _base_prices, kg_per_ton

# ─── Feed parameters (local copy of lignin_saf/settings/process_params.py: feed_parameters) ──
# Vary these for the supply-chain scale analysis.
feed_parameters = {
    'flow'           : 2000,  # [dry metric tons per day]
    'moisture'       : 0.2,   # [wt fraction] moisture content of as-received biomass
    'poplar_density' : 485,  # [kg/m3] bulk density of poplar chips
}

# ─── Feedstock price (local copy of the calc in lignin_saf/settings/prices.py) ────────────────
# Vary this to explore the feedstock-sourcing-distance vs. demand relationship.
feedstock_price_dry_ton = 79.17  # [USD / dry short ton]
feedstock_price = feedstock_price_dry_ton / kg_per_ton / (1 + feed_parameters['moisture'])  # [USD/kg wet]

# ─── Prices dict: all other prices reused from lignin_saf.settings.prices; Feedstock overridden ─
prices = dict(_base_prices)
prices['Feedstock'] = feedstock_price
