




import biosteam as bst, numpy as np
from math import ceil

from typing import Optional
from biosteam.units.design_tools import (
    PressureVessel, 
)
 
from lignin_saf.ligsaf_settings import solvolysis_parameters

class SolvolysisReactor(bst.Unit, bst.units.design_tools.PressureVessel):

    """
    Plug flow reactor for solvolysis reaction, where a solvent is used to extract lignin present
    in plant cell wall

    Residence time low enough for the unstable extracted intermediates to be stablized in the downstream hydrogenolysis step
    Design based off [1],[2]. Pressure drop calculations from [3]

    By default,  current design supports multiples of 3 identical biomass beds, with 2x operational beds at any given time, 
    offset by 1 hour each. With a 3 hr reaction time + 1 hr turnaround, this gives near continuous throughput
    Example... t = 0 - 1 hr : bed 1, bed 2 online, bed 3 cleaning, 
                t = 1 - 2 hr, bed 2, bed 3 online, bed 1 cleaning
    Since at any given time, the complete throughput is mantained by 2x reactors, the total volumetric flow rate 
    of solvent is constant

    The maximum volume of an individual reactor was fixed at 600 m3, similar to what was suggested in Bartling et al
    For the solvent flow rate of 9 L/kg dry biomass, this corresponds to  
    
    Assumed: Extraction efficiency constant along the reaction residence time
    No energy released on extraction of lignin. Although this assumption might be revised in the future
    
    
    
    References
    ----------------------------------------------------------------------------------
        [1] Bartling, Andrew W., et al. 
        "Techno-economic analysis and life cycle assessment of a biorefinery utilizing
        reductive catalytic fractionation." Energy & Environmental Science 14.8 (2021): 4147-4168.

        [2] Anderson, Eric M., et al. 
        "Flowthrough reductive catalytic fractionation of biomass." Joule 1.3 (2017): 613-622.

        [3] Froment, Gilbert F., Kenneth B. Bischoff, and Juray De Wilde. 
        Chemical reactor analysis and design. Vol. 2. New York: Wiley, 1990.
   -----------------------------------------------------------------------------------

    
    """



    _F_BM_default = {'Horizontal pressure vessel': 3.05,
                     'Vertical pressure vessel': 4.16,
                     'Platform and ladders': 1.}                   

    auxiliary_unit_names = (
        'pump_1', 'heat_exchanger_1'
    )

    _N_ins = 2
    _N_outs = 2
    
    _units = {**PressureVessel._units,
              'Pressure drop': 'bar',
              'Batch time': 'hr',
              'Turnaround time': 'hr',
              'Time on stream': 'hr',
              'Residence time': 'hr',
              'Total beds': "",
              'Beds in service': "",
              'Total volume': 'm3',
              'Reactor volume': 'm3',
              'Biomass volume per bed': 'm3',
              'Solvent volume per bed': 'm3',
              'Instantaneous loading': 'L/kg',
              'Solvent loading': 'L/kg'}
    


    # Default operating temperature [K]
    T_default: float = 463.15                   # 190 C from  https://doi.org/10.1016/j.joule.2017.10.004

    #: Default operating pressure [Pa]
    P_default:  float = 6e6                     # 6 MPa from https://doi.org/10.1016/j.joule.2017.10.004
    
    #: Default residence time [hr]
    tau_default: float = 2                      # Total 3 hr RCF reaction time divided into 2:1 since solvolysis is more kinetically limiting according to https://pubs.acs.org/doi/full/10.1021/acssuschemeng.8b01256

    #: Default cleaning and unloading time (hr).
    tau_0_default: float  = 1                    # from https://doi.org/10.1039/D1EE01642C
    
    # Default superficial velocity of solvent (m/s)
    superficial_velocity_default: float = 0.01   # Gives L/D ≈ 3 (L ≈ 20 m, D ≈ 6.3 m) at Q = V_solvent/tau_residence

    # Default methanol decomposition (%)
    methanol_decomposition_default: float = 0.005 # From https://doi.org/10.1039/D1EE01642C

    # Default poplar bed void fraction (epsilon)
    void_frac_default: float = 0.5                # Just assumed here, can be fine tuned once data is known. Assyned because this value gives a low value for pressure drop


    # Fixed bed configuration
    N_total_default: int = 4                       # Total beds (3 operating + 1 cleaning)
    N_working_default: int = 3                     # Beds operating at any time

    # Default hydraulic residence time [hr]
    tau_residence_default: float = 1/3             # 20 minutes — determines solvent flow rate per reactor

    # Default poplar bulk density [kg/m³]
    poplar_density_default: float = 485            # Bulk density of poplar chips

    # Default free-space fraction of reactor volume
    free_frac_default: float = 0.10                # 10% kept free for gas disengagement / headspace

    # Default poplar diameter [m]
    poplar_diameter_default: float = 0.004        # https://doi.org/10.1039/D1EE01642C mentions < 5mm, Here 4 mm is considered
    
    # Default maximum vessel volume [m3]
    V_max_default: float = 600                    # Bartling paper considered reactor volume as 600 m3

    # Hard upper bound on individual vessel volume. _size_bed() scales N_total in
    # integer multiples of the ideal-stagger base count until each vessel stays
    # at or below this limit, preserving the stagger timing exactly.
    V_max_limit_default: float = 600              # [m³]

    # Maximum allowable L/D ratio. Ideal packed-bed range is 3–5; hard limit is 10.
    # If the geometry computed from superficial_velocity exceeds this, u is reduced
    # analytically so that L/D = LD_max exactly. Pressure drop is recomputed at the
    # adjusted u since self.superficial_velocity is updated when the cap triggers.
    LD_max_default: float = 5.0



    def _init(
            self,
            T: Optional[float] = None,
            P: Optional[float] = None,
            tau: Optional[float] = None,
            vessel_material: Optional[str] = None,
            vessel_type: Optional[str] = None,
            tau_0: Optional[float] = None,
            superficial_velocity: Optional[float] = None,
            methanol_decomposition: Optional[float] = None,
            void_frac: Optional[float] = None,
            tau_residence: Optional[float] = None,
            poplar_density: Optional[float] = None,
            free_frac: Optional[float] = None,
            poplar_diameter: Optional[float] = None,
            V_max: Optional[float] = None,
            V_max_limit: Optional[float] = None,
            LD_max: Optional[float] = None,
            *,
            reaction_1,
            reaction_2,
            reaction_3
            ):


        self.T = self.T_default if T is None else T
        self.P = self.P_default if P is None else P
        self.tau = self.tau_default if tau is None else tau
        self.vessel_material = 'Stainless steel 316' if vessel_material is None else vessel_material
        self.vessel_type = 'Vertical' if vessel_type is None else vessel_type
        self.tau_0 = self.tau_0_default if tau_0 is None else tau_0
        self.superficial_velocity = self.superficial_velocity_default if superficial_velocity is None else superficial_velocity
        self.methanol_decomposition = self.methanol_decomposition_default if methanol_decomposition is None else methanol_decomposition
        self.void_frac = self.void_frac_default if void_frac is None else void_frac
        self.tau_residence  = self.tau_residence_default  if tau_residence  is None else tau_residence
        self.poplar_density = self.poplar_density_default if poplar_density is None else poplar_density
        self.free_frac      = self.free_frac_default      if free_frac      is None else free_frac
        self.poplar_diameter = self.poplar_diameter_default if poplar_diameter is None else poplar_diameter
        self.V_max = self.V_max_default if V_max is None else V_max
        self.V_max_limit     = self.V_max_limit_default     if V_max_limit     is None else V_max_limit
        self.LD_max          = self.LD_max_default          if LD_max          is None else LD_max
        self.reaction_1 = reaction_1
        self.reaction_2 = reaction_2
        self.reaction_3 = reaction_3
        pump_1 = self.auxiliary('pump_1', bst.Pump, ins = self.ins[1])
        # heat_exchanger_1 = self.auxiliary('heat_exchanger_1', bst.HXutility, pump_1.outs[0])







    def compute_Q_total(self):
        """Return Q_total [m³/hr] from bed geometry alone. No side effects. Callable before simulate()."""
        dry_biomass_kgday = self.ins[0].F_mass * 24.0                   # Previously sized just based on dry biomass weight, but realistically moisture needs to be accounted for 
        cycle_time = self.tau + self.tau_0
        N_total_base = max(2, round(cycle_time / self.tau_0))
        N_working_base = min(N_total_base - 1, max(1, round(N_total_base * self.tau / cycle_time)))
        for k in range(1, 101):
            N_total = k * N_total_base
            N_working = k * N_working_base
            batches_per_day = N_total * (24.0 / cycle_time)
            biomass_per_batch = dry_biomass_kgday / batches_per_day
            V_biomass = biomass_per_batch / self.poplar_density
            V_void = self.void_frac * V_biomass
            V_solvent = V_void * (1.0 + self.free_frac)
            V_max_candidate = (1.0 - self.void_frac) * V_biomass + V_solvent
            if V_max_candidate <= self.V_max_limit + 0.5:
                break
        return N_working * (V_solvent / self.tau_residence)

    def _size_bed(self):

        #### Fixed bed configuration -- N_total set by ideal staggering formula ########

        cycle_time        = self.tau + self.tau_0                  # [hr] e.g. 3 hr on-stream + 1 hr cleaning = 4 hr
        # ins[0] carries the Poplar group (dry biomass) + Water; BioSTEAM stores in kg/hr
        dry_biomass_kgday = self.ins[0].imass['Poplar'] * 24.0    # [kg/day]

        # Ideal stagger base: N_total_base = cycle_time / tau_0 reactors are the minimum
        # for a perfectly staggered schedule (one cleaning slot always occupied).
        # N_working_base = N_total_base × (tau / cycle_time) beds active at any instant.
        # Clamped so at least 1 bed is always online and at least 1 is always cleaning.
        N_total_base   = max(2, round(cycle_time / self.tau_0))
        N_working_base = min(N_total_base - 1,
                             max(1, round(N_total_base * self.tau / cycle_time)))

        # Scale up by integer multiples k = 1, 2, 3, … until each vessel fits within
        # V_max_limit. Scaling by k reduces biomass_per_batch (more, smaller batches),
        # which shrinks V_biomass and thus V_max.
        #   N_total = k × N_total_base,  N_working = k × N_working_base,
        #   N_offline = k × (N_total_base − N_working_base)
        for k in range(1, 101):
            N_total   = k * N_total_base
            N_working = k * N_working_base

            batches_per_day   = N_total * (24.0 / cycle_time)
            biomass_per_batch = dry_biomass_kgday / batches_per_day
            V_biomass         = biomass_per_batch / self.poplar_density
            V_solid           = (1 - self.void_frac) * V_biomass       # [m3] actual wood volume
            V_void            = (self.void_frac * V_biomass)           # [m3] interparticle voids (filled with solvent)
            V_excess_solvent  = V_void*(self.free_frac)                # [m3] Excess solvent to satisfy mass transfer considerations
            V_solvent         = V_void + V_excess_solvent              # solvent occupies the interparticle void and some excess
            
            V_max_candidate   = (V_solid + V_solvent)  # = V_biomass / (1 - free_frac)
            # Q is derived from residence time and void volume; not an input
            Q_per_reactor     = V_solvent / self.tau_residence        # [m3/hr]
            Q_total           = N_working * Q_per_reactor
            if V_max_candidate <= self.V_max_limit + 0.5:
                break
        else:
            raise ValueError(
                f"No feasible reactor count (tried up to k=100 × {N_total_base} = "
                f"{100 * N_total_base} beds) for void_frac={self.void_frac}, "
                f"tau_residence={self.tau_residence} hr, V_max_limit={self.V_max_limit} m³. "
                f"Consider reducing void_frac or tau_residence, or increasing V_max_limit."
            )

        self.V_max      = V_max_candidate
        self.Q_total    = Q_total                                     # [m3/hr] — used by meoh_water_flow spec
        self._loading   = Q_total * 1000.0 * 24.0 / dry_biomass_kgday  # [L/kg] derived loading for reporting
        V_total         = N_total * self.V_max
        self._V_biomass = V_biomass
        self._V_solvent = V_solvent
        self._instantaneous_loading = (V_solvent*1000)/biomass_per_batch

        #### Flow rate and reactor geometry ########

        u  = self.superficial_velocity                             # [m/s]
        A  = Q_per_reactor / (u * 3600)                           # [m2] cross-sectional area
        diameter = 2 * (A / np.pi) ** 0.5                         # [m]
        length   = self.V_max / A                                  # [m]

        # Enforce L/D ≤ LD_max by reducing u analytically.
        # L/D = V_max × √π / (2 × A^(3/2))  →  A = (V_max × √π / (2 × LD_max))^(2/3)
        if length / diameter > self.LD_max:
            A        = (self.V_max * np.pi ** 0.5 / (2.0 * self.LD_max)) ** (2.0 / 3.0)
            u        = Q_per_reactor / (A * 3600)
            diameter = 2 * (A / np.pi) ** 0.5
            length   = self.V_max / A
            self.superficial_velocity = u   # update so pressure drop is consistent

        self.area     = A
        self.diameter = diameter
        self.length   = length

        return length, diameter, N_total, N_working, V_total

        
    def _run(self):
        biomass, solvent = self.ins
        used_biomass, used_solvent = self.outs

        used_solvent.copy_like(solvent) 
        used_biomass.copy_like(biomass) 

        used_solvent.P = self.P                                             # Outlet pressure is set to reactor pressure. Inlet pressure will be greater to account for pressure drop
        used_solvent.T = self.T                                             # Since isothermal operation
        
        for chem_id in ('Methanol', 'Water'):
            used_biomass.imass[chem_id] = used_solvent.imass[chem_id] * 0.005


        self.reaction_1(used_biomass) 
        self.reaction_2(used_solvent)

        solubilized_lignin = used_biomass.imass['SolubleLignin'] 
        used_solvent.imass['l', 'SolubleLignin'] += solubilized_lignin      # Soluble lignin dissolves in solvent effluent stream 
        used_biomass.imass['SolubleLignin'] = 0                             # No soluble lignin remaining in biomass (assuming 100% extraction efficiency)




        extractives = used_biomass.imass['Extract']                         # From Table S1 https://www.rsc.org/suppdata/d1/gc/d1gc01591e/d1gc01591e1.pdf,
                                                                            # it follows that the extractives component of poplar is 'extracted' in the solvent stream
        used_solvent.imass['l','Extract'] = (1-solvolysis_parameters['Extractives_retention'])*extractives
        used_biomass.imass['Extract'] = (solvolysis_parameters['Extractives_retention'])*extractives

        acetate = used_biomass.imass['Acetate']
        used_solvent.imass['l', 'Acetate'] =  acetate *(1-solvolysis_parameters['Acetate_retention']) # Assuming acetate dissolves as acetic acid with methanol,
                                                                             # BioSTEAM Chemicals assumes same properties for acetic acid and acetate, otherwise is acetate was a pseudocomponent, it might have still stayed in solid phase
        used_biomass.imass['Acetate'] = acetate*solvolysis_parameters['Acetate_retention']
        self.reaction_3(used_solvent)


        cellulose_mass = used_biomass.imass['Glucan']
        used_solvent.imass['l', 'Glucan'] = cellulose_mass*(1-solvolysis_parameters['Cellulose_retention']) # Dissolved cellulose assumed to be in liquid phase as solution with solvent
        used_biomass.imass['Glucan'] =  cellulose_mass*solvolysis_parameters['Cellulose_retention']
                                                               

        xylose_mass = used_biomass.imass['Xylan']
        used_solvent.imass['l', 'Xylan'] = xylose_mass * (1-solvolysis_parameters['Xylose_retention']) # Dissolved xylose assumed to be  liquid phase as solution with solvent
        used_biomass.imass['Xylan'] = xylose_mass * solvolysis_parameters['Xylose_retention']

        arabinan_mass = used_biomass.imass['Arabinan']
        used_solvent.imass['l', 'Arabinan'] = arabinan_mass * (1-solvolysis_parameters['Arabinan_retention'])

        used_biomass.imass['Arabinan'] = arabinan_mass * solvolysis_parameters['Arabinan_retention']
        
        mannan_mass = used_biomass.imass['Mannan']
        used_solvent.imass['l', 'Mannan'] = mannan_mass * (1-solvolysis_parameters['Mannan_retention']) 
        used_biomass.imass['Mannan'] = mannan_mass * solvolysis_parameters['Mannan_retention']

        galactan_mass = used_biomass.imass['Galactan']
        used_solvent.imass['l', 'Galactan'] = galactan_mass * (1-solvolysis_parameters['Galactan_retention']) 
        used_biomass.imass['Galactan'] = galactan_mass * solvolysis_parameters['Galactan_retention']
        

        # The temperature and pressure of the carbohydrate pulp is not changed here, I'm assuming I obtain the pulp at ambient conditons 
        # once RCF reaction is complete for downstream processing
        



    def _calculate_pressure_drop(self, bed_length):

        D = self.poplar_diameter                                # [m] poplar particle diameter
        rho = self.ins[1].rho                                   # [kg/m3] 
        mu = self.ins[1].get_property('mu', 'kg/m/s')           # [Pa s] methanol water viscosity 
        epsilon = self.void_frac                                # Void fraction 
        u = self.superficial_velocity                           # [m/s] superficial velocity  

        
        
        Re = (D*rho*u)/mu
        if Re/(1-epsilon) < 500: # Erun equation
            f = ((1-epsilon)/(epsilon**3))*(1.75+(150*(1-epsilon)/Re))
            dP = (f * ((rho*(u**2))/D)* bed_length)*1e-5                # [bar] 1e-5 converts Pa to bar
        elif 1000 < Re/(1-epsilon) < 5000: # Handley and Heggs
            f = ((1-epsilon)/(epsilon**3))*(1.24+(368*(1-epsilon)/Re))
            dP = (f * ((rho*(u**2))/D)* bed_length)*1e-5
        else: # Hicks equation which fits in Wentz and Thodos results for very high Re
            f = 6.8*(((1-epsilon)**1.2)/epsilon**3)*Re**-0.2
            dP = (f * ((rho*(u**2))/D) * bed_length)*1e-5
        return dP

        

    def _design(self):
        length, diameter, N_reactors, N_operating, total_volume = self._size_bed()   # Calling size bed function to determine diameter and length 
        


        
        
        
        cycle_time = self.tau + self.tau_0

        self.set_design_result('Diameter', 'ft', diameter)
        self.set_design_result('Length', 'ft', length)
        self.set_design_result('Reactor volume', 'm3', self.V_max)
        self.set_design_result('Total volume', 'm3', total_volume)
        self.set_design_result('Total beds', '', N_reactors)
        self.set_design_result('Beds in service', '', N_operating)
        self.set_design_result('Time on stream', 'hr', self.tau)
        self.set_design_result('Residence time', 'hr', self.tau_residence)
        self.set_design_result('Turnaround time', 'hr', self.tau_0)
        self.set_design_result('Batch time', 'hr', cycle_time)
        self.set_design_result('Biomass volume per bed', 'm3', self._V_biomass)
        self.set_design_result('Solvent volume per bed', 'm3', self._V_solvent)
        self.set_design_result('Instantaneous loading', 'L/kg', self._instantaneous_loading)
        self.set_design_result('Solvent loading', 'L/kg', self._loading)

        
        
        # Calculates weight based off pressure, diameter and length
        # Adds vcessel type wall thickness, vessel weight, diameter and length to dictionary
        # But diameter and length are already there because of set_design_result above
        
        self.design_results.update(
            self._vertical_vessel_design(    
                self.P*(1/6894.76),
                self.design_results['Diameter']*3.28084,
                self.design_results['Length']*3.28084
            )
        )
        
                            

        pressure_drop = self._calculate_pressure_drop(length)                  
        
        self.set_design_result('Pressure drop', 'bar', pressure_drop)
        self.pump_1.P = (self.P - self.ins[1].P) + (pressure_drop*1e5)
        self.pump_1.simulate()





    def _cost(self):
        design = self.design_results # Calling the dictionary used to store design results in design method above 

        baseline_purchase_costs = self.baseline_purchase_costs # Dictionary for storing baseline costs

        weight = design['Weight']  # weight parameter stores the value from the 'Weight' key in the design dictionnary
        
        N_reactors = design['Total beds']
        # Calculates the baseline purchase cost based off diameter length and weight
        baseline_purchase_costs.update( 
            self._vessel_purchase_cost(weight, design['Diameter'], design['Length'])
        )

        self.parallel['self'] = N_reactors # Used to create multiple of the same beds
        self.parallel['pump_1'] = 1 # Just one pump needed, valves will redirect to whichever bed is online


        
       
        """
        ---------
          
        Parameters that can be further fine-tuned based on industry/national lab data
        - Void fraction of poplar bed: Herein assumed 0.5, this is subject to change
        - Working volue fraction: Herein assumed 80%, but can change depending on how well mass transfer occurs in real reactors
        - V_max: Maximum volume of a single reactor, herein assumed as 600 m3 based on Bartling et al 2021 paper, but subject to change
        - residence time: Herein 2 hrs, but could change based on which regime is more limiting. 


        ----------

        """

    

        



