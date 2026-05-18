# RCF + cellulosic ethanol without dilute-acid pretreatment with oil and monomer purification and with etj

from lignin_saf.ligsaf_chemicals import create_chemicals
from lignin_saf.ligsaf_settings import feed_parameters, prices
from lignin_saf.systems.rcf import create_rcf_system
from lignin_saf.systems.cellulosic_ethanol_no_preatreatment import create_cellulosic_ethanol_system
from lignin_saf.systems.rcf_oil_purification import create_rcf_oil_purification_system
from lignin_saf.systems.monomer_purification import create_monomer_purification_system
from atj_saf.atj_bst.etj_no_facilities import create_etj_system_no_facilities

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

rcf_oil_purification_sys = create_rcf_oil_purification_system(ins=F.RCF_CRUDE_OUT)
rcf_oil_purification_sys.simulate()

monomer_purification_sys = create_monomer_purification_system(ins=F.PURE_OIL_OUT)
monomer_purification_sys.simulate()

# ── Cellulosic ethanol — Carbohydrate_Pulp feeds directly into fermentation ─
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

# ── WWT: RCF wastewater + ethanol stillage filtrate ────────────────────────
WWT = bst.create_conventional_wastewater_treatment_system(
    'WWT',
    ins=[F.RCF_WW_OUTS, F.WW_10, F.WastePulp, F.WW_11, F.WW_12, F.ETJ_WW_OUTS] + etoh_ww,
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
gas_mixer.ins.append(F.ETJ_PSAWASTE_OUTS)

BT = bst.facilities.BoilerTurbogenerator('BT', fuel_price=prices['CH4'])
BT.ins[0] = solids_to_BT.outs[0]
BT.ins[1] = gas_mixer.outs[0]

rcf_pure_mon_etoh_etj_system = bst.System(
    'RCF_PURE_MON_ETOH_system',
    path=(rcf_system, rcf_oil_purification_sys, monomer_purification_sys, etoh_system, etj_system, WWT),
    facilities=[solids_to_BT, gas_mixer, BT],
)
rcf_pure_mon_etoh_etj_system.simulate()

integrated_tea = create_cellulosic_ethanol_tea(rcf_pure_mon_etoh_etj_system)

print(f'The MSP for SAF is  {round(((integrated_tea.solve_price(F.ETJ_SAF_OUT)*F.ETJ_SAF_OUT.rho)/264.172),2)} USD/gal')

