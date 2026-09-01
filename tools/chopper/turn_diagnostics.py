"""
Per-turn diagnostic data model -- tools/binary-distillation-turn-diagnostics-plan.md
Step 2.

Owns: construction of an empty per-turn diagnostic record, safe conversion
of nested values to JSON-compatible data, a bounded human-readable console
renderer, JSONL serialization, and state-diff construction.

Deliberately independent of Ollama and BioSTEAM -- takes/returns plain
dicts only, and never executes a workflow operation (WRITE/READ/action).
Diagnostic mode built on this module must never change routing, validation,
execution, or state (architectural invariant 7 of the plan).
"""
import json


def new_turn_record(turn_id, user_text):
    """Construct one empty per-turn diagnostic record matching the plan's
    documented conceptual shape (see the plan's "Target diagnostic
    pipeline" section)."""
    return {
        'turn_id': turn_id,
        'user_text': user_text,
        'route': None,  # 'fast_path' | 'model_interpretation'
        'interpretation': {
            'model': None,
            'attempts': [],
            'retry_used': False,
            'final_intent': None,
        },
        'validation': {
            'transaction': None,
            'normalized_updates': [],
            'invalid_updates': [],
            'conflicts': [],
        },
        'execution': {
            'operations': [],
            'write_performed': False,
            'write_kwargs': {},
            'action': None,
            'query_results': [],
        },
        'state': {
            'before': None,
            'after': None,
            'changed_fields': [],
        },
        'final_response': None,
    }


def to_jsonable(value, _seen=None):
    """Safely convert an arbitrary nested value into JSON-serializable data.

    Never raises. An object that cannot be represented as plain JSON data
    (an Ollama client, a BioSTEAM unit/stream, an arbitrary exception, a
    bare callable) is replaced with a short type/repr marker rather than
    serialized directly or allowed to raise a TypeError -- architectural
    invariant 9: "Diagnostic records must contain only JSON-serializable
    values."
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
    """Flatten a nested dict into {dotted.path: leaf_value} pairs, so a
    diff over (e.g.) the accumulated workflow state's nested 'feed' key
    reports exactly which leaf changed, not "the whole feed dict differs"."""
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
    """Bounded diff between two (possibly nested) state dicts -- returns a
    list of `{'field', 'before', 'after'}` entries, one per leaf path whose
    value actually changed. Unchanged fields are excluded entirely."""
    flat_before = _flatten(before or {})
    flat_after = _flatten(after or {})
    changed = []
    for key in sorted(set(flat_before) | set(flat_after)):
        b, a = flat_before.get(key), flat_after.get(key)
        if b != a:
            changed.append({'field': key, 'before': to_jsonable(b), 'after': to_jsonable(a)})
    return changed


def render_human_readable(record):
    """Bounded, human-readable console rendering with the section headers
    from the plan's Step 2. Deliberately does NOT print the complete
    workflow assessment -- only the bounded state diff and the exact
    rejected updates/queries/operations, per Step 2's "Do not print the
    complete workflow assessment to the console by default."""
    lines = []

    lines.append('[TURN]')
    lines.append(f"  turn_id: {record.get('turn_id')}")
    lines.append(f"  user_text: {record.get('user_text')}")

    lines.append('[ROUTE]')
    lines.append(f"  route: {record.get('route')}")

    interpretation = record.get('interpretation') or {}
    attempts = interpretation.get('attempts') or []
    for i, attempt in enumerate(attempts, start=1):
        lines.append(f'[INTERPRETATION ATTEMPT {i}]')
        lines.append(f"  raw: {attempt.get('raw')}")
        lines.append(f"  parse_result: {attempt.get('parse_result')}")
    if interpretation.get('retry_used'):
        lines.append('  (structural retry used)')

    lines.append('[PARSED INTENT]')
    lines.append(f"  final_intent: {interpretation.get('final_intent')}")

    validation = record.get('validation') or {}
    lines.append('[VALIDATION]')
    lines.append(f"  normalized_updates: {validation.get('normalized_updates')}")
    lines.append(f"  invalid_updates: {validation.get('invalid_updates')}")
    lines.append(f"  conflicts: {validation.get('conflicts')}")
    if validation.get('semantic_retry'):
        lines.append(f"  semantic_retry: {validation.get('semantic_retry')}")

    execution = record.get('execution') or {}
    lines.append('[EXECUTION]')
    lines.append(f"  operations: {execution.get('operations')}")
    lines.append(f"  write_performed: {execution.get('write_performed')}")
    lines.append(f"  write_kwargs: {execution.get('write_kwargs')}")
    lines.append(f"  action: {execution.get('action')}")
    lines.append(f"  query_results: {execution.get('query_results')}")

    state = record.get('state') or {}
    lines.append('[STATE DIFF]')
    changed = state.get('changed_fields') or []
    if changed:
        for entry in changed:
            lines.append(f"  {entry['field']}: {entry['before']!r} -> {entry['after']!r}")
    else:
        lines.append('  (no change)')

    lines.append('[FINAL RESPONSE]')
    lines.append(f"  {record.get('final_response')}")

    return '\n'.join(lines)


def append_jsonl(record, path):
    """Append one JSON-serialized diagnostic record as a single line to
    `path`. Never silently swallows a write failure -- an inability to
    write raises so the caller can surface a clear error, per Step 6:
    "inability to write a diagnostic file must produce a clear error
    without silently changing workflow state." Does not itself touch any
    workflow state."""
    line = json.dumps(to_jsonable(record))
    with open(path, 'a', encoding='utf-8') as f:
        f.write(line + '\n')
