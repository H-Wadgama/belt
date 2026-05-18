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
        etoh_in = bst.Stream(
            'Ethanol_In',
            Ethanol = etoh_flow,
            Water =  etoh_flow*((1-feed_parameters['purity'])/(feed_parameters['purity'])),
            units = 'kg/hr',
            T = feed_parameters['temperature'],
            P = feed_parameters['pressure'],
            phase = feed_parameters['phase'])
    else:
        etoh_in = ins


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
    syndol_replacement    = bst.Stream('Dehyd_cat_replacement', phase = 's')
    ni_si_al_replacement  = bst.Stream('Olig_cat_replacement',  phase = 's')
    co_mo_replacement     = bst.Stream('Hydgn_cat_replacement', phase = 's')


    # Area 100: Feed Storage
    #etoh_storage = EthanolStorageTank('T101', ins = etoh_in)

    h2_in = bst.Stream(ID = 'Hydrogen_In', P = 3e6, phase = 'g')
    h2_storage = HydrogenStorageTank('T102', ins = h2_in)


    # Area 200: Catalytic Upgrading
    pump_1 = bst.Pump('P201', ins = etoh_in, P = 1373000)

    furnace_1 = bst.HXutility('H201', ins = pump_1.outs[0], T = 500, rigorous = True)

    mixer_1 = bst.Mixer('M201', ins = (furnace_1.outs[0], dehyd_recycle), rigorous = True)

    furnace_2 = bst.HXutility('H202', ins = mixer_1.outs[0], T = 481 + 273.15, rigorous = True)

    dehyd_1 = AdiabaticReactor('R201', ins = furnace_2.outs[0],
                            conversion = dehyd_data['conv'],
                            temperature = dehyd_data['temp'],
                            pressure = dehyd_data['pressure'],
                            WHSV = dehyd_data['whsv'],
                            vessel_type = 'Vertical',
                            vessel_material = 'Stainless steel 316',
                            catalyst_price=price_data['dehydration_catalyst'],
                            catalyst_lifetime = dehyd_data['catalyst_lifetime'],
                            reaction = dehydration_rxn)

    @dehyd_1.add_specification(run = True)
    def update_syndol_flow():
        # Catalyst weight = feed_flow / WHSV — identical to AdiabaticReactor._design() formula
        cat_wt = dehyd_1.ins[0].F_mass / dehyd_data['whsv']
        syndol_replacement.imass['Syndol'] = cat_wt / dehyd_data['catalyst_lifetime'] / 8760  # kg/hr


    splitter_1 = bst.Splitter('S201', ins = dehyd_1.outs[0], outs = ('flash_in', dehyd_recycle), split = 0.3)

    flash_1 = bst.Flash('T201', ins = splitter_1.outs[0], outs = ('ETHYLENE_WATER', 'WW_1'), T= 420,  P = 1.063e6)

    comp_1 = bst.IsentropicCompressor('K201', ins = flash_1.outs[0], P = 2e6, vle = True, eta = 0.72, driver_efficiency = 1)

    distillation_1 = bst.BinaryDistillation('D201', ins = comp_1.outs[0],
                                                outs = ('ethylene_water', 'WW'),
                                    LHK = ('Ethylene', 'Water'),
                                    P = 2e+06,
                                    y_top = 0.999, x_bot = 0.001, k = 2,
                                    is_divided = False)

    comp_2 = bst.IsentropicCompressor('K202', ins = distillation_1.outs[0], P = olig_data['pressure'], vle = True, eta = 0.72, driver_efficiency = 1)

    distillation_2 = bst.BinaryDistillation('D202', ins = comp_2.outs[0],
                                    LHK = ('Ethylene', 'Ethanol'),
                                    P = 3.5e+06,
                                    y_top = 0.9999, x_bot = 0.0001, k = 2,
                                    is_divided = False)

    cooler_3 = bst.HXutility('H203', ins = distillation_2.outs[0], T = 393.15, rigorous = True)

    mixer_2 = bst.Mixer(ID = 'M202', ins = (cooler_3.outs[0],ethylene_recycle), rigorous = True)

    olig_1 = IsothermalReactor('R202', ins = mixer_2.outs[0],
                                conversion = olig_data['conv'],
                                temperature = olig_data['temp'],
                                pressure = olig_data['pressure'],
                                WHSV = olig_data['whsv'],
                                catalyst_price = price_data['oligomerization_catalyst'],
                            reaction = oligomerization_rxn)

    @olig_1.add_specification(run = True)
    def update_ni_si_al_flow():
        cat_wt = olig_1.ins[0].F_mass / olig_data['whsv']
        ni_si_al_replacement.imass['Nickel_SiAl'] = cat_wt / olig_data['catalyst_lifetime'] / 8760  # kg/hr


    splitter_2 = bst.Splitter('S202', ins = olig_1.outs[0], outs = (ethylene_recycle,'oligs'),  split = {'Ethylene':1.0})

    # 3:1 excess hydrogen to oligomers molar ratio, with 100% molar conversion 2x moles oligomer H2 is left,
    # and 85 mol% is recovered, so fresh H2 must cover reacted H2 (1x moles oligomer) and PSA losses (0.15 * 2x moles oligomer)
    @h2_storage.add_specification(run = True)
    def h2_flow():
        total_h2_req = 3 * (olig_1.outs[0].imol['Butene'] + olig_1.outs[0].imol['Hex-1-ene']
                            + olig_1.outs[0].imol['Dec-1-ene'] + olig_1.outs[0].imol['Octadec-1-ene'])
        h2_storage.ins[0].imol['Hydrogen'] = total_h2_req - h2_recycle.imol['Hydrogen']


    mixer_4 = bst.Mixer('M203', ins = (h2_storage.outs[0], splitter_2.outs[1], h2_recycle), rigorous = True)

    furnace_3 = bst.HXutility('H204', mixer_4.outs[0], T = 350 +273.15, rigorous = True)

    hydgn_1 = AdiabaticReactor('R203', ins = furnace_3.outs[0],
                            conversion = hydgn_data['conv'],
                            temperature = hydgn_data['temp'],
                            pressure = hydgn_data['pressure'],
                            WHSV = hydgn_data['whsv'],
                            catalyst_price = price_data['hydrogenation_catalyst'],
                            reaction = hydrogenation_rxn)

    @hydgn_1.add_specification(run = True)
    def update_co_mo_flow():
        cat_wt = hydgn_1.ins[0].F_mass / hydgn_data['whsv']
        co_mo_replacement.imass['CobaltMolybdenum'] = cat_wt / hydgn_data['catalyst_lifetime'] / 8760  # kg/hr


    cooler_5 = bst.HXutility('H205', ins = hydgn_1.outs[0], T = 250, rigorous = True)

    flash_2 = bst.Flash('T202', ins = cooler_5-0, T = 250, P = 5e5)

    psa_splitter = bst.Splitter('S203', ins = flash_2-0, outs = (h2_recycle,'ETJ_PSAWASTE_OUTS'),  split = {'Hydrogen':h2_recovery})


    # Area 300: Product Fractionation
    distillation_3 = bst.BinaryDistillation('D301', ins = flash_2.outs[1],
                                    outs = ('distillate', 'bottoms'),
                                    LHK = ('Hexane', 'Decane'),
                                    y_top = 0.99, x_bot = 0.01, k = 2,
                                    is_divided = True)

    distillation_4 = bst.BinaryDistillation('D302', ins = distillation_3.outs[1],
                                    outs = ('distillate_1', 'bottoms_1'),
                                    LHK = ('Decane', 'Octadecane'),
                                    y_top = 0.99, x_bot = 0.01, k = 2,
                                    is_divided = True)

    cooler_6 = bst.HXutility('H301', ins = distillation_3.outs[0], V = 0, rigorous = True)

    cooler_7 = bst.HXutility('H302', ins = distillation_4.outs[0], T = 15+273.15, rigorous = True)

    # rigorous=True VLE can produce a trace gas fraction at 15°C; override to liquid after each run
    # so HydrocarbonProductTank always receives a single-phase liquid stream
    @cooler_7.add_specification(run = False)
    def simulate_cooler_7():
        cooler_7._run()
        cooler_7._design()
        cooler_7._cost()
        cooler_7.outs[0].phase = 'l'

    cooler_8 = bst.HXutility('H303', ins = distillation_4.outs[1], T = 15+273.15, rigorous = True)

    @cooler_8.add_specification(run = False)
    def simulate_cooler_8():
        cooler_8._run()
        cooler_8._design()
        cooler_8._cost()
        cooler_8.outs[0].phase = 'l'


    # Area 500: Product Storage
    rn_storage  = HydrocarbonProductTank('T501', ins = cooler_6.outs[0], outs = 'RN')
    saf_storage = HydrocarbonProductTank('T502', ins = cooler_7.outs[0], outs = 'ETJ_SAF_OUT')
    rd_storage  = HydrocarbonProductTank('T503', ins = cooler_8.outs[0], outs = 'RD')


    # Area 600: Wastewater collection (no WWT facility — routed to central utilities in combined system)
    WW_mixer = bst.Mixer('ETJ_WW_MIX', ins = (flash_1-1, distillation_1-1, distillation_2-1), rigorous = True)
    WW_cooler = bst.HXutility('H602', ins = WW_mixer.outs[0], outs = 'ETJ_WW_OUTS', V = 0, rigorous = True)

    catalyst_replacement_unit = CatalystMixer(ins = (syndol_replacement, ni_si_al_replacement, co_mo_replacement))


    etj_sys = bst.System('atj_sys', path = (pump_1, furnace_1, mixer_1, furnace_2, dehyd_1, splitter_1, flash_1, comp_1,
                                            distillation_1, comp_2, distillation_2, cooler_3, mixer_2,
                                            olig_1, splitter_2, h2_storage, mixer_4, furnace_3, hydgn_1, cooler_5,
                                            flash_2, psa_splitter, distillation_3, distillation_4, cooler_6, cooler_7, cooler_8,
                                            rn_storage, saf_storage, rd_storage, WW_mixer, WW_cooler, catalyst_replacement_unit),
                                            recycle = (dehyd_recycle, ethylene_recycle, h2_recycle))

    return etj_sys
