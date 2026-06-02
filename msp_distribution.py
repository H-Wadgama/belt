import pandas as pd
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt
from scipy import stats

plt.rc('font', family='Arial')

import os
_dir = os.path.dirname(os.path.abspath(__file__))
df = pd.read_csv(
    os.path.join(_dir, 'lignin_saf', 'spearman_gsa_5000_runs.csv'),
    header=[0, 1], index_col=0, skiprows=[2], encoding='utf-8-sig'
)

msp_values = df[("TEA", "Minimum jet selling price [USD/gal]")].dropna().values

fig, ax = plt.subplots(figsize=(4.5, 3.5))

ax.hist(
    msp_values,
    bins=60,
    density=True,
    color="#44AA99",
    edgecolor='white',
    linewidth=0.3,
    alpha=0.85,
    label='Simulated runs'
)

kde = stats.gaussian_kde(msp_values)
x_range = np.linspace(msp_values.min(), msp_values.max(), 500)
ax.plot(x_range, kde(x_range), color='black', linewidth=1.5, label='KDE')

p10, p50, p90 = np.percentile(msp_values, [10, 50, 90])
ax.axvline(p50, color='black', linestyle='--', linewidth=1.0, label=f'Median: ${p50:.2f}/gal')
ax.axvline(p10, color='gray', linestyle=':', linewidth=1.0, label=f'P10: ${p10:.2f}/gal')
ax.axvline(p90, color='gray', linestyle=':', linewidth=1.0, label=f'P90: ${p90:.2f}/gal')

ax.set_xlabel('MJSP (USD/gal)', fontsize=12, color='black')
ax.set_ylabel('Probability density', fontsize=12, color='black')

ax.tick_params(axis='both', which='major', labelsize=10, width=1.0, length=5)
for spine in ax.spines.values():
    spine.set_linewidth(1)

ax.legend(fontsize=8, frameon=False)

plt.tight_layout()
plt.savefig('msp_distribution.png', dpi=300, bbox_inches='tight')
plt.savefig('msp_distribution.svg', bbox_inches='tight')
#plt.show()

print(f"N = {len(msp_values):,}")
print(f"Mean:   ${msp_values.mean():.2f}/gal")
print(f"Median: ${p50:.2f}/gal")
print(f"Std:    ${msp_values.std():.2f}/gal")
print(f"P10:    ${p10:.2f}/gal")
print(f"P90:    ${p90:.2f}/gal")