from lignin_saf.ligsaf_settings import rcf_oil_yield, h2_consumption, feed_parameters, prices, rcf_conditions

class HydrogenolysisReactor(bst.Unit, bst.units.design_tools.PressureVessel):


    #auxiliary_unit_names = (
    #    'heat_exchanger_2'
    #)
    _F_BM_default = {**bst.design_tools.PressureVessel._F_BM_default}
    
    _N_ins = 3
    _N_outs = 2
    
    _units = {**PressureVessel._units,
              'Duty': 'kJ/hr',
              'Residence time': 'hr',
              'Reactor volume': 'm3',
              'Total volume': 'm3',
              'Number of reactors': '',
              'Catalyst loading cost': 'USD'}
    


    # Default operating temperature [K]
    T_default: float = 463.15                   # 190 C from https://doi.org/10.1016/j.joule.2017.10.004

    #: Default operating pressure [Pa]
    P_default: float = 6e6                      # 6 MPa from https://doi.org/10.1016/j.joule.2017.10.004

    #: Default hydraulic residence time [hr] — determines reactor volume from Q
    tau_residence_default: float = 1/3          # 20 min

    # Default superficial velocity (m/s) — adjusted analytically if L/D is out of range
    superficial_velocity_default: float = 0.001

    # Default catalyst bed void fraction — fraction of bed volume occupied by fluid
    void_frac_default: float = 0.7

    # Default free-space fraction of total reactor volume (headspace above packed bed)
    free_frac_default: float = 0.20

    # Hard upper bound on individual vessel volume [m³]; N_reactors is scaled up to satisfy this
    V_max_limit_default: float = 100

    # Minimum allowable L/D ratio; u is increased analytically if L/D drops below this
    LD_min_default: float = 3.0

    # Maximum allowable L/D ratio; u is reduced analytically if L/D exceeds this
    LD_max_default: float = 10.0

    h2_consumption_default: float = h2_consumption   # kg H₂ per dry kg biomass feed

    def _init(
            self,
            T: Optional[float] = None,
            P: Optional[float] = None,
            tau_residence: Optional[float] = None,
            vessel_material: Optional[str] = None,
            vessel_type: Optional[str] = None,
            superficial_velocity: Optional[float] = None,
            void_frac: Optional[float] = None,
            free_frac: Optional[float] = None,
            V_max_limit: Optional[float] = None,
            LD_min: Optional[float] = None,
            LD_max: Optional[float] = None,
            h2_consumption: Optional[float] = None,
            *,
            reaction
            ):

        self.T = self.T_default if T is None else T
        self.P = self.P_default if P is None else P
        self.tau_residence = self.tau_residence_default if tau_residence is None else tau_residence
        self.vessel_material = 'Stainless steel 316' if vessel_material is None else vessel_material
        self.vessel_type = 'Vertical' if vessel_type is None else vessel_type
        self.superficial_velocity = self.superficial_velocity_default if superficial_velocity is None else superficial_velocity
        self.void_frac = self.void_frac_default if void_frac is None else void_frac
        self.free_frac = self.free_frac_default if free_frac is None else free_frac
        self.V_max_limit = self.V_max_limit_default if V_max_limit is None else V_max_limit
        self.LD_min = self.LD_min_default if LD_min is None else LD_min
        self.LD_max = self.LD_max_default if LD_max is None else LD_max
        self.h2_consumption = self.h2_consumption_default if h2_consumption is None else h2_consumption
        self.reaction = reaction
        heat_exchanger_2 = self.auxiliary('heat_exchanger_2', bst.HXutility)


    def _size_bed(self):

        #### Volumetric flow and reactor volume sizing ########

        # Total feed flow: liquid solvent/lignin (ins[0]) + hydrogen gas (ins[1])
        Q_total = self.ins[0].F_vol + self.ins[1].F_vol        # [m³/hr]

        # Fluid holdup in the catalyst bed voids
        V_fluid = Q_total * self.tau_residence                 # [m³]

        # Packed bed volume (catalyst particles + void space)
        V_bed = V_fluid / self.void_frac                       # [m³]

        # Total reactor volume: bed + free headspace above bed
        V_reactor_total = V_bed / (1.0 - self.free_frac)      # [m³]

        # Number of parallel reactors so each vessel stays within V_max_limit
        N_reactors = max(1, ceil(V_reactor_total / self.V_max_limit))
        V_per_reactor = V_reactor_total / N_reactors           # [m³]
        Q_per_reactor = Q_total / N_reactors                   # [m³/hr]

        #### Reactor geometry ########

        u = self.superficial_velocity
        A = Q_per_reactor / (u * 3600)                        # [m²]
        diameter = 2.0 * (A / np.pi) ** 0.5                   # [m]
        length = V_per_reactor / A                             # [m]

        # Enforce L/D within [LD_min, LD_max]; adjust u analytically if needed.
        # From L/D = V/(A) / (2√(A/π)) → A = (V√π / (2·(L/D)))^(2/3)
        LD = length / diameter
        if LD > self.LD_max:
            A = (V_per_reactor * np.pi ** 0.5 / (2.0 * self.LD_max)) ** (2.0 / 3.0)
            u = Q_per_reactor / (A * 3600)
            self.superficial_velocity = u
            diameter = 2.0 * (A / np.pi) ** 0.5
            length = V_per_reactor / A
        elif LD < self.LD_min:
            A = (V_per_reactor * np.pi ** 0.5 / (2.0 * self.LD_min)) ** (2.0 / 3.0)
            u = Q_per_reactor / (A * 3600)
            self.superficial_velocity = u
            diameter = 2.0 * (A / np.pi) ** 0.5
            length = V_per_reactor / A

        self.area = A
        self.diameter = diameter
        self.length = length
        self.N_reactors = N_reactors

        return length, diameter, V_per_reactor, V_reactor_total, N_reactors
        
    def _run(self):
        solvent, hydrogen, cat_in = self.ins
        effluent, cat_out = self.outs

        

        effluent.copy_like(solvent)
        self.reaction(effluent)

        cat_out.copy_like(cat_in)


        h2 = hydrogen.imass['Hydrogen'] 

        effluent.imass['g', 'Hydrogen'] = h2 - ((self.h2_consumption)*(2e6/24)) # 5 % h2 consumption

        effluent.T = self.T # Assuming isothermal operation
        effluent.P = self.P # Assuming no P drop




    #def _calculate_pressure_drop(self):
        # NOT OPERATIONAL FOR HYDROGENOLYSIS REACTOR

        #D = self.poplar_diameter # [m] poplar particle diameter
        #rho_solv = self.ins[1].rho  # [kg/m3] methanol water density
        #mu = self.ins[1].get_property('mu', 'kg/m/s') # [Pa s] methanol water viscosity 
        #epsilon = self.void_frac # Void fraction 
        #u = self.superficial_velocity # [m/s] superficial velocity          
        
        #Re = (D*rho_solv*u)/mu
        #if Re/(1-epsilon) < 500: # Erun equation
        #    dP = ((1-epsilon)/(epsilon**3))*(1.75+(150*(1-epsilon)/Re))
        #elif 1000 < Re/(1-epsilon) < 5000: # Handley and Heggs
        #    dP = ((1-epsilon)/(epsilon**3))*(1.24+(368*(1-epsilon)/Re))
        #else: # Hicks equation which fits in Wentz and Thodos results for very high Re
        #    dP = 6.8*(((1-epsilon)**1.2)/epsilon**3)*Re**-0.2
        #return dP

        

    def _design(self):
        length, diameter, V_per_reactor, V_total, N_reactors = self._size_bed()

        self.set_design_result('Diameter', 'ft', diameter)
        self.set_design_result('Length', 'ft', length)
        self.set_design_result('Reactor volume', 'm3', V_per_reactor)
        self.set_design_result('Total volume', 'm3', V_total)
        self.set_design_result('Residence time', 'hr', self.tau_residence)
        self.set_design_result('Number of reactors', '', N_reactors)

        self.design_results.update(
            self._vertical_vessel_design(
                self.P * (1/6894.76),
                self.design_results['Diameter'] * 3.28084,
                self.design_results['Length'] * 3.28084
            )
        )

        duty = (rcf_oil_yield['Monomers'])**0.5 * self.ins[0].imol['SolubleLignin'] * 1000 * 60.5 * 4.184
        # B-O-4 linkages in lignin [mol fraction] × SolubleLignin [kmol/hr] × 1000 [mol/kmol] × 60.5 kcal/mol × 4.184 kJ/kcal

        self.add_heat_utility(duty / N_reactors, self.T)
        self.set_design_result('Duty', 'kJ/hr', duty)


        

    #def _init_results(self):
    #    super()._init_results()
    #    self.add_OPEX = {}



        

    def _cost(self):
        design = self.design_results
        baseline_purchase_costs = self.baseline_purchase_costs
        weight = design['Weight']
        N_reactors = design['Number of reactors']

        catalyst_cost = prices['NiC_catalyst'] * rcf_conditions['cat_loading'] * ((feed_parameters['flow'] * 1e3)/24) * self.tau_residence
        design['Catalyst loading cost'] = catalyst_cost

        baseline_purchase_costs.update(
            self._vessel_purchase_cost(weight, design['Diameter'], design['Length'])
        )

        self.parallel['self'] = N_reactors






