
operating_days = 330


# Process conditions from Bartling et al 2021 unless specified otherwise


# Feed
feed_parameters = {
    'flow' : 2000,                   # [dry metric tons per day], consistent with other TEA models 
    'moisture' : 0.2         # [%] 20% moisture
}


# RCF
rcf_conditions =  {
    'T'       : 225 + 273.15,      # [K]
    'P'       : 63e5,              # [bar]
    'tau_s'   : 3,                 # [hr] Time on stream per solvolysis batch (3 hr total RCF, 1 hr cleaning → 4 hr cycle, 6 batches/reactor/day)
    'tau_s_res': 20/60,             # [hr] Hydraulic residence time of solvent in solvolysis bed (20 min)
    'tau_h'   : 1/3,               # [hr] Hydrogenolysis reaction residence time
    'cat_loading' : 0.1,           # [kg/kg]  1:10 catalyst: dry biomass feed by wt
    'cat_lifetime' : 12,              # [months] Catalyst lifetime from Bartling et al,
    'tau_h' : 1/3                    # [hr] Hydrogenolysis residence time
}


solvent_losses = 0.005

poplar_density = 485               # [kg/m³] Bulk density of poplar chips
free_frac      = 0.10              # [-] Fraction of reactor volume kept free (headspace / gas disengagement)



meoh_h2o = 90                      # [ratio] Solvent : Water ratio (1:1 v/v, 50 vol% MeOH / 50 vol% H2O)
methanol_to_biomass = 9            # [L/kg] from https://doi.org/10.1016/j.copbio.2018.12.005
                                   # Surprisingly, Bartling et al assumes a 9L/kg for a flow through
                                   # configuration which is very less.

# Maximum allowable volume per reactor vessel. N_total is the minimum number of reactors
# such that each vessel stays at or below this limit.
V_max_limit = 600                  # [m³]


h2_consumption = 0.0266             # h2 consumption per kg RCF oil generated. From Webber et al. SI https://www.nature.com/articles/s41563-024-02024-6
h2_pressure = 3e6                   # [Pa] 30 bar hydrogen outlet pressure from PEM electrolysis
h2_rcf_excess = 1.2                 # Excess H2 flowing through the system - completely

solvolysis_parameters = {
    'Cellulose_retention' : 0.9,    # [%] 90% cellulose retained in biomass pulp after RCF
     'Xylose_retention' : 0.93,     # [%] 93% xylose retained in biomass pulp after RCF
     'Extractives_retention' : 0,   # [%] extractives retention in biomass from 10.1039/d1gc01591e Table S1 (no extractives in post-solvolysis poplar).  # Also validated from SI Table S17 of Bartling et al where extractives total amount (kg) in RCF oil is similar to what is in the poplar feed            
     'Acetate_retention' : 0,       # [%] acetate retention in biomass from 10.1039/d1gc01591e Table S1 (no acetate in post-solvolysis poplar)
     'Arabinan_retention' : 0.4,    # [%] Bartling et al
     'Galactan_retention' : 0.5,    # [%] Bartling et al
     'Mannan_retention' : 0.5,      # [%] Bartling et al
     'Delignification' : 0.563,     # [%] 
     'MeOH_CO' : 0.364/100,   # [wt%] methanol lost as CH4. From https://pubs.rsc.org/en/content/articlelanding/2015/cc/c5cc04025f Table 1 where 0.13 mol% of methanol lost as CH4 for Ru/C catalyst
                                    # reactor was batch and hydrogen was fed at 3 MPa within the reactor, also biomass was birchwood, so this might be different in my case
    'MeOH_CH4' :    0.128/100     # [wt%] methanol lost as CH4. From https://pubs.rsc.org/en/content/articlelanding/2015/cc/c5cc04025f Table 1 where 0.08 mol% of methanol lost as CH4 for Ru/C catalyst
                                    # reactor was batch and hydrogen was fed at 3 MPa within the reactor, also biomass was birchwood so this might be different in my case
}




     
h2_biomass_ratio = 0.006029923    # Ratio of mass flow of h2 by the mass flow of dry biomass feed from Bartling et al, SI stream tables (Table S2)




catalyst_loading = 0.1             # 1:10 catalyst: dry biomass feed by wt 

# RCF oil composition

rcf_oil_yield = {
    'Monomers' : 0.5,
    'Dimers' : 0.25,
    'Oligomers' : 0.25
}

condensation_extent = 0.05

