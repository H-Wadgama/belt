# Global imports
import biosteam as bst, thermosteam as tmo, biorefineries as bf, numpy as np, pandas as pd
from biorefineries import cellulosic
from biosteam import main_flowsheet as F, units
from atj_saf.atj_bst.etj_chemicals import create_chemicals
from math import ceil
from scipy.optimize import brentq
from biosteam.units.distillation import compute_stages_McCabeThiele


chemicals = tmo.Chemicals(['Water', 'Methanol', 'Ethanol'], cache=True)
bst.settings.set_thermo(chemicals)
feed = bst.Stream('feed', Water=50, Methanol=50, units = 'kmol/hr', phase='g', T = 405, P = 101325)


D1 = bst.units.BinaryDistillation('D1', ins=feed,
                        outs=('distillate', 'bottoms_product'),
                        LHK=('Methanol', 'Water'),
                        y_top = 0.90, x_bot = 0.1,
                        k=2,
                        partial_condenser=True)
D1.simulate()


def compute_binary_feed_stage(feed, distillate, bottoms, LHK, y_top, x_bot, P, k,
                               Rmin_user=0.433):
    """
    Independently reproduce BioSTEAM's BinaryDistillation McCabe-Thiele feed-stage
    calculation (see BinaryDistillation._run_McCabeThiele in biosteam/units/distillation.py)
    using only public thermosteam/biosteam APIs, without touching D1's private state.

    Parameters
    ----------
    feed : bst.Stream
        Combined feed to the column (liquid and/or vapor).
    distillate, bottoms : bst.Stream
        Simulated distillate and bottoms product streams.
    LHK : tuple[str]
        Light and heavy keys.
    y_top : float
        Light key molar fraction in the distillate.
    x_bot : float
        Light key molar fraction in the bottoms product.
    P : float
        Column pressure [Pa].
    k : float
        Ratio of actual reflux to minimum reflux.
    Rmin_user : float
        User-enforced minimum reflux ratio floor.

    Returns
    -------
    dict with theoretical_stages, theoretical_feed_stage, Rmin, R, q, zf, x_m, y_m
    """
    chemicals = feed.chemicals
    LHK_index = chemicals.get_index(LHK)

    # --- Feed light-key mole fraction (zf) ---
    liq_mol = feed.imol['l']
    vap_mol = feed.imol['g']
    LHK_mol = liq_mol[LHK_index] + vap_mol[LHK_index]
    zf = LHK_mol[0] / LHK_mol.sum()

    # --- Feed quality (q), via bubble/dew point enthalpies ---
    data = feed.get_data()
    H_feed = feed.H
    try: feed.T = feed.dew_point_at_P().T
    except Exception: pass
    feed.phase = 'g'
    H_vap = feed.H
    try: feed.T = feed.bubble_point_at_P().T
    except Exception: pass
    feed.phase = 'l'
    H_liq = feed.H
    q = (H_vap - H_feed) / (H_vap - H_liq)
    feed.set_data(data)
    if abs(q - 1) < 1e-4:
        q = 1 - 1e-4

    # --- q-line ---
    q_line = lambda x: q * x / (q - 1) - zf / (q - 1)

    # --- Minimum reflux: intersection of q-line with the equilibrium curve ---
    solve_Ty = bottoms.get_bubble_point(LHK).solve_Ty
    Rmin_intersection = lambda x: q_line(x) - solve_Ty(np.array((x, 1 - x)), P)[1][0]
    x_Rmin = brentq(Rmin_intersection, 1e-9, 1 - 1e-9)
    y_Rmin = q_line(x_Rmin)
    m = (y_Rmin - y_top) / (x_Rmin - y_top)
    Rmin = m / (1 - m)
    if Rmin < Rmin_user:
        Rmin = Rmin_user
    R = k * Rmin

    # --- Rectifying operating line & its intersection with the q-line (x_m, y_m) ---
    m1 = R / (R + 1)
    b1 = y_top - m1 * y_top
    rs = lambda y: (y - b1) / m1  # x as a function of y, rectifying line
    y_m = (q * b1 + m1 * zf) / (q - m1 * (q - 1))
    x_m = rs(y_m)

    # --- Stripping operating line, through the bottoms point and (x_m, y_m) ---
    m2 = (x_bot - y_m) / (x_bot - x_m)
    b2 = y_m - m2 * x_m
    ss = lambda y: (y - b2) / m2  # x as a function of y, stripping line

    # --- Step off stages bottom-up: stripping line first, then rectifying line ---
    x_stages = [x_bot]
    y_stages = [x_bot]
    T_stages = []
    compute_stages_McCabeThiele(P, ss, x_stages, y_stages, T_stages, x_m, solve_Ty)
    yi = y_stages[-1]
    xi = rs(yi)
    x_stages[-1] = xi if xi < 1 else 0.99999
    compute_stages_McCabeThiele(P, rs, x_stages, y_stages, T_stages, y_top, solve_Ty)

    # --- Locate the feed stage: where the staircase crosses y_m ---
    N_stages = len(x_stages)
    feed_stage = ceil(N_stages / 2)
    for i in range(len(y_stages) - 1):
        if y_stages[i] < y_m < y_stages[i + 1]:
            feed_stage = i + 1

    return dict(
        theoretical_stages=N_stages,
        theoretical_feed_stage=N_stages - feed_stage,
        Rmin=Rmin, R=R, q=q, zf=zf, x_m=x_m, y_m=y_m,
    )


