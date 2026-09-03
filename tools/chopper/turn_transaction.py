"""
TurnTransaction validation and execution --
tools/binary-distillation-issues-9-1-2026-fifth.md Parts 7-9.

`validate_turn_intent` never raises on bad model output (malformed model
output is a data error, not a Python exception -- Part 7) and never mutates
state. `execute_turn_transaction` is the only place a WRITE actually
happens, and it always happens exactly once per transaction, in the fixed
order from Part 8: optional RESET -> one atomic WRITE -> one ProblemSnapshot
-> every query resolved from that snapshot, in order -> at most one
compatible action against post-WRITE state.

Both functions are deliberately decoupled from
`binary_distillation_workflow_agent.py` and from Ollama entirely -- they
take a plain `runtime` dict of callables (dependency injection), so they can
be tested with a fake in-memory workflow state and no live LLM (per the
doc's "Do not rely on a live LLM for transaction correctness").
"""
from problem_snapshot import build_problem_snapshot, read_problem_value


def _coerce_value(entry, value):
    """Coerce/validate a proposed value against `entry`'s declared
    `value_type`/`constraints`/`allowed_values`. Returns (coerced_value,
    None) on success or (None, reason) on failure. Python owns this
    regardless of what JSON type the model actually sent (Part 7) -- the
    live adapter probes showed a numeric field occasionally arriving as a
    JSON string."""
    value_type = entry.get('value_type')

    if value_type == 'number':
        if isinstance(value, bool):
            return None, 'expected a number, got a boolean'
        if isinstance(value, (int, float)):
            num = float(value)
        elif isinstance(value, str):
            try:
                num = float(value)
            except ValueError:
                return None, 'expected a number'
        else:
            return None, 'expected a number'
        constraints = entry.get('constraints') or {}
        if 'min' in constraints and num < constraints['min']:
            return None, f"below minimum {constraints['min']}"
        if 'max' in constraints and num > constraints['max']:
            return None, f"above maximum {constraints['max']}"
        return num, None

    if value_type == 'boolean':
        if isinstance(value, bool):
            return value, None
        if isinstance(value, str):
            low = value.strip().lower()
            if low in ('true', 'yes', '1'):
                return True, None
            if low in ('false', 'no', '0'):
                return False, None
        return None, 'expected a boolean'

    if value_type == 'enum':
        allowed = entry.get('allowed_values') or []
        if isinstance(value, str):
            for candidate in allowed:
                if candidate.lower() == value.strip().lower():
                    return candidate, None
        return None, f'expected one of {allowed}'

    if value_type == 'list':
        if isinstance(value, list) and all(isinstance(v, str) for v in value) and value:
            return value, None
        return None, 'expected a non-empty list of names'

    # Any other declared type -- pass through unchanged.
    return value, None


def _compile_update_kwargs(valid_updates, registry):
    """Compile a list of individually-validated updates into the exact
    kwargs shape `update_binary_distillation_problem` expects -- keyed
    entries (component_flows) merge into one dict argument; units on a
    keyed component_flows update also set the shared `component_flow_units`
    argument."""
    kwargs = {}
    for u in valid_updates:
        entry = registry[u['field']]
        binding = entry['write_binding']
        if entry.get('keyed'):
            kwargs.setdefault(binding, {})[u['entity']] = u['value']
            if binding == 'component_flows' and u.get('units'):
                kwargs['component_flow_units'] = u['units']
            if binding == 'composition' and u.get('basis'):
                kwargs['composition_basis'] = u['basis']
        else:
            kwargs[binding] = u['value']
    return kwargs


def _field_metadata(entry):
    """A small, deliberately allowlisted subset of a registry entry's own
    metadata -- never the entry itself, so a callable accessor
    (`read_accessor`/`units_accessor`/`provenance_accessor`/`unit_accessor`)
    can never leak into a diagnostic record -- tools/binary-distillation-
    turn-diagnostics-plan.md Step 4."""
    if entry is None:
        return None
    return {
        'keyed': bool(entry.get('keyed')),
        'entity_type': entry.get('entity_type'),
        'value_type': entry.get('value_type'),
        'write_binding': entry.get('write_binding'),
    }


