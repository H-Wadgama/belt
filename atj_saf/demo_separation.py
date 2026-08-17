import matplotlib
matplotlib.use('Agg')

import biosteam as bst

from sweep_separation import sweep_reflux_ratio
from separation_plots import (
    plot_purity_vs_reflux,
    plot_utility_cost_vs_reflux,
    plot_reflux_sweep,
)

bst.settings.set_thermo(['Water', 'Methanol', 'Glycerol'], cache=True)

feed = bst.Stream('feed', flow=(80, 100, 25), units='kmol/hr')
feed.T = feed.bubble_point_at_P().T

# k multipliers over minimum reflux, not absolute L/D values.
reflux_ratios_k = [1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5]

df = sweep_reflux_ratio(
    feed=feed,
    LHK=('Methanol', 'Water'),
    reflux_ratios_k=reflux_ratios_k,
    P=101325,
    spec='purity',
    target='top',
    y_top=0.99,
    x_bot=0.01,
    csv_path='demo_reflux_ratio_sweep.csv',
)

print(df)

# 1. Call each plot function individually, saving each to its own file.
plot_purity_vs_reflux(df, save_path='demo_purity_vs_reflux.png', show=False)
plot_utility_cost_vs_reflux(df, save_path='demo_utility_cost_vs_reflux.png', show=False)

# 2. Or use the convenience wrapper to draw both at once.
plot_reflux_sweep(df, save_dir='.', show=False)

print('Saved: demo_purity_vs_reflux.png, demo_utility_cost_vs_reflux.png, '
      'purity_vs_reflux.png, utility_cost_vs_reflux.png')
