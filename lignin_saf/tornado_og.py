"""
Local Sensitivity Analysis — Tornado Plot
==========================================
Baseline MJSP = $22.05  (adjust X_LABEL and BASELINE_MJSP below as needed)

Bar shading convention:
  DARK  shade  →  bar at LOW  parameter value
  LIGHT shade  →  bar at HIGH parameter value

Y-axis label format:  "Parameter [baseline_value] (unit)"
"""

import matplotlib
matplotlib.use("Agg")          # remove this line if running interactively
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.transforms as mtransforms
import numpy as np

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION  ← edit here
# ─────────────────────────────────────────────────────────────────────────────
BASELINE_MJSP = 22.05
X_LABEL       = "Minimum Selling Price (USD GJ$^{-1}$)"

# Category colors: (dark_shade, light_shade)
#   DARK  = bar when parameter is at its LOW  value
#   LIGHT = bar when parameter is at its HIGH value
COLORS = {
    "Overall": ("#1565C0", "#90CAF9"),   # blue
    "RCF":     ("#BF360C", "#FFCCBC"),   # deep orange
    "HDO":     ("#2E7D32", "#A5D6A7"),   # green
    "EHF":     ("#6A1B9A", "#CE93D8"),   # purple
    "OP":      ("#AD1457", "#F48FB1"),   # pink
    "MP":      ("#00695C", "#80CBC4"),   # teal
}
CAT_ORDER = ["Overall", "RCF", "HDO", "EHF", "OP", "MP"]