# Conditions for the Hydrodeoxygenation reaction to produce cycloalkanes from the monomers by ring hydrogenation + aryl bond cleavaage
hdo_params = {
    'T' : 573.15,        # [C] 300 C from [1][2][5]
    'P': 5e6,            # [Pa] 5 MPa from [1][2][5]
    'tau' : 5,           # [hr] Total 5 hr reaction time [1][2]
    'tau_0' : 1,         # [hr] Assumed time required to cool down the reactor
    'free_frac' : 0.1,   # [%] 10% kept free for gas disengagement / headspace
    'V_max' : 600,       # [m3] Assumed, as was maximum volume in [4]
    'aspect_ratio' : 5,  # Assumed
    'solvent_decomp' : 0.05,
    'solvent_req' : 0.04,    # [m3/kg] From [1]
    'catalyst_req' : 0.8,
    'h2_excess' : 1.5,    # 1.5 x stoichiometric amount of H2 required is fed - Assumed
    'cat_lifetime' : 12    # [months] Catalyst lifetime 
}















##### Conversion factors ########
kg_per_ton = 907.1846 # kg per metric ton
moisture = 0.2

feedstock_price = 80 # USD/dry metric ton from Bartling et al
feedstock_price = feedstock_price/kg_per_ton/(1+moisture)
usd_per_pound = 1.35


# Chemicals from cellulosic ethanol model
# Prices are in 2007 USD (from 2011 Humbird report), and are updated to 2016 USD here 
# Prices are from September since end of fiscal year
# Using Federal Reserve Economic Data (FRED) St. Louis Fed data (accessed 9/17/2025)

sulfuric_acid_price = 0.08972 *  (128.9/174.8)              # [USD/kg] Sulfuric acid price update from https://fred.stlouisfed.org/series/WPU0613020T1
ammonia_price = 0.4486 * (229.7/227.5)                      # [USD/kg] Ammonia price update from https://fred.stlouisfed.org/series/WPU061
cellulase_price = 0.212 * (233.6/180.1)                     # [USD/kg] Cellulase price update from https://fred.stlouisfed.org/series/WPU0679
CSL_price = 0.05682 * (221.3/226.7)                         # [USD/kg] Corn steep liquor price update from https://fred.stlouisfed.org/series/WPU065201. CSL is a nitrogen containing compound
DAP_price = 0.98692 * (221.3/226.7)                         # [USD/kg] DAP price update from https://fred.stlouisfed.org/series/WPU065201. DAP is a nitrogen containing compound
caustic_price = 0.07476 * (135.3/116.6)                     # [USD/kg] Casutic price update from https://fred.stlouisfed.org/series/WPU06130302
denaturant_price = 0.756 * (152.0/225.6)                    # [USD/kg] Denaturant update from https://fred.stlouisfed.org/series/WPU0571. Denaturant is gasoline
cooling_tower_chemicals_price = 3.0 * (155.6/165.0)         # [USD/kg] Cooling tower chemcials update from https://fred.stlouisfed.org/series/PCU325998325998A. cooling tower chemicals are used for water treatment
FOD_lime_price = 0.19938 * (237.5/164.6)                    # [USD/kg] FGD lime update from https://fred.stlouisfed.org/series/WPU06130213
boiler_chemicals_price = 4.99586 * (248.8/189.5)            # [USD/kg] Boiler chemicals update from https://fred.stlouisfed.org/series/WPU0613. Boiler chemicals are ash which is inorganic
hexane_price = (712/1000) * usd_per_pound * (226.6/285.6)   # [USD/kg] Price of 712 pounds per tonne for 2018 from https://doi.org/10.1126%2Fscience.aau1567. Price updated to 2016 USD using https://fred.stlouisfed.org/series/WPU0614
ethyl_acetate_price = 2.5 * usd_per_pound * (226.6/218.9)   # [USD/kg] Price of 2.5 pounds per kg for 2020 from https://doi.org/10.1039%2Fd3ee00965c. Price updated to 2016 USD using https://fred.stlouisfed.org/series/WPU0614
# ethanol_price = 2.15 *   # TODO: complete CEPCI ratio before adding to prices dict
natural_gas_price = 0.264
dodecane_price = 1                                          # [USD/kg] Highly assumed - couldn't get a price for it. 
hdo_cat_price = 158.4                                             # [USD/kg] Same price as Nickel on SIlica Alumina for ETJ oligomerization
h2_price = 3.7                                              # ATR with CCS with compression and truck transport


prices = {
    'Feedstock' : feedstock_price,
    'Methanol' :  0.27455,               # [USD/kg] from Bartling et al
    'Hydrogen' : h2_price,                  # [USD/kg] same as ATJ model
    'NiC_catalyst' : 37.5,              # [USD/kg] from Bartling et al
    'H2SO4' : sulfuric_acid_price,
    'NH3' : ammonia_price,
    'Cellulase' : cellulase_price,
    'CSL' : CSL_price,
    'DAP' : DAP_price,
    'Caustic' : caustic_price,
    'Denaturant' : denaturant_price,
    'CT_chemicals' : cooling_tower_chemicals_price,
    'FOD_lime' : FOD_lime_price,
    'Boiler_chemicals' : boiler_chemicals_price,
    'Hexane' : hexane_price,
    'EthylAcetate': ethyl_acetate_price,
    'CH4' :  natural_gas_price,
    'Dodecane' : dodecane_price,
    'HDO_Cat' : hdo_cat_price

}


