# Multicomponent Distillation Model Context

## Purpose and Current Scope

This context file records only the assumptions and inputs needed while
testing `tools/chopper/multicomponent_distillation_agent.py`.

Assume every feed sent to this agent contains **three or more nonzero-flow
components**.

Behavior shared with the binary distillation workflow should remain inherited
from `tools/binary-distillation-context.md`. This file does not attempt to
restate or catalogue that inherited behavior.

## Feed-Phase Evaluation

For the current version, the feed thermal condition must be explicitly defined
by **temperature**. Enthalpy and feed quality are not accepted inputs. The
temperature must never be silently defaulted to the bubble point.

## Essential Inputs (Table 3-1 Analog, Multicomponent)

1. **At least three component identities.**
2. **Feed quantity and composition**, given in either of these forms:
   - a flow rate for every component; or
   - the total feed flow rate and fractions for all but one component. The
     remaining fraction and all component flow rates are then calculated.
   All directly supplied component flows must use one shared unit. All
   composition fractions must use one common mole or mass basis.
3. **Units for the feed flow rate.** Units must be explicitly stated. When
   bare percentages are supplied, their basis is inferred deterministically
   from the total-flow unit: `mol/hr` or `kmol/hr` means mole basis, and
   `kg/hr` means mass basis. An explicitly stated composition basis overrides
   that inference and may differ from the total-flow basis; molecular-weight
   conversion is then required.
4. **Feed pressure.** Its units must be explicitly stated.
5. **Feed temperature.** Its units must be explicitly stated, and it must
   never be defaulted to the bubble point.

## Current Model Assumption

Reflux is assumed to be a saturated liquid. This is a current model
limitation, not an input the agent should request from the user, and it does
not add any calculation beyond feed-phase evaluation.

## Initially Supported Units

- Component or total flow: `kmol/hr`, `mol/hr`, or `kg/hr`.
- Pressure: `Pa`, `kPa`, `bar`, or `atm`.
- Temperature: `K` or `degC`.

If a value that requires units is provided without them, the agent must ask
for the units and list the supported choices. It must never infer units.

The agent may infer only a bare composition's basis from an explicitly given
total-flow unit according to the rule above. It must not infer pressure,
temperature, component flows, or their units.

## Output Boundary

Once the feed is complete, the agent reports only the equilibrium phase and
the molar vapor and liquid fractions. It does not route the feed, select a
separation, or perform a distillation design.
