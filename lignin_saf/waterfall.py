import matplotlib.pyplot as plt
from matplotlib.transforms import blended_transform_factory
from mpl_toolkits.axes_grid1.inset_locator import mark_inset

# ─── Data ────────────────────────────────────────────────────────────────────
base_val = 17.13

# Each category's levers, applied sequentially: (description, resulting MJSP, color)
rcf_levers = [
    ("Reaction time → 1 hr",        13.77, "#1A3E5C"),
    ("Residence time → 36 min",     13.15, "#5B9BD5"),
    ("No external H₂",              12.86, "#9DC3E6"),
]
hdo_levers = [
    ("Batch time → 2 hr",           12.09, "#145A32"),
    ("Solvent loading → 10 L/kg",   10.26, "#27AE60"),
    ("Dodecane price −50%",         10.13, "#82E0AA"),
]
feedstock_levers = [
    ("Poplar price → 50 USD/DMT",    9.68, "#BF5B21"),
]
# EHF: a cluster of small, mostly-offsetting price cuts — the CSL step actually
# *raises* MJSP slightly, so the path isn't monotonic. Plotted as individual
# floating bars (rather than a touching stack) and magnified in an inset since
# the deltas ($0.07-0.79) are too fine to read against the full $0-19 axis.
ehf_levers = [
    ("Cellulase", 8.89, "#3D2C6B"),
    ("Caustic",   8.79, "#6A4C93"),
    ("DAP",       8.67, "#9D85C2"),
    ("CSL",       8.74, "#CBBEDC"),
]

cat_main = {
    "Base Case": "#1C1C1C",
    "RCF":       "#2E5F8E",
    "HDO":       "#2A7A52",
    "Feedstock": "#BF5B21",
    "EHF":       "#5A3E85",
}

x_base, x_rcf, x_hdo, x_feed = 0, 1, 2, 3
x_ehf = [4.0, 4.5, 5.0, 5.5]
bar_w, bar_w_ehf = 0.52, 0.35
hw, hw_ehf = bar_w / 2, bar_w_ehf / 2


def fmt_delta(d):
    return f"{'+' if d > 0 else '−'}${abs(d):.2f}"


def build_stack(levers, x, start_val):
    current = start_val
    out = []
    for lbl, nv, col in levers:
        out.append({"x": x, "bottom": nv, "height": current - nv,
                    "delta": nv - current, "color": col, "label": lbl})
        current = nv
    return out


rcf_segs  = build_stack(rcf_levers, x_rcf, base_val)
hdo_segs  = build_stack(hdo_levers, x_hdo, rcf_segs[-1]["bottom"])
feed_segs = build_stack(feedstock_levers, x_feed, hdo_segs[-1]["bottom"])

# EHF — floating bars: each spans [min(prev, new), max(prev, new)] so a step
# that raises MJSP (CSL) draws upward instead of breaking a touching stack.
ehf_segs = []
current = feed_segs[-1]["bottom"]
for (lbl, nv, col), x in zip(ehf_levers, x_ehf):
    lo, hi = sorted((current, nv))
    ehf_segs.append({"x": x, "bottom": lo, "height": hi - lo, "end": nv,
                     "delta": nv - current, "color": col, "label": lbl})
    current = nv

end_val = {"RCF": rcf_segs[-1]["bottom"], "HDO": hdo_segs[-1]["bottom"],
           "Feedstock": feed_segs[-1]["bottom"], "EHF": ehf_segs[-1]["end"]}

# ─── Figure ──────────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(15, 7.5))
fig.patch.set_facecolor("white")
ax.set_facecolor("white")
fig.subplots_adjust(bottom=0.32, right=0.97, left=0.06, top=0.93)

# ─── Base bar ────────────────────────────────────────────────────────────────
ax.bar(x_base, base_val, bottom=0, color=cat_main["Base Case"], width=bar_w,
       edgecolor="white", linewidth=0.8, zorder=3)
ax.text(x_base, base_val / 2, f"${base_val:.2f}", ha="center", va="center",
        fontsize=11, fontweight="bold", color="white", zorder=4)

# ─── Stacked columns (RCF, HDO, Feedstock) ───────────────────────────────────
for segs in (rcf_segs, hdo_segs, feed_segs):
    for s in segs:
        ax.bar(s["x"], s["height"], bottom=s["bottom"], color=s["color"],
               width=bar_w, edgecolor="white", linewidth=1.5, zorder=3)

# ─── EHF cluster — individual floating bars ──────────────────────────────────
for s in ehf_segs:
    is_increase = s["delta"] > 0
    ax.bar(s["x"], s["height"], bottom=s["bottom"], color=s["color"],
           width=bar_w_ehf, edgecolor=("#B33A3A" if is_increase else "white"),
           linewidth=1.2, hatch=("///" if is_increase else None), zorder=3)

# ─── End-of-section value callouts ───────────────────────────────────────────
for cat, x in (("RCF", x_rcf), ("HDO", x_hdo), ("Feedstock", x_feed)):
    val = end_val[cat]
    ax.text(x, val - 0.3, f"${val:.2f}", ha="center", va="top", fontsize=9,
            fontweight="bold", color=cat_main[cat], zorder=4, clip_on=False)
