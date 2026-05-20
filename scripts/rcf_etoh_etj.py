# Combines RCF + cellulosic ethanol production + ETJ

from lignin_saf.ligsaf_chemicals import create_chemicals
from lignin_saf.ligsaf_settings import feed_parameters, prices
from lignin_saf.systems.rcf import create_rcf_system
from lignin_saf.systems.rcf_oil_purification import create_rcf_oil_purification_system
from lignin_saf.systems.monomer_purification import create_monomer_purification_system
from lignin_saf.systems.ligsaf_utilities import create_rcf_utilities_system
from lignin_saf.systems.cellulosic_ethanol import create_cellulosic_ethanol_system
from lignin_saf.cellulosic_tea import create_cellulosic_ethanol_tea
from atj_saf.atj_bst.etj_ligfirst import create_etj_system_no_facilities

from biosteam import main_flowsheet as F
import biosteam as bst
import pandas as pd
import numpy as np

chems = create_chemicals()
bst.settings.set_thermo(chems)
bst.settings.CEPCI = 541.7   # 2016 USD basis

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
rcf_oil_purification_sys = create_rcf_oil_purification_system(ins=F.RCF_Oil)
monomer_purification_sys = create_monomer_purification_system(ins=F.Purified_RCF_Oil)
rcf_oil_purification_sys.simulate()
monomer_purification_sys.simulate()

# ── Cellulosic ethanol co-product ──────────────────────────────────────────
# create_cellulosic_ethanol_system omits BT (CHP) and WWT via WWT=False,
# CHP=False in its create_all_facilities call, so no ID conflicts arise
# with the shared RCF utilities created below.
ethanol_system = create_cellulosic_ethanol_system(ins=F.Carbohydrate_Pulp, add_denaturant=False)
ethanol_system.simulate()

# Explicit stream routing — verified against stock cellulosic.create_cellulosic_ethanol_system:
#   fermentation vent (F.vent) is atmospheric — not burned in BT
#   CT blowdown goes to PWC via blowdown_recycle=True — not to WWT
#   cooling water and CT evaporation must not be captured
etoh_ww     = [F.pretreatment_wastewater, F.unit.S401.outs[1]]
etoh_solids = [F.unit.S401.outs[0]]


# Removing the NH3 fraction of the ethanol output - in the future CBP will remove this anyways, so I've just modelled it as a splitter
nh3_splitter = bst.units.Splitter(ins = F.T703.outs[0], split = {'NH3':1.0} )
nh3_splitter.simulate()

# Ethanol to Jet system
etj_system = create_etj_system_no_facilities(ins = nh3_splitter.outs[1])
etj_system.simulate()

etoh_ww.append(F.H602.outs[0])


# ── Area 400/500: Shared utilities ─────────────────────────────────────────
BT, WWT, gas_mixer = create_rcf_utilities_system()
gas_mixer.ins.append(F.etj_waste_gases)
# Route ethanol streams into the shared RCF utilities.
F.unit.M601.ins.extend(etoh_ww)

solids_to_BT = bst.Mixer('MIX_BT_solids', ins=[WWT.outs[1]] + etoh_solids)
BT.ins[0] = solids_to_BT.outs[0]
# Fermentation vent is atmospheric — do NOT route to gas_mixer


# Wire WWT RO-treated water to PWC; create_all_facilities(WWT=False) leaves M2
# (placeholder mixer for WWT water) empty, so PWC would otherwise purchase
# ~480,000 kg/hr of fresh water unnecessarily (~$1.1M/yr spurious cost).
F.unit.PWC.ins[0] = WWT.outs[2]

rcf_combined_system = bst.System(
    'Combined_RCF_System',
    path=(rcf_system, rcf_oil_purification_sys, monomer_purification_sys, ethanol_system, nh3_splitter, etj_system, WWT),
    facilities=[solids_to_BT, gas_mixer, BT],
)

rcf_combined_system.simulate()
rcf_combined_system.show()

# ── Labor (Seider methodology) ─────────────────────────────────────────────
operators_per_section = 1
num_process_sections = 3
num_operators_per_shift = operators_per_section * num_process_sections * 1
num_shifts = 5
pay_rate = 40
DWandB = num_operators_per_shift * num_shifts * 2080 * pay_rate
Dsalaries_benefits = 0.15 * DWandB
O_supplies = 0.06 * DWandB
technical_assistance = 5 * 75000
control_lab = 5 * 80000
labor = DWandB + Dsalaries_benefits + O_supplies + technical_assistance + control_lab

# ── TEA and MSP ────────────────────────────────────────────────────────────
integrated_tea = create_cellulosic_ethanol_tea(rcf_combined_system)
integrated_tea.labor_cost = labor

print(f'The MSP for RCF monomers is  {round(integrated_tea.solve_price(F.RCF_Monomers), 3)} USD/kg')


rcf_combined_system.diagram('rcf_etoh_etj.png', format = 'png')