def normalize_turn_intent_updates(updates):
    """
    Deterministically expand each (possibly untrusted) TurnIntent update
    entry into a flat list of scalar-shaped normalized entries --
    tools/binary-distillation-issues-9-1-2026-sixth.md Part 4.

    A scalar entry (no `items`) passes through one-to-one. A collection
    entry (`items` present) expands to one normalized entry PER item,
    each carrying the parent's `field`/`subject` -- this is the only place
    a collection update is turned into the exact per-(field, entity) shape
    `validate_turn_intent`'s existing per-update loop already knows how to
    validate; no second validation path is created for collections (Part 4:
    "reuse the existing validator... do not create a second validation
    path").

    A structurally malformed shape -- `items` given together with a
    top-level `value` or non-null `entity` (Part 2: "top-level entity and
    value must not coexist with items"), an empty/non-list `items`, or an
    item missing its own explicit `entity` -- normalizes to a SINGLE
    entry carrying `_shape_error` instead of a usable value, so
    `validate_turn_intent` rejects it as one invalid update (the whole
    update batch still zero-WRITEs, per the existing atomicity rule)
    rather than silently expanding a broken shape into several bogus
    per-item entries.

    Every returned entry carries `update_index` (position in the ORIGINAL
    `updates` list -- shared across every entry expanded from the same
    collection update) and `source_update` (the original, unexpanded
    update dict exactly as proposed -- collection form preserved, never
    collapsed) so a rejection can still report exactly what was proposed.
    """
    normalized = []
    for index, u in enumerate(updates):
        if not isinstance(u, dict):
            normalized.append({
                'field': None, 'entity': None, 'subject': None, 'value': None,
                'units': None, 'basis': None, '_shape_error': 'update_not_an_object',
                'update_index': index, 'source_update': u,
            })
            continue

        field = u.get('field')
        has_items = 'items' in u and u['items'] is not None
        has_top_level_value = 'value' in u
        has_top_level_entity = u.get('entity') is not None

        if has_items and (has_top_level_value or has_top_level_entity):
            normalized.append({
                'field': field, 'entity': None, 'subject': u.get('subject'), 'value': None,
                'units': None, 'basis': None, '_shape_error': 'items_cannot_coexist_with_entity_or_value',
                'update_index': index, 'source_update': u,
            })
            continue

        if not has_items:
            normalized.append({
                'field': field, 'entity': u.get('entity'), 'subject': u.get('subject'),
                'value': u.get('value'), 'units': u.get('units'), 'basis': u.get('basis'),
                'update_index': index, 'source_update': u,
            })
            continue

        items = u.get('items')
        if not isinstance(items, list) or not items:
            normalized.append({
                'field': field, 'entity': None, 'subject': u.get('subject'), 'value': None,
                'units': None, 'basis': None, '_shape_error': 'items_must_be_a_non_empty_list',
                'update_index': index, 'source_update': u,
            })
            continue

        if not all(isinstance(entry, dict) and entry.get('entity') for entry in items):
            normalized.append({
                'field': field, 'entity': None, 'subject': u.get('subject'), 'value': None,
                'units': None, 'basis': None, '_shape_error': 'missing_entity',
                'update_index': index, 'source_update': u,
            })
            continue

        for entry in items:
            normalized.append({
                'field': field, 'entity': entry.get('entity'), 'subject': u.get('subject'),
                'value': entry.get('value'), 'units': entry.get('units'), 'basis': entry.get('basis'),
                'update_index': index, 'source_update': u, '_from_items': True,
            })
    return normalized


def _invalid_update_record(index, update, reason, entry):
    """One rejected update, enriched with enough context to diagnose it
    without consulting the original raw model response -- Step 4. 'update'
    and 'reason' are unchanged from the pre-Step-4 shape (existing callers
    read them); 'update_index'/'field_metadata'/'effect' are additive."""
    return {
        'update_index': index,
        'update': update,
        'reason': reason,
        'field_metadata': _field_metadata(entry),
        'effect': 'entire_update_batch_rejected',
    }


