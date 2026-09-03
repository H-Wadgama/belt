"""
Model-facing problem field / action registry --
tools/binary-distillation-issues-9-1-2026-fifth.md Parts 1-3.

One authoritative metadata registry describing every field the active
binary-distillation workflow schema supports for turn-based READ/WRITE
access (`PROBLEM_FIELD_REGISTRY`), plus the small set of stable action verbs
it supports (`ACTION_REGISTRY`), bundled into one `ACTIVE_WORKFLOW_SCHEMA`.

This registry describes ACCESS -- it does not store values. Canonical
mutable state remains `binary_distillation_workflow_agent._workflow_state`;
this module only tells `turn_intent.py`/`turn_transaction.py`/
`problem_snapshot.py` how to validate, read, write, and format each field
without duplicating its value (Part 2).

Deliberately scoped to the CURRENT single-feed/single-column binary
workflow's own fields -- see the module docstring note on `subject` handling
below for how this stays extensible to a future multi-unit state without
claiming to support one today.

Each accessor callable takes a `ProblemSnapshot` (see `problem_snapshot.py`)
and an optional `entity` (for keyed fields), and returns `(found, value)`.
Accessors never mutate the snapshot and never raise for a merely-missing
value (missing => `(False, None)`); a genuinely programmer-error case (an
accessor called for a subject it was never registered against) is a bug, not
a data condition, and is guarded against by `problem_snapshot.read_problem_value`
before any accessor is ever invoked for an unsupported subject.

tools/binary-distillation-issues-9-1-2026-eighth.md Step 4/5 adds one
READ-ONLY, non-state entry -- `design_option_requirements` -- that answers a
WORKFLOW-DEFINITION question ("what does Case A need?", "what are the
inputs for the four cases?") from the same static
`problem_spec.CASE_FIELD_SUMMARY` the deterministic checker itself uses,
rather than the accumulated engineering problem state. This is
deliberately NOT a fake engineering-state field: its 'value' is never read
from `snapshot['inputs']`/`snapshot['assessment']['feed']` the way every
other entry above is -- it is computed fresh from the static registry every
call, so there is nothing to store, invalidate, or accidentally leak into a
WRITE.
"""
from problem_spec import CASE_FIELD_SUMMARY

# ---------------------------------------------------------------------------
# Scalar "current_problem" fields -- read from snapshot['inputs'] (the flat
# accumulated WRITE-tool fields), written via the matching
# update_binary_distillation_problem kwarg (`write_binding`).
# ---------------------------------------------------------------------------


def _scalar_accessors(key):
    def read(snapshot, entity=None):
        value = snapshot['inputs'].get(key)
        return (value is not None, value)

    def provenance(snapshot, entity=None):
        value = snapshot['inputs'].get(key)
        return 'user_explicit' if value is not None else None

    return read, provenance


def _unit_scalar_accessor(key):
    """Optional alternate accessor for a scalar field when accessed with a
    `subject={'kind': 'unit_operation', 'id': ...}` -- reads from
    `snapshot['units'][id]` instead of `snapshot['inputs']`. The real
    single-column workflow never populates `snapshot['units']`, so this path
    is exercised only by the scalability fixture tests -- see
    tools/binary-distillation-issues-9-1-2026-fifth.md Part 3's own D1/D2
    example and the "Subject-aware access" scalability acceptance test."""

    def read(snapshot, unit_dict, entity=None):
        value = unit_dict.get(key)
        return (value is not None, value)

    return read


