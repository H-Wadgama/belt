import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from scipy import stats

plt.rc('font', family='Arial')

import os
_dir = os.path.dirname(os.path.abspath(__file__))
df = pd.read_excel(
    os.path.join(_dir, 'lignin_saf', 'uncertainty-gsa', 'bartling_trial_7.xlsx'),
    header=[0, 1], index_col=0, skiprows=[2]
)

msp_values = df[("TEA", "Minimum jet selling price [USD/gal]")].dropna().values

fig = plt.figure(figsize=(6, 3.7))
gs = gridspec.GridSpec(2, 1, height_ratios=[1, 4], hspace=0.05)

ax_box = fig.add_subplot(gs[0])
ax_kde = fig.add_subplot(gs[1], sharex=ax_box)

# KDE
kde = stats.gaussian_kde(msp_values)
x_range = np.linspace(msp_values.min(), msp_values.max(), 500)
kde_values = kde(x_range)
ax_kde.plot(x_range, kde_values, color='black', linewidth=1.5)
ax_kde.fill_between(x_range, kde_values, color='#e39e9c', alpha=0.6)

#baseline_mjsp = 1.26
#ax_kde.axvline(baseline_mjsp, color='#a87c9f', linestyle='--', linewidth=1.2)
#e39e9c
bartling_price = 1.13
ax_kde.axvline(bartling_price, color='#43706c', linestyle=':', linewidth=1.5)
#ax_kde.text(baseline_mjsp, 1.02, 'Baseline MJSP',
#            ha='center', va='bottom', fontsize=9, color='black',
#            transform=ax_kde.get_xaxis_transform())

from matplotlib.lines import Line2D
legend_elements = [
    #Line2D([0], [0], color='#a87c9f', linestyle='--', linewidth=1.2, label='Baseline (this work)'),
    Line2D([0], [0], color='#43706c', linestyle=':', linewidth=1.5, label='Bartling et al.'),
]
ax_kde.legend(handles=legend_elements, loc='upper right', fontsize=9,
              frameon=True, framealpha=0.8, edgecolor='none')

ax_kde.set_xlabel('MSP of crude RCF oil (USD/kg)', fontsize=12, color='black')
ax_kde.set_ylabel('Probability density', fontsize=12, color='black')
ax_kde.tick_params(axis='both', which='major', labelsize=10, width=1.0, length=5)
for spine in ax_kde.spines.values():
    spine.set_linewidth(1)

# Horizontal box plot
ax_box.boxplot(
    msp_values,
    vert=False,
    widths=0.5,
    patch_artist=True,
    boxprops={"facecolor": "#d87774", "edgecolor": 'black', "linewidth": 1},
    medianprops={"color": "black", "linewidth": 1},
    whiskerprops={"color": "black", "linewidth": 1},
    capprops={"color": "black", "linewidth": 1},
    flierprops={"marker": "o", "markersize": 2, "markerfacecolor": "none",
                "markeredgecolor": "black", "markeredgewidth": 0.5}
)
#ax_box.scatter(baseline_mjsp, 1, marker='D', s=50,
#               facecolor='lightgray', edgecolor='black', linewidth=1, zorder=10)
#ax_box.axvline(baseline_mjsp, color='#a87c9f', linestyle='--', linewidth=1.2)
ax_box.axvline(bartling_price, color='#43706c', linestyle=':', linewidth=1.5)

ax_box.set_yticks([])
ax_box.tick_params(axis='x', which='both', bottom=False, labelbottom=False)
for spine in ax_box.spines.values():
    spine.set_visible(False)

plt.savefig('box_plot_distribution_bartling2.png', dpi=600, bbox_inches='tight')
plt.savefig('box_plot_distribution_bartling2.svg', bbox_inches='tight')
plt.show()
