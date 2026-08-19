"""
The single tool exposed to the LLM: `optimize_separation`.

Wraps `optimizer.optimize_reflux_ratio` behind a JSON-in/JSON-out function
so an Ollama tool-calling model (e.g. qwen3:8b) can build a feed stream
from plain component/flow numbers, run the reflux-ratio sweep, and get
back a plain dict it can summarize in natural language.

`optimize_separation`'s type hints and docstring are read directly by
`ollama`'s `convert_function_to_tool` (triggered by passing the function
itself in `tools=[...]`) to build the JSON schema the model sees -- so
keep the signature and the per-argument docstring lines accurate; they
are the model's only view of what this tool does.
"""
import biosteam as bst

from optimizer import optimize_reflux_ratio

DEFAULT_REFLUX_RATIOS_K = [1.2, 1.5, 1.75, 2.0, 2.5, 3.0, 3.5]

_call_count = 0


def _jsonify(value):
    """Recursively convert numpy/pandas scalars to plain JSON-safe types."""
    if isinstance(value, dict):
        return {k: _jsonify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonify(v) for v in value]
    if hasattr(value, 'item'):  # numpy scalar (e.g. np.float64, np.bool_)
        return value.item()
    return value


def optimize_separation(
    components: dict[str, float],
    light_key: str,
    heavy_key: str,
    units: str = 'kmol/hr',
    spec: str = 'purity',
    target: str = 'top',
    purity_target: float | None = None,
    recovery_target: float | None = None,
    pressure_Pa: float = 101325,
    reflux_ratios_k: list[float] | None = None,
) -> dict:
    """Size and cost a binary distillation column for a feed, sweeping reflux ratio to find the cheapest design that hits a purity or recovery target.

    Args:
        components: Feed component flow rates, e.g. {"Water": 80, "Methanol": 100, "Glycerol": 25}. Keys must be valid BioSTEAM/chemicals-package chemical names (e.g. "Water", "Methanol", "Ethanol", "Glycerol", "Ethylene").
        light_key: Component name of the light key -- the component that should concentrate in the distillate (top) product.
        heavy_key: Component name of the heavy key -- the component that should concentrate in the bottoms (bottom) product.
        units: Flow rate units for the `components` values. Either "kmol/hr" or "kg/hr".
        spec: Which kind of target to hit: "purity" (product concentration) or "recovery" (fraction of feed component recovered).
        target: Which outlet is the product of interest: "top" (distillate) or "bottom" (bottoms).
        purity_target: Required if spec is "purity". Target mole fraction (0-1) of the target key in the product stream, e.g. 0.99 for 99% pure.
        recovery_target: Required if spec is "recovery". Target fractional recovery (0-1) of the target key to the product stream, e.g. 0.99 for 99% recovery.
        pressure_Pa: Column operating pressure in Pascal. Default 101325 (1 atm).
        reflux_ratios_k: List of reflux ratio multipliers (k = actual reflux ratio / minimum reflux ratio) to sweep, e.g. [1.5, 2.0, 2.5]. If omitted, a default sweep from 1.2x to 3.5x minimum reflux is used.

    Returns:
        A dict with the cheapest feasible design (or a message explaining why none was feasible), including capital cost, utility cost, achieved purity/recovery, and reflux ratio. Also includes 'key_selection', a validity check on light_key/heavy_key: if 'key_selection.warning' is not null, another feed component boils between the two keys and is a 'distributed' component the shortcut method can't resolve -- ALWAYS check this before attributing an infeasible result to reflux ratio or purity/recovery target.
    """
    global _call_count
    _call_count += 1
    bst.main_flowsheet.set_flowsheet(f'sep_agent_{_call_count}')

    chem_ids = sorted(set(components) | {light_key, heavy_key})
    bst.settings.set_thermo(chem_ids, cache=True)

    feed = bst.Stream('agent_feed', units=units, **components)
    feed.T = feed.bubble_point_at_P().T

    result = optimize_reflux_ratio(
        feed=feed,
        LHK=(light_key, heavy_key),
        reflux_ratios_k=reflux_ratios_k or DEFAULT_REFLUX_RATIOS_K,
        P=pressure_Pa,
        spec=spec,
        target=target,
        purity_target=purity_target,
        recovery_target=recovery_target,
    )

    return _jsonify({
        'found': result['found'],
        'message': result['message'],
        'n_feasible': result['n_feasible'],
        'n_total': result['n_total'],
        'best_design': result['best_design'],
        'key_selection': result['key_selection'],
    })


TOOLS = [optimize_separation]
TOOL_FUNCTIONS = {'optimize_separation': optimize_separation}
