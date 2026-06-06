# RCF + cellulosic ethanol without dilute-acid pretreatment

from lignin_saf.ligsaf_chemicals import create_chemicals
from lignin_saf.settings.process_params import feed_parameters, solvolysis_params, hydrogenolysis_params, rcf_oil_yield, additional_rcf
from lignin_saf.settings.prices import prices,  _feedstock_price_dry_ton, kg_per_ton, h2_price
from lignin_saf.settings.tea_params import operating_days, labor
from lignin_saf.systems.rcf import create_rcf_system
from lignin_saf.systems.cellulosic_ethanol_no_preatreatment import create_cellulosic_ethanol_system
from lignin_saf.cellulosic_tea import create_cellulosic_ethanol_tea

from lignin_saf.ligsaf_units import HydrogenStorageTank


from biosteam import main_flowsheet as F
import biosteam as bst

chems = create_chemicals()
bst.settings.set_thermo(chems)
bst.settings.CEPCI = 840

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


# ── Cellulosic ethanol — Carbohydrate_Pulp feeds directly into fermentation ─
etoh_system = create_cellulosic_ethanol_system(ins=F.Carbohydrate_Pulp)
etoh_system.simulate()

# No pretreatment_wastewater — only S401 stillage filtrate goes to WWT.
etoh_ww     = [F.unit.S401.outs[1]]
etoh_solids = [F.unit.S401.outs[0]]

# ── WWT: RCF wastewater + ethanol stillage filtrate ────────────────────────
WWT = bst.create_conventional_wastewater_treatment_system(
    'WWT',
    ins=[F.RCF_WW_OUTS] + etoh_ww,
)
for unit in WWT.units:
    if hasattr(unit, 'strict_moisture_content'):
        unit.strict_moisture_content = False

# Wire WWT RO-treated water to PWC; create_all_facilities(WWT=False) leaves
# M2 (placeholder mixer) empty, so PWC would otherwise buy ~480,000 kg/hr
# of fresh water unnecessarily.
F.unit.PWC.ins[0] = WWT.outs[2]

solids_to_BT = bst.Mixer('MIX_BT_solids', ins=[WWT.outs[1]] + etoh_solids)
gas_mixer    = bst.Mixer('MIX_BT_gas',    ins=[F.RCF_PSAWASTE_OUTS, WWT.outs[0]])

BT = bst.facilities.BoilerTurbogenerator('BT', fuel_price=prices['CH4'])
BT.ins[0] = solids_to_BT.outs[0]
BT.ins[1] = gas_mixer.outs[0]



h2_rcf = bst.Stream()
h2_rcf.copy_like(F.RCF_H2_IN)

shared_h2_storage = HydrogenStorageTank('H2_TK', ins=h2_rcf)



rcf_etoh_system = bst.System(
    'RCF_ETOH_system',
    path=(rcf_system, etoh_system, WWT),
    facilities=[solids_to_BT, gas_mixer, BT, shared_h2_storage],
)

rcf_etoh_system.simulate()
integrated_tea = create_cellulosic_ethanol_tea(rcf_etoh_system)
F.ethanol.price = 0.76


F.cellulase.price = prices['Cellulase'] 
F.CSL.price = prices ['CSL'] 
F.DAP.price = prices['DAP'] 
F.caustic.price = prices['Caustic']
F.denaturant.price =  prices['Denaturant'] 
F.cooling_tower_chemicals.price = prices['CT_chemicals'] 


#print(f'The MSP for RCF crude oil is  {round(integrated_tea.solve_price(F.RCF_CRUDE_OUT), 3)} USD/kg')

# Labor cost from [1]
# [1] W. Seider et al., Product and Process Design Principles. 2016. John Wiley & Sons.
# Table 17.3 from [1]
# For RCF - 6 operators for the reactors (solids-fluids processing, and > 100 ton/day so 3 x 2 =6 ), and 2 for the distillation columns downstream for solvent recovery. Total operators: 8
# For ethanol production, 6 operators for reactors as solids-fluids processing and large volumes so 3 x 2 = 6, and then 2 for the beer column downstream for ethanol purification. Total operators: 8
# 1 operators for the storage. Total operators: 1
# 1 operators for WWT (I think complexity of feed streams), and 1 for BT. Total operator: 2
# Total operators per shift: 19

num_operators_per_shift = 19
num_shifts              = 5       # number of operator shifts (4 working + 1 relief)
pay_rate                = 40      # [USD/hr] operator base pay rate

DWandB             = num_operators_per_shift * num_shifts * 2080 * pay_rate
Dsalaries_benefits = 0.15 * DWandB          # 15% of DW&B for salaried staff + benefits
O_supplies         = 0.06 * DWandB          # 6% of DW&B for operating supplies
technical_assistance = 5 * 75_000           # 5 technical staff @ $75,000/yr
control_lab          = 5 * 80_000           # 5 lab/QC staff  @ $80,000/yr

labor = DWandB + Dsalaries_benefits + O_supplies + technical_assistance + control_lab
# [USD/yr] total annual labor cost; passed to tea.labor_cost after creating the TEA object

integrated_tea.operating_days = 330
integrated_tea.labor_cost = labor

model = bst.Model(rcf_etoh_system)

from chaospy import distributions as shape
param = model.parameter



var_50 = 0.5 # 50% variation in parameters - set for a few
var_20 = 0.2 # 20% variation in other parameters

# Distillation col 1 light key recovery at the top
dist = shape.Uniform(lower = 0.7, 
                     upper = 0.9999) 
@param(name = 'Light key recovery - column 1',
    element = 'Overall', 
    kind = 'coupled',
    units = 'wt%',
    baseline = additional_rcf['rcf_col_1_light_dist_recovery'], distribution = dist)
def set_light_key_recovery_column_1(i):
    additional_rcf['rcf_col_1_light_dist_recovery'] = i
    F.unit.RCF_COL1.Lr = i


metric = model.metric
@metric(name='Minimum Jet Selling Price', element='TEA', units='USD/gal')
def get_msp():
    msp = (integrated_tea.solve_price(F.RCF_CRUDE_OUT))
    return msp



import numpy as np
np.random.seed(3198)
samples = model.sample(N=1000, rule = 'L')  # Change this to 3000 later
model.load_samples(samples)


model.evaluate()