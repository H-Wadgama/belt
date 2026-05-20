import math, biosteam as bst, numpy as np
from typing import Optional
from biosteam.units.design_tools import (PressureVessel,)
from math import ceil


class AdiabaticReactor(bst.Unit, bst.units.design_tools.PressureVessel):

    """
    Reactor class for an adiabatic catalytic reaction. 
    Can be used for one or multiple parallel reactions. 

    Parameters
    ----------
    ins :               Inlet stream -> 1 
    outs :              Outlet stream -> 1 
    conversion :        defaults to 100% conversion 
    temperature :       defaults to 280 C 
    pressure :          defaults to 1 bar (100000 Pa)
    WHSV :              weighted hourly space velocity (ratio of hourly feed flow to the catalyst weight)
    aspect_ratio :      length to diameter ratio defaults to 3.0
    catalyst_density :  defaults to 0.72 kg/L for HZSM-5
    catalyst_price :    defaults to $100/kg 
    catalyst_lifetime : defaults to  year

    """
    _F_BM_default = {'Horizontal pressure vessel': 3.05,
                     'Vertical pressure vessel': 4.16,
                     'Platform and ladders': 1.,
                     'Catalyst loading cost':1.}

    
    _N_ins = 1
    _N_outs = 1

    _units = {
        'Catalyst Weight': 'kg',
        'Volume': 'L',
        'Pressure': 'psi',
        'Length': 'ft',
        'Diameter': 'ft',
        'Wall thickness': 'in',
        'Vessel Weight': 'lb',
        'Duty': 'kJ/hr',
        'Catalyst loading cost': 'USD'}
    

    

    def _init(self, conversion = 1, 
                 temperature = 300, 
                 pressure = 1e5, 
                 WHSV = 1, 
                 vessel_material: Optional[str] = None,
                vessel_type: Optional[str] = None,
        aspect_ratio = 3.0, 
        catalyst_density = 0.72, 
        catalyst_price = 100, 
        catalyst_lifetime = 1, 
        *, 
        reaction):
        

        self.conversion = conversion
        self.temperature = temperature
        self.pressure = pressure
        self.WHSV = WHSV
        self.vessel_material = 'Stainless steel 316' if vessel_material is None else vessel_material
        self.vessel_type = 'Vertical' if vessel_type is None else vessel_type
        self.aspect_ratio = aspect_ratio
        self.catalyst_density = catalyst_density
        self.catalyst_price = catalyst_price
        self.catalyst_lifetime = catalyst_lifetime
        self.reaction = reaction

    def _run(self): 
            inf, = self.ins
            eff, = self.outs
            eff.mix_from(self.ins)
            self.reaction.adiabatic_reaction(eff)

            


        
    def _design(self):
        D = self.design_results
        feed_flow = self.ins[0].F_mass
        catalyst_weight = feed_flow/self.WHSV 
        reactor_volume = (catalyst_weight/self.catalyst_density)*1.15 #15% extra for volume
        
        diameter =  ((4*((reactor_volume*0.001)/(0.3048**3)))/
                     (3.14*self.aspect_ratio))**(1/3)
        length = self.aspect_ratio*diameter

        self.design_results.update(
            self._vertical_vessel_design(    
                self.pressure*(1/6894.76),
                diameter, 
                length
            )
        )
        
        duty =  self.outs[0].H - self.ins[0].H + self.outs[0].Hf - self.ins[0].Hf   # Should be 0 for adiabatic operation

        D['Catalyst Weight'] = catalyst_weight
        D['Volume'] = reactor_volume
        D['Length'] = length
        D['Diameter'] = diameter
        D['Duty'] = duty


    def _cost(self):
        design = self.design_results
        baseline_purchase_costs = self.baseline_purchase_costs

        weight = design['Weight']  

        # Calculates the baseline purchase cost based off diameter length and weight
        baseline_purchase_costs.update( 
            self._vessel_purchase_cost(weight, design['Diameter'], design['Length'])
        )
        
        catalyst_loading_cost = self.catalyst_price*design['Catalyst Weight']
        baseline_purchase_costs['Catalyst loading cost'] = catalyst_loading_cost
         
# getter setter to ensure values of conversion 0 < x < 1
    @property
    def conversion(self):
        '''Conversion of primary reactant in reactor'''
        return self._conversion
    @conversion.setter
    def conversion(self, i):
        if not 0 <= i <= 1:
            raise AttributeError('`conversion` must be within [0, 1], '
                                    f'the provided value {i} is outside this range.')
        self._conversion = i