_feed_temperature_read, _feed_temperature_prov = _scalar_accessors('feed_temperature_K')
_feed_quality_read, _feed_quality_prov = _scalar_accessors('feed_quality')
_feed_enthalpy_read, _feed_enthalpy_prov = _scalar_accessors('feed_enthalpy_kJ_per_hr')
_pressure_read, _pressure_prov = _scalar_accessors('pressure_Pa')
_reflux_condition_read, _reflux_condition_prov = _scalar_accessors('reflux_condition')
_xD_read, _xD_prov = _scalar_accessors('xD')
_xB_read, _xB_prov = _scalar_accessors('xB')
_Lr_read, _Lr_prov = _scalar_accessors('Lr')
_Hr_read, _Hr_prov = _scalar_accessors('Hr')
_distillate_flow_read, _distillate_flow_prov = _scalar_accessors('distillate_flow')
_bottoms_flow_read, _bottoms_flow_prov = _scalar_accessors('bottoms_flow')
_boilup_ratio_read, _boilup_ratio_prov = _scalar_accessors('boilup_ratio_VB')
_external_reflux_read, _external_reflux_prov = _scalar_accessors('external_reflux_ratio_LD')
_reflux_k_read, _reflux_k_prov = _scalar_accessors('reflux_ratio_multiplier_k')
_ofp_read, _ofp_prov = _scalar_accessors('use_optimum_feed_plate')


# ---------------------------------------------------------------------------
# Derived / feed-quantity fields -- read from
# snapshot['assessment']['feed'] (the normalized feed_state -- see
# feed_state.assess_feed_state), NEVER from snapshot['inputs']. This is the
# fix for Failure 2: total_flow is frequently 'derived', not
# 'user_explicit', and must be read from the one place derivation actually
# happens (Part 9).
# ---------------------------------------------------------------------------


def _total_flow_read(snapshot, entity=None):
    feed = snapshot['assessment'].get('feed') or {}
    value = feed.get('total_flow')
    return (value is not None, value)


def _total_flow_units(snapshot, entity=None):
    feed = snapshot['assessment'].get('feed') or {}
    return feed.get('total_flow_units') or feed.get('component_flow_units')


def _total_flow_provenance(snapshot, entity=None):
    feed = snapshot['assessment'].get('feed') or {}
    return feed.get('total_flow_provenance')


def _component_flows_read(snapshot, entity=None):
    feed = snapshot['assessment'].get('feed') or {}
    flows = feed.get('component_flows') or {}
    if entity is None:
        return (False, None)
    return (entity in flows, flows.get(entity))


def _component_flows_units(snapshot, entity=None):
    feed = snapshot['assessment'].get('feed') or {}
    return feed.get('component_flow_units')


def _component_flows_provenance(snapshot, entity=None):
    feed = snapshot['assessment'].get('feed') or {}
    prov = feed.get('component_flows_provenance') or {}
    return prov.get(entity) if entity is not None else None


def _composition_read(snapshot, entity=None):
    feed = snapshot['assessment'].get('feed') or {}
    comp = feed.get('composition') or {}
    if entity is None:
        return (False, None)
    return (entity in comp, comp.get(entity))


def _composition_provenance(snapshot, entity=None):
    feed = snapshot['assessment'].get('feed') or {}
    prov = feed.get('composition_provenance') or {}
    return prov.get(entity) if entity is not None else None


def _component_names_read(snapshot, entity=None):
    feed = snapshot['assessment'].get('feed') or {}
    names = feed.get('component_names') or []
    return (bool(names), list(names))


def _component_names_provenance(snapshot, entity=None):
    feed = snapshot['assessment'].get('feed') or {}
    return 'user_explicit' if feed.get('component_names') else None


# ---------------------------------------------------------------------------
# Workflow-definition field -- reads the STATIC CASE_FIELD_SUMMARY, never
# the accumulated problem state. `entity`, when given, is the Design Option
# letter ('A'/'B'/'C'/'D'), NOT a component name -- this field is
# deliberately `keyed: False` in the registry entry below (see that entry's
# comment) so `problem_snapshot.read_problem_value` never tries to
# normalize it against the feed's own component names.
# ---------------------------------------------------------------------------


