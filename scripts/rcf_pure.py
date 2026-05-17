# RCF + oil purification system


from lignin_saf.ligsaf_chemicals import create_chemicals
from lignin_saf.ligsaf_settings import feed_parameters, prices
from lignin_saf.systems.rcf import create_rcf_system
from lignin_saf.cellulosic_tea import create_cellulosic_ethanol_tea
from lignin_saf.systems.rcf_oil_purification import create_rcf_oil_purification_system

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


rcf_system = create_rcf_system(ins=poplar_in)
rcf_system.simulate()




rcf_oil_purification_sys = create_rcf_oil_purification_system(ins=F.RCF_CRUDE_OUT)
rcf_oil_purification_sys.simulate()

WWT = bst.create_conventional_wastewater_treatment_system('WWT', ins=(F.WW_10, F.WastePulp, F.RCF_WW_OUTS))


for unit in WWT.units:
    if hasattr(unit, 'strict_moisture_content'):
        unit.strict_moisture_content = False   # ← toggle here
    # To adjust the target moisture fraction (default 0.79 from Humbird):
    # if hasattr(unit, 'moisture_content'):
    #     unit.moisture_content = 0.6

BT = bst.facilities.BoilerTurbogenerator('BT', fuel_price=prices['CH4'])

gas_mixer= bst.Mixer('MIX_BT_gas',    ins=(WWT.outs[0], F.RCF_PSAWASTE_OUTS))

BT.ins[0] = WWT.outs[1]   # Connecting sludge to BT solids feed
BT.ins[1] = gas_mixer.outs[0]   # Connecting biogas from WW treatment and PSA waste gases from RCF




rcf_pure_oil_system = bst.System(
    'Solo RCF system',
    path=(rcf_system, rcf_oil_purification_sys, WWT),
    facilities=[gas_mixer, BT],
)
rcf_pure_oil_system.simulate()

integrated_tea = create_cellulosic_ethanol_tea(rcf_pure_oil_system)

print(f'The MSP for RCF crude oil is  {round(integrated_tea.solve_price(F.PURE_OIL_OUT), 3)} USD/kg')


