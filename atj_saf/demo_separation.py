import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')

import biosteam as bst

# chopper's modules import each other with bare same-directory imports
# (e.g. `from sweep_separation import ...`), which only resolve when that
# directory is on sys.path -- true when running a script from inside it
# directly, but not when importing it as a package from here.
sys.path.insert(0, str(Path(__file__).parent.parent / 'tools' / 'chopper'))

from optimizer import optimize_reflux_ratio
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

result = optimize_reflux_ratio(
    feed=feed,
    LHK=('Methanol', 'Water'),
    reflux_ratios_k=reflux_ratios_k,
    P=101325,
    spec='purity',
    target='top',
    purity_target=0.99,
    csv_path='demo_reflux_ratio_sweep.csv',
)

df = result['sweep_df']
print(df)

print(f"\nn_feasible: {result['n_feasible']}/{result['n_total']}")
print(result['message'])
if result['found']:
    print('\nBest design:')
    for k, v in result['best_design'].items():
        print(f'  {k}: {v}')

# 1. Call each plot function individually, saving each to its own file.
plot_purity_vs_reflux(df, save_path='demo_purity_vs_reflux.png', show=False)
plot_utility_cost_vs_reflux(df, save_path='demo_utility_cost_vs_reflux.png', show=False)

# 2. Or use the convenience wrapper to draw both at once.
plot_reflux_sweep(df, save_dir='.', show=False)

print('\nSaved: demo_purity_vs_reflux.png, demo_utility_cost_vs_reflux.png, '
      'purity_vs_reflux.png, utility_cost_vs_reflux.png')
