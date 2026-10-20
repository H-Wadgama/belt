# Uptime sweep: 2000 DMT/day biorefinery, 90% uptime (baseline) down to 50%.
#
# For each uptime level this script reports:
#   - MJSP [USD/gal]
#   - MJSP increase vs. the 90% baseline (absolute and %)
#   - the feedstock price (at restored 90%/330-day operation) that would give the
#     SAME MJSP as the degraded-uptime scenario -- i.e. the maximum premium the
#     plant could pay for a more reliable feedstock supply and be no worse off.
#
# Builds on the single-point (90% vs 85%) breakeven pattern already validated in
# x-chain-analysis.py, generalized into a sweep. See project memory:
# project_feedstock_demand_scale_tradeoff, project_tea_shared_operating_hours_gotcha.

from biosteam import main_flowsheet as F
import biosteam as bst
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
bst.settings.CEPCI = 840   # 2026 basis
bst.settings.electricity_price = prices['electricity']

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

nh3_splitter = bst.units.Splitter(ins=F.T703.outs[0], split={'NH3': 1.0})
nh3_splitter.simulate()

etj_system = create_etj_system_no_facilities(ins=nh3_splitter.outs[1])
etj_system.simulate()

etoh_ww = [F.pretreatment_wastewater, F.unit.S401.outs[1]]
etoh_solids = [F.unit.S401.outs[0]]

WWT = bst.create_conventional_wastewater_treatment_system('WWT', ins=[F.ETJ_WW_OUTS] + etoh_ww)
F.unit.PWC.ins[0] = WWT.outs[2]

solids_to_BT = bst.Mixer('MIX_BT_solids', ins=[WWT.outs[1]] + etoh_solids)
BT = bst.facilities.BoilerTurbogenerator('BT', fuel_price=prices['CH4'])
gas_mixer = bst.Mixer('MIX_BT_gas', ins=(WWT.outs[0], F.ETJ_PSAWASTE_OUTS))
BT.ins[0] = solids_to_BT.outs[0]
BT.ins[1] = gas_mixer.outs[0]

h2_etj = bst.Stream()
h2_etj.copy_like(F.ETJ_H2_IN)
h2_storage = HydrogenStorageTank('H2_TK', ins=h2_etj)

etoh_etj_system = bst.System(
    'Cellulosic_ETJ',
    path=(etoh_system, nh3_splitter, etj_system, WWT),
    facilities=[solids_to_BT, gas_mixer, h2_storage, BT],
)
etoh_etj_system.simulate()

F.ETJ_H2_IN.price = prices['hydrogen']
F.ETJ_RN_OUT.price = prices['renewable_naphtha']
F.ETJ_RD_OUT.price = prices['renewable_diesel']
F.sulfuric_acid.price = prices['H2SO4']
F.ammonia.price = prices['NH3']
F.cellulase.price = prices['Cellulase']
F.CSL.price = prices['CSL']
F.DAP.price = prices['DAP']
F.caustic.price = prices['Caustic']
F.denaturant.price = prices['Denaturant']
F.cooling_tower_chemicals.price = prices['CT_chemicals']

num_operators_per_shift = 30
num_shifts = 5
pay_rate = 40
DWandB = num_operators_per_shift * num_shifts * 2080 * pay_rate
Dsalaries_benefits = 0.15 * DWandB
O_supplies = 0.06 * DWandB
technical_assistance = 5 * 75_000
control_lab = 5 * 80_000
labor = DWandB + Dsalaries_benefits + O_supplies + technical_assistance + control_lab

plant_start_year, plant_end_year = 2025, 2055
n_operating_years = plant_end_year - plant_start_year

# ─── Baseline: 90% uptime, approximated as 330 days/yr per repo convention ────
baseline_operating_days = 330

