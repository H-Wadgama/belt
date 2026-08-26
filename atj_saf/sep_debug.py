#First create a VLE object:


from thermosteam import indexer, equilibrium, settings
settings.set_thermo(['Water', 'Ethanol', 'Methanol', 'Propanol'], cache=True)
imol = indexer.MolarFlowIndexer(
            l=[('Water', 304), ('Ethanol', 30)],
            g=[('Methanol', 40), ('Propanol', 1)])
vle = equilibrium.VLE(imol)
vle

#Equilibrium given vapor fraction and pressure:
vle(V=0.5, P=101325)

#Equilibrium given enthalpy and pressure:
H = vle.thermo.mixture.xH(vle.imol, T=363.88, P=101325)
vle(H=H, P=101325)

# My example where I want to calculate vle
import biosteam as bst
bst.settings.set_thermo(['Benzene', 'Toluene'], cache=True)
feed = bst.Stream('feed', flow=(50, 50), T = 405, P = 101325)

heater = bst.units.HXutility(ins = feed, T = 415, rigorous = True)
heater.simulate()

heater.outs[0]

# Calculate VLE at 300 K / 101325 Pa for heater.outs[0]
# bst.Stream has a built-in .vle equilibrium object (no need to build a
# MolarFlowIndexer by hand like the example above). Calling stream.vle(...)
# converts the stream to a two-phase MultiStream in place and flashes it,
# so operate on a copy if you don't want to mutate heater.outs[0].
outlet = heater.outs[0].copy()
outlet.vle(T=300, P=101325)
outlet.show()
print('Vapor fraction:', outlet.vapor_fraction)
print('Gas phase mol:', outlet.imol['g'])
print('Liquid phase mol:', outlet.imol['l'])