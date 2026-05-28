from biosteam import main_flowsheet as F
import biosteam as bst
import thermosteam as tmo
import pandas as pd
import numpy as np


from lignin_saf.ligsaf_chemicals import create_chemicals
from lignin_saf.settings.process_params import feed_parameters, solvolysis_params, hydrogenolysis_params, hdo_params, etoac_purification, hexane_purification, rcf_oil_yield
from lignin_saf.settings.prices import prices,  _feedstock_price_dry_ton, kg_per_ton, h2_price
from lignin_saf.settings.tea_params import operating_days, labor
from lignin_saf.systems.rcf import create_rcf_system
from lignin_saf.systems.rcf_oil_purification import create_rcf_oil_purification_system
from lignin_saf.systems.monomer_purification import create_monomer_purification_system
from lignin_saf.systems.hdo import create_hdo_system
from lignin_saf.systems.cellulosic_ethanol_no_preatreatment import create_cellulosic_ethanol_system
from atj_saf.atj_bst.etj_ligfirst import create_etj_system_no_facilities
from lignin_saf.cellulosic_tea import create_cellulosic_ethanol_tea

from lignin_saf.ligsaf_units import HydrogenStorageTank


chems = create_chemicals()
bst.settings.set_thermo(chems)
bst.settings.CEPCI = 840   # 2026 basis. CEPCI 
bst.settings.electricity_price = prices['electricity']

# Poplar group must be defined before creating any stream that references it
chems.define_group(
    name='Poplar',
    IDs=['Glucan', 'Xylan', 'Arabinan', 'Mannan', 'Galactan',
         'Sucrose', 'Lignin', 'Acetate', 'Extract', 'Ash'],
    composition=[0.464, 0.134, 0.002, 0.037, 0.014,
                 0.001, 0.285, 0.035, 0.016, 0.012],
    wt=True
)

poplar_in = bst.Stream('Poplar_In',
                       Poplar=feed_parameters['flow'] * 1e3,
                       Water=feed_parameters['moisture'] * feed_parameters['flow'] * 1e3,
                       phase='l', units='kg/d', price=prices['Feedstock'])

# ── Area 200: RCF process ──────────────────────────────────────────────────
rcf_system = create_rcf_system(ins=poplar_in)
rcf_system.simulate()

# ── Area 300: Purification ─────────────────────────────────────────────────
rcf_oil_purification_sys = create_rcf_oil_purification_system(ins=F.RCF_CRUDE_OUT)
monomer_purification_sys = create_monomer_purification_system(ins=F.PURE_OIL_OUT)
rcf_oil_purification_sys.simulate()
monomer_purification_sys.simulate()

# ── Area 400: Hydrodeoxygenation ───────────────────────────────────────────
hdo_system = create_hdo_system(ins=F.MON_MONOMERS_OUT)
hdo_system.simulate()

etoh_system = create_cellulosic_ethanol_system(ins=F.Carbohydrate_Pulp, add_denaturant=False)
etoh_system.simulate()

# No pretreatment_wastewater — only S401 stillage filtrate goes to WWT.
etoh_ww     = [F.unit.S401.outs[1]]
etoh_solids = [F.unit.S401.outs[0]]

# Removing the NH3 fraction of the ethanol output - in the future CBP will remove this anyways, so I've just modelled it as a splitter
nh3_splitter = bst.units.Splitter(ins = F.T703.outs[0], split = {'NH3':1.0} )
nh3_splitter.simulate()

# Ethanol to Jet system
etj_system = create_etj_system_no_facilities(ins = nh3_splitter.outs[1])
etj_system.simulate()


WWT = bst.create_conventional_wastewater_treatment_system('WWT', ins=[F.WW_10, F.WastePulp, F.RCF_WW_OUTS, F.WW_11, F.WW_12, F.HDO_WW, F.HDO_wash_water, F.ETJ_WW_OUTS] + etoh_ww)

for unit in WWT.units:
    if hasattr(unit, 'strict_moisture_content'):
        unit.strict_moisture_content = False

F.unit.PWC.ins[0] = WWT.outs[2]

solids_to_BT = bst.Mixer('MIX_BT_solids', ins=[WWT.outs[1]] + etoh_solids)


BT = bst.facilities.BoilerTurbogenerator('BT', fuel_price=prices['CH4'])


