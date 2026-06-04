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


rcf_etoh_system = bst.System(
    'RCF_ETOH_system',
    path=(rcf_system, etoh_system, WWT),
    facilities=[solids_to_BT, gas_mixer, BT],
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

integrated_tea.operating_days


# Different sections

rcf = [F.MIX100, F.RCF_PUMP1, F.RCF_HX1, F.RCF_RXR1, F.RCF_MIX2, F.RCF_HX2, F.RCF_RXR2, F.RCF_FLSH1, F.RCF_COMP1,
F.RCF_FLSH2, F.RCF_HX3, F.RCF_PSA1, F.RCF_PUMP2, F.RCF_COL1, F.RCF_COL2, F.RCF_MIX3, F.RCF_HX4, F.RCF_FLSH3, F.RCF_MIX4, F.RCF_FLSH4]

etoh = [F.M301, F.H301, F.R301, F.DAP_storage, F.S301, F.CSL_storage, F.S302, F.R303, F.R302, F.T301, F.M304, F.D401, F.M401, F.T302, F.P401, F.H401, F.D402, F.P401, F.D403, F.H402, F.U401, F.H403, 
        F.T701, F.P701, F.T702, F.P702, F.M701, F.T703, F.P403, F.M1, F.S401 ]


other_utilities = [F.CWP, F.CT, F.FWT, F.ADP, F.PWC]

BT = [BT]

WWT = [WWT]

import numpy as np
rcf_area_ic = sum(u.installed_cost for u in rcf)
etoh_ic =  sum(u.installed_cost for u in etoh)
BT_installed_cost = F.BT.installed_cost
WWT_installed_cost  = F.WWTC.installed_cost
other_utilities_ic = sum(u.installed_cost for u in other_utilities)
installed_costs_arr = np.array([rcf_area_ic, etoh_ic, other_utilities_ic,
                            BT_installed_cost, WWT_installed_cost])


methanol_price = F.RCF_MEOH_IN.F_mass * prices['Methanol'] * integrated_tea.operating_hours
hydrogen_price = (F.RCF_H2_IN.F_mass * prices['Hydrogen']) * integrated_tea.operating_hours
                  
poplar_price = F.Poplar_In.F_mass * prices['Feedstock'] * integrated_tea.operating_hours
catalyst = (
    F.RCF_CAT_IN.F_mass * prices['NiC_catalyst']) * integrated_tea.operating_hours


cellulase_cost = F.cellulase.F_mass * prices['Cellulase'] * integrated_tea.operating_hours

# NOTE: F.denaturant has zero flow (add_denaturant=False), so it contributes $0.
# Included here for completeness — it is priced and appears in the TEA material_cost.
fermentation_chems_cost = (
    F.CSL.F_mass * prices['CSL']
    + F.DAP.F_mass * prices['DAP']
    + F.caustic.F_mass * prices['Caustic']
    + F.denaturant.F_mass * prices['Denaturant']
    + F.cooling_tower_chemicals.F_mass * prices['CT_chemicals']
) * integrated_tea.operating_hours    


# Electricity costs 
rcf_electricity = sum(u.power_utility.power for u in rcf)*bst.settings.electricity_price*integrated_tea.operating_hours
etoh_electricity = sum(u.power_utility.power for u in etoh)*bst.settings.electricity_price*integrated_tea.operating_hours
BT_electricity = F.BT.power_utility.power*bst.settings.electricity_price*integrated_tea.operating_hours
WWT_electricity = F.WWTC.power_utility.power*bst.settings.electricity_price*integrated_tea.operating_hours

# Utility costs
rcf_utility_cost = sum(u.utility_cost if u.utility_cost is not None else 0 for u in rcf)*integrated_tea.operating_hours
etoh_utility_cost = sum(u.utility_cost if u.utility_cost is not None else 0 for u in etoh)*integrated_tea.operating_hours
BT_utility_cost = F.BT.utility_cost*integrated_tea.operating_hours
WWT_utility_cost = F.WWTC.utility_cost*integrated_tea.operating_hours
other_utilities_utility_cost = sum(u.utility_cost if u.utility_cost is not None else 0 for u in other_utilities)*integrated_tea.operating_hours

total_utility_cost = (rcf_utility_cost + etoh_utility_cost +
                      BT_utility_cost + WWT_utility_cost +
                      other_utilities_utility_cost)


import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# ── Font ──────────────────────────────────────────────────────────────────────
font_pref = ["Arial", "Liberation Sans", "DejaVu Sans"]
available = [f.name for f in matplotlib.font_manager.fontManager.ttflist]
chosen = next((f for f in font_pref if f in available), "DejaVu Sans")
print(f"Font: {chosen}")

plt.rcParams.update({
    "font.family": chosen,
    "mathtext.fontset": "custom",
    "mathtext.rm": chosen,
    "mathtext.it": chosen,
    "mathtext.bf": chosen,
})
plt.rcParams['svg.fonttype'] = 'none'

oi_colors = [
    '#5778a4', '#e49444', '#d1615d', '#85b6b2', '#6a9f58',
    '#e7ca60', '#a87c9f', '#f1a2a9', '#967662', '#b8b0ac', "#8D86C9"
]

ic_categories = [
    "RCF",
    "Ethanol production", "Boiler Turbogenerator",
    "WasteWater Treatment", "Other utilities"
]

ic_values = [
    rcf_area_ic, etoh_ic, BT_installed_cost, WWT_installed_cost,
    other_utilities_ic
]

op_categories = [
    "Feedstock",
    "Methanol",
    "Hydrogen",
    "Catalyst",
    "Cellulase",
    "Fermentation\nchemicals",
    "Utilities",
]

op_values = [
    poplar_price,
    methanol_price,
    hydrogen_price,
    catalyst,
    cellulase_cost,
    fermentation_chems_cost,
    total_utility_cost,
]

# ── Figure ────────────────────────────────────────────────────────────────────
DPI      = 300
fig_w_in = 1500/1.4 / DPI
fig_h_in = 1260/1.4 / DPI

FS_TITLE  = 9
FS_TOTAL  = 13
FS_PCT    = 6
FS_LEGEND = 6

fig, ax = plt.subplots(figsize=(fig_w_in, fig_h_in))


def draw_pie(ax, vals, cats, title, total_label):
    total = sum(vals)
    fracs = [v / total for v in vals]
    n = len(vals)

    wedges, _ = ax.pie(
        vals,
        colors=oi_colors[:n],
        startangle=90,
        counterclock=False,
        wedgeprops=dict(
            linewidth=0,
            edgecolor="none",
        ),
    )

    r_outer = 1.0

    # ── Collect label info ────────────────────────────────────────────────
    label_info = []
    for i, (wedge, frac) in enumerate(zip(wedges, fracs)):
        pct   = frac * 100
        theta = np.deg2rad((wedge.theta1 + wedge.theta2) / 2)
        label_info.append({
            "theta":    theta,
            "pct":      pct,
            "cat":      cats[i],
            "is_right": np.cos(theta) >= 0,
        })

    # ── Split into left/right, sorted top → bottom by sin(theta) ─────────
    right = sorted([d for d in label_info if     d["is_right"]],
                   key=lambda d: np.sin(d["theta"]), reverse=True)
    left  = sorted([d for d in label_info if not d["is_right"]],
                   key=lambda d: np.sin(d["theta"]), reverse=True)

    # ── Evenly distribute y positions across each side ────────────────────
    Y_TOP, Y_BOT = 1.40, -1.40

    def y_positions(n_labels):
        return list(np.linspace(Y_TOP, Y_BOT, n_labels)) if n_labels > 1 else [0.0]

    right_ys = y_positions(len(right))
    left_ys  = y_positions(len(left))

    # ── Fixed x anchors ───────────────────────────────────────────────────
    # "conn" = where the diagonal meets the underline
    # "far"  = the far end of the underline
    X_R_CONN, X_R_FAR = 1.22,  2.20
    X_L_CONN, X_L_FAR = -1.22, -2.20

    # ── Draw each group ───────────────────────────────────────────────────
    GAP    = 0.05   # gap between underline and bottom of percentage text
    LINE_H = 0.22   # vertical distance between percentage and category name

    def draw_group(group, ys, is_right):
        x_conn = X_R_CONN if is_right else X_L_CONN
        x_far  = X_R_FAR  if is_right else X_L_FAR
        ha     = "left"   if is_right else "right"

        for d, y_line in zip(group, ys):
            theta = d["theta"]
            pct   = d["pct"]
            cat   = d["cat"]

            # Point just outside the outer ring
            x0 = (r_outer + 0.02) * np.cos(theta)
            y0 = (r_outer + 0.02) * np.sin(theta)

            # ── Diagonal leader line ──────────────────────────────────────
            ax.plot([x0, x_conn], [y0, y_line],
                    color="#333333", lw=0.9, solid_capstyle="round",
                    clip_on=False, zorder=5)

            # ── Horizontal underline ──────────────────────────────────────
            ax.plot([x_conn, x_far], [y_line, y_line],
                    color="#333333", lw=0.9, solid_capstyle="round",
                    clip_on=False, zorder=5)

            # ── Percentage (just above underline) ─────────────────────────
            ax.text(x_conn, y_line + GAP,
                    f"{pct:.1f}%",
                    ha=ha, va="bottom",
                    fontsize=FS_PCT,
                    color="#555555",
                    clip_on=False)

            # ── Category name (bold, above percentage) ────────────────────
            ax.text(x_conn, y_line + GAP + LINE_H,
                    cat,
                    ha=ha, va="bottom",
                    fontsize=FS_PCT,
                    fontweight="bold",
                    color="#222222",
                    clip_on=False)

    draw_group(right, right_ys, is_right=True)
    draw_group(left,  left_ys,  is_right=False)

    ax.set_title(f"{title}\n{total_label}",
                 fontsize=FS_TITLE, fontweight="bold", pad=10)
    ax.set_xlim(-2.8, 2.8)
    ax.set_ylim(-1.9, 1.75)


tic_label = f"TIC: ${rcf_etoh_system.installed_cost/1e6:.1f} MM"
draw_pie(ax, ic_values, ic_categories, "Installed Cost Breakdown", tic_label)

plt.rcParams['svg.fonttype'] = 'none'
fig.tight_layout(rect=[0, 0.02, 1, 1])
fig.savefig("installed_cost_breakdown_5.svg", format="svg", bbox_inches="tight")


# ── Operating cost pie ────────────────────────────────────────────────────────
fig2, ax2 = plt.subplots(figsize=(fig_w_in, fig_h_in))

annual_op_cost = sum(op_values)
toc_label = f"TOC: ${annual_op_cost/1e6:.1f} MM/yr"
draw_pie(ax2, op_values, op_categories, "Operating Cost Breakdown", toc_label)

plt.rcParams['svg.fonttype'] = 'none'
fig2.tight_layout(rect=[0, 0.02, 1, 1])
fig2.savefig("operating_cost_breakdown.svg", format="svg", bbox_inches="tight")



