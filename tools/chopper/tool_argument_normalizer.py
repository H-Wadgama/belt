"""
Round 1 of tools/binary-distillation-issues-9-1-2026-first.md -- hardens the
Qwen-tool-call/`feed_state.py` boundary in `update_binary_distillation_problem`.

`ollama._utils.convert_function_to_tool` already generates the correct JSON
schema from `binary_distillation_workflow_agent.update_binary_distillation_problem`'s
type hints (`component_flows: dict[str, float] | None`, `component_flow_units:
str | None`, etc. -- verified by inspecting the generated tool schema
directly). Qwen has nonetheless been observed sending schema-violating
payloads for these two fields, e.g.:

    component_names = ["Water", "Ethanol"]
    component_flows = [50, 50]                      # should be a mapping
    component_flow_units = ["kmol/hr", "kmol/hr"]    # should be a bare string

Passing these straight to `feed_state.apply_user_update()` crashes inside
`update['component_flows'].items()` with a raw `AttributeError`, since Python
type hints are not enforced at runtime. This module sits directly in front of
that call: it deterministically normalizes the specific malformed shapes above
when they are unambiguous, and otherwise returns a structured
`invalid_tool_arguments` error dict -- never a raw exception, and never a
guess when more than one interpretation is possible.

Canonical `feed_state.py` state is untouched by this module: `component_flows`
remains `dict[str, float]` and `component_flow_units` remains `str` on the way
in; the repair happens only at this LLM/tool-argument boundary, per the
architecture note in the issue doc:

    messy LLM representation -> tool argument normalizer -> canonical
    representation -> feed_state

Scope: this round only covers `component_flows` (paired against
`component_names`) and `component_flow_units`, matching the exact failure
mode observed and the Round 1 regression tests in the issue doc. Other
dict[str, float]-shaped fields (e.g. `composition`) are not in scope for this
round.
"""

_NUMERIC_TYPES = (int, float)

# Units that collapse to the same canonical form when repeated with
# different capitalization/spacing/phrasing -- e.g. Step 1.3's example,
# ["KMOL/HR", "kmol per hour"] -> "kmol/hr". Conservative and small on
# purpose: this is for collapsing repeated *duplicates* of one unit, not a
# general unit-conversion table. Anything not recognized here still
# collapses correctly as long as every entry is character-for-character
# identical after casefolding/whitespace-normalization.
_UNIT_ALIASES = {
    'kmol/hr': 'kmol/hr', 'kmol per hour': 'kmol/hr', 'kmol/h': 'kmol/hr',
    'kg/hr': 'kg/hr', 'kg per hour': 'kg/hr', 'kg/h': 'kg/hr',
    'mol/hr': 'mol/hr', 'mol per hour': 'mol/hr',
    'lb/hr': 'lb/hr', 'lb per hour': 'lb/hr',
    'lbmol/hr': 'lbmol/hr', 'lbmol per hour': 'lbmol/hr',
}


def _is_numeric(v):
    return isinstance(v, _NUMERIC_TYPES) and not isinstance(v, bool)


def _canonical_unit(u):
    if not isinstance(u, str):
        return None
    key = ' '.join(u.strip().lower().split())
    return _UNIT_ALIASES.get(key, key)


def _structured_error(field, expected, received, message):
    return {
        'valid': False,
        'error': 'invalid_tool_arguments',
        'field': field,
        'expected': expected,
        'received_type': type(received).__name__,
        'message': message,
    }