gas_mixer= bst.Mixer('MIX_BT_gas', ins=(WWT.outs[0], F.RCF_PSAWASTE_OUTS, F.HDO_purge_gases, F.ETJ_PSAWASTE_OUTS))

BT.ins[0] = solids_to_BT.outs[0]  # Connecting sludge to BT solids feed
BT.ins[1] = gas_mixer.outs[0]   # Connecting biogas from WW treatment and PSA waste gases from RCF


combined_saf = bst.units.Mixer(ins = (F.ETJ_SAF_OUT, F.HDO_CYCLOALKANES_OUT), outs = 'TOTAL_SAF', rigorous = True)

h2_rcf = bst.Stream()
h2_rcf.copy_like(F.RCF_H2_IN)

h2_hdo = bst.Stream()
h2_hdo.copy_like(F.HDO_H2_IN)

h2_etj = bst.Stream()
h2_etj.copy_like(F.ETJ_H2_IN)

# Shared H2 storage — sized from combined ETJ + HDO fresh H2 demand
h2_feed_mixer = bst.Mixer('H2_FEED_MIX', ins=(h2_rcf, h2_hdo, h2_etj))
shared_h2_storage = HydrogenStorageTank('H2_TK', ins=h2_feed_mixer.outs[0])


rcf_pure_mon_hdo_etoh_etj_system = bst.System(
    'RCF+HDO+Cellulosic_ETJ',
    path=(rcf_system, rcf_oil_purification_sys, monomer_purification_sys, hdo_system, etoh_system, nh3_splitter, etj_system, combined_saf, WWT),
    facilities=[solids_to_BT, gas_mixer, h2_feed_mixer, shared_h2_storage, BT],
)

rcf_pure_mon_hdo_etoh_etj_system.simulate()

F.ETJ_H2_IN.price = prices['hydrogen']   # 8.46 USD/kg
F.ETJ_RN_OUT.price = prices['renewable_naphtha']   # 0.71 USD/kg
F.ETJ_RD_OUT.price = prices['renewable_diesel']    # 1.888 USD/kg
#F.sulfuric_acid.price = prices['H2SO4']
#F.ammonia.price = prices['NH3']
F.cellulase.price = prices['Cellulase'] 
F.CSL.price = prices ['CSL'] 
F.DAP.price = prices['DAP'] 
F.caustic.price = prices['Caustic']
F.denaturant.price =  prices['Denaturant'] 
F.cooling_tower_chemicals.price = prices['CT_chemicals'] 
#F.FGD_lime.price = prices['FOD_lime']
#F.boiler_chemicals.price = prices['Boiler_chemicals'] 


integrated_tea = create_cellulosic_ethanol_tea(rcf_pure_mon_hdo_etoh_etj_system)

integrated_tea.labor_cost = labor
integrated_tea.operating_days = 330
mjsp = round(((integrated_tea.solve_price(F.TOTAL_SAF)*F.TOTAL_SAF.rho)/264.172),2)

# print(f'The MSP for SAF blend is  {mjsp} USD/gal')

model = bst.Model(rcf_pure_mon_hdo_etoh_etj_system)

from chaospy import distributions as shape
param = model.parameter

var_50 = 0.5 # 50% variation in parameters - set for a few
var_20 = 0.2 # 20% variation in other parameters


# Operating days — kind='isolated': only affects TEA time scaling, not mass/energy balance
dist = shape.Uniform(lower = 297 , upper = 363)
@param(name = 'Operating days',
    element = 'Overall',
    kind = 'isolated',
    units = 'days',
    baseline = integrated_tea.operating_days,
    distribution = dist)
def set_opertaing_days(i):
    integrated_tea.operating_days = i


# Poplar feedstock
dist = shape.Uniform(lower = 50 , upper = 100)
@param(name = 'Poplar feedstock price',
    element = 'Overall',
    kind = 'isolated',
    units = 'USD/DMT',
    baseline = _feedstock_price_dry_ton,
    distribution = dist)
def set_poplar_feedstock_price(i):
    # i is in USD/dry short ton; stream price must be USD/kg wet biomass
    F.Poplar_In.price = i / kg_per_ton / (1 + feed_parameters['moisture'])



