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

The feed thermal condition must be explicitly defined by **temperature,
enthalpy, or quality**. It must never be silently defaulted to the bubble
point.

## Essential Inputs (Table 3-1 Analog, Multicomponent)

1. **Column pressure.**
2. **Full feed flow rate and composition** — every component with nonzero
   flow.
3. **Feed thermal condition** — temperature, enthalpy, or quality, explicitly
   stated and never defaulted to the bubble point.
4. **Reflux thermal condition** — it must be stated rather than assumed;
   saturated liquid is usual but must be confirmed.
5. **Light key and heavy key.**