class PSA(bst.Unit, bst.units.design_tools.PressureVessel):


    """
    Design and costing of a Pressure Swing Adsorption system for purifying H2 from mix gases C0, CH4
    The model primarily follows the four bed [pressurization, feed, blowdown, purge] sequence in [1], 
    Adsorbent is Zeolite 5A, and adsorption isotherm data from [2] is used. The feed pressure was chosen
    as 5 bar deliberately because adsorption isotherms in Fig 3 [2] indicate linear isotherms until ≈ 5 bar
    pressure. 



    but deviates on some occassions by using parameters more suited for H2 purification. These deviations
    are highlighted in this docstring 


    Deviations:
    Ideally the recovery should be calculated based on eq (6) from [3].
    However, the calculation of recovery through this equation yields a value < 25 %. This is undesirable
    and commercial PSA systems for H2 have recoverys in the range of 85 - 90 %. Therefore, recovery is not
    calculated by rather a value of 85% is used.

    The model was designed for 2 beds, however, commercial H2 systems have upto 12 beds. 
    [3] mentions how the recovery for 2 bed H2 systems is low and hence 12 beds are used.
    Though the use of multiple beds will have multiple equalization stages, for the sake of simplification and for non-dynamic modeling, 
    the equalization stages are ignored.


    Model assumptions:
    Ideal gas mixture
    Isothermal operation
    Negligible axial dispersion/axial pressure gradients
    Constant pressure during feed and purge
    Linear isotherms


    References
    [1] Ruthven, D. M., Farooq, S., & Knaebel, K. S. (1996). 
        Pressure swing adsorption. John Wiley & Sons.

    [2] Yang, J., Lee, C. H., & Chang, J. W. (1997). 
    Separation of hydrogen mixtures by a two-bed pressure swing adsorption process using zeolite 5A. 
    Industrial & engineering chemistry research, 36(7), 2789-2798.

    [3] Kayser, J. C., & Knaebel, K. S. (1986). 
        Pressure swing adsorption: experimental study of an equilibrium theory. 
        Chemical engineering science, 41(11), 2931-2938.
    """


    _F_BM_default = {'Horizontal pressure vessel': 3.05,
                     'Vertical pressure vessel': 4.16,
                     'Platform and ladders': 1.}



    auxiliary_unit_names = (
        'feed_pump',
        'vaccuum_pump'
    )

    _N_ins = 1
    _N_outs = 2
    
    _units = {**PressureVessel._units,
              'Feed step time': 's',
              'Recovery' : '%',
               'Mass of adsorbent per bed': 'kg',
               'No. of beds': '',
              'Bed volume': 'm3',
              'Adsorbent cost': 'USD'}
    


    # Default recovery
    R_default: float = 0.85             # [%] From Ruthven et al, description of commercial scale PSA H2 systems

    # Default feed P
    P_feed_default: float = 5e5         # [Pa] Adsorption isotherms for CO and CH4 roughly linear till 5 atm in https://pubs.acs.org/doi/full/10.1021/ie960728h, and since I assume BLI[3], I operate in linear isotherm pressure range

    # Default purge P
    P_purge_default: float = 0.25e5     # [Pa]  Assumed, low pressure here to give a high cycle pressure

    #: Default adsorbent diameter
    pellet_dia_default = 1.57           # [mm] https://pubs.acs.org/doi/full/10.1021/ie960728h
    
    #: Default bed density
    bed_density_default: float = 795     # [kg/m3] from https://pubs.acs.org/doi/full/10.1021/ie960728h


    #: Default void fraction
    ex_void_frac_default: float = 0.315  #  https://pubs.acs.org/doi/full/10.1021/ie960728h

    N_beds_default: float = 12           # [%] From Ruthven et al, description of commercial scale PSA H2 systems

    adsorbent_cost_default: float = 5   # [$/kg] for zeolite 5A from Ruthven et al design example

    h2_purity_default: float = 1        # [%] 100% pure H2 assumed (ideally 99.99% is mentioned, so decided to go with just 100%)


    def _init(
            self,
            R: Optional[float] = None, 
            P_feed: Optional[float] = None, 
            P_purge: Optional[float] = None,
            pellet_dia: Optional[float] = None,
            bed_density: Optional[float] = None,
            vessel_material: Optional[str] = None,
            vessel_type: Optional[str] = None,
            ex_void_frac: Optional[float] = None,
            N_beds: Optional[int] = None,
            adsorbent_cost: Optional[float] = None,
            h2_purity: Optional[float] = None
            ):
        
        
        
        self.R = self.R_default if R is None else R
        self.P_feed = self.P_feed_default if P_feed is None else P_feed
        self.P_purge = self.P_purge_default if P_purge is None else P_purge
        self.pellet_dia = self.pellet_dia_default if pellet_dia is None else pellet_dia
        self.bed_density = self.bed_density_default if bed_density is None else bed_density
        self.vessel_material = 'Stainless steel 316' if vessel_material is None else vessel_material
        self.vessel_type = 'Vertical' if vessel_type is None else vessel_type
        self.ex_void_frac = self.ex_void_frac_default if ex_void_frac is None else ex_void_frac
        self.N_beds = self.N_beds_default if N_beds is None else N_beds
        self.adsorbent_cost = self.adsorbent_cost_default if adsorbent_cost is None else adsorbent_cost
        self.h2_purity = self.h2_purity_default if h2_purity is None else h2_purity

        self._raw_extract = bst.Stream()
 
        if self.ins[0].P > self.P_feed:
            raise ValueError(f'Inlet pressure ({(self.ins[0].P)/1e5} bar) is greater than PSA feed pressure ({(self.P_feed)/1e5} bar)\n Make sure inlet pressure is either less than or equal to the required PSA feed pressure!')
        self.feed_pump = self.auxiliary('feed_pump', bst.IsentropicCompressor, ins=self.ins[0], P = self.P_feed)
        self.vaccuum_pump = self.auxiliary('vaccuum_pump', bst.IsentropicCompressor, ins = self._raw_extract, outs = self.outs[1], P = 101325)
    
       
        
    
    def _selectivity_parameter(self):
        k_A = 0.2              # slope of equilibrium isotherm of component A ()
        k_B = 0.01
        ex_void_frac = self.ex_void_frac
        beta_A = (ex_void_frac+(1-ex_void_frac)*k_A)
        beta = (ex_void_frac+(1-ex_void_frac)*k_B)/(ex_void_frac+(1-ex_void_frac)*k_A)
        return beta_A, beta


    def _cycle_pressure(self):
        P_H = 5                 # [bar]   Avergae bed pressure during high pressure feed, bar
        P_L = 0.25              # [bar]   Average bed pressure during low pressure purge, bar
        P_cycle = P_H / P_L     # [ratio] PSA cycle pressure ratio
        return P_H, P_L, P_cycle
    

    def _Re(self):
        pellet_dia = self.pellet_dia                            # [mm] Diameter of adsorbent pellets
        inlet_mu = self.ins[0].get_property('mu', 'kg/m/s')        # [kg/m/s] Dynamic viscosity of feed
        mol_in = self.ins[0].F_mol * (1000/3600)                   # [mol/s] Feed flow rate 
        Re = (mol_in*(2e-3))*(pellet_dia*(1e-4))/(inlet_mu)  
        return Re

    
        

    def _adsorbent_req(self):
        beta_A, beta = self._selectivity_parameter()   
        P_H, P_L, P_cycle = self._cycle_pressure()
        Re = self._Re()

        feed = self.ins[0]
        mol_in = feed.F_mol * (1000/3600)                   # [mol/s] Feed flow rate 
        gas_constant = 8.205e-5                             # [m3atm/K/mol] Universal gas constant        bed_density = self.bed_density

        void_frac = self.ex_void_frac

        theta_tf = mol_in/P_cycle
        theta = (void_frac*P_L)/(beta_A*gas_constant*feed.T)   #[mol/m3] Vads
        V_ads_tf = theta_tf/theta

        Acs = (Re/15)  # [m2] Guess value of 15 is used, similar to design example by Ruthven et al, but this could be different for H2/CO/CH4 systems. Example by Rutvehn was for O2 separation from air
        bed_dia = 2*(Acs/np.pi)**0.5     # [m]
        L_tf = V_ads_tf/Acs
        L_guess = 2*bed_dia
        tf = L_guess/L_tf   # [s] Feed step duration
        V_ads = V_ads_tf *tf # [m3]
        m_ads = V_ads * self.bed_density
        return V_ads, m_ads, tf, L_guess, bed_dia




        
    def _run(self):

        if self.ins[0].P < self.P_feed:
            self.feed_pump.P = self.P_feed
            self.feed_pump.simulate()
        else:
            self.feed_pump.outs[0].copy_like(self.ins[0])


        feed = self.feed_pump.outs[0]
        feed.phase = 'g'
        raffinate,  = self.outs[0]


        mol_in = feed.F_mol                           # [Kmol/hr] Feed flow rate 
        y_F = feed.imol['Hydrogen']/feed.F_mol       # [frac] mol fraction of hydrogen in feed
        R = self.R
        mol_out = mol_in * y_F * R 

        raffinate.imol['Hydrogen'] = mol_out
        raffinate.P = self.P_feed          # No presure drop
        raffinate.T = self.ins[0].T        # isothermal operation
        raffinate.phase = 'g'

        
        self._raw_extract.copy_like(feed)
        
        self._raw_extract.imol['Hydrogen'] = feed.imol['Hydrogen'] - raffinate.imol['Hydrogen']
        self._raw_extract.phase = 'g'
        self._raw_extract.T = self.ins[0].T
        self._raw_extract.P = self.P_purge



            
        



       

        

    def _design(self):
        V_ads, m_ads, tf, L_guess, bed_dia = self._adsorbent_req()  
        P_H, P_L, P_cycle = self._cycle_pressure()


    
        

        self.set_design_result('Diameter', 'ft', bed_dia) 
        self.set_design_result('Length', 'ft', L_guess)
        self.set_design_result('Feed step time', 's', tf)
        self.set_design_result('Mass of adsorbent per bed', 'kg', m_ads)
        self.set_design_result('Bed volume', 'm3', V_ads)
   

 
        
        # Calculates weight based off pressure, diameter and length
        # Adds vcessel type wall thickness, vessel weight, diameter and length to dictionary
        # But diameter and length are already there because of set_design_result above
        
        self.design_results.update(
            self._vertical_vessel_design(    
                P_H*(1/6894.76),
                self.design_results['Diameter']*3.28084,
                self.design_results['Length']*3.28084
            )
        )
        

        if self.P_purge < 101325:
            self.vaccuum_pump.P = 101326
            self.vaccuum_pump.simulate()

        else:
            self.vaccuum_pump.outs[0].copy_like(self._raw_extract)

        
        self.parallel['self'] = self.N_beds # Used to create multiple of the same beds
        
        self.parallel['feed_pump']   = 1     # Just one feed pump for the beds
        self.parallel['vaccuum_pump']   = 1  # Just one vaccuum pump for the beds





    def _cost(self):
        design = self.design_results # Calling the dictionary used to store design results in design method above 

        baseline_purchase_costs = self.baseline_purchase_costs # Dictionary for storing baseline costs

        weight = design['Weight']  # weight parameter stores the value from the 'Weight' key in the design dictionnary


        adsorbent_cost = self.adsorbent_cost
        adsorbent_cost_per_bed = adsorbent_cost * design['Mass of adsorbent per bed'] 
        
        baseline_purchase_costs['Adsorbent cost'] = adsorbent_cost_per_bed



        # Calculates the baseline purchase cost based off diameter length and weight
        baseline_purchase_costs.update( 
            self._vessel_purchase_cost(weight, design['Diameter'], design['Length'])
        )
        
        self.vaccuum_pump._cost()          
   
        


        
  