# Labor cost
dist = shape.Uniform(lower = integrated_tea.labor_cost * (1-var_50) , upper = integrated_tea.labor_cost * (1+var_50) )
@param(name = 'Labor cost',
    element = 'Overall',
    kind = 'isolated',
    units = 'USD/yr',
    baseline = integrated_tea.labor_cost,
    distribution = dist)
def set_labor_cost(i): 
    integrated_tea.labor_cost = i


# Renewable napthha co-product revenue
dist = shape.Uniform(lower = 0.505 , upper = 0.77)
@param(name = 'RN co-product credit',
    element = 'Overall',
    kind = 'isolated',
    units = 'USD/kg',
    baseline =  F.ETJ_RN_OUT.price,
    distribution = dist)
def set_renewable_naptha_price(i): 
    F.ETJ_RN_OUT.price = i            


# Biodiesel co-product revenue
dist = shape.Uniform(lower = 0.63 , upper = 1.48)
@param(name = 'RD co-product credit',
       element = 'Overall',
       kind = 'isolated',
       units = 'USD/kg',
       baseline =  F.ETJ_RD_OUT.price,
       distribution = dist)
def set_bio_diesel_price(i): 
     F.ETJ_RD_OUT.price = i


# Hydrogen price
dist = shape.Uniform(lower = 2.74 , upper = 11.53)
@param(name = 'Hydrogen price',
       element = 'Overall',
       kind = 'isolated',
       units = 'USD/kg',
       baseline =  h2_price,
       distribution = dist)
def set_hydrogen_price(i):
    F.ETJ_H2_IN.price = i
    F.RCF_H2_IN.price = i
    F.HDO_H2_IN.price = i


# Hydrogen storage time
dist = shape.Uniform(lower = 0.25 , upper = 3)
@param(name = 'Hydrogen storage period',
       element = 'Overall',
       kind = 'isolated',
       units = 'days',
       baseline =  F.H2_TK.storage_period,
       distribution = dist)
def set_h2_storage_period(i):
    F.H2_TK.storage_period = i
    F.H2_TK.simulate()   # re-runs _design()/_cost() so CAPEX updates for solve_price()


# Solvolysis pressure
dist = shape.Uniform(lower = solvolysis_params['P'],  upper = 83.3e5)
@param(name = 'Solvolysis reactor pressure',
    element = 'RCF', 
    kind = 'coupled',
    units = 'Pa',
    baseline = solvolysis_params['P'], distribution = dist)
def set_solvolysis_rxr_pressure(i):
    F.RCF_RXR1.P = i  



# Solvolysis reaction time
dist = shape.Uniform(lower = 1, upper = 4)
@param(name = 'Solvolysis reaction time',
    element = 'RCF', 
    kind = 'coupled',
    units = 'hr',
    baseline = solvolysis_params['tau_s'], distribution = dist)
def set_solvolysis_reaction_time(i):
    F.RCF_RXR1.tau = i      


# Solvolysis residence time
dist = shape.Triangle(lower = 9/60, midpoint = solvolysis_params['tau_s_res'], upper = 36/60) 
@param(name = 'Solvolysis residence time',
    element = 'RCF', 
    kind = 'coupled',
    units = 'hr',
    baseline = solvolysis_params['tau_s_res'], distribution = dist)
def set_solvolysis_residence_time(i):
    F.RCF_RXR1.tau_residence = i  


# Solvolysis cleaning time
dist = shape.Uniform(lower = 0.5, upper = 4) 
@param(name = 'Solvolysis cleaning time',
    element = 'RCF', 
    kind = 'coupled',
    units = 'hr',
    baseline = F.RCF_RXR1.tau_0, distribution = dist)
def set_solvolysis_cleaning_time(i):
    F.RCF_RXR1.tau_0 = i  


# Methanol price
dist = shape.Triangle(lower = 0.2648, midpoint = F.RCF_MEOH_IN.price, upper = 0.3972)
@param(name = 'Methanol cost',
    element = 'RCF', 
    kind = 'isolated',
    units = 'USD/kg',
    baseline = F.RCF_MEOH_IN.price, distribution = dist)
def set_methanol_price(i):
    F.RCF_MEOH_IN.price = i  

