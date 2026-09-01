"""
tools/binary-distillation-issues-9-1-2026-fifth.md Parts 1-3 -- registry
shape, action binding, and the "Registry extension" scalability acceptance
test: a new field/action must work through the generic validator/reader
without editing any turn-routing logic.

Run with:
    pytest tools/chopper/test_problem_field_registry.py -v
"""
import copy

# Import the agent module first -- it binds ACTION_REGISTRY['*']['run'] at
# import time (avoiding a circular import between the registry and the
# module that owns the actual operations). Importing problem_field_registry
# alone would leave 'run' as None.
import binary_distillation_workflow_agent as agent  # noqa: F401
from problem_field_registry import ACTION_REGISTRY, ACTIVE_WORKFLOW_SCHEMA, PROBLEM_FIELD_REGISTRY
from problem_snapshot import build_problem_snapshot, read_problem_value
from turn_transaction import validate_turn_intent


def test_active_workflow_schema_shape():
    assert ACTIVE_WORKFLOW_SCHEMA['schema_id'] == 'binary_distillation_problem.v1'
    assert ACTIVE_WORKFLOW_SCHEMA['fields'] is PROBLEM_FIELD_REGISTRY
    assert ACTIVE_WORKFLOW_SCHEMA['actions'] is ACTION_REGISTRY


def test_every_field_declares_access_metadata():
    required_keys = {'readable', 'writable', 'keyed', 'value_type', 'label',
                      'description', 'read_accessor', 'units_accessor',
                      'provenance_accessor', 'allowed_subject_kinds'}
    for name, entry in PROBLEM_FIELD_REGISTRY.items():
        missing = required_keys - entry.keys()
        assert not missing, f'{name} is missing {missing}'
        if entry['writable']:
            assert 'write_binding' in entry, f'{name} is writable but has no write_binding'


def test_component_flows_is_keyed_by_component():
    entry = PROBLEM_FIELD_REGISTRY['component_flows']
    assert entry['keyed'] is True
    assert entry['entity_type'] == 'component'
    assert entry['writable'] is True


def test_total_flow_is_read_only_and_derived_or_explicit():
    entry = PROBLEM_FIELD_REGISTRY['total_flow']
    assert entry['readable'] is True
    assert entry['writable'] is False
    assert entry.get('source') == 'derived_or_explicit'


def test_actions_are_bound_to_real_callables():
    for name in ('reset_current_problem', 'calculate_current_step', 'read_calculation_status'):
        assert callable(ACTION_REGISTRY[name]['run']), f'{name} is not bound'


# ---------------------------------------------------------------------------
# Registry-extension scalability acceptance test (Part 5) -- add one
# artificial field and one artificial action to COPIES of the registries and
# prove the generic validator/reader handles them with zero edits to
# turn_transaction.py, problem_snapshot.py, or binary_distillation_workflow_agent.py.
# ---------------------------------------------------------------------------

def test_registry_extension_new_field_and_action_work_generically():
    registry = copy.deepcopy(PROBLEM_FIELD_REGISTRY)

    def _read(snapshot, entity=None):
        value = snapshot['inputs'].get('widget_count')
        return (value is not None, value)

    registry['widget_count'] = {
        'readable': True, 'writable': True, 'keyed': False,
        'label': 'widget count', 'value_type': 'number',
        'canonical_units': None,
        'description': 'A field invented purely for this test.',
        'write_binding': 'widget_count',
        'read_accessor': _read,
        'units_accessor': lambda snapshot, entity=None: None,
        'provenance_accessor': lambda snapshot, entity=None: 'user_explicit' if snapshot['inputs'].get('widget_count') is not None else None,
        'allowed_subject_kinds': ['current_problem'],
    }

    actions = copy.deepcopy(ACTION_REGISTRY)
    calls = []
    actions['do_a_widget_thing'] = {'label': 'do a widget thing', 'description': 'test-only action',
                                     'run': lambda: calls.append('ran') or {'ok': True}}
    schema = {'schema_id': 'test.v1', 'fields': registry, 'actions': actions}

    intent = {
        'version': 1,
        'updates': [{'field': 'widget_count', 'entity': None, 'subject': None, 'value': 7, 'units': None, 'basis': None}],
        'queries': [{'field': 'widget_count', 'entity': None, 'subject': None, 'raw_reference': 'widget count'}],
        'action': {'name': 'do_a_widget_thing', 'arguments': {}},
    }
    transaction = validate_turn_intent(intent, schema)

    assert transaction['update_kwargs'] == {'widget_count': 7}
    assert transaction['action'] == {'name': 'do_a_widget_thing', 'arguments': {}}
    assert transaction['action_error'] is None

    # Run the bound action directly (proving it's a real, callable entry).
    actions['do_a_widget_thing']['run']()
    assert calls == ['ran']

    # Read it back through the generic snapshot/reader.
    snapshot = build_problem_snapshot({'widget_count': 7}, assessment={'feed': {}})
    result = read_problem_value(snapshot, 'widget_count', registry=registry)
    assert result == {
        'valid': True, 'found': True, 'field': 'widget_count',
        'value': 7, 'units': None, 'provenance': 'user_explicit',
    }