class IsothermalReactor(bst.Unit, bst.units.design_tools.PressureVessel):

    '''
    Reactor class for an adiabatic catalytic reaction. 
    Can be used for one or multiple parallel reactions. 

    Parameters
    ----------
    ins :               Inlet stream -> 1 
    outs :              Outlet stream -> 1 
    conversion :        defaults to 100% conversion 
    temperature :       defaults to 280 C 
    pressure :          defaults to 1 bar (100000 Pa)
    WHSV :              weighted hourly space velocity (ratio of hourly feed flow to the catalyst weight)
    aspect_ratio :      length to diameter ratio defaults to 3.0
    catalyst_density :  defaults to 0.72 kg/L for HZSM-5
    catalyst_price :    defaults to $100/kg 
    catalyst_lifetime : defaults to  year

    
    '''

    _F_BM_default = {'Horizontal pressure vessel': 3.05,
                     'Vertical pressure vessel': 4.16,
                     'Platform and ladders': 1.,
                     'Catalyst loading cost':1.}
    
    _N_ins = 1
    _N_outs = 1

    _units = {
        'Catalyst Weight': 'kg',
        'Volume': 'L',
        'Pressure': 'psi',
        'Length': 'ft',
        'Diameter': 'ft',
        'Wall thickness': 'in',
        'Vessel Weight': 'lb',
        'Duty': 'kJ/hr',
        'Catalyst loading cost': 'USD'}
    
    #_F_BM_default: {'Horizontal pressure vessel': 3.05,
    #                'Platform and ladders': 1}
    

    def _init(self, conversion = 1, 
                 temperature = 300, 
                 pressure = 1e5, 
                 WHSV = 1, 
                 vessel_material: Optional[str] = None,
                vessel_type: Optional[str] = None,
        aspect_ratio = 3.0, 
        catalyst_density = 0.72, 
        catalyst_price = 100, 
        catalyst_lifetime = 1, 
        *, 
        reaction):
        

        self.conversion = conversion
        self.temperature = temperature
        self.pressure = pressure
        self.WHSV = WHSV
        self.vessel_material = 'Stainless steel 316' if vessel_material is None else vessel_material
        self.vessel_type = 'Vertical' if vessel_type is None else vessel_type
        self.aspect_ratio = aspect_ratio
        self.catalyst_density = catalyst_density
        self.catalyst_price = catalyst_price
        self.catalyst_lifetime = catalyst_lifetime
        self.reaction = reaction

    def _run(self):
        inf, = self.ins
        eff, = self.outs
        eff.mix_from(self.ins)
        self.reaction(eff)
        eff.P = inf.P


        
    def _design(self):
        D = self.design_results
        feed_flow = self.ins[0].F_mass
        catalyst_weight = feed_flow/self.WHSV 
        reactor_volume = (catalyst_weight/self.catalyst_density)*1.15 #15% extra for volume
        
        diameter =  ((4*((reactor_volume*0.001)/(0.3048**3)))/
                     (3.14*self.aspect_ratio))**(1/3)
        length = self.aspect_ratio*diameter

        self.design_results.update(
            self._vertical_vessel_design(    
                self.pressure*(1/6894.76),
                diameter, 
                length
            )
        )
        
        self.outs[0].T= self.ins[0].T # Isothermal operation
        duty =  self.outs[0].H - self.ins[0].H + self.outs[0].Hf - self.ins[0].Hf
        heat_utility = self.add_heat_utility(duty, self.temperature) # BioSTEAM automatically setting utility based off duty


        D['Catalyst Weight'] = catalyst_weight
        D['Volume'] = reactor_volume
        D['Length'] = length
        D['Diameter'] = diameter
        D['Duty'] = duty


    def _cost(self):
        design = self.design_results
        baseline_purchase_costs = self.baseline_purchase_costs

        weight = design['Weight']  # weight parameter stores the value from the 'Weight' key in the design dictionnary

        # Calculates the baseline purchase cost based off diameter length and weight
        baseline_purchase_costs.update( 
            self._vessel_purchase_cost(weight, design['Diameter'], design['Length'])
        )
        
        catalyst_loading_cost = self.catalyst_price*design['Catalyst Weight']
        baseline_purchase_costs['Catalyst loading cost'] = catalyst_loading_cost
         
# getter setter to ensure values of conversion 0 < x < 1
    @property
    def conversion(self):
        '''Conversion of ethanol to ethylene in this reactor'''
        return self._conversion
    @conversion.setter
    def conversion(self, i):
        if not 0 <= i <= 1:
            raise AttributeError('`conversion` must be within [0, 1], '
                                    f'the provided value {i} is outside this range.')
        self._conversion = i


        



class EthanolStorageTank(bst.Unit):
    '''
    Hydrocarbon storage tank from [1] 
    Similar storage for gasoine and jet fuel


    The costing is based off 2 tanks, 750,000 gallons each, and 7 days of storage
    The costing year in the original analysis was 2009. Costing is based off vendor 'Mueller'
    Also assumes one spare
    Purchase cost provided is multiplied with 1.7 (installation factor) provided in [1]
    Material of construction is ASTM A285 Grade C carbon steel.

    [1] Humbird, D., Davis, R., Tao, L., Kinchin, C., Hsu, D., Aden, A., ... & Dudgeon, D. (2011). 
    Process design and economics for biochemical conversion of lignocellulosic biomass to ethanol: 
    dilute-acid pretreatment and enzymatic hydrolysis of corn stover (No. NREL/TP-5100-47764). 
    National Renewable Energy Lab.(NREL), Golden, CO (United States).

    '''

    _F_BM_default = {**bst.design_tools.PressureVessel._F_BM_default}

    _N_ins = 1
    _N_outs = 1

    _units = {
        'Storage Days': 'days',
        'Total Capacity': 'gals'}



    def _init(self, storage_period = 7,
                tank_exp = 0.7):
        self.storage_period = storage_period
        self.tank_exp = tank_exp
        
            
    def _design(self):
        D = self.design_results
        ethanol_flow = self.ins[0].F_vol
        capacity = ethanol_flow  * 264.172* self.storage_period *24
        D['Total Capacity'] = capacity

    def _cost(self):
        D = self.design_results
        purchase_costs = self.baseline_purchase_costs
        total_cost = 1.7*1340000*(bst.CE/521.9)*(D['Total Capacity']/750000)**self.tank_exp 
        purchase_costs['Total Cost'] = total_cost
        
        