dist = shape.Uniform(lower=0.005, upper=0.1)
@param(name='RCF solvent losses',
       element='RCF',
       kind='coupled',
       units='-',
       baseline=solvolysis_params['solvent_losses'],
       distribution=dist)
def set_solvent_losses(i):
    solvolysis_params['solvent_losses'] = i


# RCF catalyst cost 
dist = shape.Uniform(lower = F.RCF_CAT_IN.price * (1-var_50) , upper = F.RCF_CAT_IN.price * (1+var_50) ) 
@param(name = 'RCF catalyst price',
    element = 'RCF', 
    kind = 'isolated',
    units = 'USD/kg',
    baseline = F.RCF_CAT_IN.price, distribution = dist)
def set_rcf_catalyst_price(i):
    F.RCF_CAT_IN.price = i      



# RCF catalyst lifetime 
dist = shape.Uniform(lower = solvolysis_params['cat_lifetime']*(1-var_50), upper = solvolysis_params['cat_lifetime']*(1+var_50) ) 
@param(name = 'RCF catalyst lifetime',
    element = 'RCF', 
    kind = 'isolated',
    units = 'months',
    baseline = solvolysis_params['cat_lifetime'], distribution = dist)
def set_rcf_catalyst_lifetime(i):
    solvolysis_params['cat_lifetime'] = i
    F.RCF_CAT_IN.imass['NiC'] = (
        solvolysis_params['cat_loading'] * (feed_parameters['flow'] * 1e3 / 24) * solvolysis_params['tau_h']
    ) / (i * 30 * 24)   # [kg/hr]


# RCF catalyst loading 
dist = shape.Uniform(lower = solvolysis_params['cat_loading'] * (1-var_50) , upper = solvolysis_params['cat_loading'] * (1+var_50) ) 
@param(name = 'RCF catalyst loading',
    element = 'RCF', 
    kind = 'isolated',
    units = 'kg/kg-biomass',
    baseline = solvolysis_params['cat_loading'], distribution = dist)
def set_rcf_catalyst_loading(i):
    solvolysis_params['cat_loading'] = i 
    F.RCF_CAT_IN.imass['NiC'] = (
        i * (feed_parameters['flow'] * 1e3 / 24) * solvolysis_params['tau_h']
    ) / (solvolysis_params['cat_lifetime'] * 30 * 24)   # [kg/hr]

# Cellulose retention
dist = shape.Uniform(lower=0.8, upper=1.0)
@param(name='Cellulose retention',
       element='RCF',
       kind='coupled',
       units='%',
       baseline=solvolysis_params['Cellulose_retention'],
       distribution=dist)
def set_cellulose_retention(i):
    solvolysis_params['Cellulose_retention'] = i


# Xylose retention
dist = shape.Uniform(lower=0.2, upper=1.0)
@param(name='Xylose retention',
       element='RCF',
       kind='coupled',
       units='%',
       baseline=solvolysis_params['Xylose_retention'],
       distribution=dist)
def set_xylose_retention(i):
    solvolysis_params['Xylose_retention'] = i


# Delignification
dist = shape.Uniform(lower = 0.4 , upper = 0.9)
@param(name = 'Delignfication',
       element = 'RCF',
       kind = 'coupled',
       units = '%',
       baseline = solvolysis_params['Delignification'], distribution = dist)
def set_delignfication(i):
    solvolysis_params['Delignification'] = i
    F.RCF_RXR1.reaction_1.X = i   # reaction X is baked in at create_rcf_system() time; must update directly


# Condensation extent
dist = shape.Uniform(lower = 0.136 , upper = 0.709)
@param(name = 'Condensation extent',
       element = 'RCF',
       kind = 'coupled',
       units = '%',
       baseline = hydrogenolysis_params['condensation_extent'], distribution = dist)
def set_condensation_extent(i):
    _X_scale = 1.0 - 1e-6
    hydrogenolysis_params['condensation_extent'] = i
    # X values are baked into the ParallelReaction at create_rcf_system() time; must update directly.
    # Reactions 0 & 1: Propylguaiacol/Propylsyringol (monomers that escaped condensation).
    # Reactions 4 & 5: S_Oligomer/G_Oligomer (baseline oligomers + condensed monomer fraction).
    F.RCF_RXR2.reaction[0].X = _X_scale * rcf_oil_yield['Monomers'] * 0.5 * (1 - i)
    F.RCF_RXR2.reaction[1].X = _X_scale * rcf_oil_yield['Monomers'] * 0.5 * (1 - i)
    F.RCF_RXR2.reaction[4].X = _X_scale * (rcf_oil_yield['Oligomers'] * 0.5 + rcf_oil_yield['Monomers'] * 0.5 * i)
    F.RCF_RXR2.reaction[5].X = _X_scale * (rcf_oil_yield['Oligomers'] * 0.5 + rcf_oil_yield['Monomers'] * 0.5 * i)






