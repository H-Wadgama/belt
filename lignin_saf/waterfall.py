"""
MJSP waterfall — v4 final (wider figure, inset flush right)
Layout: base(0) rcf(1.5) hdo(3) feed(4.5) chem(6) target(7.5) | inset from x≈8.5 onward
Figure is wider (21") so the inset lives entirely to the right of Target.
"""

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.transforms import blended_transform_factory

plt.rcParams.update({
    "font.family":        "sans-serif",
    "font.sans-serif":    ["Arial", "Helvetica", "DejaVu Sans"],
    "axes.spines.top":    False,
    "axes.spines.right":  False,
    "axes.spines.left":   False,
    "axes.spines.bottom": True,
    "xtick.bottom":       False,
    "ytick.left":         False,
    "axes.grid":          False,
})

# ─── Data ─────────────────────────────────────────────────────────────────────
base_val = 17.13
rcf_steps  = [(13.77,"#C0307A","A"),(13.15,"#E05090","B"),(12.86,"#F090B0","C")]
hdo_steps  = [(12.09,"#D05000","A"),(10.26,"#2A9D6A","B"),(10.13,"#50C896","C")]
feed_steps = [( 9.68,"#E07020","A")]
chem_steps = [
    ( 8.89,"#3A48C0","A"),( 8.79,"#5060CC","B"),( 8.67,"#6878D8","C"),
    ( 8.74,"#8090E0","D"),( 8.41,"#7B68EE","E"),( 8.22,"#9370DB","F"),
    ( 8.08,"#A855C8","G"),
]
target_val = 8.08

# ─── Layout ───────────────────────────────────────────────────────────────────
pos  = dict(base=0.0, rcf=1.5, hdo=3.0, feed=4.5, chem=6.0, target=7.5)
BW   = 0.52
XLIM = (-0.9, 9.2)
YLIM = (0, 20.5)

def fmt(d):
    s = "+" if d >= 0 else "−"
    return f"US${s}{abs(d):.2f} gal⁻¹"

def fbar(ax, x, lo, hi, col, hatch=None):
    ec = "#AA2222" if hatch else "white"
    ax.bar(x, hi-lo, bottom=lo, color=col, width=BW,
           edgecolor=ec, linewidth=0.8, hatch=hatch, zorder=3)

def conn(ax, x0, x1, y):
    ax.plot([x0+BW/2, x1-BW/2], [y, y],
            color="#CCCCCC", lw=0.8, ls="--", zorder=2)

def tick_lbl(ax, x, y, letter):
    lx = x - BW/2
    ax.plot([lx-0.18, lx-0.01], [y, y], color="#999999", lw=0.9, zorder=4)
    ax.text(lx-0.22, y, letter, ha="right", va="center",
            fontsize=7.5, fontweight="bold", color="#555555", zorder=5)

def delta_r(ax, x, y, text, col, fs=7.4):
    ax.text(x+BW/2+0.09, y, text, ha="left", va="center",
            fontsize=fs, color=col, zorder=5)

def lbl_above(ax, x, y, text, col, fs=8.2, dy=0.15):
    ax.text(x, y+dy, text, ha="center", va="bottom",
            fontsize=fs, fontweight="bold", color=col, zorder=5)

# ─── Figure (wide) ────────────────────────────────────────────────────────────
fig = plt.figure(figsize=(19, 7.5))
fig.patch.set_facecolor("white")

# Main axes occupies left ~55% of figure width
ax = fig.add_axes([0.05, 0.30, 0.52, 0.62])
ax.set_facecolor("white")

# ── Base ──────────────────────────────────────────────────────────────────────
ax.bar(pos["base"], base_val, color="#AAAAAA", width=BW, zorder=3)
lbl_above(ax, pos["base"], base_val, f"US${base_val:.2f} gal⁻¹", "#555555", fs=8.5)

# ── RCF ───────────────────────────────────────────────────────────────────────
conn(ax, pos["base"], pos["rcf"], base_val)
prev = base_val
for end_v, col, lbl in rcf_steps:
    fbar(ax, pos["rcf"], end_v, prev, col)
    mid = (prev+end_v)/2
    tick_lbl(ax, pos["rcf"], mid, lbl)
    delta_r(ax, pos["rcf"], mid, fmt(end_v-prev), col)
    prev = end_v