def validate_turn_intent(intent, schema, workflow_state=None):
    """
    Validate a (possibly untrusted, possibly malformed) TurnIntent into a
    TurnTransaction -- Part 7.

    Updates are ATOMIC as a group: per the doc's explicit
    "invalid second update causes zero writes" requirement, if ANY proposed
    update is invalid (unknown field, not writable, missing entity on a
    keyed field, bad value/range) OR any two valid updates conflict on the
    same (field, entity), `update_kwargs` comes back empty -- no partial
    WRITE. Queries and the action are validated independently and are never
    blocked by an invalid update set.
    """
    registry = schema['fields']
    actions_registry = schema['actions']

    normalized_updates = normalize_turn_intent_updates(intent.get('updates', []))

    valid_updates = []
    invalid_updates = []
    for nu in normalized_updates:
        index = nu['update_index']
        source_update = nu['source_update']

        shape_error = nu.get('_shape_error')
        if shape_error is not None:
            entry = registry.get(nu.get('field'))
            invalid_updates.append(_invalid_update_record(index, source_update, shape_error, entry))
            continue

        field = nu['field']
        entry = registry.get(field)
        if entry is None:
            invalid_updates.append(_invalid_update_record(index, source_update, 'unknown_field', None))
            continue
        if not entry.get('writable'):
            invalid_updates.append(_invalid_update_record(index, source_update, 'field_not_writable', entry))
            continue
        if nu.get('_from_items') and not entry.get('keyed'):
            invalid_updates.append(_invalid_update_record(index, source_update, 'items_not_supported_for_field', entry))
            continue
        entity = nu.get('entity')
        if entry.get('keyed') and not entity:
            invalid_updates.append(_invalid_update_record(index, source_update, 'missing_entity', entry))
            continue
        coerced, err = _coerce_value(entry, nu.get('value'))
        if err is not None:
            invalid_updates.append(_invalid_update_record(index, source_update, err, entry))
            continue
        valid_updates.append({
            'field': field, 'entity': entity, 'value': coerced,
            'units': nu.get('units'), 'basis': nu.get('basis'),
        })

    # Identical duplicates collapse; conflicting duplicates (same
    # field+entity, different coerced value) are recorded as conflicts.
    dedup = {}
    conflicts = []
    for vu in valid_updates:
        key = (vu['field'], vu['entity'])
        if key in dedup and dedup[key]['value'] != vu['value']:
            conflicts.append({
                'field': vu['field'], 'entity': vu['entity'],
                'values': [dedup[key]['value'], vu['value']],
            })
        dedup[key] = vu

    # A keyed field's shared unit/basis side-channel (component_flow_units
    # from component_flows, composition_basis from composition) must never
    # be silently overwritten by a different unit/basis on another entry in
    # the SAME batch -- that is silent data loss, not cosmetic last-write-
    # wins ("Mixed units" -- Part 11: "Do not silently combine incompatible
    # units"). Treated the same as an entity/value conflict: zero WRITE.
    for attr in ('units', 'basis'):
        seen_by_field = {}
        for vu in dedup.values():
            if vu.get(attr):
                seen_by_field.setdefault(vu['field'], set()).add(vu[attr])
        for field, seen in seen_by_field.items():
            if len(seen) > 1:
                conflicts.append({'field': field, 'entity': None, 'values': sorted(seen), 'kind': attr})

    if invalid_updates or conflicts:
        update_kwargs = {}
        valid_updates = []
    else:
        update_kwargs = _compile_update_kwargs(dedup.values(), registry)
        valid_updates = list(dedup.values())

    action_intent = intent.get('action')
    reset_first = False
    action = None
    action_error = None
    if action_intent is not None:
        name = action_intent.get('name')
        if name not in actions_registry:
            action_error = {'error': 'unknown_action', 'name': name}
        elif name == 'reset_current_problem':
            # RESET is executed as its own pre-WRITE step (Part 8), not a
            # post-WRITE action -- see execute_turn_transaction.
            reset_first = True
        else:
            action = {'name': name, 'arguments': action_intent.get('arguments') or {}}

    return {
        'reset_first': reset_first,
        'update_kwargs': update_kwargs,
        'valid_updates': valid_updates,
        'normalized_updates': normalized_updates,
        'invalid_updates': invalid_updates,
        'conflicts': conflicts,
        'queries': list(intent.get('queries', [])),
        'action': action,
        'action_error': action_error,
        'pending_reask': None,
    }


def is_empty_transaction(transaction):
    """True if this transaction has nothing for the deterministic pipeline
    to do -- no reset, no updates (valid or invalid), no queries, no
    action. Used by the caller to decide whether to fall back to a broad,
    Qwen-grounded elaboration response instead of a terminal one."""
    return (
        not transaction['reset_first']
        and not transaction['update_kwargs']
        and not transaction['invalid_updates']
        and not transaction['queries']
        and transaction['action'] is None
        and transaction['action_error'] is None
        and transaction.get('pending_reask') is None
    )


def make_raw_update_transaction(update_kwargs):
    """Build a TurnTransaction wrapping an already-known-valid kwargs dict
    verbatim -- used by exclusive fast-path detectors whose resolved value
    may span multiple fields at once (e.g. an `ordered_float_group` pending
    reply resolving both xD and xB together). Unlike
    `make_single_update_transaction`, no per-field breakdown is recorded in
    `valid_updates` -- fast-path WRITEs are always narrated by the model
    from the resulting assessment (Qwen-narration branch), never rendered
    by `format_transaction_response`, so the breakdown is never read."""
    return {
        'reset_first': False, 'update_kwargs': dict(update_kwargs), 'valid_updates': [],
        'normalized_updates': [], 'invalid_updates': [], 'conflicts': [],
        'queries': [], 'action': None, 'action_error': None, 'pending_reask': None,
    }


