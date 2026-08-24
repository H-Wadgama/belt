# Supply chain analysis of feedstock cost impact on MJSP
from biosteam import main_flowsheet as F
import biosteam as bst
import thermosteam as tmo
import pandas as pd
import numpy as np


from lignin_saf.ligsaf_chemicals import create_chemicals
from lignin_saf.settings.process_params import feed_parameters, additional_rcf
from lignin_saf.settings.prices import prices
from lignin_saf.settings.tea_params import operating_days, labor
from lignin_saf.systems.rcf import create_rcf_system
from lignin_saf.systems.rcf_oil_purification import create_rcf_oil_purification_system
from lignin_saf.systems.monomer_purification import create_monomer_purification_system
from lignin_saf.systems.hdo import create_hdo_system
from lignin_saf.systems.cellulosic_ethanol import create_cellulosic_ethanol_system
from atj_saf.atj_bst.etj_ligfirst import create_etj_system_no_facilities
from lignin_saf.cellulosic_tea import create_cellulosic_ethanol_tea

from lignin_saf.ligsaf_units import HydrogenStorageTank


chems = create_chemicals()
bst.settings.set_thermo(chems)
bst.settings.CEPCI = 840   # 2026 basis. CEPCI 
bst.settings.electricity_price = prices['electricity']




ethanol_in_beer = bst.Stream('Ethanol_In_Beer',
                       Ethanol=21507,
                       Water=391023,
                       Xylose=315.697,
                       Extract=12208.3,
                       AceticAcid=3663.85,
                       LacticAcid=2135.35,
                       Cellulose= 3504.6,
                       Xylan=1952.77,
                       Lignin=13131.8,
                       Protein=2635.1,
                       Ash=4107.85,
                       Cellulase=1681.7,
                       units = 'kg/hr',
                       T=115+273.15,
                       P = 6*101325)


beer_shortcut = bst.units.ShortcutColumn(
    ins = ethanol_in_beer,
    outs = ('shortcut_beer_top','shortcut_beer_bottom'),
    P = 3*101325,
    LHK=('Ethanol', 'Water'),
    Lr = 0.9913,
    Hr = 0.90717,
    k = 8,
    partial_condenser=True
)
beer_shortcut.simulate()


rectification_shortcut = bst.units.ShortcutColumn(
    ins = beer_shortcut-0,
    outs = ('shortcut_rectif_top','shortcut_rectif_bottom'),
    P = 3*101325,
    LHK=('Ethanol', 'Water'),
    y_top = 0.925/1.11,
    x_bot = 0.0005/2.55,
    k = 3
)
rectification_shortcut.simulate()


# =====================================================================
# Rigorous (MESH) beer and rectification columns, seeded from the
# converged shortcut columns above (same shortcut->rigorous handoff
# pattern as the BioSTEAM acetic acid tutorial). Neither column has an
# internal condenser (reflux=0): overhead product leaves fully vaporized.
# Column 2's overhead is instead condensed externally against a process
# water stream, split by a simplified molecular-sieve model, and the
# reject (topped up with makeup water) is recycled back in as a second
# feed at stage 1 -- acting like reflux, but as an external feed rather
# than the column's internal reflux mechanism.
#
# NOTE: N_stages/boilup are pulled directly from the shortcut columns'
# converged design, but the shortcut rectification column relies on a
# large internal reflux (R=15.3) to hit its y_top=0.833 spec. With
# reflux=0 here, column 2 does NOT reach that purity (~11 mol% ethanol
# overhead instead of ~83 mol%) -- the water balance in the recycle loop
# is dominated by this shortfall. Purity has not yet been matched;
# structure/wiring is the priority for now.
# =====================================================================

def _boilup_ratio(shortcut_column):
    outlet = shortcut_column.reboiler.outs[0]
    return outlet['g'].F_mol / outlet['l'].F_mol

boilup_beer = _boilup_ratio(beer_shortcut)
boilup_rectif = _boilup_ratio(rectification_shortcut)

N_stages_beer = int(beer_shortcut.design_results['Theoretical stages'])
feed_stage_beer = int(beer_shortcut.design_results['Theoretical feed stage'])
N_stages_rectif = max(int(rectification_shortcut.design_results['Theoretical stages']), 11)
feed_stage_rectif = int(rectification_shortcut.design_results['Theoretical feed stage'])


# --- Column 1: beer/stripping MESH column. No condenser (reflux=0):
# the top vapor leaves the column fully vaporized and feeds column 2 directly.
beer_mesh = bst.MESHDistillation(
    'beer_mesh',
    ins=(ethanol_in_beer,),
    outs=('beer_mesh_vapor', 'beer_mesh_bottoms'),
    N_stages=N_stages_beer,
    feed_stages=[feed_stage_beer],
    reflux=0,
    boilup=boilup_beer,
    LHK=('Ethanol', 'Water'),
    P=3*101325,
)