distillate, bottoms_product = D1.outs
results = compute_binary_feed_stage(
    feed=D1.mixed_feed, distillate=distillate, bottoms=bottoms_product,
    LHK=('Methanol', 'Water'), y_top=0.90, x_bot=0.1, P=101325, k=2,
)
print(results)
print('BioSTEAM design results:', D1.design_results['Theoretical stages'],
      D1.design_results['Theoretical feed stage'])


def solve_boilup_for_bottoms_purity(feed, LHK, x_bot_target, reflux, feed_stages,
                                     N_stages, P=101325, bracket=(0.1, 10.0)):
    """
    MESHDistillation has no direct product-purity spec (only Reflux/Boilup/
    Duty/Temperature at each stage), so to reproduce BinaryDistillation's
    x_bot target we root-find the `boilup` that hits it, holding
    N_stages/feed_stages/reflux fixed.

    Note: a *fresh* column is built per trial. Mutating `.boilup` on a live
    MESHDistillation instance and re-simulating does NOT force a re-solve --
    BioSTEAM's `_setup` short-circuits when `stage_specifications` is the
    same dict object as last time (`args != self._last_args` compares by
    identity-preserving equality, and the setter mutates that dict in
    place), so the "solve" silently reuses the previous boilup's result.
    """
    LK = LHK[0]

    def build(boilup):
        column = bst.units.MESHDistillation(
            ins=feed.copy(), LHK=LHK, reflux=reflux, boilup=boilup,
            feed_stages=feed_stages, N_stages=N_stages, P=P,
            full_condenser=False,
        )
        column.simulate()
        return column

    def bottoms_error(boilup):
        column = build(boilup)
        bottoms = column.outs[-1]
        return bottoms.imol[LK] / bottoms.F_mol - x_bot_target

    boilup = brentq(bottoms_error, *bracket, xtol=1e-6)
    return build(boilup), boilup


# BinaryDistillation's R is L/D; MESHDistillation's `reflux` is L/V at the
# condenser stage (see biosteam/units/stage.py: B = 1/reflux) -- convert.
reflux_LV = results['R'] / (results['R'] + 1)

D2, boilup = solve_boilup_for_bottoms_purity(
    feed, LHK=('Methanol', 'Water'), x_bot_target=0.1, reflux=reflux_LV,
    feed_stages=[results['theoretical_feed_stage']],
    N_stages=results['theoretical_stages'],
)

distillate2, bottoms2 = D2.outs
print('\nD2 reflux (L/V):', reflux_LV, '| solved boilup:', boilup)
print('D2 distillate Methanol frac:', distillate2.imol['Methanol'] / distillate2.F_mol)
print('D2 bottoms   Methanol frac:', bottoms2.imol['Methanol'] / bottoms2.F_mol)


# ---------------------------------------------------------------------------
# One-at-a-time sensitivity: swap each of D1's "actual" McCabe-Thiele design
# outputs (reflux, N_stages, feed_stage) into an otherwise-generic MESH
# column, one at a time, holding the other two at naive/generic defaults and
# boilup fixed (no root-finding). This isolates how much each individual
# "actual" value moves the resulting purities toward D1's target
# (y_top=0.90, x_bot=0.10), instead of the combined effect all three have
# together in D2 above.
# ---------------------------------------------------------------------------

def build_mesh(N_stages, feed_stage, reflux, boilup, feed=feed,
               LHK=('Methanol', 'Water'), P=101325):
    column = bst.units.MESHDistillation(
        ins=feed.copy(), LHK=LHK, reflux=reflux, boilup=boilup,
        feed_stages=[feed_stage], N_stages=N_stages, P=P,
        full_condenser=False,
    )
    column.simulate()
    distillate, bottoms = column.outs
    return dict(
        N_stages=N_stages, feed_stage=feed_stage, reflux=reflux, boilup=boilup,
        distillate_x=distillate.imol['Methanol'] / distillate.F_mol,
        bottoms_x=bottoms.imol['Methanol'] / bottoms.F_mol,
    )

# Generic/naive baseline -- deliberately NOT derived from D1 at all.
N_default = 8
feed_stage_default = 4
reflux_default = 0.5
boilup_default = 1.0

# D1's "actual" design outputs.
N_actual = results['theoretical_stages']
feed_stage_actual = results['theoretical_feed_stage']
reflux_actual = reflux_LV

trials = {
    'all defaults (no D1 info)':          build_mesh(N_default, feed_stage_default, reflux_default, boilup_default),
    'actual reflux only':                 build_mesh(N_default, feed_stage_default, reflux_actual,  boilup_default),
    'actual N_stages only':                build_mesh(N_actual,  feed_stage_default, reflux_default, boilup_default),
    'actual feed_stage only':             build_mesh(N_default, feed_stage_actual,  reflux_default, boilup_default),
    'all three actual (boilup fixed)':    build_mesh(N_actual,  feed_stage_actual,  reflux_actual,  boilup_default),
}

print('\n--- One-at-a-time sensitivity (target: y_top=0.90, x_bot=0.10) ---')
for name, r in trials.items():
    print(f"{name:38s} N={r['N_stages']:2d} feed={r['feed_stage']:2d} "
          f"reflux={r['reflux']:.3f} boilup={r['boilup']:.3f}  "
          f"-> distillate={r['distillate_x']:.3f}  bottoms={r['bottoms_x']:.3f}")