# Supply chain analysis of feedstock cost impact on MJSP
from biosteam import main_flowsheet as F
import biosteam as bst
import thermosteam as tmo
import pandas as pd
import numpy as np


from scipy.optimize import brentq

from lignin_saf.ligsaf_chemicals import create_chemicals
from scn_params import feed_parameters, prices, feedstock_price_dry_ton, feedstock_price
from lignin_saf.systems.cellulosic_ethanol import create_cellulosic_ethanol_system
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


etoh_system = create_cellulosic_ethanol_system(ins=poplar_in, add_denaturant=False)
etoh_system.simulate()

# Removing the NH3 fraction of the ethanol output - in the future CBP will remove this anyways, so I've just modelled it as a splitter
nh3_splitter = bst.units.Splitter(ins = F.T703.outs[0], split = {'NH3':1.0} )
nh3_splitter.simulate()


# Ethanol to Jet system
etj_system = create_etj_system_no_facilities(ins = nh3_splitter.outs[1])
etj_system.simulate()



# Pretreatment wastewater and S401 stillage filtrate both go to WWT.

etoh_ww = [F.pretreatment_wastewater, F.unit.S401.outs[1]]

etoh_solids = [F.unit.S401.outs[0]]

WWT = bst.create_conventional_wastewater_treatment_system('WWT', ins=[F.ETJ_WW_OUTS] + etoh_ww)
F.unit.PWC.ins[0] = WWT.outs[2]

solids_to_BT = bst.Mixer('MIX_BT_solids', ins=[WWT.outs[1]] + etoh_solids)

BT = bst.facilities.BoilerTurbogenerator('BT', fuel_price=prices['CH4'])

gas_mixer= bst.Mixer('MIX_BT_gas', ins=(WWT.outs[0], F.ETJ_PSAWASTE_OUTS))

BT.ins[0] = solids_to_BT.outs[0]  # Connecting sludge to BT solids feed
BT.ins[1] = gas_mixer.outs[0]   # Connecting biogas from WW treatment and PSA waste gases from RCF





h2_etj = bst.Stream()
h2_etj.copy_like(F.ETJ_H2_IN)

h2_storage = HydrogenStorageTank('H2_TK', ins=h2_etj)


etoh_etj_system = bst.System(
    'Cellulosic_ETJ',
    path=(etoh_system, nh3_splitter, etj_system, WWT),
    facilities=[solids_to_BT, gas_mixer, h2_storage, BT],
)

etoh_etj_system.simulate()


F.ETJ_H2_IN.price = prices['hydrogen']   # 8.46 USD/kg
F.ETJ_RN_OUT.price = prices['renewable_naphtha']   # 0.71 USD/kg
F.ETJ_RD_OUT.price = prices['renewable_diesel']    # 1.888 USD/kg
F.sulfuric_acid.price = prices['H2SO4']
F.ammonia.price = prices['NH3']
F.cellulase.price = prices['Cellulase'] 
F.CSL.price = prices ['CSL'] 
F.DAP.price = prices['DAP'] 
F.caustic.price = prices['Caustic']
F.denaturant.price =  prices['Denaturant'] 
F.cooling_tower_chemicals.price = prices['CT_chemicals'] 
#F.FOD_lime.price = prices['FOD_lime']


integrated_tea = create_cellulosic_ethanol_tea(etoh_etj_system)


# All the steps are assumed to be continuous even though hydrolysis and fermentation trains are batch, because the overall process operates continuously. Total = 11
# Ethanol produyction operators are 20 because thats what it was in the Humbird reportr
# For ETJ, 2 operators for the reactors, not treating them separately, as ETJ operations are rather conventional, (dehydration, hydrogenation atleast have been around for a while to my knowledge), 1 for 
# the distillation column. Total operators: 3
# 2 operators for the storage  - hydrogen storage will definitely need one I believe and 1 would be required for the rest, and 1 for biomass. Total operators: 3
# 2 operators for WWT (I think complexity of feed streams and solids-liquids), and 2 for BT. Total operator: 4
# Total operators per shift: 20 + 3 + 3 + 4 = 30

num_operators_per_shift = 30
num_shifts              = 5       # number of operator shifts (4 working + 1 relief)
pay_rate                = 40      # [USD/hr] operator base pay rate

DWandB             = num_operators_per_shift * num_shifts * 2080 * pay_rate
Dsalaries_benefits = 0.15 * DWandB          # 15% of DW&B for salaried staff + benefits
O_supplies         = 0.06 * DWandB          # 6% of DW&B for operating supplies
technical_assistance = 5 * 75_000           # 5 technical staff @ $75,000/yr
control_lab          = 5 * 80_000           # 5 lab/QC staff  @ $80,000/yr

labor = DWandB + Dsalaries_benefits + O_supplies + technical_assistance + control_lab
# [USD/yr] total annual labor cost; passed to tea.labor_cost after creating the TEA object

# Baseline TEA: constant 330 days/yr (the historical default).
baseline_tea = create_cellulosic_ethanol_tea(
    etoh_etj_system,
    operating_days=330,
    duration=(2025, 2055),
)
baseline_tea.labor_cost = labor
baseline_mjsp = round(((baseline_tea.solve_price(F.ETJ_SAF_OUT)*F.ETJ_SAF_OUT.rho)/264.172),2)