baseline_tea = create_cellulosic_ethanol_tea(
    etoh_etj_system,
    operating_days=baseline_operating_days,
    duration=(plant_start_year, plant_end_year),
)
baseline_tea.labor_cost = labor
baseline_mjsp = (baseline_tea.solve_price(F.ETJ_SAF_OUT) * F.ETJ_SAF_OUT.rho) / 264.172


def mjsp_of_tea(tea):
    return (tea.solve_price(F.ETJ_SAF_OUT) * F.ETJ_SAF_OUT.rho) / 264.172


# ─── Sweep: uptime 90% (baseline) down to 50%, in 5-point steps ───────────────
uptime_levels = [0.90, 0.85, 0.80, 0.75, 0.70, 0.65, 0.60, 0.55, 0.50]

rows = []
for uptime in uptime_levels:
    is_baseline = np.isclose(uptime, 0.90)
    operating_days = baseline_operating_days if is_baseline else uptime * 365

    if is_baseline:
        mjsp = baseline_mjsp
    else:
        schedule = np.full(n_operating_years, operating_days)
        downtime_tea = create_cellulosic_ethanol_tea(
            etoh_etj_system,
            operating_days=schedule,
            duration=(plant_start_year, plant_end_year),
        )
        downtime_tea.labor_cost = labor
        mjsp = mjsp_of_tea(downtime_tea)

    # Sanity check: baseline_tea must never be clobbered by a downtime_tea built in the loop.
    assert baseline_tea.operating_days == baseline_operating_days, \
        'baseline_tea was clobbered by a downtime_tea built in the sweep!'

    mjsp_increase = mjsp - baseline_mjsp
    mjsp_increase_pct = 100 * (mjsp / baseline_mjsp - 1)

    if is_baseline:
        breakeven_price_dry_ton = feedstock_price_dry_ton
        premium_usd_per_dry_ton = 0.0
        premium_pct = 0.0
    else:
        # Solve for feedstock price P' (at restored 90%/330-day operation) such that
        # MJSP(baseline_tea, feedstock_price=P') == mjsp (the degraded-uptime MJSP).
        def _objective(price_usd_per_kg_wet):
            F.Poplar_In.price = price_usd_per_kg_wet
            return mjsp_of_tea(baseline_tea) - mjsp

        lo, hi = feedstock_price, feedstock_price * 2
        while _objective(hi) < 0:
            hi *= 2
            if hi > feedstock_price * 200:
                raise RuntimeError(f'Breakeven feedstock price not found for uptime={uptime}.')

        breakeven_price_wet = brentq(_objective, lo, hi, xtol=1e-10)
        F.Poplar_In.price = feedstock_price  # restore baseline price on the stream

        breakeven_price_dry_ton = feedstock_price_dry_ton * (breakeven_price_wet / feedstock_price)
        premium_usd_per_dry_ton = breakeven_price_dry_ton - feedstock_price_dry_ton
        premium_pct = 100 * (breakeven_price_dry_ton / feedstock_price_dry_ton - 1)

    rows.append({
        'Uptime [%]': round(uptime * 100, 1),
        'Operating days/yr': round(operating_days, 2),
        'MJSP [USD/gal]': round(mjsp, 4),
        'MJSP increase vs 90% baseline [USD/gal]': round(mjsp_increase, 4),
        'MJSP increase vs 90% baseline [%]': round(mjsp_increase_pct, 2),
        'Breakeven feedstock price at 90% uptime [USD/dry ton]': round(breakeven_price_dry_ton, 2),
        'Feedstock premium [USD/dry ton]': round(premium_usd_per_dry_ton, 2),
        'Feedstock premium [%]': round(premium_pct, 2),
    })

results = pd.DataFrame(rows)
print(results.to_string(index=False))

results.to_csv('uptime_sweep_results.csv', index=False)
try:
    results.to_excel('uptime_sweep_results.xlsx', index=False)
    print('Wrote uptime_sweep_results.csv and uptime_sweep_results.xlsx')
except Exception as e:
    print(f'xlsx export failed ({e}); csv was still written.')