# HDO Reaction time 
dist = shape.Uniform(lower = 2,  upper = 8)
@param(name = 'HDO reaction time',
    element = 'HDO', 
    kind = 'coupled',
    units = 'hr',
    baseline = hdo_params['tau'], distribution = dist)
def set_hdo_reaction_time(i):
    F.HDO_RXR1.tau = i  

# Solvent loading
dist = shape.Uniform(lower=0.1, upper=0.4)
@param(name='HDO solvent loading',
       element='HDO',
       kind='coupled',
       units='m3/kg monomer',
       baseline=hdo_params['solvent_req'],
       distribution=dist)
def set_hdo_solvent_req(i):
    hdo_params['solvent_req'] = i    

# Catalyst loading
dist = shape.Uniform(lower=hdo_params['catalyst_req'] * (1-var_50), upper=hdo_params['catalyst_req'] * (1+var_50))
@param(name='HDO catalyst loading',
       element='HDO',
       kind='coupled',
       units='kg/kg monomer',
       baseline=hdo_params['catalyst_req'],
       distribution=dist)
def set_hdo_catalyst_req(i):
    hdo_params['catalyst_req'] = i


# Catalyst lifetime
dist = shape.Uniform(lower = 1, upper = 12) 
@param(name = 'HDO catalyst lifetime',
    element = 'HDO', 
    kind = 'isolated',
    units = 'months',
    baseline = hdo_params['cat_lifetime'], distribution = dist)
def set_hdo_catalyst_lifetime(i):
    hdo_params['cat_lifetime'] = i   # was 'catalyst_lifetime' — wrong key, never updated the real value
    # kind='isolated': dodecane_flow spec never runs, so update the stream directly (same pattern as RCF catalyst lifetime)
    F.HDO_CAT_IN.imass['Ni2PSiO2'] = (
        hdo_params['catalyst_req'] * F.MON_MONOMERS_OUT.F_mass * hdo_params['tau']
    ) / (i * 30 * 24)


# Dodecane price
dist = shape.Uniform(lower = 0.1 ,upper = 0.9)
@param(name = 'Dodecane cost',
    element = 'HDO', 
    kind = 'isolated',
    units = 'USD/kg',
    baseline = F.HDO_DODECANE_IN.price, distribution = dist)
def set_dodecane_in(i):
    F.HDO_DODECANE_IN.price = i  

# Glucose to ethanol conversion
dist = shape.Uniform(lower = 0.8,  upper = 0.95)
@param(name = 'Glucose to ethanol conv.',
    element = 'EHF', 
    kind = 'coupled',
    units = '-',
    baseline = F.R303.cofermentation[0].X, distribution = dist)
def set_glucose_to_ethanol_conv(i):
    F.R303.cofermentation[0].X = i  

# Glucan to glucose conversion 
dist = shape.Uniform(lower = 0.8,  upper = 0.9)
@param(name = 'Glucan to glucose conv.',
    element = 'EHF', 
    kind = 'coupled',
    units = '-',
    baseline = F.R303.saccharification[2].X, distribution = dist)
def set_glucan_to_glucose_conv(i):
    F.R303.saccharification[2].X = i  


# Saccharification residence time
dist = shape.Uniform(lower = 60 * (1-var_20),  upper = 60 * (1+var_20))
@param(name = 'Saccharification residence time',
    element = 'EHF', 
    kind = 'coupled',
    units = 'hr',
    baseline = F.R303.tau_saccharification, distribution = dist)
def set_saccharification_tau(i):
    F.R303.tau_saccharification = i  

# Cofermentation residence time
dist = shape.Uniform(lower = 36 * (1-var_20),  upper = 36 * (1+var_20))
@param(name = 'Cofermentation residence time',
    element = 'EHF', 
    kind = 'coupled',
    units = 'hr',
    baseline = F.R303.tau_cofermentation, distribution = dist)