# ─────────────────────────────────────────────────────────────────────────────
# RCF Oil Purification — Ethyl Acetate Liquid–Liquid Extraction
# References:
#   Qin et al. 2022, React. Chem. Eng. (10.1039/D2RE00275B)
#   Luo et al. 2024, ACS Sust. Chem. Eng., 12, 12919–12926
# ─────────────────────────────────────────────────────────────────────────────

etoac_purification = {
    'solvent_to_crude_ratio': 1.1,      # [L/kg]  EtOAc volume per kg crude RCF oil (10 mL/g basis from D2RE00275B)
    'etoac_h2o_ratio':        1.0,      # [v/v]   EtOAc : water volume ratio (D2RE00275B)
    'N_stages':               3,        # [-]     number of extraction stages (ACS SCE 2024)
    'EtOAc_recycle_split':    0.95,     # [-]     fraction of EtOAc recovered in centrifuge and recycled
    'oil_flash_T':            400,      # [K]     flash temperature to evaporate residual EtOAc overhead
    'oil_flash_P':            101325,   # [Pa]    flash pressure
}

# Partition coefficients for EtOAc / water LLE
# K = c_extract (EtOAc-rich phase) / c_raffinate (water-rich phase)
# Placeholder values — replace with experimental LLE data when available
# Note: Water K = 0.01 (strongly prefers aqueous raffinate); lignin products K >> 1 (prefer EtOAc)
etoac_partition_IDs = (
    'Water', 'Propylguaiacol', 'Propylsyringol',
    'Syringaresinol', 'G_Dimer', 'S_Oligomer', 'G_Oligomer',
)
etoac_partition_K = (0.01, 200.0, 200.0, 500.0, 109.0, 200.0, 200.0)


# ─────────────────────────────────────────────────────────────────────────────
# Monomer Purification — Hexane Liquid–Liquid Extraction
# Reference: Luo et al. 2021, Science (https://doi.org/10.1126/science.aau1567)
# ─────────────────────────────────────────────────────────────────────────────

hexane_purification = {
    'solvent_to_oil_ratio': 5,       # [kg/kg] hexane mass per kg purified RCF oil
    'water_hexane_ratio':   1,       # [v/v]   water : hexane volume ratio in solvent feed
    'N_stages':             3,       # [-]     number of extraction stages
    'hexane_recycle_split': 0.95,    # [-]     fraction of hexane recovered in centrifuge and recycled
    'oil_flash_T':          400,     # [K]     flash temperature to evaporate hexane from monomer extract
    'oil_flash_P':          101325,  # [Pa]    flash pressure
    'raffinate_flash_T':    400,     # [K]     flash temperature to separate oligomers from raffinate water
    'raffinate_flash_P':    101325,  # [Pa]    flash pressure
}

# Partition coefficients for hexane / water LLE
# K = c_extract (hexane-rich phase) / c_raffinate (water-rich phase)
# Placeholder values — replace with experimental LLE data when available
# NOTE: Water K = 0.01 is a placeholder; physically water strongly prefers the aqueous
#       raffinate (K << 1 expected). Update this when real data are available.
# S_Oligomer, G_Oligomer, G_Dimer, and Syringaresinol are not listed — unlisted components stay in
# the raffinate by default. Syringaresinol is a lignan DIMER (two sinapyl alcohol units linked via
# β–β′ resinol linkage) and is intentionally excluded from the monomer extract.
# Only true monomers (Propylguaiacol, Propylsyringol) partition into the hexane extract.
hexane_partition_IDs = (
    'Water', 'Propylguaiacol', 'Propylsyringol',
)
hexane_partition_K = (0.01, 2.0, 2.0)

price_data = {
    'NG' : natural_gas_price,           # [USD/kg]
    'hydrogen' : h2_price,                  # [USD/kg] for PEM electrolysis. Includes complete value chain costs (production. compression, delivery. Storage accounted for separately through storage tank costs)
    'renewable_naphtha' : 0.71,         # [USD/kg] 
    'renewable_diesel' : 1.888,         # [USD/kg] [2]
    'wastewater_treatment' : 1.85e-3,   # [USD/kg] of standard WW from [1]
    'dehydration_catalyst' : 36.81,     # [USD/kg] 
    'oligomerization_catalyst' : 158.4, # [USD/kg]
    'hydrogenation_catalyst' : 59.12,   # [USD/kg]
    'electricity' : 0.0782              # [USD/kWh]
 }