# ─────────────────────────────────────────────────────────────────────────────
# DATA
# (label, unit, category, param_baseline, param_low, param_high,
#  mjsp_at_low_param, mjsp_at_high_param)
# ─────────────────────────────────────────────────────────────────────────────
data = [
    # ── Overall / system-wide ───────────────────────────────────────────────
    ("Operating days",              "days",               "Overall", 330,      297,      363,      22.82, 21.42),
    ("Poplar feedstock",            "USD/dry MT",         "Overall", 70,       50,       100,      21.59, 22.74),
    ("Labor cost",                  "MM USD/yr",          "Overall", 17.89,    8.94,     26.83,    21.51, 22.59),
    ("Electricity cost",            "c/kWh",              "Overall", 8.26,     6.41,     17.98,    22.06, 21.97),
    ("Renewable naphtha price",     "USD/kg",             "Overall", 0.57,     0.505,    0.77,     22.12, 21.84),
    ("Renewable diesel price",      "USD/kg",             "Overall", 1.28,     0.63,     1.48,     22.09, 22.04),
    ("Hydrogen cost",               "USD/kg",             "Overall", 3.7,      2.74,     11.53,    21.77, 24.37),
    ("Hydrogen storage time",       "days",               "Overall", 0.5,      0.25,     3,        21.97, 22.91),
    # ── RCF ────────────────────────────────────────────────────────────────
    ("Reactor pressure",            "bar",                "RCF",     63,       63,       83.3,     22.05, 22.40),
    ("Solvolysis residence time",   "hr",                 "RCF",     18,       9,        36,       30.28, 18.31),
    ("Time on stream",              "hr",                 "RCF",     3,        1,        4,        16.73, 24.68),
    ("Methanol cost",               "USD/kg",             "RCF",     0.331,    0.2648,   0.3972,   21.20, 22.90),
    ("Catalyst cost (RCF)",         "USD/kg",             "RCF",     37.5,     18.75,    56.25,       22.05, 22.05),
    ("Catalyst lifetime (RCF)",     "months",             "RCF",     12,       6,        24,       22.05, 22.05),
    ("Catalyst loading (RCF)",      "kg/kg dry biomass",  "RCF",     0.1,      0.05,     0.15,     22.05, 22.05),
    ("Reactor cleaning time",       "hr",                 "RCF",     1,        0.5,      4,        22.03, 23.50),
    ("Solvent loss (drying pulp)",  "%",                  "RCF",     0.01,     0.005,    0.1,      22.04, 23.62),
    ("Cellulose retention",         "%",                  "RCF",     0.9,      0.8,      1,        23.67, 20.69),
    ("Xylose retention",            "%",                  "RCF",     0.93,     0.2,      1,        25.79, 21.74),
    ("Delignification",             "%",                  "RCF",     0.563,    0.4,      0.9,      21.94, 21.99),
    ("Condensation extent",         "%",                  "RCF",     0.136,    0,        0.709,    21.67, 23.96),
    # ── HDO ────────────────────────────────────────────────────────────────
    ("Reaction time",               "hr",                 "HDO",     5,        2,        8,        21.29, 22.68),
    ("Solvent loading",             "m3/kg HDO lignin",   "HDO",     0.04,     0.01,     0.07,     19.77, 23.95),
    ("Catalyst loading (HDO)",      "kg/kg HDO lignin",   "HDO",     0.8,      0.4,      1.2,      21.94, 22.15),
    ("Catalyst lifetime (HDO)",     "yr",                 "HDO",     6,        3,        12,       22.26, 21.94),
    ("Catalyst cost (HDO)",         "USD/kg",             "HDO",     158.4,    79.2,     237.6,    21.94, 22.15),
    ("Solvent cost",                "USD/kg",             "HDO",     0.5022,   0.10044,  0.90396,  21.18, 22.90),
    # ── EHF ────────────────────────────────────────────────────────────────
    ("Conv. glucose to ethanol",    "%",                  "EHF",     0.95,     0.7,      0.95,     25.27, 22.05),
    ("Conv. glucan to glucose",     "%",                  "EHF",     0.9,      0.7,      0.9,      25.05, 22.05),
    ("Saccharification res. time",  "hr",                 "EHF",     60,       48,       72,       22.03, 22.07),
    ("Cofermentation res. time",    "hr",                 "EHF",     36,       28.8,     43.2,     22.04, 22.06),
    ("Conv. xylan to xylose",       "%",                  "EHF",     0.9,      0.7,      0.9,      22.80, 22.05),
    ("Conv. xylose to ethanol",     "%",                  "EHF",     0.85,     0.7,      0.9,      22.58, 21.88),
    ("M.301 solids loading",        "wt%",                "EHF",     0.2,      0.1,      0.3,      22.14, 22.05),
    ("M.301 enzyme loading",        "wt%",                "EHF",     0.02,     0.01,     0.05,     21.25, 24.45),
    ("Cellulase price",             "USD/kg",             "EHF",     0.3877,   0.1939,   0.5816,   21.24, 22.86),
    # ── OP / MP ────────────────────────────────────────────────────────────
    ("EtOAc to crude RCF oil",      "kg/kg",              "OP",      9.1,      7.28,     10.92,    21.60, 22.49),
    ("Ethyl acetate price",         "USD/kg",             "OP",      0.77,     0.385,    1.155,    21.09, 22.97),
    ("Hexane to pure RCF oil",      "kg/kg",              "MP",      3.5,      1,        5,        21.51, 22.39),
    ("Hexane price",                "USD/kg",             "MP",      1.18,     0.59,     1.77,   21.76, 22.45),
]


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def fmt_num(v):
    """Smart formatter: integers as int, floats with minimal significant decimals."""
    try:
        if float(v) == int(float(v)):
            return str(int(float(v)))
    except (TypeError, ValueError, OverflowError):
        return str(v)
    v = float(v)
    if abs(v) >= 100: return f"{v:.0f}"
    if abs(v) >= 10:  return f"{v:.1f}"
    if abs(v) >= 1:   return f"{v:.2f}"
    if abs(v) >= 0.1: return f"{v:.3f}"
    return f"{v:.4f}"


# ─────────────────────────────────────────────────────────────────────────────
# SORT  (descending swing so largest bar appears at the top after invert_yaxis)
# ─────────────────────────────────────────────────────────────────────────────
data_sorted = sorted(data, key=lambda r: abs(r[7] - r[6]), reverse=True)

n  = len(data_sorted)
ys = np.arange(n)

# Y-tick labels: "Parameter [baseline] (unit)"
y_labels = [f"{r[0]} [{fmt_num(r[3])}] ({r[1]})" for r in data_sorted]


# ─────────────────────────────────────────────────────────────────────────────
# PLOT
# ─────────────────────────────────────────────────────────────────────────────
BAR_H = 0.60    # bar height (data units)
LPAD  = 0.06    # gap between bar tip and its value annotation
FS    = 7.5     # font size for bar-end annotations

fig, ax = plt.subplots(figsize=(14, n * 0.42 + 2.5))

