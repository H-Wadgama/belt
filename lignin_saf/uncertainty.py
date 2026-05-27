from biosteam import main_flowsheet as F
import biosteam as bst
import thermosteam as tmo
import pandas as pd
import numpy as np


from lignin_saf.ligsaf_chemicals import create_chemicals
from lignin_saf.settings.process_params import feed_parameters
from lignin_saf.settings.prices import prices
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
    path=(rcf_system, rcf_oil_purification_sys, monomer_purification_sys, hdo_system, etoh_system, etj_system, combined_saf, WWT),
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

from lignin_saf.settings.process_params import solvolysis_params, hdo_params
from lignin_saf.settings.prices import prices, _feedstock_price_dry_ton, kg_per_ton, h2_price

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


# Cellulose retention in pulp after RCF — kind='coupled': changes Glucan split in
# SolvolysisReactor._run(), which alters the carbohydrate pulp flow to the ethanol system.
# Both this module and ligsaf_units.py hold a reference to the same solvolysis_params dict,
# so mutating the dict here is immediately visible inside _run() without any changes to
# ligsaf_units.py.
dist = shape.Uniform(lower=0.5, upper=1.0)
@param(name='Cellulose retention',
       element='RCF',
       kind='coupled',
       units='-',
       baseline=solvolysis_params['Cellulose_retention'],
       distribution=dist)
def set_cellulose_retention(i):
    solvolysis_params['Cellulose_retention'] = i


# HDO dodecane solvent loading — kind='coupled': read at runtime by the dodecane_flow spec
# in systems/hdo.py (`dod_vol = ins.F_mass * hdo_params['solvent_req']`).
# Mutating the shared hdo_params dict propagates immediately to that spec without any
# changes to hdo.py. More solvent → larger reactor, higher distillation load → coupled.
dist = shape.Uniform(lower=0.1, upper=0.4)
@param(name='HDO solvent loading',
       element='HDO',
       kind='coupled',
       units='m3/kg monomer',
       baseline=hdo_params['solvent_req'],
       distribution=dist)
def set_hdo_solvent_req(i):
    hdo_params['solvent_req'] = i


# HDO catalyst loading — kind='coupled': catalyst_req is read in the dodecane_flow spec
# in systems/hdo.py (line 94: hdo_cat_in.imass['Ni2PSiO2'] = catalyst_req × ...).
# That spec sets the catalyst stream flow, which feeds into TEA material cost via stream.price.
# kind='isolated' would leave the catalyst stream flow stale. Note: catalyst_req also appears
# in HydrodeoxygenationReactor._cost() but only stores to design['Catalyst loading cost']
# (not baseline_purchase_costs), so that path is reporting only.
dist = shape.Uniform(lower=hdo_params['catalyst_req'] * 0.5, upper=hdo_params['catalyst_req'] * 1.5)
@param(name='HDO catalyst loading',
       element='HDO',
       kind='coupled',
       units='kg/kg monomer',
       baseline=hdo_params['catalyst_req'],
       distribution=dist)
def set_hdo_catalyst_req(i):
    hdo_params['catalyst_req'] = i


metric = model.metric
@metric(name='Minimum Jet Selling Price', element='TEA', units='USD/gal')
def get_msp():
    msp = (integrated_tea.solve_price(F.TOTAL_SAF) * F.TOTAL_SAF.rho) / 264.172
    return msp


from SALib.analyze import morris as morris_analyze

N_samples = 100
rule = 'MORRIS'
np.random.seed(42)
problem = model.problem()
samples = model.sample(N_samples, rule, problem=problem, num_levels=6)
model.load_samples(samples)
model.evaluate()


Y = model.table["TEA"]["Minimum Jet Selling Price [USD/gal]"].to_numpy()


Si = morris_analyze.analyze(
    problem,
    samples,
    Y,
    conf_level=0.95,
    print_to_console=True,
)


print("\n Morris Results")
results_df = pd.DataFrame({
    "Feature":  Si["names"],
    "µ*":       Si["mu_star"],
    "µ* conf":  Si["mu_star_conf"],
    "σ":        Si["sigma"],
})



