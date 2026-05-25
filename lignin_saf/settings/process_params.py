
"""Process parameters for a lignin-first biorefinery"""



# ─── Feed ─────────────────────────────────────────────────────────────────────
feed_parameters = {
    'flow'    : 2000,   # [dry metric tons per day], consistent with other TEA models
    'moisture': 0.2,    # [wt fraction] 20% moisture
    'poplar_density' : 485 # [kg/m³] bulk density of poplar chips ADD REFERENCE
}



# ─── RCF reactor conditions ───────────────────────────────────────────────────
solvolysis_params = {
    'T'                     : 225 + 273.15,  # [K]
    'P'                     : 63e5,          # [Pa] 63 bar (Vapor pressure exerted by methanol at the reaction temperature)
    'tau_s'                 : 3,             # [hr] Time on stream per solvolysis batch
    'tau_s_res'             : 20/60,         # [hr] Hydraulic residence time of solvent in bed (20 min)
    'tau_0'                 : 3,             # [hr] Cycle time (tau_s + cleaning window)
    'tau_h'                 : 1/3,           # [hr] Hydrogenolysis hydraulic residence time (20 min)
    'cat_loading'           : 0.1,           # [kg/kg] 1:10 catalyst : dry biomass by weight
    'cat_lifetime'          : 12,            # [months] from Bartling et al
    'Cellulose_retention'   : 0.9,           # [fraction] 90% cellulose retained in pulp after RCF
    'Xylose_retention'      : 0.93,          # [fraction] 93% xylose retained in pulp after RCF
    'Extractives_retention' : 0,             # [fraction] from 10.1039/d1gc01591e Table S1
    'Acetate_retention'     : 0,             # [fraction] from 10.1039/d1gc01591e Table S1
    'Arabinan_retention'    : 0.4,           # [fraction] Bartling et al.
    'Galactan_retention'    : 0.5,           # [fraction] Bartling et al.
    'Mannan_retention'      : 0.5,           # [fraction] Bartling et al.
    'Delignification'       : 0.563,         # [fraction]
    'MeOH_CO'               : 0.364/100,     # [wt frac] MeOH lost as CO  — from https://pubs.rsc.org/en/content/articlelanding/2015/cc/c5cc04025f Table 1
    'MeOH_CH4'              : 0.128/100,     # [wt frac] MeOH lost as CH₄ — same source; Ru/C catalyst, birchwood biomass
    'solvent_losses'        : 0.01,          # Solvent loss in pulp fraction after RCF - assumed
    'free_frac'             : 0.1,           # fraction of reactor volume kept free
    'V_max'                 : 600            # [m³]  From Bartling et al 
        
}

meoh_h2o             = 90          # [v/v ratio] solvent : water (50 vol% MeOH / 50 vol% H₂O → ratio of 90 w/w?)
h2_biomass_ratio  = 0.006029923     # [kg H₂/kg dry biomass] from Bartling et al. SI Table S2
h2_rcf_excess  = 1.2                # excess H₂ flowing through the system


hydrogenolysis_params = {
    'h2_consumption'        : 0.0266,       # [kg H₂/kg RCF oil] from Webber et al. SI  https://www.nature.com/articles/s41563-024-02024-6
    'duty'                  : 60.5,         # 49–72 kcal mol–1 energy required for B-0-4 bond cleavage. https://www.nature.com/articles/s41563-024-02024-6
    'condensation_extent'   : 0.136         # fraction of monomer fraction that re-polymerises during hydrogenolysis
}

# ─── RCF oil composition ─────────────────────────────────────────────────────
rcf_oil_yield = {
    'Monomers' : 0.5,
    'Dimers'   : 0.25,
    'Oligomers': 0.25,
}



# ─── HDO reactor conditions ───────────────────────────────────────────────────
hdo_params = {
    'T'              : 573.15,  # [K] 300°C from [1][2][5]
    'P'              : 5e6,     # [Pa] 5 MPa from [1][2][5]
    'tau'            : 5,       # [hr] Total reaction time from [1][2]
    'tau_0'          : 1,       # [hr] Assumed cool-down / turn-around time
    'free_frac'      : 0.1,     # [-] 10% headspace / gas disengagement
    'V_max'          : 600,     # [m³] maximum vessel volume (assumed, same as RCF)
    'aspect_ratio'   : 5,       # [-] L/D (assumed)
    'solvent_decomp' : 0.05,    # [-] fraction of solvent that decomposes per pass
    'solvent_req'    : 0.04,    # [m³/kg monomer feed] from [1]
    'catalyst_req'   : 0.8,     # [kg/kg monomer feed]
    'h2_excess'      : 1.5,     # [-] 1.5× stoichiometric H₂ fed (assumed)
    'cat_lifetime'   : 12,      # [months] catalyst lifetime
}


# ─── RCF oil purification — EtOAc liquid–liquid extraction ───────────────────
# References:
#   [1] J. H, Jang, et al.,  "Multi-pass flow-through reductive catalytic fractionation." Joule. (2022) 6(8), 1859-1875. https://doi.org/10.1016/j.joule.2022.06.016
etoac_purification = {
    'solvent_to_crude_ratio': 9.1,     # [L/kg] EtOAc per kg crude RCF oil,  from [1]
    'etoac_h2o_ratio'       : 1.0,     # [v/v]  EtOAc : water in solvent feed,from [2]
    'N_stages'              : 3,       # [-]    extraction stages — doesn't matter though since separation is assumed to be perfect
    'EtOAc_recycle_split'   : 0.95,    # [-]    fraction of EtOAc recovered in centrifuge
    'oil_flash_T'           : 400,     # [K]    flash temperature to evaporate EtOAc overhead
    'oil_flash_P'           : 101325,  # [Pa]   flash pressure
}

# Partition coefficients: K = c_extract (EtOAc-rich) / c_raffinate (water-rich)
# Placeholder values — replace with experimental LLE data when available
etoac_partition_IDs = (
    'Water', 'Propylguaiacol', 'Propylsyringol',
    'Syringaresinol', 'G_Dimer', 'S_Oligomer', 'G_Oligomer',
)
etoac_partition_K = (0.01, 200.0, 200.0, 500.0, 109.0, 200.0, 200.0)


# ─── Monomer purification — hexane liquid–liquid extraction ──────────────────
# Reference: Luo et al. 2021, Science https://doi.org/10.1126/science.aau1567
hexane_purification = {
    'solvent_to_oil_ratio' : 3.5,     # [kg/kg]  hexane mass per kg purified RCF oil
    'water_hexane_ratio'   : 1,       # [v/v]    water : hexane volume ratio in solvent feed
    'N_stages'             : 3,       # [-]      extraction stages
    'hexane_recycle_split' : 0.95,    # [-]      fraction of hexane recovered in centrifuge
    'oil_flash_T'          : 400,     # [K]      flash T to evaporate hexane from monomer extract
    'oil_flash_P'          : 101325,  # [Pa]     flash pressure
    'raffinate_flash_T'    : 400,     # [K]      flash T to separate oligomers from raffinate water
    'raffinate_flash_P'    : 101325,  # [Pa]     flash pressure
}

# Partition coefficients: K = c_extract (hexane-rich) / c_raffinate (water-rich)
# Placeholder values — replace with experimental LLE data when available.
# Syringaresinol (dimer), G_Dimer, S_Oligomer, G_Oligomer are intentionally
# unlisted so they remain in the aqueous raffinate (→ WWT), not the monomer extract.
hexane_partition_IDs = (
    'Water', 'Propylguaiacol', 'Propylsyringol',
)
hexane_partition_K = (0.01, 2.0, 2.0)