ax.text(x_ehf[-1] + hw_ehf + 0.18, end_val["EHF"], f"${end_val['EHF']:.2f}",
        ha="left", va="center", fontsize=9.5, fontweight="bold",
        color=cat_main["EHF"], zorder=4, clip_on=False)

# ─── Connector dashed lines (carry-forward MJSP floor) ───────────────────────
for (xf, hwf, xt, hwt, y) in [
    (x_base, hw, x_rcf, hw, base_val),
    (x_rcf, hw, x_hdo, hw, end_val["RCF"]),
    (x_hdo, hw, x_feed, hw, end_val["HDO"]),
    (x_feed, hw, x_ehf[0], hw_ehf, end_val["Feedstock"]),
]:
    ax.plot([xf + hwf, xt - hwt], [y, y], color="#BBBBBB", linestyle="--",
            linewidth=0.9, zorder=2)
for i in range(len(ehf_segs) - 1):
    y = ehf_segs[i]["end"]
    ax.plot([ehf_segs[i]["x"] + hw_ehf, ehf_segs[i + 1]["x"] - hw_ehf], [y, y],
            color="#CCCCCC", linestyle=":", linewidth=0.8, zorder=2)

# ─── Lever description blocks below each category ────────────────────────────
# Levers belonging to one category are written together as a short list under
# the category name (per the reference figure's "A. ... / B. ..." convention)
# instead of annotated individually on the chart — keeps the bars themselves
# clean no matter how many levers are grouped into them.
blend = blended_transform_factory(ax.transData, ax.transAxes)
y_name, y_list = -0.06, -0.115


def lever_block(segs, numbered=True, header=None):
    lines = [] if header is None else [header]
    for i, s in enumerate(segs, start=1):
        prefix = f"{i}. " if numbered else ""
        lines.append(f"{prefix}{s['label']}  ({fmt_delta(s['delta'])})")
    return "\n".join(lines)


groups = [
    ("Base Case", None, x_base),
    ("RCF",       lever_block(rcf_segs), x_rcf),
    ("HDO",       lever_block(hdo_segs), x_hdo),
    ("Feedstock", lever_block(feed_segs, numbered=False), x_feed),
    ("EHF",       lever_block(ehf_segs, header="50% price reductions:"),
     sum(x_ehf) / len(x_ehf)),
]
for name, text, x in groups:
    col = cat_main[name]
    ax.text(x, y_name, name, transform=blend, ha="center", va="top",
            fontsize=10.5, fontweight="bold", color=col, clip_on=False)
    if text:
        ax.text(x, y_list, text, transform=blend, ha="center", va="top",
                fontsize=8, color="#333333", linespacing=1.55,
                multialignment="center", clip_on=False)

# ─── Magnified inset for the EHF cluster ─────────────────────────────────────
# These four levers individually move MJSP by only $0.07-0.79 — too fine to
# read against the $0-19 axis, so the cluster is redrawn zoomed-in.
axins = ax.inset_axes([0.60, 0.55, 0.38, 0.40])
for s in ehf_segs:
    is_increase = s["delta"] > 0
    axins.bar(s["x"], s["height"], bottom=s["bottom"], color=s["color"],
              width=bar_w_ehf, edgecolor=("#B33A3A" if is_increase else "white"),
              linewidth=1.0, hatch=("///" if is_increase else None), zorder=3)
    top_y = s["bottom"] + s["height"]
    axins.text(s["x"], top_y + 0.025, fmt_delta(s["delta"]), ha="center",
               va="bottom", fontsize=7.5, fontweight="bold", color=s["color"])
for i in range(len(ehf_segs) - 1):
    y = ehf_segs[i]["end"]
    axins.plot([ehf_segs[i]["x"] + hw_ehf, ehf_segs[i + 1]["x"] - hw_ehf], [y, y],
               color="#CCCCCC", linestyle=":", linewidth=0.7, zorder=2)
axins.set_xlim(x_ehf[0] - hw_ehf - 0.18, x_ehf[-1] + hw_ehf + 0.18)
axins.set_ylim(8.55, 9.85)
axins.set_xticks(x_ehf)
axins.set_xticklabels([s["label"] for s in ehf_segs], fontsize=7.5)
axins.tick_params(axis="y", labelsize=7.5, length=2)
axins.set_facecolor("#FAFAFA")
for spine in axins.spines.values():
    spine.set_color("#AAAAAA")
    spine.set_linewidth(0.7)
axins.yaxis.grid(True, linestyle="--", linewidth=0.4, alpha=0.5, zorder=0)
axins.set_axisbelow(True)
mark_inset(ax, axins, loc1=2, loc2=3, fc="none", ec="#999999", lw=0.7, linestyle="--")

# ─── Axes styling ─────────────────────────────────────────────────────────────
ax.set_ylabel("MJSP (USD gal⁻¹)", fontsize=11, labelpad=10)
ax.set_ylim(0, 19)
ax.set_xlim(-0.6, 6.2)
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
ax.tick_params(axis="x", bottom=False, labelbottom=False)
ax.yaxis.grid(True, linestyle="--", linewidth=0.6, alpha=0.35, zorder=0)
ax.set_axisbelow(True)

plt.rcParams['svg.fonttype'] = 'none'
plt.savefig("mjsp_waterfall2.png", dpi=300, bbox_inches="tight", facecolor="white")
plt.show()
