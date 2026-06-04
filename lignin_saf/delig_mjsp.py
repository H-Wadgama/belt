import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

# Data (MM$ → BB$)
delignification = [0.563, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]
opex  = [v/1000 for v in [5218.321024, 5309.862235, 5439.598944, 5562.980258, 5693.119151, 5816.81811,  5946.523436, 6076.374523, 6200.104241]]
capex = [v/1000 for v in [1485.348204, 1494.672728, 1536.056677, 1542.900722, 1586.246676, 1597.243003, 1635.257163, 1676.443406, 1687.369986]]
sales = [v/1000 for v in [6771.141244, 6872.456452, 7045.429989, 7176.014355, 7351.436913, 7486.670278, 7656.097277, 7828.978816, 7964.170098]]
msp   = [22.08, 22.02, 22.07, 21.98, 22.03, 21.96, 21.99, 22.03, 21.96]

x = np.arange(len(delignification))
bar_width = 0.28
gap = 0.03


plt.rc('font',family='Arial')
plt.rcParams.update({
    'font.family': 'serif',
    'font.size': 10,
    'axes.linewidth': 0.8,
    'xtick.major.width': 0.8,
    'ytick.major.width': 0.8,
    'xtick.minor.width': 0.6,
    'ytick.minor.width': 0.6,
    'xtick.major.size': 4,
    'ytick.major.size': 4,
    'xtick.minor.size': 2.5,
    'ytick.minor.size': 2.5,
    'xtick.direction': 'in',
    'ytick.direction': 'in',
})

color_opex  = '#C07B6B'
color_capex = '#D4A59A'
color_sales = '#6A9BAF'
color_msp   = '#2E5F6E'

fig, ax1 = plt.subplots(figsize=(9, 5))

# --- Bars ---
ax1.bar(x - bar_width/2 - gap, [-v for v in opex],  width=bar_width, color=color_opex,  label='OPEX', zorder=3)
ax1.bar(x - bar_width/2 - gap, [-v for v in capex], width=bar_width, color=color_capex, label='CAPEX (FCI)',
        bottom=[-v for v in opex], zorder=3)
ax1.bar(x + bar_width/2 + gap, sales, width=bar_width, color=color_sales, label='Sales', zorder=3)

# Zero line
ax1.axhline(0, color='black', linewidth=0.8)

# Spines
ax1.spines['top'].set_visible(False)
for s in ['bottom', 'left', 'right']:
    ax1.spines[s].set_linewidth(0.8)

# Y axis: keep actual sign (negative shows as negative)
ax1.yaxis.set_major_formatter(ticker.FuncFormatter(lambda val, _: f'{val:.1f}'))
ax1.yaxis.set_minor_locator(ticker.AutoMinorLocator(2))
ax1.xaxis.set_minor_locator(ticker.NullLocator())
ax1.set_ylabel('Billion USD (BB $)', fontsize=10)
ax1.set_xticks(x)
ax1.set_xticklabels([str(d) for d in delignification], fontsize=9)
ax1.set_xlabel('Delignification', fontsize=10)
ax1.tick_params(which='both', direction='in', top=False, right=False)

# --- MSP line on ax2, starting from 0 ---
ax2 = ax1.twinx()
ax2.plot(x, msp, color=color_msp, linewidth=1.4, marker='o', markersize=4.5,
         markerfacecolor='white', markeredgewidth=1.4, markeredgecolor=color_msp,
         label='MSP', zorder=5)
ax2.set_ylabel('Minimum Selling Price ($/GJ)', fontsize=10)

ax2.spines['top'].set_visible(False)
ax2.spines['right'].set_linewidth(0.8)

# Start from 0, give some headroom above max
ax2.set_ylim(0, max(msp) * 1.15)
ax2.yaxis.set_major_formatter(ticker.FormatStrFormatter('%.1f'))
ax2.yaxis.set_minor_locator(ticker.AutoMinorLocator(2))
ax2.tick_params(which='both', direction='in')

# --- Combined legend ---
handles1, labels1 = ax1.get_legend_handles_labels()
handles2, labels2 = ax2.get_legend_handles_labels()
ax1.legend(handles1 + handles2, labels1 + labels2,
           frameon=True, framealpha=1, edgecolor='0.8',
           fontsize=9, loc='lower right')
plt.rcParams['svg.fonttype'] = 'none'
plt.tight_layout()
plt.savefig('delignification_chart.png', dpi=300, bbox_inches='tight')
plt.show()