def _design_option_requirements_read(snapshot, entity=None):
    if entity:
        key = str(entity).strip().upper()
        summary = CASE_FIELD_SUMMARY.get(key)
        if summary is None:
            return (False, None)
        return (True, f'Design Option {key} requires: {summary}.')
    parts = '; '.join(f'Design Option {c} = {d}' for c, d in CASE_FIELD_SUMMARY.items())
    return (True, f'The four Design Options and what each requires: {parts}.')


# ---------------------------------------------------------------------------
# PROBLEM_FIELD_REGISTRY
# ---------------------------------------------------------------------------
#
# `constraints`/`allowed_values` are ONLY populated where the existing
# deterministic workflow already enforces them elsewhere (xD/xB/Lr/Hr in
# binary_distillation_workflow.py's `_CASE_FIELD_META`,
# `reflux_condition` in problem_spec.SUPPORTED_REFLUX_CONDITIONS) --
# this registry does not invent new engineering constraints.

PROBLEM_FIELD_REGISTRY = {
    'feed_temperature_K': {
        'readable': True, 'writable': True, 'keyed': False,
        'label': 'feed temperature', 'value_type': 'number',
        'canonical_units': 'K',
        'description': 'Temperature of the feed entering the separation.',
        'write_binding': 'feed_temperature_K',
        'read_accessor': _feed_temperature_read,
        'units_accessor': lambda snapshot, entity=None: 'K',
        'provenance_accessor': lambda snapshot, entity=None: _feed_temperature_prov(snapshot),
        'allowed_subject_kinds': ['feed', 'current_problem'],
    },
    'feed_quality': {
        'readable': True, 'writable': True, 'keyed': False,
        'label': 'feed quality', 'value_type': 'number',
        'canonical_units': None,
        'description': 'Feed vapor fraction/quality (0 = saturated liquid, 1 = saturated vapor).',
        'write_binding': 'feed_quality',
        'read_accessor': _feed_quality_read,
        'units_accessor': lambda snapshot, entity=None: None,
        'provenance_accessor': lambda snapshot, entity=None: _feed_quality_prov(snapshot),
        'allowed_subject_kinds': ['feed', 'current_problem'],
    },
    'feed_enthalpy_kJ_per_hr': {
        'readable': True, 'writable': True, 'keyed': False,
        'label': 'feed enthalpy', 'value_type': 'number',
        'canonical_units': 'kJ/hr',
        'description': 'Feed molar enthalpy.',
        'write_binding': 'feed_enthalpy_kJ_per_hr',
        'read_accessor': _feed_enthalpy_read,
        'units_accessor': lambda snapshot, entity=None: 'kJ/hr',
        'provenance_accessor': lambda snapshot, entity=None: _feed_enthalpy_prov(snapshot),
        'allowed_subject_kinds': ['feed', 'current_problem'],
    },
    'pressure_Pa': {
        'readable': True, 'writable': True, 'keyed': False,
        'label': 'column pressure', 'value_type': 'number',
        'canonical_units': 'Pa',
        'description': 'Column operating pressure.',
        'write_binding': 'pressure_Pa',
        'read_accessor': _pressure_read,
        'units_accessor': lambda snapshot, entity=None: 'Pa',
        'provenance_accessor': lambda snapshot, entity=None: _pressure_prov(snapshot),
        'allowed_subject_kinds': ['unit_operation', 'current_problem'],
        'unit_accessor': _unit_scalar_accessor('pressure_Pa'),
    },
    'reflux_condition': {
        'readable': True, 'writable': True, 'keyed': False,
        'label': 'reflux condition', 'value_type': 'enum',
        'canonical_units': None, 'allowed_values': ['saturated_liquid'],
        'description': 'Reflux thermal condition.',
        'write_binding': 'reflux_condition',
        'read_accessor': _reflux_condition_read,
        'units_accessor': lambda snapshot, entity=None: None,
        'provenance_accessor': lambda snapshot, entity=None: _reflux_condition_prov(snapshot),
        'allowed_subject_kinds': ['unit_operation', 'current_problem'],
    },
    'xD': {
        'readable': True, 'writable': True, 'keyed': False,
        'label': 'xD (distillate light-key mole fraction)', 'value_type': 'number',
        'canonical_units': None, 'constraints': {'min': 0, 'max': 1},
        'description': 'Design Option A/D target distillate light-key mole fraction.',
        'write_binding': 'xD',
        'read_accessor': _xD_read,
        'units_accessor': lambda snapshot, entity=None: None,
        'provenance_accessor': lambda snapshot, entity=None: _xD_prov(snapshot),
        'allowed_subject_kinds': ['unit_operation', 'current_problem'],
    },
    'xB': {
        'readable': True, 'writable': True, 'keyed': False,
        'label': 'xB (bottoms light-key mole fraction)', 'value_type': 'number',
        'canonical_units': None, 'constraints': {'min': 0, 'max': 1},
        'description': 'Design Option A/D target bottoms light-key mole fraction.',
        'write_binding': 'xB',
        'read_accessor': _xB_read,
        'units_accessor': lambda snapshot, entity=None: None,
        'provenance_accessor': lambda snapshot, entity=None: _xB_prov(snapshot),
        'allowed_subject_kinds': ['unit_operation', 'current_problem'],
    },
    'Lr': {
        'readable': True, 'writable': True, 'keyed': False,
        'label': 'Lr (light-key recovery to distillate)', 'value_type': 'number',
        'canonical_units': None, 'constraints': {'min': 0, 'max': 1},
        'description': 'Design Option B target fractional recovery of the light key to the distillate.',
        'write_binding': 'Lr',
        'read_accessor': _Lr_read,
        'units_accessor': lambda snapshot, entity=None: None,
        'provenance_accessor': lambda snapshot, entity=None: _Lr_prov(snapshot),
        'allowed_subject_kinds': ['unit_operation', 'current_problem'],
    },
    'Hr': {
        'readable': True, 'writable': True, 'keyed': False,
        'label': 'Hr (heavy-key recovery to bottoms)', 'value_type': 'number',
        'canonical_units': None, 'constraints': {'min': 0, 'max': 1},
        'description': 'Design Option B target fractional recovery of the heavy key to the bottoms.',
        'write_binding': 'Hr',
        'read_accessor': _Hr_read,
        'units_accessor': lambda snapshot, entity=None: None,
        'provenance_accessor': lambda snapshot, entity=None: _Hr_prov(snapshot),
        'allowed_subject_kinds': ['unit_operation', 'current_problem'],
    },
    'distillate_flow': {
        'readable': True, 'writable': True, 'keyed': False,
        'label': 'distillate flow', 'value_type': 'number',
        'canonical_units': None,
        'description': 'Design Option C specified distillate flow rate.',
        'write_binding': 'distillate_flow',
        'read_accessor': _distillate_flow_read,
        'units_accessor': lambda snapshot, entity=None: None,
        'provenance_accessor': lambda snapshot, entity=None: _distillate_flow_prov(snapshot),
        'allowed_subject_kinds': ['unit_operation', 'current_problem'],
    },
    'bottoms_flow': {
        'readable': True, 'writable': True, 'keyed': False,
        'label': 'bottoms flow', 'value_type': 'number',
        'canonical_units': None,
        'description': 'Design Option C specified bottoms flow rate.',
        'write_binding': 'bottoms_flow',
        'read_accessor': _bottoms_flow_read,
        'units_accessor': lambda snapshot, entity=None: None,
        'provenance_accessor': lambda snapshot, entity=None: _bottoms_flow_prov(snapshot),
        'allowed_subject_kinds': ['unit_operation', 'current_problem'],
    },
    'boilup_ratio_VB': {
        'readable': True, 'writable': True, 'keyed': False,
        'label': 'boilup ratio (V/B)', 'value_type': 'number',
        'canonical_units': None,
        'description': 'Design Option D specified boilup ratio V/B.',
        'write_binding': 'boilup_ratio_VB',
        'read_accessor': _boilup_ratio_read,
        'units_accessor': lambda snapshot, entity=None: None,
        'provenance_accessor': lambda snapshot, entity=None: _boilup_ratio_prov(snapshot),
        'allowed_subject_kinds': ['unit_operation', 'current_problem'],
    },
    'external_reflux_ratio_LD': {
        'readable': True, 'writable': True, 'keyed': False,
        'label': 'external reflux ratio (L/D)', 'value_type': 'number',
        'canonical_units': None,
        'description': "Wankat's external/actual reflux ratio L0/D (Design Options A-C).",
        'write_binding': 'external_reflux_ratio_LD',
        'read_accessor': _external_reflux_read,
        'units_accessor': lambda snapshot, entity=None: None,
        'provenance_accessor': lambda snapshot, entity=None: _external_reflux_prov(snapshot),
        'allowed_subject_kinds': ['unit_operation', 'current_problem'],
    },
    'reflux_ratio_multiplier_k': {
        'readable': True, 'writable': True, 'keyed': False,
        'label': 'reflux ratio multiplier k', 'value_type': 'number',
        'canonical_units': None,
        'description': 'Internal shortcut-method reflux multiplier k = R/Rmin.',
        'write_binding': 'reflux_ratio_multiplier_k',
        'read_accessor': _reflux_k_read,
        'units_accessor': lambda snapshot, entity=None: None,
        'provenance_accessor': lambda snapshot, entity=None: _reflux_k_prov(snapshot),
        'allowed_subject_kinds': ['unit_operation', 'current_problem'],
    },
    'use_optimum_feed_plate': {
        'readable': True, 'writable': True, 'keyed': False,
        'label': 'use-optimum-feed-plate setting', 'value_type': 'boolean',
        'canonical_units': None,
        'description': 'Whether the design should use the optimum feed plate (common to all four Design Options).',
        'write_binding': 'use_optimum_feed_plate',
        'read_accessor': _ofp_read,
        'units_accessor': lambda snapshot, entity=None: None,
        'provenance_accessor': lambda snapshot, entity=None: _ofp_prov(snapshot),
        'allowed_subject_kinds': ['unit_operation', 'current_problem'],
    },
    'total_flow': {
        'readable': True, 'writable': False, 'keyed': False,
        'label': 'total feed flow rate', 'value_type': 'number',
        'canonical_units': None,  # dynamic -- see units_accessor
        'description': 'Total feed flow rate (explicit or derived from component flows).',
        'source': 'derived_or_explicit',
        'read_accessor': _total_flow_read,
        'units_accessor': _total_flow_units,
        'provenance_accessor': _total_flow_provenance,
        'allowed_subject_kinds': ['feed', 'current_problem'],
    },
    'component_flows': {
        'readable': True, 'writable': True, 'keyed': True, 'entity_type': 'component',
        'label': 'component feed flow', 'value_type': 'number',
        'canonical_units': None,  # dynamic -- see units_accessor
        'description': 'Per-component feed flow rate, keyed by component name.',
        'write_binding': 'component_flows',
        'read_accessor': _component_flows_read,
        'units_accessor': _component_flows_units,
        'provenance_accessor': _component_flows_provenance,
        'allowed_subject_kinds': ['feed', 'current_problem'],
    },
    'composition': {
        'readable': True, 'writable': True, 'keyed': True, 'entity_type': 'component',
        'label': 'component mole/mass fraction', 'value_type': 'number',
        'canonical_units': None, 'constraints': {'min': 0, 'max': 1},
        'description': 'Per-component feed composition fraction, keyed by component name.',
        'write_binding': 'composition',
        'read_accessor': _composition_read,
        'units_accessor': lambda snapshot, entity=None: None,
        'provenance_accessor': _composition_provenance,
        'allowed_subject_kinds': ['feed', 'current_problem'],
    },
    'component_names': {
        'readable': True, 'writable': True, 'keyed': False,
        'label': 'named feed components', 'value_type': 'list',
        'canonical_units': None,
        'description': (
            'The FULL, current list of feed component names -- use this ONLY when the '
            'user names components WITHOUT stating any flow/quantity for them yet (e.g. '
            '"separate methanol and water"). If the user gives per-component flows in '
            'the same message, use component_flows instead (it establishes identity '
            'automatically) and do not also write component_names.'
        ),
        'write_binding': 'component_names',
        'read_accessor': _component_names_read,
        'units_accessor': lambda snapshot, entity=None: None,
        'provenance_accessor': _component_names_provenance,
        'allowed_subject_kinds': ['feed', 'current_problem'],
    },
    'design_option_requirements': {
        'readable': True, 'writable': False,
        # NOT `keyed: True` -- `keyed` means "entity is a per-instance key
        # into accumulated STATE" (e.g. a component name into
        # component_flows) and requires an entity be given at all;
        # `entity` here is an OPTIONAL Design Option letter into a static
        # lookup table, and "all four" (entity omitted) is a fully valid
        # question.
        'keyed': False,
        'label': 'Design Option A-D requirements', 'value_type': 'string',
        'canonical_units': None,
        'description': (
            'STATIC definition of what each Design Option (Wankat Case) A-D '
            'requires -- NOT part of the engineering problem state, and never '
            'affected by what has been supplied so far. Query this for a '
            'WORKFLOW question about what a Design Option needs in general '
            '(e.g. "what are the inputs for the four cases?", "what does '
            'Design Option A need?", "what do I still need for Design Option '
            'D?") -- never guess these requirements from your own knowledge. '
            'Pass the Design Option letter ("A"/"B"/"C"/"D") as "entity" to '
            'ask about ONE option, or omit "entity" to ask about all four.'
        ),
        'write_binding': None,
        'read_accessor': _design_option_requirements_read,
        'units_accessor': lambda snapshot, entity=None: None,
        'provenance_accessor': lambda snapshot, entity=None: 'workflow_definition',
        'allowed_subject_kinds': ['current_problem'],
    },
}