def normalize_component_flows(component_names, component_flows):
    """
    Returns `(normalized, error)` -- exactly one is `None`.

    `normalized` is `None` when the caller didn't pass `component_flows`
    at all (nothing to do) OR when it is returned unchanged because it was
    already a valid `dict[str, float]` -- in both cases the caller should
    leave its own `component_flows` argument as-is. `normalized` is a
    `dict[str, float]` only when an actual list->dict conversion happened.
    """
    if component_flows is None:
        return None, None

    if isinstance(component_flows, dict):
        for k, v in component_flows.items():
            if not isinstance(k, str) or not _is_numeric(v):
                return None, _structured_error(
                    'component_flows', 'mapping of component name to numeric flow',
                    component_flows,
                    f'component_flows entry {k!r}: {v!r} is not a numeric flow.',
                )
        return None, None

    if isinstance(component_flows, (list, tuple)):
        if not isinstance(component_names, (list, tuple)) or not component_names:
            return None, _structured_error(
                'component_flows', 'mapping of component name to numeric flow',
                component_flows,
                'component_flows was given as a list but there is no matching '
                'component_names list in this same call to pair it against.',
            )
        if len(component_flows) != len(component_names):
            return None, _structured_error(
                'component_flows', 'mapping of component name to numeric flow',
                component_flows,
                f'component_flows has {len(component_flows)} entries but '
                f'component_names has {len(component_names)} -- lengths must '
                'match to pair them positionally.',
            )
        names = list(component_names)
        if len(set(names)) != len(names) or not all(isinstance(n, str) for n in names):
            return None, _structured_error(
                'component_flows', 'mapping of component name to numeric flow',
                component_flows,
                'component_names must be unique strings to pair positionally '
                'against a parallel component_flows list.',
            )
        if not all(_is_numeric(v) for v in component_flows):
            return None, _structured_error(
                'component_flows', 'mapping of component name to numeric flow',
                component_flows,
                'component_flows must contain only numeric values.',
            )
        return dict(zip(names, component_flows)), None

    return None, _structured_error(
        'component_flows', 'mapping of component name to numeric flow',
        component_flows,
        f'component_flows must be a mapping of component name to numeric '
        f'flow, got {type(component_flows).__name__}.',
    )


def normalize_component_flow_units(component_flow_units):
    """
    Returns `(normalized, error)` -- exactly one is `None`.

    `normalized` is `None` when the caller didn't pass
    `component_flow_units` at all, meaning "leave it as-is"; otherwise it
    is the collapsed `str` value to use.
    """
    if component_flow_units is None:
        return None, None
    if isinstance(component_flow_units, str):
        return None, None
    if isinstance(component_flow_units, (list, tuple)):
        if not component_flow_units:
            return None, _structured_error(
                'component_flow_units', 'string', component_flow_units,
                'component_flow_units was an empty list.',
            )
        if not all(isinstance(u, str) for u in component_flow_units):
            return None, _structured_error(
                'component_flow_units', 'string', component_flow_units,
                'component_flow_units contained a non-string entry.',
            )
        canon = [_canonical_unit(u) for u in component_flow_units]
        if len(set(canon)) != 1:
            return None, _structured_error(
                'component_flow_units', 'string', component_flow_units,
                f'component_flow_units gave conflicting units {component_flow_units!r} '
                '-- units must be identical for every component in one call.',
            )
        return component_flow_units[0], None
    return None, _structured_error(
        'component_flow_units', 'string', component_flow_units,
        f'component_flow_units must be a string, got {type(component_flow_units).__name__}.',
    )


def normalize_write_arguments(component_names, component_flows, component_flow_units):
    """
    Normalizes/validates just the `component_flows`/`component_flow_units`
    pair of `update_binary_distillation_problem`'s arguments against
    `component_names`. Never raises.

    Returns `(normalized, error)`:
      - On success: `error` is `None`, `normalized` is
        `{'component_flows': ..., 'component_flow_units': ...}` with each
        value either the original argument (unchanged) or its canonical
        replacement -- always safe to assign straight back into the
        caller's local variables.
      - On failure: `normalized` is `None`, `error` is a structured
        `invalid_tool_arguments` dict (see `_structured_error`) --
        callers should return this directly as the tool result instead of
        proceeding to `feed_state.apply_user_update()`.
    """
    flows, err = normalize_component_flows(component_names, component_flows)
    if err is not None:
        return None, err

    units, err = normalize_component_flow_units(component_flow_units)
    if err is not None:
        return None, err

    return {
        'component_flows': component_flows if flows is None else flows,
        'component_flow_units': component_flow_units if units is None else units,
    }, None
