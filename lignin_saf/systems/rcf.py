import biosteam as bst
from lignin_saf.ligsaf_units import SolvolysisReactor, HydrogenolysisReactor, PSA, CatalystMixer
from lignin_saf.ligsaf_chemicals import create_chemicals
from lignin_saf.ligsaf_settings import (
    rcf_oil_yield, prices, feed_parameters, rcf_conditions,
    solvolysis_parameters, meoh_h2o, h2_biomass_ratio,
    poplar_density, free_frac,
    V_max_limit, condensation_extent, h2_pressure, operating_days, h2_consumption, h2_rcf_excess
)


def create_rcf_system(ins=None):
    """
    Build and return the RCF loop as a bst.System.

    Parameters
    ----------
    ins : bst.Stream, optional
        Poplar feedstock stream. If None, a default stream is created
        from feed_parameters in ligsaf_settings.py.

    Returns
    -------
    bst.System
        'RCF_System' with meoh_recycle and hydrogen_recycle converged.

    Notes
    -----
    Caller is responsible for setting up thermodynamics before calling:
        chems = create_chemicals()
        bst.settings.set_thermo(chems)
        bst.settings.CEPCI = 541.7
    """
    chems = bst.settings.chemicals

    # Poplar pseudocomponent group (Bartling et al Table S1)
    # Re-defining is safe — thermosteam silently overwrites existing groups
    chems.define_group(
        name='Poplar',
        IDs=['Glucan', 'Xylan', 'Arabinan', 'Mannan', 'Galactan',
             'Sucrose', 'Lignin', 'Acetate', 'Extract', 'Ash'],
        composition=[0.464, 0.134, 0.002, 0.037, 0.014,
                     0.001, 0.285, 0.035, 0.016, 0.012],
        wt=True
    )

    # ── Feedstock ─────────────────────────────────────────────────────────────
    if ins is None:
        ins = bst.Stream('Poplar_In',
                         Poplar=feed_parameters['flow'] * 1e3,
                         Water=feed_parameters['moisture'] * feed_parameters['flow'] * 1e3,
                         phase='l', units='kg/d', price=prices['Feedstock'])

    # ── Recycle streams ───────────────────────────────────────────────────────
    rcf_meoh_recycle = bst.MultiStream('Meoh_recycle', phases=('s', 'l', 'g'))
    rcf_h2_recycle = bst.Stream('hydrogen_recycle', P=rcf_conditions['P'], phase='g')


    

    # ── Co-feeds ──────────────────────────────────────────────────────────────
    # Methanol and water split into separate streams so price applies only to methanol
    rcf_meoh_in = bst.Stream('RCF_MEOH_IN', Methanol=0.0, phase='l', units='kg/hr', price=prices['Methanol'])
    rcf_water_in = bst.Stream('RCF_H2O_IN', Water=0.0, phase='l', units='kg/hr')

    
    # Catalyst
    rcf_cat_in = bst.Stream(
        ID='RCF_CAT_IN',
        NiC=(rcf_conditions['cat_loading'] * (feed_parameters['flow'] * 1e3 / 24) * rcf_conditions['tau_h']) / (rcf_conditions['cat_lifetime'] * 30),
        units='kg/day', phase='s', price=prices['NiC_catalyst']
    )

    # H2 required depends on amount of lignin oil, which depends on the extent of delignifciation
    # 0.15 is for 15% loss in PSA and h2_rcf_excess is 1.2 x the minimum H2 required to ensure there is always sufficient H2 flowing 
    h2_required = ((ins.imass['Lignin']*solvolysis_parameters['Delignification']*h2_consumption)/(1-0.15))*h2_rcf_excess # Miscalculating

    rcf_h2_in = bst.Stream('RCF_H2_IN',
                             Hydrogen=h2_required,
                             units='kg/hr',
                             T=80 + 273.15,   # 80°C PEM electrolyzer outlet
                             P=rcf_conditions['P'],           # 30 bar PEM electrolyzer outlet
                             phase='g',
                             price = prices['Hydrogen'])


    # ── Unit operations ───────────────────────────────────────────────────────

    # MeOH mixer: adjusts fresh feed to make up for what the recycle doesn't supply
    rcf_mix_1 = bst.units.Mixer('MIX100', ins=(rcf_meoh_in, rcf_water_in, rcf_meoh_recycle), rigorous=True)

    @rcf_mix_1.add_specification(run=True)
    def meoh_water_flow():
        meoh_fresh     = rcf_mix_1.ins[0]
        water_fresh    = rcf_mix_1.ins[1]
        recycle_solvent = rcf_mix_1.ins[2]
        total_vol_hr = rcf_rxr_1.compute_Q_total()  # m³/hr — derived from bed geometry
        meoh_flow_mol = (
            total_vol_hr * meoh_h2o / (meoh_h2o + 1)
            * chems['Methanol'].rho(phase='l', T=rcf_conditions['T'], P=rcf_conditions['P'])
            * (1 / chems['Methanol'].MW)
        )
        water_flow_mol = (
            total_vol_hr / (meoh_h2o + 1)
            * chems['Water'].rho(phase='l', T=rcf_conditions['T'], P=rcf_conditions['P'])
            * (1 / chems['Water'].MW)
        )
        meoh_fresh.imol['Methanol']  = meoh_flow_mol  - recycle_solvent.imol['Methanol']
        water_fresh.imol['Water']    = water_flow_mol - recycle_solvent.imol['Water']
        rcf_mix_1.outs[0].phases = ('s', 'l', 'g')  # needed by downstream reactors

    rcf_pump_1 = bst.units.Pump('RCF_PUMP1', ins=rcf_mix_1-0, P=rcf_conditions['P'])

    rcf_hx_1 = bst.units.HXutility('RCF_HX1', ins=rcf_pump_1-0, T=rcf_conditions['T'], rigorous=True)

    @rcf_hx_1.add_specification(run=True)
    def set_meoh_heater_phases():
        rcf_hx_1.outs[0].phases = ('l', 'g')

    # Solvolysis reactions
    solvolysis_rxn = bst.Reaction(
        'Lignin -> SolubleLignin', reactant='Lignin',
        X=solvolysis_parameters['Delignification'],
        basis='wt', correct_atomic_balance=False
    )
    methanol_decomposition_rxn = bst.ParallelReaction([
        bst.Reaction('Methanol,l -> Methane,g', reactant='Methanol', phases='lg',
                     X=solvolysis_parameters['MeOH_CH4'], basis='wt', correct_atomic_balance=False),
        bst.Reaction('Methanol,l -> CO,g', reactant='Methanol', phases='lg',
                     X=solvolysis_parameters['MeOH_CO'], basis='wt', correct_atomic_balance=False),
    ])

    # Deacetylation
    deacetylation = bst.Reaction('Acetate -> AceticAcid', reactant = 'Acetate', X = 1.0) # From https://doi.org/10.1002/cssc.201601121

    rcf_rxr_1 = SolvolysisReactor(
        'RCF_RXR1',
        ins=(ins, rcf_hx_1-0),
        outs=('Wet_Pulp', 'Solvolysis_Liquor'),
        T=rcf_conditions['T'],
        P=rcf_conditions['P'],
        tau=rcf_conditions['tau_s'],               # 3 hr time on stream per batch
        tau_0=rcf_conditions['tau_0'],                                   # 1 hr cleaning/turnaround
        tau_residence=rcf_conditions['tau_s_res'], # 20 min hydraulic residence time
        void_frac=0.5,
        superficial_velocity=0.01,
        poplar_density=poplar_density,             # 485 kg/m³ bulk density
        free_frac=free_frac,                       # 10% free headspace
        V_max_limit=V_max_limit,                   # hard upper bound on vessel volume
        reaction_1=solvolysis_rxn,
        reaction_2=methanol_decomposition_rxn,
        reaction_3 = deacetylation
    )

    # H2 mixer: adjusts fresh H2 to make up for recycle shortfall
    rcf_mix_2 = bst.units.Mixer('RCF_MIX2', ins=(rcf_h2_in, rcf_h2_recycle))

    @rcf_mix_2.add_specification(run=True)
    def h2_flow():
        fresh_h2 = rcf_mix_2.ins[0]
        recycle_h2 = rcf_mix_2.ins[1]
        fresh_h2.imass['Hydrogen'] = (h2_required) - recycle_h2.imass['Hydrogen']
        rcf_mix_2.outs[0].phase = 'g'

    rcf_hx_2 = bst.units.HXutility('RCF_HX2', ins=rcf_mix_2-0, T=rcf_conditions['T'], rigorous=True)

    @rcf_hx_2.add_specification(run=True)
    def set_h2_preheat_phase():
        rcf_hx_2.outs[0].phase = 'g'

    # Hydrogenolysis reactions
    # The six parallel reactions are designed so that ΣXi = Monomers + Dimers + Oligomers = 1.0
    # for any condensation_extent (algebraic identity). BioSTEAM's ParallelReaction captures the
    # initial reactant amount and subtracts Xi×SL0 sequentially; the check raises InfeasibleRegion
    # when remaining < -1e-12. At high delignification (large SL0), floating-point error in the
    # sum can exceed this threshold. Scale all X values by (1 - 1e-6) to leave ~1 ppm unconverted
    # and keep the residual well above -1e-12 for any feasible SL0.
    _X_scale = 1.0 - 1e-6
    hydrogenolysis = bst.ParallelReaction([
        bst.Reaction('SolubleLignin,l -> Propylguaiacol,l', reactant='SolubleLignin', phases='lg',
                     X=_X_scale * rcf_oil_yield['Monomers'] * 0.5*(1-condensation_extent), basis='wt', correct_atomic_balance=False),
        bst.Reaction('SolubleLignin,l -> Propylsyringol,l', reactant='SolubleLignin', phases='lg',
                     X=_X_scale * rcf_oil_yield['Monomers'] * 0.5*(1-condensation_extent), basis='wt', correct_atomic_balance=False),
        bst.Reaction('SolubleLignin,l -> Syringaresinol,l', reactant='SolubleLignin', phases='lg',
                     X=_X_scale * rcf_oil_yield['Dimers'] * 0.5, basis='wt', correct_atomic_balance=False),
        bst.Reaction('SolubleLignin,l -> G_Dimer,l', reactant='SolubleLignin', phases='lg',
                     X=_X_scale * rcf_oil_yield['Dimers'] * 0.5, basis='wt', correct_atomic_balance=False),
        bst.Reaction('SolubleLignin,l -> S_Oligomer,l', reactant='SolubleLignin', phases='lg',
                     X=_X_scale * (rcf_oil_yield['Oligomers'] * 0.5 + rcf_oil_yield['Monomers'] * 0.5 * condensation_extent), basis='wt', correct_atomic_balance=False),
        bst.Reaction('SolubleLignin,l -> G_Oligomer,l', reactant='SolubleLignin', phases='lg',
                     X=_X_scale * (rcf_oil_yield['Oligomers'] * 0.5 + rcf_oil_yield['Monomers'] * 0.5 * condensation_extent), basis='wt', correct_atomic_balance=False),
    ])

    rcf_rxr_2 = HydrogenolysisReactor(
        'RCF_RXR2',
        ins=(rcf_rxr_1.outs[1], rcf_hx_2-0, rcf_cat_in),
        P=rcf_conditions['P'],
        T=rcf_conditions['T'],
        tau_residence = rcf_conditions['tau_h'],
        superficial_velocity=0.003,
        reaction=hydrogenolysis,
    )

    rcf_flsh_1 = bst.units.Flash('RCF_FLSH1', ins=rcf_rxr_2-0, T=320, P=5e5)

    rcf_comp_1 = bst.units.IsentropicCompressor('RCF_COMP1', ins=rcf_flsh_1-0, P=5e5, vle=True)
    rcf_flsh_2 = bst.units.Flash('RCF_FLSH2', ins=rcf_comp_1-0, T=260, P=5e5)

    rcf_hx_3 = bst.units.HXutility('RCF_HX3', ins=rcf_flsh_2-0, T=303, rigorous=True)

    @rcf_hx_3.add_specification(run=True)
    def set_psa_inlet_phase():
        rcf_hx_3.outs[0].phase = 'g'

    rcf_psa_1 = PSA('RCF_PSA1', ins=rcf_hx_3.outs[0], outs=('', 'RCF_PSAWASTE_OUTS'))

    rcf_pump_2 = bst.units.IsentropicCompressor('RCF_PUMP2', ins=rcf_psa_1-0, outs=rcf_h2_recycle,
                                              P=rcf_conditions['P'], vle=True)

    @rcf_pump_2.add_specification(run=True)
    def set_h2_pump_phase():
        rcf_pump_2.outs[0].phase = 'g'

    rcf_col_1 = bst.units.BinaryDistillation(
        'RCF_COL1', ins=rcf_flsh_1-1,
        LHK=('Methanol', 'Water'),
        Lr=0.9995, Hr=1 - 0.967, P=101325,
        vessel_material='Stainless steel 316',
        k=2, partial_condenser=True,
    )

    rcf_col_2 = bst.units.BinaryDistillation(
        'RCF_COL2', ins=rcf_col_1-0,
        outs=('', 'To_WW_Treatment'),
        LHK=('Methanol', 'Water'),
        y_top=0.9, x_bot=0.001, P=101325, k=2,
    )

    rcf_mix_3 = bst.units.Mixer('RCF_MIX3', ins=(rcf_col_2-0, rcf_flsh_2-1), rigorous=True)

    rcf_hx_4 = bst.units.HXutility('RCF_HX4', ins=rcf_mix_3.outs[0], outs=rcf_meoh_recycle,
                                    V=0, rigorous=True)

    rcf_flsh_3 = bst.units.Flash('RCF_FLSH3', ins=rcf_col_1-1,
                                    outs=('To_WW_Treatment_2', 'RCF_CRUDE_OUT'), T=400, P=101325)

    rcf_mix_4 = bst.Mixer('RCF_MIX4',
        ins=(rcf_col_2.outs[1], rcf_flsh_3.outs[0]), outs='RCF_WW_OUTS'
    )

      # outs[0]: evaporated MeOH/water from pulp — currently unrecovered (future: route to WWT or solvent recovery)
    rcf_flsh_4 = bst.Flash('RCF_FLSH4', rcf_rxr_1.outs[0], outs=('', 'Carbohydrate_Pulp'), T=400, P=1e5)

    # ── Assemble system ───────────────────────────────────────────────────────
    return bst.System(
        'RCF_System',
        path=(
            rcf_mix_1, rcf_pump_1, rcf_hx_1, rcf_rxr_1,
            rcf_mix_2, rcf_hx_2, rcf_rxr_2,
            rcf_flsh_1, rcf_comp_1, rcf_flsh_2, rcf_hx_3,
            rcf_psa_1, rcf_pump_2, rcf_col_1, rcf_col_2,
            rcf_mix_3, rcf_hx_4, rcf_flsh_3, rcf_mix_4, rcf_flsh_4
        ),
        recycle=(rcf_meoh_recycle, rcf_h2_recycle),
    )