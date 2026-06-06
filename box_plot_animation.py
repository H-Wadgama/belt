import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.animation as animation
import matplotlib.patches as mpatches
from scipy import stats

plt.rc('font', family='Arial')

import os
_dir = os.path.dirname(os.path.abspath(__file__))
df = pd.read_excel(
    os.path.join(_dir, 'lignin_saf', 'uncertainty-gsa', 'bartling_trial_5.xlsx'),
    header=[0, 1], index_col=0, skiprows=[2]
)
msp_values = df[("TEA", "Minimum jet selling price [USD/gal]")].dropna().values
baseline_mjsp = 1.38

# Box plot statistics
q1, med, q3 = np.percentile(msp_values, [25, 50, 75])
iqr = q3 - q1
lower_w = msp_values[msp_values >= q1 - 1.5 * iqr].min()
upper_w = msp_values[msp_values <= q3 + 1.5 * iqr].max()
fliers = msp_values[(msp_values < q1 - 1.5 * iqr) | (msp_values > q3 + 1.5 * iqr)]

# KDE
pad = 0.05 * (msp_values.max() - msp_values.min())
x_min = msp_values.min() - pad
x_max = msp_values.max() + pad
xr = np.linspace(x_min, x_max, 500)
kde_vals = stats.gaussian_kde(msp_values)(xr)

# Subsample points for phase 1 (cap at 150 frames)
N_PTS = min(150, len(msp_values))
sample_idx = np.round(np.linspace(0, len(msp_values) - 1, N_PTS)).astype(int)
anim_pts = msp_values[sample_idx]
rng = np.random.default_rng(42)
jitter = rng.uniform(-0.33, 0.33, N_PTS)

# Frame counts per phase
F1 = N_PTS  # Phase 1: one frame per point
F2 = 60     # Phase 2: box construction  (20 whiskers + 15 box + 15 median + 10 fliers)
F3 = 60     # Phase 3: KDE               (40 curve sweep + 20 fill fade)
TOTAL = F1 + F2 + F3

BOX_Y = 1.0
BOX_H = 0.5  # matches matplotlib boxplot widths=0.5

fig = plt.figure(figsize=(4.5, 4.2))
gs = gridspec.GridSpec(2, 1, height_ratios=[1, 4], hspace=0.05)
ax_box = fig.add_subplot(gs[0])
ax_kde = fig.add_subplot(gs[1])


def ease(t):
    t = float(np.clip(t, 0.0, 1.0))
    return t * t * (3.0 - 2.0 * t)


def setup_axes():
    ax_box.set_xlim(x_min, x_max)
    ax_box.set_ylim(0.3, 1.7)
    ax_box.set_yticks([])
    ax_box.tick_params(axis='x', which='both', bottom=False, labelbottom=False)
    for sp in ax_box.spines.values():
        sp.set_visible(False)

    ax_kde.set_xlim(x_min, x_max)
    ax_kde.set_xlabel('RCF Crude price (USD/kg)', fontsize=12)
    ax_kde.set_ylabel('Probability density', fontsize=12)
    ax_kde.tick_params(axis='both', which='major', labelsize=10, width=1.0, length=5)
    for sp in ax_kde.spines.values():
        sp.set_linewidth(1)

    ax_box.axvline(baseline_mjsp, color='black', ls='--', lw=1.2, zorder=1)
    ax_kde.axvline(baseline_mjsp, color='black', ls='--', lw=1.2)
    ax_kde.text(baseline_mjsp, 1.02, 'Baseline MJSP', ha='center', va='bottom',
                fontsize=9, color='black', transform=ax_kde.get_xaxis_transform())


def draw_bg_points():
    ax_box.scatter(anim_pts, BOX_Y + jitter, s=8, color='#9bc3c0',
                   edgecolors='black', lw=0.3, alpha=0.12, zorder=2)
    ax_kde.scatter(anim_pts, np.zeros(N_PTS), marker='|', s=30,
                   color='black', alpha=0.18, lw=0.5, zorder=2)