rcf_end = prev

# ── HDO ───────────────────────────────────────────────────────────────────────
conn(ax, pos["rcf"], pos["hdo"], rcf_end)
prev = rcf_end
for end_v, col, lbl in hdo_steps:
    fbar(ax, pos["hdo"], end_v, prev, col)
    mid = (prev+end_v)/2
    tick_lbl(ax, pos["hdo"], mid, lbl)
    delta_r(ax, pos["hdo"], mid, fmt(end_v-prev), col)
    prev = end_v
hdo_end = prev

# ── Feedstock ─────────────────────────────────────────────────────────────────
conn(ax, pos["hdo"], pos["feed"], hdo_end)
prev = hdo_end
end_v, col, lbl = feed_steps[0]
fbar(ax, pos["feed"], end_v, prev, col)
mid = (prev+end_v)/2
tick_lbl(ax, pos["feed"], mid, lbl)
lbl_above(ax, pos["feed"], prev, fmt(end_v-prev), col, fs=8.0)
feed_end = end_v

# ── Other chemicals — stacked ─────────────────────────────────────────────────
conn(ax, pos["feed"], pos["chem"], feed_end)
prev_c = feed_end
for end_v, col, lbl in chem_steps:
    lo, hi = sorted((prev_c, end_v))
    fbar(ax, pos["chem"], lo, hi, col, hatch="///" if end_v > prev_c else None)
    prev_c = end_v
chem_end = prev_c
lbl_above(ax, pos["chem"], feed_end, fmt(chem_end-feed_end), "#3A48C0", fs=8.0)

# ── Target ────────────────────────────────────────────────────────────────────
conn(ax, pos["chem"], pos["target"], chem_end)
ax.bar(pos["target"], target_val, color="#606060", width=BW, zorder=3)
lbl_above(ax, pos["target"], target_val, f"US${target_val:.2f} gal⁻¹", "#444444", fs=8.5)

# ─── SAF + Y-axis ─────────────────────────────────────────────────────────────
# SAF at figure level, top-right corner
fig.text(0.985, 0.96, "SAF", ha="right", va="top", fontsize=11, color="#444444")
for yv in range(0, 21, 5):
    ax.plot([-0.62,-0.52], [yv,yv], color="#BBBBBB", lw=0.8, zorder=1)
    ax.text(-0.67, yv, str(yv), ha="right", va="center",
            fontsize=8, color="#888888")
ax.text(-1.12, 10, "MJSP (USD gal⁻¹)", ha="center", va="center",
        fontsize=9, color="#666666", rotation=90)

# ─── Main axes styling ────────────────────────────────────────────────────────
ax.set_ylim(*YLIM); ax.set_xlim(*XLIM)
ax.spines["bottom"].set_linewidth(1.2)
ax.set_yticks([])
ax.tick_params(axis="x", bottom=False, labelbottom=False)
ax.axhline(0, color="#888888", lw=1.2, zorder=1)

# ── Zoom rectangle around stacked column ─────────────────────────────────────
zx0 = pos["chem"] - BW/2 - 0.06
zx1 = pos["chem"] + BW/2 + 0.06
zy0 = chem_end - 0.12
zy1 = feed_end + 0.12
ax.add_patch(Rectangle((zx0, zy0), zx1-zx0, zy1-zy0,
             fill=False, edgecolor="#777777", lw=1.0, zorder=6))

# ─── Category labels ──────────────────────────────────────────────────────────
blend = blended_transform_factory(ax.transData, ax.transAxes)
cats = [
    (pos["base"],  "Base case",        None),
    (pos["rcf"],   "RCF\noptimization",
     "A.  Reaction time → 1 hr\nB.  Residence time → 36 min\nC.  No external H₂"),
    (pos["hdo"],   "HDO\noptimization",
     "A.  Batch time → 2 hr\nB.  Solvent loading → 10 L/kg\nC.  Dodecane −50%"),
    (pos["feed"],  "Feedstock\nprice", "A.  Poplar → 50 USD/DMT"),
    (pos["chem"],  "Other\nchemicals", "see inset →"),
    (pos["target"],"Target",           None),
]
for x, name, desc in cats:
    ax.text(x, -0.065, name, transform=blend, ha="center", va="top",
            fontsize=9.0, fontweight="bold", color="#333333",
            multialignment="center", clip_on=False)
    if desc:
        ax.text(x, -0.185, desc, transform=blend, ha="center", va="top",
                fontsize=7.2, color="#555555", linespacing=1.5,
                multialignment="center", clip_on=False)

