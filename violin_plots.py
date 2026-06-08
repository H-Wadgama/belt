import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.transforms as transforms
import numpy as np

BASE = 'lignin_saf/uncertainty-gsa'
TEA_COL = ('TEA', 'Minimum jet selling price [USD/gal]')

def load_mjsp(path):
    df = pd.read_excel(path, sheet_name=0, header=[0, 1], index_col=0)
    return df[TEA_COL].dropna().values


bartling = load_mjsp(f'{BASE}/bartling_trial_5.xlsx')
oil      = load_mjsp(f'{BASE}/oil_trial_1.xlsx')

datasets  = [bartling, oil]
positions = [1, 2]
COLORS    = ['#4E8098', '#C8963E']   # teal-blue, warm amber
LABELS    = ['Monomer purification\n(hexane LLE)', 'Oil purification\n(ethyl acetate LLE)']

fig, ax = plt.subplots(figsize=(6, 6))

for pos, data, color in zip(positions, datasets, COLORS):
    # violin
    vp = ax.violinplot(data, positions=[pos], widths=0.55,
                       showmedians=False, showextrema=False)
    body = vp['bodies'][0]
    body.set_facecolor(color)
    body.set_alpha(0.75)
    body.set_edgecolor('black')
    body.set_linewidth(1.2)

    # box-and-whisker drawn in white inside the violin
    q25, q50, q75 = np.percentile(data, [25, 50, 75])
    iqr = q75 - q25
    wlo = max(data.min(), q25 - 1.5 * iqr)
    whi = min(data.max(), q75 + 1.5 * iqr)
    bw  = 0.07   # half-width of the IQR box

    # whisker lines — simple black lines
    ax.vlines(pos, wlo, q25, color='black', lw=1.2, zorder=3)
    ax.vlines(pos, q75, whi, color='black', lw=1.2, zorder=3)
    # whisker caps
    ax.hlines([wlo, whi], pos - bw * 0.6, pos + bw * 0.6, color='black', lw=1.2, zorder=3)

    # IQR box (white fill, black border)
    box = mpatches.FancyBboxPatch(
        (pos - bw, q25), 2 * bw, iqr,
        boxstyle='square,pad=0', lw=1.2,
        edgecolor='black', facecolor='white', zorder=5
    )
    ax.add_patch(box)

    # median line in the box, colored to match violin
    ax.hlines(q50, pos - bw, pos + bw, color=color, lw=2.2, zorder=6)

# sample count labels just below the x-axis tick labels
# use a blended transform: x in data coords, y in axes-fraction coords
for pos, data in zip(positions, datasets):
    trans = transforms.blended_transform_factory(ax.transData, ax.transAxes)
    ax.text(pos, -0.08, f'{len(data):,}', ha='center', va='top',
            fontsize=9, color='#555555', transform=trans)

# axes styling — clean, no top/right spine (matches demo)
ax.set_xticks(positions)
ax.set_xticklabels(LABELS, fontsize=10)
ax.set_ylabel('MJSP [USD/gal]', fontsize=11)
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
ax.set_xlim(0.4, 2.6)
ax.tick_params(axis='x', length=0)

plt.tight_layout()
plt.savefig('violin_mjsp.svg', bbox_inches='tight')
plt.savefig('violin_mjsp.png', dpi=150, bbox_inches='tight')
plt.show()
print('Saved violin_mjsp.svg and violin_mjsp.png')