# --- Column 2: rectification MESH column. Also no internal condenser;
# "reflux" instead re-enters as a second feed at stage 1 (top stage), coming
# from the molecular-sieve loop below -- same pattern as the acetic acid
# tutorial's externally-supplied reflux feed. Initial guess matches the
# target reject composition to help the recycle solver converge.
reflux_recycle = bst.Stream('reflux_recycle', Ethanol=5331.9, Water=2043,
                             units='kg/hr', T=71+273.15, P=3*101325, phase='l')

rectif_mesh = bst.MESHDistillation(
    'rectif_mesh',
    ins=(beer_mesh-0, reflux_recycle),
    outs=('rectif_mesh_vapor', 'rectif_mesh_bottoms'),
    N_stages=N_stages_rectif,   # 15
    feed_stages=[9,8],
    reflux=rectification_shortcut.design_results['Minimum reflux'],
    boilup=boilup_rectif,
    LHK=('Ethanol', 'Water'),
    P=3*101325
)

# --- Heat recovery: condense the rectifier's vapor product against process
# water (33 C -> 100 C), sized by direct energy balance each pass.
sieve_water_in = bst.Stream('sieve_water_in', Water=1, units='kmol/hr',
                             T=33+273.15, P=101325, phase='l')

HX_sieve = bst.HXprocess(
    'HX_sieve',
    ins=(rectif_mesh-0, sieve_water_in),
    outs=('rectif_vapor_cooled', 'sieve_water_heated'),
)

@HX_sieve.add_specification(run=True)
def set_sieve_water_flow():
    vapor_in = HX_sieve.ins[0]
    liquid_ref = vapor_in.copy()
    liquid_ref.phase = 'l'
    Q = vapor_in.H - liquid_ref.H  # duty released condensing vapor to liquid at column P
    water_ref_in = bst.Stream(None, Water=1, units='kmol/hr', T=33+273.15,
                               P=101325, phase='l', thermo=chems)
    water_ref_out = water_ref_in.copy()
    water_ref_out.T = 100+273.15
    dH_per_kmol = water_ref_out.H - water_ref_in.H
    HX_sieve.ins[1].imol['Water'] = Q / dH_per_kmol

# --- Molecular sieve, modeled as a component splitter: rejects exactly
# enough water and ethanol (capped at what's actually available) to target
# a reject of 5331.9 kg/hr ethanol / 2043 kg/hr water, recomputed every
# pass from the *actual* HX_sieve outlet -- not the static shortcut-column
# snapshot, which drifts arbitrarily far from the converged MESH column's
# real overhead flow once N_stages/reflux/feed_stages change. AceticAcid/
# LacticAcid are not water-selective, so they're routed entirely to
# product -- leaving them unspecified defaults them to the reject side and
# causes runaway accumulation in the recycle loop.
target_reflux_ethanol = 5331.9  # kg/hr
target_reflux_water = 2043      # kg/hr

molecular_sieve = bst.Splitter(
    'molecular_sieve',
    ins=HX_sieve-0,
    outs=('sieve_product', 'sieve_reject'),
    split=dict(Ethanol=0.0, Water=0.0, AceticAcid=1.0, LacticAcid=1.0),
)

@molecular_sieve.add_specification(run=True)
def set_molecular_sieve_split():
    feed = molecular_sieve.ins[0]
    avail_ethanol = feed.imass['Ethanol']
    avail_water = feed.imass['Water']
    ethanol_reject_frac = min(target_reflux_ethanol / avail_ethanol, 1.0) if avail_ethanol > 0 else 0.0
    water_reject_frac = min(target_reflux_water / avail_water, 1.0) if avail_water > 0 else 0.0
    molecular_sieve.isplit['Ethanol'] = 1 - ethanol_reject_frac
    molecular_sieve.isplit['Water'] = 1 - water_reject_frac

# --- Makeup water tops the sieve reject up to the target reflux water flow
# (only needed if the column's overhead can't supply 2043 kg/hr water on
# its own; recomputed every pass). No pump: makeup water is assumed
# available at 3 atm already.
makeup_water = bst.Stream('makeup_water', Water=0, units='kg/hr',
                           T=25+273.15, P=3*101325, phase='l')

reflux_mixer = bst.Mixer('reflux_mixer', ins=(molecular_sieve-1, makeup_water),
                          outs='reflux_mixed')

@reflux_mixer.add_specification(run=True)
def set_makeup_water_flow():
    reject_water = molecular_sieve.outs[1].imass['Water']
    makeup_water.imass['Water'] = max(target_reflux_water - reject_water, 0.0)

# Final cooler brings the combined reject + makeup water back to 71 C before
# re-entering the column; no pump/compressor -- pressure carries through at 3 atm.
cooler_reflux = bst.HXutility('cooler_reflux', ins=reflux_mixer-0,
                               outs=reflux_recycle, T=71+273.15,
                               rigorous=True)

rectif_loop_sys = bst.System(
    'rectif_loop_sys',
    path=(beer_mesh, rectif_mesh, HX_sieve, molecular_sieve, reflux_mixer, cooler_reflux),
    recycle=reflux_recycle,
)
rectif_loop_sys.simulate()