# ─── INSET axes (right panel, separate axes) ──────────────────────────────────
# Placed in the right 42% of the figure, vertically aligned with main plot
axins = fig.add_axes([0.57, 0.30, 0.41, 0.62])
axins.set_facecolor("#FAFAFA")

INS_BW = 0.70
N = len(chem_steps)
ins_xs = [float(i) for i in range(N)]

prev = feed_end
for i, (end_v, col, lbl) in enumerate(chem_steps):
    xi = ins_xs[i]
    lo, hi = sorted((prev, end_v))
    is_up = end_v > prev
    axins.bar(xi, hi-lo, bottom=lo, color=col, width=INS_BW,
              edgecolor="#AA2222" if is_up else "white",
              linewidth=0.8, hatch="///" if is_up else None, zorder=3)
    if i < N-1:
        axins.plot([xi+INS_BW/2, ins_xs[i+1]-INS_BW/2], [end_v, end_v],
                   color="#CCCCCC", lw=0.7, ls=":", zorder=2)
    d = end_v - prev
    if not is_up:
        axins.text(xi, hi+0.012, fmt(d), ha="center", va="bottom",
                   fontsize=7, fontweight="bold", color=col, zorder=5)
    else:
        axins.text(xi, lo-0.032, fmt(d), ha="center", va="top",
                   fontsize=7, fontweight="bold", color=col, zorder=5)
    prev = end_v

y_pad = 0.20
axins.set_ylim(chem_end-y_pad, feed_end+y_pad)
axins.set_xlim(-INS_BW*0.85, ins_xs[-1]+INS_BW*0.85)
axins.set_xticks(ins_xs)
axins.set_xticklabels([s[2] for s in chem_steps],
                       fontsize=9, fontweight="bold", color="#444444")
axins.tick_params(axis="x", length=0, pad=4)
axins.set_yticks([8.0, 8.25, 8.50, 8.75, 9.0, 9.25, 9.50, 9.68])
axins.tick_params(axis="y", labelsize=7.5, length=2, width=0.5, color="#AAAAAA")
axins.yaxis.grid(True, linestyle="--", linewidth=0.35, alpha=0.55, zorder=0)
axins.set_axisbelow(True)
for sp in ["top","right"]:
    axins.spines[sp].set_visible(False)
axins.spines["bottom"].set_color("#AAAAAA"); axins.spines["bottom"].set_linewidth(0.8)
axins.spines["left"].set_color("#AAAAAA");   axins.spines["left"].set_linewidth(0.8)
axins.set_title("Other chemicals — detail", fontsize=9, fontweight="bold",
                color="#333333", pad=6, loc="left")

# ─── Connector lines: zoom rect right edge → inset left edge ─────────────────
# After draw to fix transforms
fig.canvas.draw()

def fig_to_ax_data(src_ax, dst_ax, fx, fy):
    """src_ax axes-fraction → dst_ax data coords"""
    disp = src_ax.transAxes.transform((fx, fy))
    return dst_ax.transData.inverted().transform(disp)

# inset left edge in main-axes data coords
ins_tl = fig_to_ax_data(axins, ax, 0.0, 1.0)
ins_bl = fig_to_ax_data(axins, ax, 0.0, 0.0)

# Connect right side of zoom rect to left edge of inset panel
ax.plot([zx1, ins_tl[0]], [zy1, ins_tl[1]],
        color="#AAAAAA", lw=0.9, ls="--", zorder=5, clip_on=False)
ax.plot([zx1, ins_bl[0]], [zy0, ins_bl[1]],
        color="#AAAAAA", lw=0.9, ls="--", zorder=5, clip_on=False)

plt.rcParams["svg.fonttype"] = "none"

plt.savefig("mjsp_waterfall3.png", dpi=300, bbox_inches="tight", facecolor="white")
plt.show()
