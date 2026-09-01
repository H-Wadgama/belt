"""
ProblemSnapshot construction and the generic state-value reader --
tools/binary-distillation-issues-9-1-2026-fifth.md Parts 9-10.

A `ProblemSnapshot` is a read-only, per-transaction VIEW derived from
canonical state -- never a second mutable store (Part 1/9). It is built
fresh after every WRITE by the transaction executor
(`turn_transaction.execute_turn_transaction`), and every READ in that turn
resolves against that one snapshot.

`build_problem_snapshot` deliberately takes `inputs`/`assessment`/
`calculation` as plain arguments rather than importing
`binary_distillation_workflow_agent` itself -- that module imports THIS one
(and `problem_field_registry`), so importing it back here would be
circular. The agent module is the one place that actually calls
`get_binary_distillation_problem()` / `calculate_current_binary_distillation_problem()`
and hands the results in.
"""
import difflib

from problem_field_registry import PROBLEM_FIELD_REGISTRY


def build_problem_snapshot(workflow_state, assessment, calculation=None, units=None):
    """
    Build one read-only ProblemSnapshot.

    workflow_state : the accumulated flat `_workflow_state` dict (including
        its nested 'feed' key) -- only its non-'feed' scalar fields are
        exposed as `snapshot['inputs']`; `snapshot['assessment']['feed']` is
        the authoritative source for feed quantities (Part 9: "Never copy
        derived snapshot values into canonical inputs").
    assessment : the already-computed `get_binary_distillation_problem()`
        result for this same state (built by the caller, post-WRITE).
    calculation : the latest calculation result, or None.
    units : optional dict of {unit_id: {field: value, ...}} for a future
        multi-unit-operation state -- always empty/omitted in the real
        single-column workflow today (see `problem_field_registry.py`'s
        `unit_accessor` note); only ever populated by test fixtures proving
        the subject-aware reader works when such state exists.
    """
    return {
        'schema_id': 'binary_distillation_problem.v1',
        'inputs': {k: v for k, v in workflow_state.items() if k != 'feed'},
        'assessment': assessment,
        'calculation': calculation,
        'units': units or {},
    }


def _normalize_entity(snapshot, entity):
    """Case-insensitive match of `entity` against the feed's own established
    `component_names` (Part 3: "safe normalization such as case-insensitive
    exact matching... Do not infer chemical synonyms from model knowledge").
    Returns the canonical name if a match is found, otherwise `entity`
    unchanged (so a WRITE naming a genuinely new component still works)."""
    if entity is None:
        return None
    names = (snapshot['assessment'].get('feed') or {}).get('component_names') or []
    for name in names:
        if name.lower() == entity.lower():
            return name
    return entity


def read_problem_value(snapshot, field, entity=None, subject=None,
                        registry=PROBLEM_FIELD_REGISTRY):
    """
    Generic READ over a ProblemSnapshot -- Part 10. Never raises; every
    outcome (found / known-but-missing / unknown field / unknown subject /
    unknown entity) is returned as a small dict.
    """
    entry = registry.get(field)
    if entry is None:
        near_matches = difflib.get_close_matches(field, list(registry.keys()), n=1, cutoff=0.45)
        return {
            'valid': False, 'error': 'unknown_problem_field',
            'field': field, 'near_matches': near_matches,
        }
    if not entry.get('readable', False):
        return {'valid': False, 'error': 'field_not_readable', 'field': field}

    allowed_subject_kinds = entry.get('allowed_subject_kinds', ['current_problem'])
    subject_kind = (subject or {}).get('kind', 'current_problem')
    if subject_kind not in allowed_subject_kinds:
        return {
            'valid': False, 'error': 'unknown_problem_subject',
            'field': field, 'subject': subject,
        }

    if entry.get('keyed'):
        if entity is None:
            return {'valid': False, 'error': 'unknown_problem_entity', 'field': field}
        entity = _normalize_entity(snapshot, entity)

    if subject_kind == 'unit_operation':
        unit_id = (subject or {}).get('id')
        unit_dict = (snapshot.get('units') or {}).get(unit_id)
        if unit_dict is None or 'unit_accessor' not in entry:
            return {
                'valid': False, 'error': 'unknown_problem_subject',
                'field': field, 'subject': subject,
            }
        found, value = entry['unit_accessor'](snapshot, unit_dict, entity)
        units = entry['units_accessor'](snapshot, entity) if found else None
        provenance = 'user_explicit' if found else None
    else:
        found, value = entry['read_accessor'](snapshot, entity)
        units = entry['units_accessor'](snapshot, entity) if found else None
        provenance = entry['provenance_accessor'](snapshot, entity) if found else None

    result = {
        'valid': True, 'found': found, 'field': field,
        'value': value if found else None,
        'units': units, 'provenance': provenance,
    }
    if entry.get('keyed'):
        result['entity'] = entity
    return result