class CatalystMixer(bst.Unit):

    _N_ins = 1
    _N_outs = 1

    def _init(self):
        pass
 
    
    def _run(self):
        pass

    def _design(self):
        pass

        

        
from lignin_saf.ligsaf_settings import hdo_params, prices
 

import biosteam as bst, numpy as np
from math import ceil

from typing import Optional
from biosteam.units.design_tools import (
    PressureVessel, 
)
 

class HydrodeoxygenationReactor(bst.Unit, bst.units.design_tools.PressureVessel):

    """
    Batch reactor for HDO of lignin oil
    Designed to process RCF monomers only right now, but functionality for dimers needs to be added

    Reaction based on ring hydrogenation + aryl bond cleavage to produce cycloalkanes
    Alternative reaction scheme, where aromatic ring of monomers is preserved and just the aryl bond is cleaved (CBI) might be considered later

    Duty estimated based on ring hydrogenation enthalpy stated in [3]. Could be refined 

    All reaction conditions are typically cited from [1],[2] unless noted otherwise   

    Maximum volume is capped at 600 m3 [4], and number of reactors is scaled accordingly. Hence the reactors are technically oversized

    
    References
    ----------------------------------------------------------------------------------
        [1] Bruno Pandalone et al.,
        "Optimum Lignin Oil - Finding the Most Suitable Feedstock to Replace Cycloalkanes in Sustainable Aviation Fuel (SAF)"
        ChemSusChem. 2025. 18(11). https://doi.org/10.1002/cssc.202402531
        [2] Bruno Pandalone et al.,
        "Molecule-to-molecule conversion of RCF lignin oil to sustainable aviation fuel"
        Chem Circularity. 2026. https://doi.org/10.1016/j.checir.2026.100025
        [3] Matthew S. Webber et al., 
        " Lignin deoxygenation for the production of sustainable aviation fuel blendstocks"
        Nature Materials. 2024. 23, 1622-1638. https://doi.org/10.1038/s41563-024-02024-6
        [4] Andrew W. Bartling, et al.,
        "Techno-economic analysis and life cycle assessment of a biorefinery utilizing reductive catalytic fractionation." 
        Energy & Environmental Science. 2021. 4147-4168. https://doi.org/10.1039/D1EE01642C
        [5] Zhengwen Cao et al.,
        "A Convergent Approach for a Deep Converting Lignin-First Biorefinery Rendering High-Energy-Density Drop-in Fuels."
        Joule. 2018. 2(6). https://doi.org/10.1016/j.joule.2018.03.012
    -----------------------------------------------------------------------------------

    """



    _F_BM_default = {'Horizontal pressure vessel': 3.05,
                     'Vertical pressure vessel': 4.16,
                     'Platform and ladders': 1.}                   

    _N_ins = 2
    _N_outs = 2
    
    _units = {**PressureVessel._units,
              'Batch time': 'hr',
              'Turnaround time': 'hr',
              'Time on stream': 'hr',
              'Total beds': "",
              'Beds in service': "",
              'Total volume': 'm3',
              'Reactor volume': 'm3',
              'Catalyst loading cost' : 'USD',
              'Duty' : 'kJ/hr'}
    


    # Default operating temperature [K]
    T_default: float = 573.15                       # 300 C from [1][2][5]

    #: Default operating pressure [Pa]
    P_default:  float = 5e6                         # 5 MPa from [1][2][5]
    
    #: Default reaction time [hr]
    tau_default: float = 5                          # Total 5 hr reaction time [1][2]

    #: Default cleaning and unloading time (hr).
    tau_0_default: float  = 1                       # Assumed time required to cool down the reactor 

    # Fixed bed configuration
    N_total_default: int =  3                       # Total beds (2 operating + 1 cleaning)

    N_working_default: int = 2                      # Beds operating at any time

    # Default free-space fraction of reactor volume
    free_frac_default: float = 0.10                 # 10% kept free for gas disengagement / headspace
    
    # Default maximum vessel volume [m3]
    V_max_default: float = 600                     # Assumed, as was maximum volume in [4]

    # Aspect ratio (L/D of the reactor)
    aspect_ratio: float = 5.0                      # Assumed



    def _init(
            self,
            T: Optional[float] = None,
            P: Optional[float] = None,
            tau: Optional[float] = None,
            vessel_material: Optional[str] = None,
            vessel_type: Optional[str] = None,
            tau_0: Optional[float] = None,
            free_frac: Optional[float] = None,
            V_max: Optional[float] = None,
            aspect_ratio: Optional[float] = None,
            *,
            reaction_1            
            ):


        self.T = self.T_default if T is None else T
        self.P = self.P_default if P is None else P
        self.tau = self.tau_default if tau is None else tau
        self.vessel_material = 'Stainless steel 316' if vessel_material is None else vessel_material
        self.vessel_type = 'Vertical' if vessel_type is None else vessel_type
        self.tau_0 = self.tau_0_default if tau_0 is None else tau_0
        self.free_frac      = self.free_frac_default      if free_frac      is None else free_frac
        self.V_max = self.V_max_default if V_max is None else V_max
        self.aspect_ratio          = self.aspect_ratio         if aspect_ratio          is None else aspect_ratio
        self.reaction = reaction_1
        # heat_exchanger_1 = self.auxiliary('heat_exchanger_1', bst.HXutility, pump_1.outs[0])






    def _size_bed(self):

        cycle_time        = self.tau + self.tau_0                  

        # Total monomer flow
        total_monomer_flow = self.ins[0].F_vol                      # [m3/hr]

        V_theoretical = total_monomer_flow * self.tau               # [m3] Theoretical volume required
        
        V_actual = V_theoretical*(1+self.free_frac)                 # [m3] Actual volume required based on free fraction
        
        N_working = ceil(V_actual/self.V_max)                       # Number of working reactors based off maximum volume
        N_offline = ceil(N_working*(self.tau_0/cycle_time))         # Number of offline beds, calculated based off cleaning time and the total cycle time, rounded off to the next number
        N_total = N_working + N_offline                             # Total beds required
        V_total = N_total * self.V_max                              # Total volume required
        
        diameter = ((4*self.V_max)/(self.aspect_ratio*np.pi))**(1/3)
        length = self.aspect_ratio * diameter


        return length, diameter, N_total, N_working, V_total

        
    def _run(self):
        inf, catalyst_in = self.ins
        eff, catalyst_out = self.outs

        eff.copy_like(inf)
        self.reaction(eff)

        eff.imass['l', 'Dodecane'] = eff.imass['l', 'Dodecane']*(1-hdo_params['solvent_decomp']) # 0.5% dodecane lost due to decomposition
        eff.imass['g', 'Dodecane'] = eff.imass['g', 'Dodecane']*(1-hdo_params['solvent_decomp']) # 0.5% dodecane lost due to decomposition


        catalyst_out.copy_like(catalyst_in)
        
        eff.P = self.P                                             # Assuming no P drop sinnce its a batch reactor
        eff.T = self.T                                             # Assuming isothermal operation
    
        

    def _design(self):
        length, diameter, N_total, N_working, V_total = self._size_bed()   # Calling size bed function to determine diameter and length 
        
        cycle_time = self.tau + self.tau_0
        self.set_design_result('Diameter', 'ft', diameter)
        self.set_design_result('Length', 'ft', length)
        self.set_design_result('Reactor volume', 'm3', self.V_max)
        self.set_design_result('Total volume', 'm3', V_total)
        self.set_design_result('Total beds', '', N_total)
        self.set_design_result('Beds in service', '', N_working)
        self.set_design_result('Time on stream', 'hr', self.tau)
        self.set_design_result('Turnaround time', 'hr', self.tau_0)
        self.set_design_result('Batch time', 'hr', cycle_time)


        
        
        # Calculates weight based off pressure, diameter and length
        # Adds vessel type wall thickness, vessel weight, diameter and length to dictionary
        # But diameter and length are already there because of set_design_result above
        
        self.design_results.update(
            self._vertical_vessel_design(    
                self.P*(1/6894.76),
                self.design_results['Diameter']*3.28084,
                self.design_results['Length']*3.28084
            )
        )
        
                            

        duty = -70 * self.ins[0].imol['Hydrogen'] * 1000  # Aromatic hydrogenation has duty between 58-70 kJ/mol H2 according to https://www.nature.com/articles/s41563-024-02024-6

        self.add_heat_utility(duty/N_total, self.T, agent = bst.HeatUtility.get_cooling_agent('chilled_water'))   # BioSTEAM defaulted to cooling water but chilled water more probable since reaction is very exothermic 
        self.set_design_result('Duty', 'kJ/hr', duty)





    def _cost(self):
        design = self.design_results # Calling the dictionary used to store design results in design method above 

        baseline_purchase_costs = self.baseline_purchase_costs # Dictionary for storing baseline costs

        monomer_flow = (self.ins[0].imass['Propylguaiacol'] + self.ins[0].imass['Propylsyringol'])
        catalyst_cost = prices['HDO_Cat'] * hdo_params['catalyst_req'] * monomer_flow * self.tau
        design['Catalyst loading cost'] = catalyst_cost

        weight = design['Weight']  # weight parameter stores the value from the 'Weight' key in the design dictionnary
        
        N_reactors = design['Total beds']
        # Calculates the baseline purchase cost based off diameter length and weight
        baseline_purchase_costs.update( 
            self._vessel_purchase_cost(weight, design['Diameter'], design['Length'])
        )

        self.parallel['self'] = N_reactors # Used to create multiple of the same beds




