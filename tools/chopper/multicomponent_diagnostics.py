"""
Per-turn diagnostic data model for the multicomponent distillation
feed-phase agent -- tools/multicomponent-distillation-debugging-plan.md.

Owns: construction of an empty per-turn diagnostic record, safe conversion
of nested values to JSON-compatible data, an added/changed/removed state
diff, and the two renderers (`--debug` human-readable, `--debug-json`
JSON). Printing and CLI flag handling stay in
`multicomponent_distillation_agent.py` -- this module only builds and
formats data.

Deliberately independent of Ollama and BioSTEAM -- takes/returns plain
dicts only, and never calls `multicomponent_feed_tool.update_multicomponent_feed`,
`reset_multicomponent_feed_session`, or any other state-changing function.
Diagnostic mode built on this module must never change routing,
validation, execution, or feed state (the plan's core invariant: "Debugging
must be disabled by default and must not change normal agent behavior").
"""
import json


def new_turn_record(turn_number, user_message):
    """Construct one empty per-turn diagnostic record matching the plan's
    "Diagnostic Record" shape."""
    return {
        'turn': turn_number,
        'user_message': user_message,
        'pending_before': None,
        'state_before': None,
        'model': {},
        'prechecks': {},
        'grounding': {'accepted': {}, 'rejected': {}},
        'function_calls': [],
        'state_after': None,
        'state_diff': {},
        'reply': None,
        'exit_path': None,
    }


def to_jsonable(value, _seen=None):
    """Safely convert an arbitrary nested value into JSON-serializable
    data. Never raises. An object that cannot be represented as plain JSON
    data (an Ollama client, a BioSTEAM unit/stream, an arbitrary
    exception, a bare callable) is replaced with a short type/repr marker
    rather than serialized directly or allowed to raise a TypeError --
    "Record only JSON-safe values. Do not include BioSTEAM stream or
    chemical objects."
    """
    if _seen is None:
        _seen = set()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        obj_id = id(value)
        if obj_id in _seen:
            return '<circular>'
        nested_seen = _seen | {obj_id}
        return {str(k): to_jsonable(v, nested_seen) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        obj_id = id(value)
        if obj_id in _seen:
            return '<circular>'
        nested_seen = _seen | {obj_id}
        return [to_jsonable(v, nested_seen) for v in value]
    if callable(value):
        name = getattr(value, '__name__', type(value).__name__)
        return f'<callable:{name}>'
    if isinstance(value, BaseException):
        return f'<exception:{type(value).__name__}:{value}>'
    try:
        json.dumps(value)
        return value
    except TypeError:
        return f'<non_serializable:{type(value).__name__}>'


def _flatten(value, prefix=''):
    """Flatten a nested dict into {dotted.path: leaf_value} pairs so a
    diff over (e.g.) `component_flows` reports exactly which component
    key changed. Lists (e.g. `component_names`) are left as atomic leaf
    values -- "Nested component MAPPINGS should be compared by component
    key", not list contents index-by-index."""
    out = {}
    if isinstance(value, dict):
        if not value and prefix:
            out[prefix] = value
        for key, sub in value.items():
            child_prefix = f'{prefix}.{key}' if prefix else str(key)
            out.update(_flatten(sub, child_prefix))
    else:
        out[prefix or ''] = value
    return out


def compute_state_diff(before, after):
    """Bounded diff between two (possibly nested) state dicts. Returns
    `{'added': {...}, 'changed': {...}, 'removed': {...}}` keyed by
    dotted field path; unchanged fields are excluded entirely so
    human-readable rendering never prints them."""
    flat_before = _flatten(before or {})
    flat_after = _flatten(after or {})
    added, changed, removed = {}, {}, {}
    for key in sorted(set(flat_before) | set(flat_after)):
        in_before = key in flat_before
        in_after = key in flat_after
        if in_before and not in_after:
            removed[key] = to_jsonable(flat_before[key])
        elif in_after and not in_before:
            added[key] = to_jsonable(flat_after[key])
        else:
            b, a = flat_before[key], flat_after[key]
            if b != a:
                changed[key] = {'before': to_jsonable(b), 'after': to_jsonable(a)}
    return {'added': added, 'changed': changed, 'removed': removed}


def render_human_readable(record):
    """Bounded, human-readable trace with the section headers from the
    plan's "Small Diagnostics Module" example. An empty section is omitted
    entirely -- "Omit an empty section only when it carries no
    information.\""""
    lines = [f"[debug turn {record.get('turn')}]"]
    lines.append(f"[user message] {record.get('user_message')}")

    pending_before = record.get('pending_before')
    if pending_before:
        lines.append(f"[pending before] {pending_before}")

    state_before = record.get('state_before')
    if state_before:
        lines.append(f"[state before] {state_before}")

    model = record.get('model') or {}
    if model:
        lines.append(
            f"[model proposal] call_count={model.get('call_count')} "
            f"retry_used={model.get('retry_used')} "
            f"parse_succeeded={model.get('parse_succeeded')}"
        )
        for i, raw in enumerate(model.get('raw_responses') or [], start=1):
            lines.append(f"  raw[{i}]: {raw}")
        lines.append(f"  parsed: {model.get('parsed_proposal')}")

    prechecks = record.get('prechecks') or {}
    if prechecks:
        lines.append(f"[prechecks] {prechecks}")

    grounding = record.get('grounding') or {}
    accepted = grounding.get('accepted')
    rejected = grounding.get('rejected')
    if accepted:
        lines.append(f"[grounding accepted] {accepted}")
    if rejected:
        lines.append(f"[grounding rejected] {rejected}")

    for call in record.get('function_calls') or []:
        lines.append(f"[calling {call.get('name')}] {call.get('arguments')}")
        lines.append(f"[function result] {call.get('result')}")

    diff = record.get('state_diff') or {}
    if diff.get('added') or diff.get('changed') or diff.get('removed'):
        lines.append('[state diff]')
        for key, val in (diff.get('added') or {}).items():
            lines.append(f"  added.{key}: {val!r}")
        for key, val in (diff.get('changed') or {}).items():
            lines.append(f"  changed.{key}: before={val.get('before')!r} after={val.get('after')!r}")
        for key, val in (diff.get('removed') or {}).items():
            lines.append(f"  removed.{key}: {val!r}")
    else:
        lines.append('[state diff] (no change)')

    lines.append(f"[exit path] {record.get('exit_path')}")
    lines.append(f"[reply] {record.get('reply')}")

    return '\n'.join(lines)


def render_json(record):
    """One complete JSON object per turn -- `--debug-json`'s output."""
    return json.dumps(to_jsonable(record))