# ─── Downtime scenario: 85% operating factor (310.25 days/yr) ────────────────────────
# Baseline operating schedule is 330 days/yr (~90% operating factor, 0.90 * 365 = 328.5,
# approximated in the model as 330). Here we model increased downtime: 85% operating
# factor -> 0.85 * 365 = 310.25 days/yr, all else (feedstock price, system design) held
# fixed. Fewer operating days means less annual production to spread fixed CAPEX/labor
# costs over, so MJSP rises even though variable (feedstock) costs fall proportionally.
#
# downtime_tea is built as a MultiYearCellulosicEthanolTEA, triggered by passing an
# *array* of operating_days (one constant entry per operating year) instead of a scalar.
# CellulosicEthanolTEA (plain, scalar operating_days) reads/writes operating_hours
# directly on the shared etoh_etj_system object, so a second plain instance would
# silently overwrite baseline_tea's 330-day schedule (see cellulosic_tea.py docstring
# and project memory: project_tea_shared_operating_hours_gotcha). MultiYearCellulosic-
# EthanolTEA keeps a fully private operating_hours/sales/material_cost/utility_cost/
# solve_price, so it coexists safely with baseline_tea on the same system -- no reset
# of baseline_tea needed anywhere below.
downtime_operating_days = 0.85 * 365   # = 310.25 days/yr
n_operating_years = 2055 - 2025
downtime_operating_days_schedule = np.full(n_operating_years, downtime_operating_days)

downtime_tea = create_cellulosic_ethanol_tea(
    etoh_etj_system,
    operating_days=downtime_operating_days_schedule,
    duration=(2025, 2055),
)
downtime_tea.labor_cost = labor
downtime_mjsp = round(((downtime_tea.solve_price(F.ETJ_SAF_OUT)*F.ETJ_SAF_OUT.rho)/264.172),2)

# Sanity check: baseline_tea must be unaffected by downtime_tea's creation/use.
assert baseline_tea.operating_days == 330, 'baseline_tea was clobbered by downtime_tea!'

print(f"Baseline MJSP  (330.00 days/yr, {feedstock_price_dry_ton} USD/dry ton feedstock): {baseline_mjsp} USD/gal")
print(f"Downtime MJSP  ({downtime_operating_days} days/yr = 85% operating factor, same feedstock price): {downtime_mjsp} USD/gal")
print(f"MJSP increase from downtime: {round(downtime_mjsp - baseline_mjsp, 2)} USD/gal "
      f"({round(100*(downtime_mjsp/baseline_mjsp - 1), 1)}%)")


# ─── Feedstock-price breakeven at restored (330-day) operation ───────────────────────
# Question: if the plant could restore full 330-day operation (e.g. by paying a premium
# for a more reliable/guaranteed feedstock supply instead of being downtime-constrained),
# how much MORE could it afford to pay for feedstock and still be no worse off (same
# MJSP) than the degraded 310.25-day / baseline-feedstock-price scenario above?
#
# Solve for feedstock price P' such that:
#     MJSP(operating_days=330, feedstock_price=P') == downtime_mjsp
# Stream prices don't affect the physical simulation (only TEA cash flows), so this is
# a fast "isolated"-style perturbation: no re-simulation of etoh_etj_system is needed,
# only repeated calls to baseline_tea.solve_price(). Because downtime_tea is a
# MultiYearCellulosicEthanolTEA (private operating_hours, never touching
# etoh_etj_system.operating_hours), baseline_tea is still correctly at 330 days here --
# no reset needed before reusing it, unlike if downtime_tea had been a second plain
# CellulosicEthanolTEA.

def _mjsp_at_feedstock_price(price_usd_per_kg_wet):
    F.Poplar_In.price = price_usd_per_kg_wet
    return (baseline_tea.solve_price(F.ETJ_SAF_OUT) * F.ETJ_SAF_OUT.rho) / 264.172

def _objective(price_usd_per_kg_wet):
    return _mjsp_at_feedstock_price(price_usd_per_kg_wet) - downtime_mjsp

# Expand the upper bracket until the objective changes sign (MJSP is monotonically
# increasing in feedstock price), rather than assuming a fixed multiplier.
lo, hi = feedstock_price, feedstock_price * 2
while _objective(hi) < 0:
    hi *= 2
    if hi > feedstock_price * 100:
        raise RuntimeError("Breakeven feedstock price not found within 100x baseline.")

breakeven_feedstock_price = brentq(_objective, lo, hi)

# Restore baseline feedstock price on the stream before any further use of the system/TEA.
F.Poplar_In.price = feedstock_price

# Conversion from USD/kg-wet to USD/dry-ton is linear, so the price ratio is preserved.
breakeven_feedstock_price_dry_ton = feedstock_price_dry_ton * (breakeven_feedstock_price / feedstock_price)
feedstock_price_premium_pct = 100 * (breakeven_feedstock_price_dry_ton / feedstock_price_dry_ton - 1)

print(f"Breakeven feedstock price (330 days/yr, same MJSP as downtime scenario): "
      f"{round(breakeven_feedstock_price_dry_ton, 2)} USD/dry ton "
      f"(+{round(feedstock_price_premium_pct, 1)}% vs baseline {feedstock_price_dry_ton} USD/dry ton)")