def update(frame):
    ax_box.clear()
    ax_kde.clear()
    setup_axes()

    # ── Phase 1: points appear one by one ────────────────────────────────────
    if frame < F1:
        n = frame + 1
        ax_box.scatter(anim_pts[:n], BOX_Y + jitter[:n], s=8, color='#9bc3c0',
                       edgecolors='black', lw=0.3, alpha=0.7, zorder=3)
        ax_kde.scatter(anim_pts[:n], np.zeros(n), marker='|', s=30,
                       color='black', alpha=0.45, lw=0.5, zorder=3)
        ax_box.text(0.01, 0.95, f'n = {n}', transform=ax_box.transAxes,
                    fontsize=8, va='top', ha='left')

    # ── Phase 2: box plot builds ──────────────────────────────────────────────
    elif frame < F1 + F2:
        draw_bg_points()
        f2 = frame - F1

        # Eased progress for each sub-phase
        t_w = ease(f2 / 19)            # whiskers extend:  frames  0–19
        t_b = ease((f2 - 20) / 14)     # box fades in:     frames 20–34
        t_m = ease((f2 - 35) / 14)     # median appears:   frames 35–49
        t_f = ease((f2 - 50) / 9)      # fliers appear:    frames 50–59

        # Whiskers + caps
        lx = q1 - t_w * (q1 - lower_w)
        rx = q3 + t_w * (upper_w - q3)
        ax_box.plot([lx, q1], [BOX_Y, BOX_Y], 'k-', lw=1, zorder=4)
        ax_box.plot([lx, lx], [BOX_Y - BOX_H / 2, BOX_Y + BOX_H / 2], 'k-', lw=1, zorder=4)
        ax_box.plot([q3, rx], [BOX_Y, BOX_Y], 'k-', lw=1, zorder=4)
        ax_box.plot([rx, rx], [BOX_Y - BOX_H / 2, BOX_Y + BOX_H / 2], 'k-', lw=1, zorder=4)

        # Box rectangle fades in
        if t_b > 0:
            ax_box.add_patch(mpatches.Rectangle(
                (q1, BOX_Y - BOX_H / 2), q3 - q1, BOX_H,
                facecolor='#9bc3c0', edgecolor='black', lw=1, alpha=t_b, zorder=5
            ))

        # Median line fades in
        if t_m > 0:
            ax_box.plot([med, med], [BOX_Y - BOX_H / 2, BOX_Y + BOX_H / 2],
                        'k-', lw=1, alpha=t_m, zorder=6)

        # Fliers fade in
        if t_f > 0 and len(fliers) > 0:
            ax_box.scatter(fliers, np.full(len(fliers), BOX_Y),
                           marker='o', s=4, facecolors='none',
                           edgecolors='black', lw=0.5, alpha=t_f, zorder=7)

        # Baseline diamond appears with box
        t_d = ease((f2 - 20) / 14)
        if t_d > 0:
            ax_box.scatter(baseline_mjsp, BOX_Y, marker='D', s=50,
                           facecolor='lightgray', edgecolor='black',
                           lw=1, alpha=t_d, zorder=10)

    # ── Phase 3: KDE sweeps in ────────────────────────────────────────────────
    else:
        draw_bg_points()

        # Final static box plot
        ax_box.boxplot(
            msp_values, vert=False, widths=BOX_H, patch_artist=True,
            boxprops={"facecolor": "#9bc3c0", "edgecolor": 'black', "linewidth": 1},
            medianprops={"color": "black", "linewidth": 1},
            whiskerprops={"color": "black", "linewidth": 1},
            capprops={"color": "black", "linewidth": 1},
            flierprops={"marker": "o", "markersize": 2, "markerfacecolor": "none",
                        "markeredgecolor": "black", "markeredgewidth": 0.5}
        )
        ax_box.scatter(baseline_mjsp, 1, marker='D', s=50,
                       facecolor='lightgray', edgecolor='black', lw=1, zorder=10)
        ax_box.set_xlim(x_min, x_max)
        ax_box.set_ylim(0.3, 1.7)

        f3 = frame - F1 - F2
        i_curve = max(2, int(500 * ease(f3 / 39)))  # curve sweeps left→right: frames  0–39
        t_fill = ease((f3 - 40) / 19)               # fill fades in:           frames 40–59

        ax_kde.plot(xr[:i_curve], kde_vals[:i_curve], color='black', lw=1.5, zorder=4)
        if t_fill > 0:
            ax_kde.fill_between(xr, kde_vals, color='#bf9fb9', alpha=0.6 * t_fill, zorder=3)


anim = animation.FuncAnimation(fig, update, frames=TOTAL, interval=50, repeat=False)

# Requires Pillow: pip install pillow
anim.save('box_plot_animation2.gif', writer='pillow', fps=24, dpi=150)
# For a smaller, smoother file (requires ffmpeg):
# anim.save('box_plot_animation.mp4', writer='ffmpeg', fps=24, dpi=150)

plt.show()