def make_single_update_transaction(field, value, entity=None, units=None):
    """Build a TurnTransaction wrapping exactly one already-known-valid
    field/value pair -- used by exclusive fast-path detectors (Part 6) so
    they share the same execution/formatting pipeline as the model path
    rather than having their own bespoke side effect."""
    if entity is not None:
        update_kwargs = {field: {entity: value}}
        if units and field == 'component_flows':
            update_kwargs['component_flow_units'] = units
    else:
        update_kwargs = {field: value}
    return {
        'reset_first': False,
        'update_kwargs': update_kwargs,
        'valid_updates': [{'field': field, 'entity': entity, 'value': value, 'units': units, 'basis': None}],
        'normalized_updates': [], 'invalid_updates': [], 'conflicts': [],
        'queries': [], 'action': None, 'action_error': None, 'pending_reask': None,
    }


def make_action_transaction(action_name, arguments=None):
    """Build an action-only TurnTransaction -- used by exclusive fast-path
    detectors for 'proceed'/progress-question routing (Part 6)."""
    return {
        'reset_first': False, 'update_kwargs': {}, 'valid_updates': [],
        'normalized_updates': [], 'invalid_updates': [], 'conflicts': [],
        'queries': [], 'action': {'name': action_name, 'arguments': arguments or {}},
        'action_error': None, 'pending_reask': None,
    }


def make_query_transaction(field, entity=None, subject=None, raw_reference=None):
    """Build a query-only TurnTransaction -- used by an exclusive fast-path
    detector whose target field is unambiguous from phrasing alone (same
    spirit as `make_action_transaction`), e.g. a workflow-definition
    question like "what are the inputs for the four cases?"
    (tools/binary-distillation-issues-9-1-2026-eighth.md Step 4/5). Routes
    through the SAME terminal, Python-rendered query pipeline
    (`format_transaction_response`) as a model-proposed query -- no special
    casing downstream."""
    return {
        'reset_first': False, 'update_kwargs': {}, 'valid_updates': [],
        'normalized_updates': [], 'invalid_updates': [], 'conflicts': [],
        'queries': [{'field': field, 'entity': entity, 'subject': subject, 'raw_reference': raw_reference}],
        'action': None, 'action_error': None, 'pending_reask': None,
    }


def make_pending_reask_transaction(pending_request):
    """Build a terminal, Python-only TurnTransaction that re-asks for the
    live `pending_request` instead of executing anything --
    tools/binary-distillation-issues-9-1-2026-eighth.md Step 1: a generic
    short reply ("yes", "sure", "go ahead", ...) must never be read as
    answering -- or as permission to bypass -- a specific outstanding
    question Python could not already resolve it against. Carries no
    updates/queries/action; `_dispatch_transaction` reads `pending_reask`
    directly and renders its `prompt` with no model call and no state
    change, so this can never accidentally trigger a calculation or a
    write."""
    return {
        'reset_first': False, 'update_kwargs': {}, 'valid_updates': [],
        'normalized_updates': [], 'invalid_updates': [], 'conflicts': [],
        'queries': [], 'action': None, 'action_error': None,
        'pending_reask': pending_request,
    }


def execute_turn_transaction(transaction, runtime):
    """
    Execute one validated TurnTransaction -- Part 8's fixed order.

    `runtime` (dependency injection, so this never needs a live LLM or the
    agent module to be tested):
        'reset'          : callable() -> dict
        'update'         : callable(**kwargs) -> assessment dict
        'get_state'      : callable() -> the flat workflow_state dict (incl. 'feed')
        'get_calculation': callable() -> latest calculation result, or None
        'run_action'     : callable(name, arguments) -> action result dict
    """
    if transaction['reset_first']:
        runtime['reset']()

    # Step 3 -- exactly one atomic WRITE, even when update_kwargs is empty
    # (a harmless no-op merge through the existing WRITE path, per Part 8:
    # "perform one atomic WRITE" is unconditional).
    assessment = runtime['update'](**transaction['update_kwargs'])

    # Step 4 -- one post-WRITE ProblemSnapshot.
    snapshot = build_problem_snapshot(
        runtime['get_state'](), assessment, runtime['get_calculation'](),
    )

    # Step 5 -- resolve every query from that snapshot, in order. Side
    # reads never mutate state -- read_problem_value only ever reads.
    query_results = [
        read_problem_value(snapshot, q['field'], entity=q.get('entity'), subject=q.get('subject'))
        for q in transaction['queries']
    ]

    # Step 6 -- at most one compatible action against post-WRITE state.
    action_result = None
    if transaction['action'] is not None:
        action_result = runtime['run_action'](
            transaction['action']['name'], transaction['action']['arguments'],
        )

    return {
        'snapshot': snapshot,
        'assessment': assessment,
        'query_results': query_results,
        'action_result': action_result,
    }
