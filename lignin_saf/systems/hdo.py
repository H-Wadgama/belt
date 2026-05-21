import biosteam as bst
from lignin_saf.ligsaf_units import HydrodeoxygenationReactor, PSA, HydrocarbonProductTank
from lignin_saf.ligsaf_settings import hdo_params, h2_pressure, prices, operating_days

def create_hdo_system(ins=None):
    """
    Build and return the HDO loop as a bst.System.

    Parameters
    ----------
    ins : bst.Stream, optional
        RCF_Monomers stream containing Propylguaiacol and Propylsyringol.
        If None, pulled from the main flowsheet as F.RCF_Monomers.

    Returns
    -------
    bst.System
        'HDO_System' with hydrogen and dodecane (solvent for HDO) recycle

    Notes
    -----
    Caller is responsible for setting up thermodynamics before calling:
        chems = create_chemicals()
        bst.settings.set_thermo(chems)
        bst.settings.CEPCI = 541.7

    Named output streams for downstream wiring:
        HDO_purge_gases  — PSA purge (H2, CH4, light gases) → route to gas_mixer, which goes to BT
        HDO_wash_water   — liquid from Flash (HDO_FLSH2). Almost pure water - routed to WWT
        HDO_WW           — water tops from HDO_COL2 → route to WWT
        SAF_CycloAlkane  — propylcyclohexane product
    """
    from biosteam import main_flowsheet as F

    if ins is None:
        ins = F.RCF_Monomers

    chems = bst.settings.chemicals

    # ── Hydrodeoxygenation reactions ──────────────────────────────────────────
    hydrodeoxygenation_rxn = bst.ParallelReaction([
        bst.Reaction(
            'Propylguaiacol,l + 6Hydrogen,g -> 1propylcyclohexane,l + 2Water,l + Methane,g',
            reactant='Propylguaiacol', phases='lg', X=1.0, basis='mol',
        ),
        bst.Reaction(
            '1Propylsyringol,l + 8Hydrogen,g -> 1propylcyclohexane,l + 3Water,l + 2Methane,g',
            reactant='Propylsyringol', phases='lg', X=1.0, basis='mol',
        ),
    ])

    # ── Recycle streams ───────────────────────────────────────────────────────
    hdo_h2_recycle = bst.Stream('HDO_H2_RECYCLE', phase='g', P=hdo_params['P'])
    hdo_dodecane_recycle = bst.Stream('HDO_DODECANE_RECYCLE', Dodecane=0, phase='l', P=101325, T=300)

    # ── Fresh feeds ───────────────────────────────────────────────────────────
    hdo_h2_in = bst.Stream(
        ID='HDO_H2_IN', Hydrogen=0, units='kmol/hr',
        P=h2_pressure, phase='g', price=prices['Hydrogen'],
    )
    hdo_dodecane_in = bst.Stream(
        ID='HDO_DODECANE_IN', Dodecane=0, units='kg/hr',
        P=101325, T=300, phase='l', price = prices['Dodecane'],
    )
    hdo_cat_in = bst.Stream(
        ID='HDO_CAT_IN', Ni2PSiO2=0, units='kg/hr', phase='s', price =  prices['HDO_Cat']
    )

    # ── H2 mixer: adjusts fresh H2 to make up for recycle shortfall ──────────
    hdo_h2_mix = bst.units.Mixer('HDO_MIX1', ins=(hdo_h2_in, hdo_h2_recycle))

    @hdo_h2_mix.add_specification(run=True)
    def h2_flow():
        fresh_h2 = hdo_h2_mix.ins[0]
        recycle_h2 = hdo_h2_mix.ins[1]
        h2_required = (
            6 * ins.imol['Propylguaiacol'] + 8 * ins.imol['Propylsyringol']
        ) * hdo_params['h2_excess']
        fresh_h2.imol['Hydrogen'] = max(0.0, h2_required - recycle_h2.imol['Hydrogen'])
        hdo_h2_mix.outs[0].phase = 'g'

    # ── Dodecane mixer: adjusts fresh dodecane to make up for recycle shortfall ─
    hdo_dodecane_mix = bst.units.Mixer('HDO_MIX2', ins=(hdo_dodecane_in, hdo_dodecane_recycle))

    @hdo_dodecane_mix.add_specification(run=True)
    def dodecane_flow():
        fresh_dod = hdo_dodecane_mix.ins[0]
        recycle_dod = hdo_dodecane_mix.ins[1]
        dod_vol = ins.F_mass * hdo_params['solvent_req']        # m3/hr
        dod_rho = chems['Dodecane'].rho(phase='l', T=300, P=101325)  # kg/m3
        fresh_dod.imass['Dodecane'] = max(
            0.0, dod_vol * dod_rho - recycle_dod.imass['Dodecane']
        )
        hdo_cat_in.imass['Ni2PSiO2'] = (hdo_params['catalyst_req'] * ins.F_mass * hdo_params['tau']) / (hdo_params['cat_lifetime'] * 30 * 24)


    # ── Main feed mixer ───────────────────────────────────────────────────────
    hdo_mix_3 = bst.units.Mixer(
        ID='HDO_MIX3',
        ins=(hdo_h2_mix-0, ins, hdo_dodecane_mix-0),
        rigorous=True,
    )

    # ── Compress to HDO operating pressure ───────────────────────────────────
    hdo_comp_1 = bst.units.IsentropicCompressor(
        'HDO_COMP1', ins=hdo_mix_3-0, P=hdo_params['P'], vle=True,
    )

    # ── Heat to HDO operating temperature ─────────────────────────────────────
    hdo_hx_1 = bst.units.HXutility(
        ID='HDO_HX1', ins=hdo_comp_1-0, T=hdo_params['T'], rigorous=True,
    )

    # ── HDO reactor ───────────────────────────────────────────────────────────
    hdo_rxr_1 = HydrodeoxygenationReactor(
        ID='HDO_RXR1',
        ins=(hdo_hx_1-0, hdo_cat_in),
        T=hdo_params['T'],
        P=hdo_params['P'],
        tau=hdo_params['tau'],
        tau_0=hdo_params['tau_0'],
        free_frac=hdo_params['free_frac'],
        V_max=hdo_params['V_max'],
        aspect_ratio=hdo_params['aspect_ratio'],
        reaction_1=hydrodeoxygenation_rxn,
    )

    # ── Cool reactor effluent before pressure let-down ────────────────────────
    hdo_hx_2 = bst.units.HXutility(ID='HDO_HX2', ins=hdo_rxr_1-0, T=400, rigorous=True)

    # ── Depressurize to atmospheric ───────────────────────────────────────────
    hdo_v_1 = bst.units.IsenthalpicValve(ID='HDO_V1', ins=hdo_hx_2-0, P=101325, vle=True)

    # ── Primary flash: separate gas (H2, methane) from liquid (product + solvent) ─
    hdo_flsh_1 = bst.units.Flash(ID='HDO_FLSH1', ins=hdo_v_1-0, T=298, P=101325)

    # ── Secondary flash: dry gas before PSA; liquid is near-pure water ────────
    # HDO_wash_water (outs[1]), will be routed to WWT in script that calls it
    hdo_flsh_2 = bst.units.Flash(
        ID='HDO_FLSH2', ins=hdo_flsh_1-0,
        outs=('', 'HDO_wash_water'),
        T=275, P=5e5,
    )

    # ── Reheat dried gas to PSA inlet temperature ─────────────────────────────
    hdo_hx_3 = bst.units.HXutility(ID='HDO_HX3', ins=hdo_flsh_2-0, T=303, rigorous=True)

    # ── PSA: recover H2 for recycle; purge light gases → route to gas_mixer → BT ─
    hdo_psa_1 = PSA(ID='HDO_PSA1', ins=hdo_hx_3-0, outs=('', 'HDO_purge_gases'))

    # ── Recompress recovered H2 to HDO operating pressure for recycle ─────────
    hdo_h2_comp = bst.units.IsentropicCompressor(
        'HDO_COMP_H2', ins=hdo_psa_1-0, outs=hdo_h2_recycle,
        P=hdo_params['P'], vle=True,
    )

    @hdo_h2_comp.add_specification(run=True)
    def set_h2_recycle_phase():
        hdo_h2_comp.outs[0].phase = 'g'

    # ── Solvent recovery: separate propylcyclohexane (tops) from dodecane (bottoms) ─
    hdo_col_1 = bst.units.BinaryDistillation(
        ID='HDO_COL1',
        ins=hdo_flsh_1-1,
        LHK=('propylcyclohexane', 'Dodecane'),
        Lr=0.99, Hr=1 - 0.0001, P=101325,
        vessel_material='Stainless steel 316',
        k=2, partial_condenser=True,
    )

    # ── Cool recovered dodecane to feed temperature for recycle ───────────────
    hdo_dodecane_cooler = bst.units.HXutility(
        ID='HDO_HX_DOD', ins=hdo_col_1-1, outs=hdo_dodecane_recycle,
        T=300, rigorous=True,
    )

    # ── Product column: remove residual water (HDO_WW, tops); isolate propylcyclohexane (SAF_CycloAlkane, bottoms) ─
    hdo_col_2 = bst.units.BinaryDistillation(
        ID='HDO_COL2',
        ins=hdo_col_1-0,
        outs=('HDO_WW', ''),
        LHK=('Water', 'Propylcyclohexane'),
        y_top=0.9, x_bot=0.001, P=101325, k=2,
    )   

    hdo_hx_4 = bst.units.HXutility('HDO_HX4', ins = hdo_col_2-1, T = 15+273.15, rigorous = True)

    hdo_tk_1 = HydrocarbonProductTank('HDO_TK1', ins = hdo_hx_4-0, outs = 'HDO_CYCLOALKANES_OUT')




    # ── Assemble system ───────────────────────────────────────────────────────
    return bst.System(
        'HDO_System',
        path=(
            hdo_h2_mix, hdo_dodecane_mix, hdo_mix_3,
            hdo_comp_1, hdo_hx_1, hdo_rxr_1,
            hdo_hx_2, hdo_v_1, hdo_flsh_1,
            hdo_flsh_2, hdo_hx_3, hdo_psa_1, hdo_h2_comp,
            hdo_col_1, hdo_dodecane_cooler, hdo_col_2, hdo_hx_4, hdo_tk_1
        ),
        recycle=(hdo_h2_recycle, hdo_dodecane_recycle),
    )