def set_cofermentation_tau(i):
    F.R303.tau_cofermentation = i  


# Xylose to ethanol conversion
dist = shape.Uniform(lower = 0.8, upper = 0.9)
@param(name = 'Xylose to ethanol conv.',
    element = 'EHF', 
    kind = 'coupled',
    units = '-',
    baseline = F.R303.cofermentation[4].X, distribution = dist)
def set_xylose_to_ethanol_conv(i):
    F.R303.cofermentation[4].X = i      

# Xylan to xylose conversion
dist = shape.Uniform(lower=0.8, upper=0.9)
@param(name='Xylan to xylose conversion',
       element='Cellulosic ethanol',
       kind='coupled',
       units='-',
       baseline=F.unit.R301.reactions[0].X,
       distribution=dist)
def set_xylan_to_xylose_conversion(i):
    F.unit.R301.reactions[0].X = i



# Cellulase enzyme loading
dist = shape.Uniform(lower = 0.01, upper = 0.05)
@param(name = 'Cellulase enzyme loading',
    element = 'EHF', 
    kind = 'coupled',
    units = 'wt%',
    baseline = F.M301.enzyme_loading, distribution = dist)
def set_enzyme_loading(i):
    F.M301.enzyme_loading = i  


# Cellulase price
dist = shape.Uniform(lower = F.M301.ins[1].price * (1-var_50), upper = F.M301.ins[1].price * (1+var_50))
@param(name = 'Cellulase price',
    element = 'EHF',
    kind = 'isolated',
    units = 'USD/kg',
    baseline = F.M301.ins[1].price, distribution = dist)
def set_cellulase_price(i):
    F.M301.ins[1].price = i


    
# Etyl acetate solvent to crude RCF oil ratio
dist = shape.Uniform(lower=etoac_purification['solvent_to_crude_ratio'] * (1 - var_20),
                     upper=etoac_purification['solvent_to_crude_ratio'] * (1 + var_20))
@param(name='EtOAc solvent to crude ratio',
       element='OP',
       kind='coupled',
       units='L/kg',
       baseline=etoac_purification['solvent_to_crude_ratio'],
       distribution=dist)
def set_etoac_solvent_to_crude_ratio(i):
    etoac_purification['solvent_to_crude_ratio'] = i


# Ethyl acetate price
dist = shape.Uniform(lower = F.EthylAcetate_in.price * (1-var_50), upper = F.EthylAcetate_in.price * (1+var_50))
@param(name = 'Ethyl acetate price',
    element = 'OP', 
    kind = 'isolated',
    units = 'USD/kg',
    baseline = F.EthylAcetate_in.price, distribution = dist)
def set_ethyl_acetate_price(i):
    F.EthylAcetate_in.price = i  


# Hexane solvent to pure RCF oil ratio
dist = shape.Uniform(lower=1, upper = 5)
@param(name='Hexane solvent to pure oil ratio',
       element='MP',
       kind='coupled',
       units='kg/kg',
       baseline=hexane_purification['solvent_to_oil_ratio'],
       distribution=dist)
def set_hexane_to_pure_rcf_oil_ratio(i):
    hexane_purification['solvent_to_oil_ratio'] = i

# Hexane price
dist = shape.Uniform(lower = F.Hexane_In.price * (1-var_50), upper = F.Hexane_In.price * (1+var_50))
@param(name = 'Hexane price',
    element = 'MP', 
    kind = 'isolated',
    units = 'USD/kg',
    baseline = F.Hexane_In.price, distribution = dist)
def set_hexane_price(i):
    F.Hexane_In.price = i  


metric = model.metric
@metric(name='Minimum Jet Selling Price', element='TEA', units='USD/gal')
def get_msp():
    msp = (integrated_tea.solve_price(F.TOTAL_SAF) * F.TOTAL_SAF.rho) / 264.172
    return msp

import numpy as np
np.random.seed(3045)
samples = model.sample(N=100, rule = 'L')  # Change this to 3000 later
model.load_samples(samples)

model.evaluate()

df_rho, df_p = model.spearman_r()
print(df_rho["TEA", "Minimum jet selling price [USD/gal]"])