class HydrogenStorageTank(bst.Unit):
    '''
    Hydrogen storage tank based off the method by [1]

    Method assumes compressd H2 gas storage at 20 MPa
    Installed cost of tank calculated was ($600/lb)*(500 lb tank) = $300,000 per tank
    Installed cost of tank is then subsequently scaled up using an exponent of 0.75 from [1]
    
    _N_ins = 1 (just one hydrogen feed)
    _N_outs = 1
    storage_period = defaults to 7 days of storage
    tank_exp = scale up factor for storage tank based off [1]

    [1] Amos, W. A. (1999). Costs of storing and transporting hydrogen (No. NREL/TP-570-25106; ON: DE00006574). National Renewable Energy Lab.(NREL), Golden, CO (United States).

    '''

    _F_BM_default = {**bst.design_tools.PressureVessel._F_BM_default}

    _N_ins = 1
    _N_outs = 1

    _units = {
        'Storage Days': 'days',
        'Total Capacity': 'kg'}



    def _init(self, storage_period = 7, tank_exp = 0.75):
        self.storage_period = storage_period
        self.tank_exp = tank_exp        
        self.max_size = 1300   # Maximum compressor sizing limited to 1,300 kg because of high capital costs [1]
    

        


    def _design(self):
        D = self.design_results
        h2_flow = self.ins[0].F_mass 
        capacity = h2_flow * self.storage_period * 24 
        D['Total Capacity'] = capacity
        N_vessels = ceil(capacity/self.max_size)   
        self.parallel['self'] = N_vessels

    def _cost(self):
        D = self.design_results
        purchase_costs = self.baseline_purchase_costs

        total_cost = (600*500) * (self.max_size /(500/2.2))**self.tank_exp
        purchase_costs['Total Cost'] = total_cost

        # total_cost_cepci_update = total_cost * (bst.CE/381.1)
        # total_cost_remove_lang_factor = (total_cost_cepci_update/5.04)
        #D['Total Cost'] = total_cost_cepci_update
        #purchase_costs['Total Cost'] = total_cost_remove_lang_factor
        


class HydrocarbonProductTank(bst.Unit):
    '''
    Hydrocarbon storage tank from [1].
    Study assumed same storage vessels for gasoline and diesel. Costing based off Aspen Capital Cost Estimator tool
    Gasoline similar to renewable naphtha and diesel similar to SAF, so we assume 1 type of storage 
    for hydrocarbon products.
    Cost is given as installed equipment cost in 2013 dollars, for a 500,000 gal storage tank at 15 psi, and 250 F
    Material of construction is carbon steel. 
    Scaling exponent is 0.7. Study also accounts for one spare tank
    

    [2] Dutta, A., Sahir, A. H., Tan, E., Humbird, D., Snowden-Swan, L. J., Meyer, P. A., ... & Lukas, J. 
    (2015). Process design and economics for the conversion of lignocellulosic biomass to hydrocarbon fuels:
    Thermochemical research pathways with in situ and ex situ upgrading of fast pyrolysis vapors 
    (No. PNNL-23823). Pacific Northwest National Lab.(PNNL), Richland, WA (United States).


    '''


    _F_BM_default = {**bst.design_tools.PressureVessel._F_BM_default}

    _N_ins = 1
    _N_outs = 1

    _units = {
        'Storage Days': 'days',
        'Total Capacity': 'gals'}

    
    def _init(self, storage_period = 14,
                tank_exp = 0.7):
        self.storage_period = storage_period
        self.tank_exp = tank_exp
        
            
    def _design(self):
        D = self.design_results
        hydrocarbon_flow = self.ins[0].F_vol
        capacity = hydrocarbon_flow  * 264.172* self.storage_period *24
        D['Total Capacity'] = capacity

    def _cost(self):
        D = self.design_results
        purchase_costs = self.baseline_purchase_costs
        total_cost = 1553400*(bst.CE/567.3)*(D['Total Capacity']/500000)**self.tank_exp

        purchase_costs['Total Cost'] = total_cost
        
        
    
  
class CatalystMixer(bst.Unit):

    _N_ins = 1
    _N_outs = 1


    _ins_size_is_fixed = False

    def _init(self):
        pass
 
    
    def _run(self):
        feeds = [i for i in self.ins]
        effluent, = self.outs
        effluent.mix_from(feeds)

        

    def _design(self):
        pass
        
    
    