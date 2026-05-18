# RCF + cellulosic ethanol without dilute-acid pretreatment

from lignin_saf.ligsaf_chemicals import create_chemicals
from lignin_saf.ligsaf_settings import feed_parameters, prices
from lignin_saf.systems.rcf import create_rcf_system
from lignin_saf.systems.cellulosic_ethanol_no_preatreatment import create_cellulosic_ethanol_system
from lignin_saf.cellulosic_tea import create_cellulosic_ethanol_tea

from biosteam import main_flowsheet as F
import biosteam as bst

chems = create_chemicals()
bst.settings.set_thermo(chems)
bst.settings.CEPCI = 541.7

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

rcf_etoh_system = bst.System(
    'RCF_ETOH_system',
    path=(rcf_system, etoh_system, WWT),
    facilities=[solids_to_BT, gas_mixer, BT],
)
rcf_etoh_system.simulate()

integrated_tea = create_cellulosic_ethanol_tea(rcf_etoh_system)

print(f'The MSP for RCF crude oil is  {round(integrated_tea.solve_price(F.RCF_CRUDE_OUT), 3)} USD/kg')

