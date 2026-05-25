
""" Price data for lignin-first biorefinery updated to 2025/2026 """


# ─── Unit conversion factors ─────────────────────────────────────────────────
kg_per_ton    = 907.1846    # [kg / short ton]
usd_per_pound = 1.35        # [USD / lb]
mj_per_btu    = 0.00105506  # [MJ / BTU]


# ─── Feedstock ───────────────────────────────────────────────────────────────
_feedstock_price_dry_ton = 70           # [USD / dry short ton] from Bartling et al.
_moisture                = 0.2          # [wt fraction] moisture content of as-received biomass
moisture                 = _moisture    # exported alias used in feedstock_price calc
feedstock_price = _feedstock_price_dry_ton / kg_per_ton / (1 + _moisture)  # [USD/kg wet]


# ─── Cost updates ────────────────────────────────────────────
# Prices from Humbird 2011 (2007 USD base) were updated to 2016 first for comparison with Bartling et al baseline
# This update used specific chemical indexes for the chemicals
# The prices were then updated to 2025/2026 using a general PPI (All Commodities PPIACO) from FRED (St. Louis Fed)

sep_2016 = 186.9    # PPI, Sep 2016 
jan_2026 = 263.53   # PPI, Jan 2026 


# ─── Cellulosic ethanol chemicals (Humbird 2011 base prices) ─────────────────
# Base prices are in 2007 USD from Table B.2 of the Humbird 2011 NREL report.
# Each price uses its own FRED series for escalation (index_current / index_base).
# Series IDs are listed after each line for traceability.

sulfuric_acid_price           = 0.08972  * (128.9/174.8) * (jan_2026/sep_2016)
# [USD/kg]  FRED series: WPU0613020T1 (Sulfuric acid)

ammonia_price                 = 0.4486   * (229.7/227.5) * (jan_2026/sep_2016)
# [USD/kg]  FRED series: WPU061 (Industrial chemicals)

cellulase_price               = 0.212    * (233.6/180.1) * (jan_2026/sep_2016)
# [USD/kg]  FRED series: WPU0679 (Biological products)

CSL_price                     = 0.05682  * (221.3/226.7) * (jan_2026/sep_2016)
# [USD/kg]  FRED series: WPU065201 (Nitrogenous fertilizers — proxy for corn steep liquor)

DAP_price                     = 0.98692  * (221.3/226.7) * (jan_2026/sep_2016)
# [USD/kg]  FRED series: WPU065201 (Nitrogenous fertilizers — proxy for DAP)

caustic_price                 = 0.07476  * (135.3/116.6) * (jan_2026/sep_2016)
# [USD/kg]  FRED series: WPU06130302 (Sodium hydroxide / caustic soda)

denaturant_price              = 0.756    * (152.0/225.6) * (jan_2026/sep_2016)
# [USD/kg]  FRED series: WPU0571 (Petroleum refinery products — proxy for gasoline denaturant)

cooling_tower_chemicals_price = 3.0      * (155.6/165.0) * (jan_2026/sep_2016)
# [USD/kg]  FRED series: PCU325998325998A (Specialty chemicals)

FOD_lime_price                = 0.19938  * (237.5/164.6) * (jan_2026/sep_2016)
# [USD/kg]  FRED series: WPU06130213 (Lime)

boiler_chemicals_price        = 4.99586  * (248.8/189.5) * (jan_2026/sep_2016)
# [USD/kg]  FRED series: WPU0613 (Industrial inorganic chemicals — proxy for boiler treatment)


# ─── RCF-specific chemicals ───────────────────────────────────────────────────
hexane_price        = 1178   / 1000     # [USD/kg] 1178 USD/MT price for January 2026 from https://www.procurementresource.com/resource-center/hexane-price-trends
ethyl_acetate_price = 777    / 1000     # [USD/kg] Price of $777/MT was reported for Sep 2025. so this is used https://www.intratec.us/solutions/primary-commodity-prices/commodity/ethyl-acetate-prices
dodecane_price      = 502.33 / 1000     # [USD/kg] LAO price from https://www.chemanalyst.com/Pricing-data/linear-alpha-olefin-1103. for quarter ending March 2026. Should be higher than normal 
hdo_cat_price       = 158.4             # [USD/kg] Ni₂P/SiO₂ — same price as Ni/SiAl for ETJ oligomerization
methanol_price      = 331    / 1000     # [USD/kg] 331 USD/tonne was 4th quarter of 2025 price from https://www.methanex.com/news/release/methanex-reports-fourth-quarter-2025-results/


# ─── Hydrogen ────────────────────────────────────────────────────────────────
h2_price = 2.3 + 1.1 + 0.3           # ATR with CCS with compression and truck transport


# ─── Natural gas ─────────────────────────────────────────────────────────────
natural_gas_HHV   = 55                                    # [MJ/kg] https://group.met.com/en/media/energy-insight/calorific-value-of-natural-gas/
natural_gas_price = 3.52 / 1e6 / mj_per_btu              # [USD/MJ] Jan 2025 Henry Hub — EIA https://www.eia.gov/dnav/ng/hist/rngwhhdA.htm
nautral_gas_price = natural_gas_price * natural_gas_HHV   # [USD/kg] NOTE: typo in name preserved for backward compatibility


# ─── Co-products ─────────────────────────────────────────────────────────────
biodiesel_price = (3.74 * 264.172) / 773.94               # [USD/kg] derived from USD/gal https://afdc.energy.gov/fuels/prices.html


# ─── Consolidated price dictionaries ─────────────────────────────────────────
# `prices`     — feedstocks and chemicals consumed by the RCF + cellulosic ethanol system
# `price_data` — co-product prices and utility rates for the ETJ / HDO extended system

prices = {
    'Feedstock'        : feedstock_price,
    'Methanol'         : methanol_price,
    'Hydrogen'         : h2_price,
    'NiC_catalyst'     : 37.5,                      # [USD/kg] from Bartling et al.
    'H2SO4'            : sulfuric_acid_price,
    'NH3'              : ammonia_price,
    'Cellulase'        : cellulase_price,
    'CSL'              : CSL_price,
    'DAP'              : DAP_price,
    'Caustic'          : caustic_price,
    'Denaturant'       : denaturant_price,
    'CT_chemicals'     : cooling_tower_chemicals_price,
    'FOD_lime'         : FOD_lime_price,
    'Boiler_chemicals' : boiler_chemicals_price,
    'Hexane'           : hexane_price,
    'EthylAcetate'     : ethyl_acetate_price,
    'CH4'              : nautral_gas_price,          # USD/kg natural gas
    'Dodecane'         : dodecane_price,
    'HDO_Cat'          : hdo_cat_price,
    'NG'                       : natural_gas_price,  # [USD/MJ]
    'hydrogen'                 : h2_price,            # [USD/kg]
    'renewable_naphtha'        : 0.57,                # [USD/kg] price for 2025 https://report.basf.com/2025/en/combined-managements-report/basf-groups-business-year/economic-environment/key-commodities.html
    'renewable_diesel'         : biodiesel_price,     # [USD/kg]
    'wastewater_treatment'     : 1.85e-3,             # [USD/kg] standard WW — Humbird 2011 
    'dehydration_catalyst'     : 36.81,               # [USD/kg]
    'oligomerization_catalyst' : 158.4,               # [USD/kg]
    'hydrogenation_catalyst'   : 59.12,               # [USD/kg]
    'electricity'              : 0.0826,              # [USD/kWh] US industrial average, March 2025  https://www.eia.gov/electricity/monthly/epm_table_grapher.php?t=epmt_5_6_a
}

