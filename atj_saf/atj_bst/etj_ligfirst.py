# Global imports
import biosteam as bst, thermosteam as tmo, biorefineries as bf, numpy as np, pandas as pd
from biorefineries import cellulosic
from biosteam import main_flowsheet as F, units

# Local imports
from atj_saf.atj_bst.etj_chemicals import create_chemicals
from atj_saf.atj_bst.etj_settings import feed_parameters, dehyd_data, olig_data, prod_selectivity, hydgn_data, price_data, h2_recovery
from atj_saf.atj_bst.etj_utils import calculate_ethanol_flow
from atj_saf.atj_bst.atj_bst_units import AdiabaticReactor, IsothermalReactor, EthanolStorageTank, HydrocarbonProductTank, HydrogenStorageTank, CatalystMixer
def create_etj_system_no_facilities(ins=None):
    if ins is None:
        bst.F.set_flowsheet('etj')
        etj_chems = create_chemicals()
        bst.settings.set_thermo(etj_chems)

    etoh_flow = calculate_ethanol_flow(9)

    # Bioethanol feed — use caller-supplied stream or create from settings
    if ins is None:
        etj_etoh_in = bst.Stream(
            'ETJ_ETOH_IN',
            Ethanol = etoh_flow,
            Water =  etoh_flow*((1-feed_parameters['purity'])/(feed_parameters['purity'])),
            units = 'kg/hr',
            T = feed_parameters['temperature'],
            P = feed_parameters['pressure'],
            phase = feed_parameters['phase'])
    else:
        etj_etoh_in = ins


    # Reactions

    #1) Gas phase dehydration of ethanol to ethylene
    dehydration_rxn = bst.Reaction('Ethanol,g -> Water,g + Ethylene,g', reactant = 'Ethanol',
                                X = dehyd_data['conv'], phases = 'lg',  basis = 'mol')


    #2) Ethylene oligomerization to olefins in gas and liquid phase
    oligomerization_rxn = bst.ParallelReaction([
    bst.Reaction('2Ethylene,g -> Butene,g',            reactant = 'Ethylene',     X = olig_data['conv']*prod_selectivity['C4H8'],    basis = 'wt',  phases = 'lg',  correct_atomic_balance = True),
    bst.Reaction('3Ethylene,g -> Hex-1-ene,g',       reactant = 'Ethylene',     X = olig_data['conv']*prod_selectivity['C6H12'],   basis = 'wt',  phases = 'lg',  correct_atomic_balance = True),
    bst.Reaction('5Ethylene,g -> Dec-1-ene,l',         reactant = 'Ethylene',     X = olig_data['conv']*prod_selectivity['C10H20'],  basis = 'wt',  phases = 'lg',  correct_atomic_balance = True),
    bst.Reaction('9Ethylene,g -> Octadec-1-ene,l',     reactant = 'Ethylene',     X = olig_data['conv']*prod_selectivity['C18H36'],  basis = 'wt',  phases = 'lg',  correct_atomic_balance = True)])


    hydrogenation_rxn = bst.ParallelReaction([
    bst.Reaction('Butene,g + Hydrogen,g -> Butane,g',               reactant = 'Butene',          X = hydgn_data['conv'],  basis = 'mol',  phases = 'lg',  correct_atomic_balance = True),
    bst.Reaction('Butene,l + Hydrogen,g -> Butane,l',               reactant = 'Butene',          X = hydgn_data['conv'],  basis = 'mol',  phases = 'lg',  correct_atomic_balance = True),
    bst.Reaction('Hex-1-ene,g + Hydrogen,g -> Hexane,g',            reactant = 'Hex-1-ene',       X = hydgn_data['conv'],  basis = 'mol',  phases = 'lg',  correct_atomic_balance = True),
    bst.Reaction('Hex-1-ene,l + Hydrogen,g -> Hexane,l',            reactant = 'Hex-1-ene',       X = hydgn_data['conv'],  basis = 'mol',  phases = 'lg',  correct_atomic_balance = True),
    bst.Reaction('Dec-1-ene,l + Hydrogen,g -> Decane,l',            reactant = 'Dec-1-ene',       X = hydgn_data['conv'],  basis = 'mol',  phases = 'lg',  correct_atomic_balance = True),
    bst.Reaction('Dec-1-ene,g + Hydrogen,g -> Decane,g',            reactant = 'Dec-1-ene',       X = hydgn_data['conv'],  basis = 'mol',  phases = 'lg',  correct_atomic_balance = True),
    bst.Reaction('Octadec-1-ene,l + Hydrogen,g -> Octadecane,l',    reactant = 'Octadec-1-ene',   X = hydgn_data['conv'],  basis = 'mol',  phases = 'lg',  correct_atomic_balance = True),
    bst.Reaction('Octadec-1-ene,g + Hydrogen,g -> Octadecane,g',    reactant = 'Octadec-1-ene',   X = hydgn_data['conv'],  basis = 'mol',  phases = 'lg',  correct_atomic_balance = True)])


    # Recycle streams
    dehyd_recycle = bst.MultiStream('dehyd_recycle', phases = ('g','l'))         # Unreacted ethanol
    ethylene_recycle = bst.MultiStream('ethylene_recycle', phases = ('g','l'))   # Unreacted ethylene
    h2_recycle= bst.Stream(ID = 'h2_recycle', P = 3e6, phase = 'g')              # Excess hydrogen

    # Catalyst replacement streams — flows updated each iteration via add_specification on each reactor
    syndol_replacement    = bst.Stream('Dehyd_cat_replacement', phase = 's', price = price_data['dehydration_catalyst'])
    ni_si_al_replacement  = bst.Stream('Olig_cat_replacement',  phase = 's', price = price_data['oligomerization_catalyst'])
    co_mo_replacement     = bst.Stream('Hydgn_cat_replacement', phase = 's', price = price_data['hydrogenation_catalyst'])


    # Area 100: Feed Storage
    #etoh_storage = EthanolStorageTank('T101', ins = etoh_in)

    etj_h2_in = bst.Stream(ID = 'ETJ_H2_IN', P = 3e6, phase = 'g')
    etj_mix_1 = bst.units.Mixer('ETJ_MIX1', ins = etj_h2_in, rigorous = True)


    # Area 200: Catalytic Upgrading
    etj_pump_1 = bst.Pump('ETJ_PUMP1', ins = etj_etoh_in, P = 1373000)

    etj_hx_1 = bst.HXutility('ETJ_HX1', ins = etj_pump_1.outs[0], T = 500, rigorous = True)

    etj_mix_2 = bst.Mixer('ETJ_MIX2', ins = (etj_hx_1.outs[0], dehyd_recycle), rigorous = True)

    etj_hx_2 = bst.HXutility('ETJ_HX2', ins = etj_mix_2.outs[0], T = 481 + 273.15, rigorous = True)

    etj_rxr_1 = AdiabaticReactor('ETJ_RXR1', ins = etj_hx_2.outs[0],
                            conversion = dehyd_data['conv'],
                            temperature = dehyd_data['temp'],
                            pressure = dehyd_data['pressure'],
                            WHSV = dehyd_data['whsv'],
                            vessel_type = 'Vertical',
                            vessel_material = 'Stainless steel 316',
                            catalyst_price=price_data['dehydration_catalyst'],
                            catalyst_lifetime = dehyd_data['catalyst_lifetime'],
                            reaction = dehydration_rxn)

    @etj_rxr_1.add_specification(run = True)
    def update_syndol_flow():
        # Catalyst weight = feed_flow / WHSV — identical to AdiabaticReactor._design() formula
        cat_wt = etj_rxr_1.ins[0].F_mass / dehyd_data['whsv']
        syndol_replacement.imass['Syndol'] = cat_wt / dehyd_data['catalyst_lifetime'] / 8760  # kg/hr


    etj_split_1 = bst.Splitter('ETJ_SPLIT1', ins = etj_rxr_1.outs[0], outs = ('flash_in', dehyd_recycle), split = 0.3)

    etj_flsh_1 = bst.Flash('ETJ_FLSH1', ins = etj_split_1.outs[0], outs = ('ETHYLENE_WATER', 'ETJ_WW1'), T= 420,  P = 1.063e6)

    etj_comp_1 = bst.IsentropicCompressor('ETJ_COMP1', ins = etj_flsh_1.outs[0], P = 2e6, vle = True, eta = 0.72, driver_efficiency = 1)

    etj_col_1 = bst.BinaryDistillation('ETJ_COL1', ins = etj_comp_1.outs[0],
                                                outs = ('ethylene_water', 'WW'),
                                    LHK = ('Ethylene', 'Water'),
                                    P = 2e+06,
                                    y_top = 0.999, x_bot = 0.001, k = 2,
                                    is_divided = False)

    etj_comp_2 = bst.IsentropicCompressor('ETJ_COMP2', ins = etj_col_1.outs[0], P = olig_data['pressure'], vle = True, eta = 0.72, driver_efficiency = 1)

    etj_col_2 = bst.BinaryDistillation('ETJ_COL2', ins = etj_comp_2.outs[0],
                                    LHK = ('Ethylene', 'Ethanol'),
                                    P = 3.5e+06,
                                    y_top = 0.9999, x_bot = 0.0001, k = 2,
                                    is_divided = False)

    etj_hx_3 = bst.HXutility('ETJ_HX3', ins = etj_col_2.outs[0], T = 393.15, rigorous = True)

    etj_mix_3 = bst.Mixer(ID = 'ETJ_MIX3', ins = (etj_hx_3.outs[0],ethylene_recycle), rigorous = True)

    etj_rxr_2 = IsothermalReactor('ETJ_RXR2', ins = etj_mix_3.outs[0],
                                conversion = olig_data['conv'],
                                temperature = olig_data['temp'],
                                pressure = olig_data['pressure'],
                                WHSV = olig_data['whsv'],
                                catalyst_price = price_data['oligomerization_catalyst'],
                            reaction = oligomerization_rxn)

    @etj_rxr_2.add_specification(run = True)
    def update_ni_si_al_flow():
        cat_wt = etj_rxr_2.ins[0].F_mass / olig_data['whsv']
        ni_si_al_replacement.imass['Nickel_SiAl'] = cat_wt / olig_data['catalyst_lifetime'] / 8760  # kg/hr


    etj_split_2 = bst.Splitter('ETJ_SPLIT2', ins = etj_rxr_2.outs[0], outs = (ethylene_recycle,'oligs'),  split = {'Ethylene':1.0})

    # 3:1 excess hydrogen to oligomers molar ratio, with 100% molar conversion 2x moles oligomer H2 is left,
    # and 85 mol% is recovered, so fresh H2 must cover reacted H2 (1x moles oligomer) and PSA losses (0.15 * 2x moles oligomer)
    @etj_mix_1.add_specification(run = True)
    def h2_flow():
        total_h2_req = 3 * (etj_rxr_2.outs[0].imol['Butene'] + etj_rxr_2.outs[0].imol['Hex-1-ene']
                            + etj_rxr_2.outs[0].imol['Dec-1-ene'] + etj_rxr_2.outs[0].imol['Octadec-1-ene'])
        etj_mix_1.ins[0].imol['Hydrogen'] = total_h2_req - h2_recycle.imol['Hydrogen']


    etj_mix_4 = bst.Mixer('ETJ_MIX4', ins = (etj_mix_1.outs[0], etj_split_2.outs[1], h2_recycle), rigorous = True)

    etj_hx_4 = bst.HXutility('ETJ_HX4', etj_mix_4.outs[0], T = 350 +273.15, rigorous = True)

    etj_rxr_3 = AdiabaticReactor('ETJ_RXR3', ins = etj_hx_4.outs[0],
                            conversion = hydgn_data['conv'],
                            temperature = hydgn_data['temp'],
                            pressure = hydgn_data['pressure'],
                            WHSV = hydgn_data['whsv'],
                            catalyst_price = price_data['hydrogenation_catalyst'],
                            reaction = hydrogenation_rxn)

    @etj_rxr_3.add_specification(run = True)
    def update_co_mo_flow():
        cat_wt = etj_rxr_3.ins[0].F_mass / hydgn_data['whsv']
        co_mo_replacement.imass['CobaltMolybdenum'] = cat_wt / hydgn_data['catalyst_lifetime'] / 8760  # kg/hr


    etj_hx_5 = bst.HXutility('ETJ_HX5', ins = etj_rxr_3.outs[0], T = 250, rigorous = True)

    etj_flsh_2 = bst.Flash('ETJ_FLSH2', ins = etj_hx_5-0, T = 250, P = 5e5)

    etj_split_3 = bst.Splitter('ETJ_SPLIT3', ins = etj_flsh_2-0, outs = (h2_recycle,'ETJ_PSAWASTE_OUTS'),  split = {'Hydrogen':h2_recovery})


    # Area 300: Product Fractionation
    etj_col_3 = bst.BinaryDistillation('ETJ_COL3', ins = etj_flsh_2.outs[1],
                                    outs = ('distillate', 'bottoms'),
                                    LHK = ('Hexane', 'Decane'),
                                    y_top = 0.99, x_bot = 0.01, k = 2,
                                    is_divided = True)

    etj_col_4 = bst.BinaryDistillation('ETJ_COL4', ins = etj_col_3.outs[1],
                                    outs = ('distillate_1', 'bottoms_1'),
                                    LHK = ('Decane', 'Octadecane'),
                                    y_top = 0.99, x_bot = 0.01, k = 2,
                                    is_divided = True)

    etj_hx_6 = bst.HXutility('ETJ_HX6', ins = etj_col_3.outs[0], V = 0, rigorous = True)

    etj_hx_7 = bst.HXutility('ETJ_HX7', ins = etj_col_4.outs[0], T = 15+273.15, rigorous = True)

    # rigorous=True VLE can produce a trace gas fraction at 15°C; override to liquid after each run
    # so HydrocarbonProductTank always receives a single-phase liquid stream
    @etj_hx_7.add_specification(run = False)
    def simulate_cooler_7():
        etj_hx_7._run()
        etj_hx_7._design()
        etj_hx_7._cost()
        etj_hx_7.outs[0].phase = 'l'

    etj_hx_8 = bst.HXutility('ETJ_HX8', ins = etj_col_4.outs[1], T = 15+273.15, rigorous = True)

    @etj_hx_8.add_specification(run = False)
    def simulate_cooler_8():
        etj_hx_8._run()
        etj_hx_8._design()
        etj_hx_8._cost()
        etj_hx_8.outs[0].phase = 'l'


    # Area 500: Product Storage
    etj_tk_1  = HydrocarbonProductTank('ETJ_TK1', ins = etj_hx_6.outs[0], outs = 'ETJ_RN_OUT')
    etj_tk_2 = HydrocarbonProductTank('ETJ_TK2', ins = etj_hx_7.outs[0], outs = 'ETJ_SAF_OUT')
    etj_tk_3  = HydrocarbonProductTank('ETJ_TK3', ins = etj_hx_8.outs[0], outs = 'ETJ_RD_OUT')


    # Area 600: Wastewater collection (no WWT facility — routed to central utilities in combined system)
    WW_mixer = bst.Mixer('ETJ_WW_MIX', ins = (etj_flsh_1-1, etj_col_1-1, etj_col_2-1), outs = 'ETJ_WW_OUTS', rigorous = True)

    catalyst_replacement_unit = CatalystMixer('ETJ_CAT_MIX', ins = (syndol_replacement, ni_si_al_replacement, co_mo_replacement))




    etj_sys = bst.System('atj_sys', path = (etj_mix_1, etj_pump_1, etj_hx_1, etj_mix_2, etj_hx_2, etj_rxr_1, etj_split_1, etj_flsh_1, etj_comp_1,
                                            etj_col_1, etj_comp_2, etj_col_2, etj_hx_3, etj_mix_3,
                                            etj_rxr_2, etj_split_2, etj_mix_4, etj_hx_4, etj_rxr_3, etj_hx_5,
                                            etj_flsh_2, etj_split_3, etj_col_3, etj_col_4, etj_hx_6, etj_hx_7, etj_hx_8,
                                            etj_tk_1, etj_tk_2, etj_tk_3, WW_mixer, catalyst_replacement_unit),
                                            recycle = (dehyd_recycle, ethylene_recycle, h2_recycle))

    return etj_sys