import biosteam as bst
import numpy as np
from biosteam import main_flowsheet as F


from lignin_saf.settings import (
    hexane_purification,
    hexane_partition_IDs,
    hexane_partition_K,
)
from lignin_saf.settings import prices

def create_monomer_purification_system(ins=None):
    """
    Build and return the hexane LLE monomer purification system.

    Separates the purified RCF oil (output of EtOAc LLE FLASH201) into
    true monomers via hexane liquid-liquid extraction. Dimers (Syringaresinol,
    G_Dimer) and oligomers (S_Oligomer, G_Oligomer) are not assigned partition
    coefficients and remain in the aqueous raffinate (WW_12).

    NOTE: Syringaresinol is a lignan DIMER (two sinapyl alcohol units linked via
    a beta-beta' resinol linkage), not a monomer. It is intentionally excluded
    from the hexane partition data so it reports to WW_12 alongside G_Dimer.

    Parameters
    ----------
    ins : bst.Stream, optional
        Purified RCF oil inlet. If None, F.Purified_RCF_Oil is taken from
        the main flowsheet — rcf_oil_purification_sys must have been simulated first.

    Returns
    -------
    bst.System
        'Monomer_Purification_System' with hexane_recycle converged.

    Notes
    -----
    Caller must configure thermodynamics before calling:
        chems = create_chemicals()
        bst.settings.set_thermo(chems)
        bst.settings.CEPCI = 541.7

    Key output streams (accessible via F.<name> after simulate()):
        RCF_Monomers   — bottoms of FLASH301; true monomers only (Propylguaiacol, Propylsyringol)
        WW_11          — water bleed from CENT303 hexane decanter; to wastewater treatment
        WW_12          — aqueous raffinate from LLE300; contains Syringaresinol, G_Dimer, S_Oligomer, G_Oligomer; to WWT
    """
    purified_rcf = F.Purified_RCF_Oil if ins is None else ins

    chems = bst.settings.chemicals

    solvent_to_oil      = hexane_purification['solvent_to_oil_ratio']
    water_hexane_ratio  = hexane_purification['water_hexane_ratio']
    N_stages            = hexane_purification['N_stages']
    recycle_split       = hexane_purification['hexane_recycle_split']
    oil_flash_T         = hexane_purification['oil_flash_T']
    oil_flash_P         = hexane_purification['oil_flash_P']

    hexane_rho = chems['Hexane'].rho(phase='l', T=298.15, P=101325)
    water_rho  = chems['Water'].rho(phase='l', T=298.15, P=101325)

    partition_data = {
        'K':                   np.array(hexane_partition_K, dtype=float),
        'IDs':                 hexane_partition_IDs,
        'raffinate_chemicals': ['Water'],
        'extract_chemicals':   ['Hexane'],
    }

    # ── Streams ───────────────────────────────────────────────────────────────
    hexane_recycle = bst.Stream('hexane_recycle')
    # Hexane and water split into separate streams so price applies only to hexane
    hexane_in = bst.Stream(
        'Hexane_In',
        Hexane=solvent_to_oil * purified_rcf.F_mass,
        units='kg/hr',
        price=prices['Hexane'],
    )
    water_in_hexane = bst.Stream(
        'Water_in_hexane',
        Water=solvent_to_oil * purified_rcf.F_mass * (water_rho / hexane_rho) * water_hexane_ratio,
        units='kg/hr',
    )

    # ── Unit operations ───────────────────────────────────────────────────────

    # Fresh hexane + fresh water + recycle; spec sets makeup to cover the deficit each iteration
    hexane_mixer = bst.Mixer('MIX300', ins=(hexane_in, water_in_hexane, hexane_recycle), rigorous=False)

    @hexane_mixer.add_specification(run=True)
    def adjust_fresh_solvent_flow():
        hexane_fresh = hexane_mixer.ins[0]
        water_fresh  = hexane_mixer.ins[1]
        recycle      = hexane_mixer.ins[2]
        hexane_fresh.imass['Hexane'] = (
            hexane_purification['solvent_to_oil_ratio'] * purified_rcf.F_mass - recycle.imass['Hexane']
        )
        water_fresh.imass['Water'] = (
            hexane_purification['solvent_to_oil_ratio'] * purified_rcf.F_mass * (water_rho / hexane_rho) * water_hexane_ratio
            - recycle.imass['Water']
        )

    # LLE: purified oil contacts hexane/water countercurrently; only true monomers
    # (Propylguaiacol, Propylsyringol) partition into hexane extract; Syringaresinol
    # (a dimer), G_Dimer, S_Oligomer, and G_Oligomer are unlisted → stay in raffinate
    lle_column = bst.MultiStageMixerSettlers(
        'LLE300',
        ins=(purified_rcf, hexane_mixer-0),
        outs=('', 'WW_12'),
        feed_stages=(0, -1),
        N_stages=N_stages,
        partition_data=partition_data,
        use_cache=True,
    )

    # Flash hexane overhead; monomers/dimers exit as bottoms
    monomer_flash = bst.units.Flash(
        'FLASH301',
        ins=lle_column-0,
        outs=('', 'MON_MONOMERS_OUT'),
        T=oil_flash_T,
        P=oil_flash_P,
    )

    # Condense hexane vapor for decanting
    solvent_cooler = bst.units.HXutility(
        'HX302',
        ins=monomer_flash-0,
        V=0,
        rigorous=True,
    )

    # Split hexane from water; hexane-rich phase recycled, water bleed to wastewater
    solvent_decanter = bst.LiquidsSplitCentrifuge(
        'CENT303',
        ins=solvent_cooler-0,
        outs=(hexane_recycle, 'WW_11'),
        split={'Hexane': recycle_split},
    )

    # ── Assemble system ───────────────────────────────────────────────────────
    return bst.System(
        'Monomer_Purification_System',
        path=(hexane_mixer, lle_column, monomer_flash, solvent_cooler, solvent_decanter),
        recycle=hexane_recycle,
    )
