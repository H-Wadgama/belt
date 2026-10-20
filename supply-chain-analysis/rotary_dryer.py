# Standalone rotary dryer heat-utility cost unit for the supply-chain-analysis manuscript.
#
# Not connected to any process streams (_N_ins = _N_outs = 0). Given a process duty
# [kJ/hr] and the process-side inlet/outlet temperature, it calls BioSTEAM's
# Unit.add_heat_utility to select a heating/cooling agent and price the utility --
# the same mechanism used by AdiabaticReactor in atj_saf/atj_bst/atj_bst_units.py.
# No design/purchase cost is modeled; this unit only reports a utility operating cost.
import biosteam as bst

__all__ = ('RotaryDryer',)


class RotaryDryer(bst.Unit):
    """
    Standalone heat-utility cost unit representing a rotary dryer's operating cost.

    Parameters
    ----------
    duty :
        Process heat duty required [kJ/hr]. Positive for heating, negative for cooling.
    T_in :
        Process-side inlet temperature [K].
    T_out :
        Process-side outlet temperature [K].
    agent :
        Utility agent to use. Either a `bst.UtilityAgent`, a heating/cooling agent ID
        string (e.g. 'low_pressure_steam', 'natural_gas'), or None to let BioSTEAM
        pick a suitable agent automatically from T_in/T_out.
    """
    _N_ins = 0
    _N_outs = 0

    def __init__(self, ID='', duty=0., T_in=298.15, T_out=298.15, agent=None, thermo=None):
        super().__init__(ID, ins=None, outs=(), thermo=thermo)
        self.duty = duty
        self.T_in = T_in
        self.T_out = T_out
        self.agent = agent

    def _run(self):
        pass

    def _design(self):
        D = self.design_results
        D['Duty'] = self.duty
        D['Inlet temperature'] = self.T_in
        D['Outlet temperature'] = self.T_out

    def _cost(self):
        agent = self.agent
        if isinstance(agent, str):
            agent = (bst.HeatUtility.get_heating_agent(agent) if self.duty >= 0
                      else bst.HeatUtility.get_cooling_agent(agent))
        self.add_heat_utility(self.duty, self.T_in, self.T_out, agent=agent)
