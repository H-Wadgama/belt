import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.lines as mlines
import numpy as np

import os
_dir = os.path.dirname(os.path.abspath(__file__))
df = pd.read_csv(os.path.join(_dir, 'morris-100-sigma-mu.csv'), encoding='utf-8-sig')
plt.rc('font',family='Arial')


# ── Parameters to include ────────────────────────────────────────────────────
PARAMS = [
    'HDO reaction time',
    'HDO solvent loading',
    'HDO catalyst loading',
    'HDO catalyst lifetime',
    'Dodecane cost',
]
# ─────────────────────────────────────────────────────────────────────────────

# Style per parameter: (marker, facecolor)
STYLES = [
    ('o',  '#e63946'),  # circle       – red
    ('s',  '#457b9d'),  # square       – steel blue
    ('^',  '#2a9d8f'),  # triangle up  – teal
    ('D',  '#e9c46a'),  # diamond      – amber
    ('v',  '#f4a261'),  # triangle dn  – orange
#    ('p',  '#6a4c93'),  # pentagon     – purple
#    ('*',  '#1d3557'),  # star         – navy
#    ('h',  '#a8dadc'),  # hexagon      – light teal
#    ('P',  '#e76f51'),  # plus         – burnt orange
#    ('X',  '#52b788'),  # x-fill       – green
]

df = df[df['Feature'].isin(PARAMS)].set_index('Feature').loc[PARAMS]

mu     = df['µ*'].values
sigma  = df['σ'].values
labels = df.index.values

# ── figure ───────────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(7, 5.5))

legend_handles = []

for i, (lbl, (marker, color)) in enumerate(zip(labels, STYLES)):
    ax.plot(
        mu[i], sigma[i],
        marker=marker,
        color=color,
        linestyle='None',
        markersize=8 if marker == '*' else 7,
        markeredgewidth=0.6,
        markeredgecolor='white',
        alpha=0.92,
        zorder=3,
    )
    handle = mlines.Line2D(
        [], [], marker=marker, color=color,
        linestyle='None',
        markersize=7 if marker == '*' else 6,
        markeredgewidth=0.5,
        markeredgecolor='white',
        label=lbl,
    )
    legend_handles.append(handle)

lim = max(ax.get_xlim()[1], ax.get_ylim()[1])
ax.plot([0, lim], [0, lim], linestyle=':', color='gray', linewidth=0.9, zorder=1)

ax.set_xlabel(r'$\mu^*$', fontsize=16)
ax.set_ylabel(r'$\sigma$', fontsize=16)
ax.set_title('Morris method 100 (HDO)', fontsize=16, fontweight='bold', pad=12)

for spine in ax.spines.values():
    spine.set_linewidth(0.8)
ax.tick_params(labelsize=16, length=4, width=0.8)

legend = ax.legend(
    handles=legend_handles,
    fontsize=12,
    frameon=False,
    framealpha=0.95,
    edgecolor='#cccccc',
    loc='upper left',
    handletextpad=0.6,
    borderpad=0.8,
    labelspacing=0.5,
)
legend.get_frame().set_linewidth(0.6)

plt.tight_layout()
plt.savefig('morris_100_hdo.png', dpi=300, bbox_inches='tight')
print("Saved.")