# ---------------------------------------------------------------------------
# ACTION_REGISTRY -- Part 8's generic verbs. Each entry's 'run' callable is
# bound lazily (via binary_distillation_workflow_agent._bind_action_registry)
# to that module's existing reset_workflow_session /
# calculate_current_binary_distillation_problem /
# get_binary_distillation_calculation_status functions, so this registry has
# no import-time dependency on the agent module (avoids a circular import --
# the agent module imports THIS module).
# ---------------------------------------------------------------------------

ACTION_REGISTRY = {
    'reset_current_problem': {
        'label': 'reset the current problem',
        'description': 'Clears all previously-remembered inputs for the current binary-distillation problem.',
        'run': None,  # bound at import time by the agent module
    },
    'calculate_current_step': {
        'label': 'calculate the current step',
        'description': 'Runs the deterministic feed-phase calculation for the current problem, if ready.',
        'run': None,
    },
    'read_calculation_status': {
        'label': 'read calculation status',
        'description': 'Reports the most recent calculation result and calculation-progress state, without running a new calculation.',
        'run': None,
    },
}


def bind_action(name, run_callable):
    """Wire an ACTION_REGISTRY entry's 'run' callable -- called once at
    import time by binary_distillation_workflow_agent.py to avoid a circular
    import between this registry module and the agent module that owns the
    actual action implementations."""
    ACTION_REGISTRY[name]['run'] = run_callable


ACTIVE_WORKFLOW_SCHEMA = {
    'schema_id': 'binary_distillation_problem.v1',
    'fields': PROBLEM_FIELD_REGISTRY,
    'actions': ACTION_REGISTRY,
}