class HydrogenStorageTank(bst.Unit):
    '''
    Hydrogen storage tank based off the method by [1]

    Method assumes compressd H2 gas storage at 20 MPa
    Installed cost of tank calculated was ($600/lb)*(500 lb tank) = $300,000 per tank [1]
    Installed cost of tank is then subsequently scaled up using an exponent of 0.75 from [1]
    Costs are in 1995 dollars (CEPCI : 381.1) in Amos et al., and are updated to biosteams system-level CEPCI using bst.CE
    
    _N_ins = 1 (hydrogen feed)
    _N_outs = 1
    storage_period = defaults to 7 days of storage [1]
    tank_exp = scale up factor for storage tank based off [1]

    [1] Amos, W. A. (1999). Costs of storing and transporting hydrogen (No. NREL/TP-570-25106; ON: DE00006574). National Renewable Energy Lab.(NREL), Golden, CO (United States).

    '''

    _F_BM_default = {**bst.design_tools.PressureVessel._F_BM_default}

    _N_ins = 1
    _N_outs = 1

    _units = {
        'Storage Days': 'days',
        'Total Capacity': 'kg'}

    # default storage period
    storage_default: float = 7.0                       # [days] 7 days of storage - assumed, as no good heuristic yet for hydrogen storage

    #: Default operating pressure [Pa]
    max_capacity_default:  float = 1300                # [kg] [5 MPa from [1][2][5]]
    

        
    def _init(
            self, 
            storage_period : Optional[float] = None, 
            max_capacity : Optional[float] = None, 
            tank_exp = 0.75):
    
        self.storage_period = self.storage_default if storage_period is None else storage_period
        self.max_capacity = self.max_capacity_default if max_capacity is None else max_capacity
        self.tank_exp = tank_exp
    


    def _design(self):
        D = self.design_results
        h2_flow = self.ins[0].imass['Hydrogen'] 
        capacity = h2_flow * self.storage_period * 24 
        D['Total Capacity'] = self.max_capacity
        N_vessels = ceil(capacity/self.max_capacity)   
        self.parallel['self'] = N_vessels

    def _cost(self):
        D = self.design_results
        purchase_costs = self.baseline_purchase_costs
        CEPCI_1995 = 381.1

        cost_update = 600 * (bst.CE/CEPCI_1995)  # Updating tank cost from 1995 (original report by Amos et al) to 2017 (biosteam default)
                
        total_cost = (cost_update*500) * (self.max_capacity /(500/2.2))**self.tank_exp  # Scale up costs to 1300 kg 
        purchase_costs['Total Cost'] = total_cost


class HydrocarbonProductTank(bst.Unit):
    '''
    Hydrocarbon storage tank from [1].
    Study assumed same storage vessels for gasoline and diesel. In the study, costing is based off Aspen Capital Cost Estimator tool
    Gasoline similar to renewable naphtha and diesel similar to SAF, so we assume 1 type of storage 
    for hydrocarbon products.
    Cost is given as installed equipment cost in 2013 dollars (CEPCI: 567.3), for a 500,000 gal storage tank at 15 psi, and 250 F
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
        CEPCI_2013 = 567.3
        total_cost = 1553400*(bst.CE/CEPCI_2013)*(D['Total Capacity']/500000)**self.tank_exp

        purchase_costs['Total Cost'] = total_cost
        
        

        
       
    
    