for i, (name, unit, cat, p_base, p_low, p_high, m_low, m_high) in enumerate(data_sorted):
    dark_c, light_c = COLORS[cat]
    y = ys[i]

    # Each half-bar is anchored at the baseline and extends toward m_low / m_high
    w_low  = abs(m_low  - BASELINE_MJSP)
    w_high = abs(m_high - BASELINE_MJSP)
    l_low  = min(m_low,  BASELINE_MJSP)
    l_high = min(m_high, BASELINE_MJSP)

    # Draw the longer bar first so the shorter one is fully visible on top
    bar_specs = sorted(
        [(w_low,  l_low,  dark_c),
         (w_high, l_high, light_c)],
        key=lambda b: b[0], reverse=True
    )
    for w, l, color in bar_specs:
        if w > 1e-6:
            ax.barh(y, w, BAR_H, left=l, color=color,
                    edgecolor='white', linewidth=0.4, zorder=2)

    # ── Bar-end annotations: show the parameter value at each bound ───────
    for m_val, p_val in [(m_low, p_low), (m_high, p_high)]:
        if abs(m_val - BASELINE_MJSP) < 1e-6:
            continue  # zero-length bar → skip label
        if m_val < BASELINE_MJSP:
            ax.text(m_val - LPAD, y, fmt_num(p_val),
                    ha='right', va='center', fontsize=FS, color='#1a1a1a')
        else:
            ax.text(m_val + LPAD, y, fmt_num(p_val),
                    ha='left',  va='center', fontsize=FS, color='#1a1a1a')


# ── Baseline vertical line ────────────────────────────────────────────────
ax.axvline(BASELINE_MJSP, color='black', linewidth=1.6, zorder=5)

# Baseline label: annotate just above the top x-tick using data coords
# (placed at y = -0.5 in the inverted axis, which is just above the first row)
ax.annotate(
    f"${BASELINE_MJSP:.2f}",
    xy=(BASELINE_MJSP, -0.5), xycoords='data',
    xytext=(0, 4), textcoords='offset points',
    ha='center', va='bottom', fontsize=8.5, fontweight='bold', color='black'
)


# ── Y-axis ────────────────────────────────────────────────────────────────
ax.set_yticks(ys)
ax.set_yticklabels(y_labels, fontsize=8.0)
ax.invert_yaxis()                          # y=0 (largest swing) goes to top
ax.tick_params(axis='y', length=0, pad=4)
ax.set_ylim(n - 0.5, -0.5)               # restore sensible limits after invert


# ── X-axis ────────────────────────────────────────────────────────────────
ax.set_xlabel(X_LABEL, fontsize=10, labelpad=8)
ax.tick_params(axis='x', labelsize=9)
ax.grid(axis='x', which='major', linestyle='--', linewidth=0.5,
        alpha=0.4, zorder=0)


# ── Spine cleanup ─────────────────────────────────────────────────────────
for spine in ['top', 'right', 'left']:
    ax.spines[spine].set_visible(False)
ax.spines['bottom'].set_linewidth(0.8)


# ── Legend ────────────────────────────────────────────────────────────────
present_cats = {r[2] for r in data}
handles = []
for cat in CAT_ORDER:
    if cat not in present_cats:
        continue
    dc, lc = COLORS[cat]
    handles += [
        mpatches.Patch(facecolor=dc, edgecolor='#888', linewidth=0.5,
                       label=f"{cat} — low"),
        mpatches.Patch(facecolor=lc, edgecolor='#888', linewidth=0.5,
                       label=f"{cat} — high"),
    ]

leg = ax.legend(
    handles=handles, fontsize=7.5, ncol=3, loc='lower right',
    framealpha=0.93, edgecolor='#cccccc',
    title="Dataset  (dark = low param value,  light = high param value)",
    title_fontsize=7.5,
)
leg.get_frame().set_linewidth(0.6)


# ── Title ─────────────────────────────────────────────────────────────────
ax.set_title(
    "Local Sensitivity Analysis — Tornado Plot",
    fontsize=11, pad=14, loc='left', fontweight='bold'
)


# ── Layout & Save ─────────────────────────────────────────────────────────
fig.subplots_adjust(left=0.285, right=0.97, top=0.95, bottom=0.05)

plt.savefig("tornado_plot_v2.png", dpi=300, bbox_inches=None)
#plt.savefig("tornado_plot.pdf", bbox_inches=None)
# print("Saved: tornado_plot.png  |  tornado_plot.pdf")