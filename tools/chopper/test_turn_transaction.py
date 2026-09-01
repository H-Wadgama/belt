"""
tools/binary-distillation-issues-9-1-2026-fifth.md Parts 7-8 --
TurnTransaction validation and execution. No live LLM: `validate_turn_intent`
takes a plain TurnIntent dict, and `execute_turn_transaction` takes a fake,
in-memory `runtime` dict of callables.

Run with:
    pytest tools/chopper/test_turn_transaction.py -v
"""
import binary_distillation_workflow_agent as agent  # binds ACTION_REGISTRY['*']['run']
from problem_field_registry import ACTIVE_WORKFLOW_SCHEMA
from turn_transaction import (
    execute_turn_transaction,
    is_empty_transaction,
    make_action_transaction,
    make_raw_update_transaction,
    validate_turn_intent,
)


def _intent(updates=None, queries=None, action=None):
    return {'version': 1, 'updates': updates or [], 'queries': queries or [], 'action': action}


def _upd(field, value, entity=None, units=None):
    return {'field': field, 'entity': entity, 'subject': None, 'value': value, 'units': units, 'basis': None}


def _qry(field, entity=None, raw_reference=None):
    return {'field': field, 'entity': entity, 'subject': None, 'raw_reference': raw_reference}


# ---------------------------------------------------------------------------
# validate_turn_intent
# ---------------------------------------------------------------------------

def test_all_updates_validate_before_mutation_single_valid_update():
    transaction = validate_turn_intent(_intent(updates=[_upd('pressure_Pa', 101325)]), ACTIVE_WORKFLOW_SCHEMA)
    assert transaction['update_kwargs'] == {'pressure_Pa': 101325}
    assert transaction['invalid_updates'] == []


def test_invalid_second_update_causes_zero_writes():
    transaction = validate_turn_intent(_intent(updates=[
        _upd('pressure_Pa', 101325),
        _upd('nonexistent_field', 5),
    ]), ACTIVE_WORKFLOW_SCHEMA)
    assert transaction['update_kwargs'] == {}
    assert len(transaction['invalid_updates']) == 1
    assert transaction['invalid_updates'][0]['reason'] == 'unknown_field'


def test_readonly_field_update_is_invalid():
    transaction = validate_turn_intent(_intent(updates=[_upd('total_flow', 100)]), ACTIVE_WORKFLOW_SCHEMA)
    assert transaction['update_kwargs'] == {}
    assert transaction['invalid_updates'][0]['reason'] == 'field_not_writable'


def test_keyed_update_without_entity_is_invalid():
    transaction = validate_turn_intent(_intent(updates=[_upd('component_flows', 50)]), ACTIVE_WORKFLOW_SCHEMA)
    assert transaction['update_kwargs'] == {}
    assert transaction['invalid_updates'][0]['reason'] == 'missing_entity'


def test_identical_duplicate_updates_collapse():
    transaction = validate_turn_intent(_intent(updates=[
        _upd('pressure_Pa', 101325), _upd('pressure_Pa', 101325),
    ]), ACTIVE_WORKFLOW_SCHEMA)
    assert transaction['update_kwargs'] == {'pressure_Pa': 101325}
    assert transaction['conflicts'] == []


def test_conflicting_duplicate_updates_reject():
    transaction = validate_turn_intent(_intent(updates=[
        _upd('pressure_Pa', 101325), _upd('pressure_Pa', 200000),
    ]), ACTIVE_WORKFLOW_SCHEMA)
    assert transaction['update_kwargs'] == {}
    assert len(transaction['conflicts']) == 1
    assert transaction['conflicts'][0]['field'] == 'pressure_Pa'


def test_keyed_updates_compile_into_one_write_argument():
    transaction = validate_turn_intent(_intent(updates=[
        _upd('component_flows', 50, entity='Ethanol', units='kmol/hr'),
        _upd('component_flows', 50, entity='Water', units='kmol/hr'),
    ]), ACTIVE_WORKFLOW_SCHEMA)
    assert transaction['update_kwargs'] == {
        'component_flows': {'Ethanol': 50.0, 'Water': 50.0},
        'component_flow_units': 'kmol/hr',
    }


def test_value_coercion_numeric_string_to_float():
    transaction = validate_turn_intent(_intent(updates=[_upd('xD', '0.95')]), ACTIVE_WORKFLOW_SCHEMA)
    assert transaction['update_kwargs'] == {'xD': 0.95}


def test_range_constraint_rejected():
    transaction = validate_turn_intent(_intent(updates=[_upd('xD', 1.5)]), ACTIVE_WORKFLOW_SCHEMA)
    assert transaction['update_kwargs'] == {}
    assert 'maximum' in transaction['invalid_updates'][0]['reason']


def test_queries_independent_of_invalid_updates():
    """An invalid update must not block an otherwise-valid query in the same
    turn (queries and the update set are validated independently)."""
    transaction = validate_turn_intent(_intent(
        updates=[_upd('nonexistent_field', 5)],
        queries=[_qry('pressure_Pa')],
    ), ACTIVE_WORKFLOW_SCHEMA)
    assert transaction['update_kwargs'] == {}
    assert transaction['queries'] == [_qry('pressure_Pa')]


def test_reset_action_folds_into_reset_first_not_a_post_write_action():
    transaction = validate_turn_intent(_intent(action={'name': 'reset_current_problem'}), ACTIVE_WORKFLOW_SCHEMA)
    assert transaction['reset_first'] is True
    assert transaction['action'] is None


def test_unknown_action_is_rejected_without_blocking_updates():
    transaction = validate_turn_intent(_intent(
        updates=[_upd('pressure_Pa', 101325)],
        action={'name': 'launch_the_rocket'},
    ), ACTIVE_WORKFLOW_SCHEMA)
    assert transaction['action'] is None
    assert transaction['action_error'] == {'error': 'unknown_action', 'name': 'launch_the_rocket'}
    assert transaction['update_kwargs'] == {'pressure_Pa': 101325}  # not blocked


def test_compatible_action_with_update():
    transaction = validate_turn_intent(_intent(
        updates=[_upd('feed_temperature_K', 355)],
        action={'name': 'calculate_current_step'},
    ), ACTIVE_WORKFLOW_SCHEMA)
    assert transaction['update_kwargs'] == {'feed_temperature_K': 355}
    assert transaction['action'] == {'name': 'calculate_current_step', 'arguments': {}}


def test_is_empty_transaction():
    assert is_empty_transaction(validate_turn_intent(_intent(), ACTIVE_WORKFLOW_SCHEMA)) is True
    assert is_empty_transaction(validate_turn_intent(_intent(updates=[_upd('pressure_Pa', 1)]), ACTIVE_WORKFLOW_SCHEMA)) is False


# ---------------------------------------------------------------------------
# execute_turn_transaction -- fake in-memory runtime, no live agent module.
# ---------------------------------------------------------------------------

class _FakeRuntime:
    """A minimal, self-contained stand-in for the agent module's own state,
    so `execute_turn_transaction` can be tested without any Ollama or
    BioSTEAM dependency."""

    def __init__(self):
        self.state = {'feed': {'component_names': []}}
        self.calculation = None
        self.reset_calls = 0
        self.update_calls = []
        self.action_calls = []

    def reset(self):
        self.reset_calls += 1
        self.state = {'feed': {'component_names': []}}
        self.calculation = None

    def update(self, **kwargs):
        self.update_calls.append(kwargs)
        self.state.update({k: v for k, v in kwargs.items() if k != 'feed'})
        if kwargs:
            self.calculation = None  # a real WRITE invalidates stale calculation results
        return {'feed': self.state.get('feed', {}), **{k: v for k, v in self.state.items() if k != 'feed'}}

    def get_state(self):
        return self.state

    def get_calculation(self):
        return self.calculation

    def run_action(self, name, arguments):
        self.action_calls.append((name, arguments))
        return {'action': name, 'ran': True}

    def as_dict(self):
        return {
            'reset': self.reset, 'update': self.update, 'get_state': self.get_state,
            'get_calculation': self.get_calculation, 'run_action': self.run_action,
        }


def test_execute_exactly_one_write_for_multi_update_transaction():
    runtime = _FakeRuntime()
    transaction = validate_turn_intent(_intent(updates=[
        _upd('pressure_Pa', 101325), _upd('feed_temperature_K', 355),
    ]), ACTIVE_WORKFLOW_SCHEMA)

    execute_turn_transaction(transaction, runtime.as_dict())

    assert len(runtime.update_calls) == 1
    assert runtime.update_calls[0] == {'pressure_Pa': 101325, 'feed_temperature_K': 355}


def test_reads_use_post_write_state_and_preserve_order():
    runtime = _FakeRuntime()
    transaction = validate_turn_intent(_intent(
        updates=[_upd('pressure_Pa', 101325)],
        queries=[_qry('pressure_Pa'), _qry('feed_temperature_K')],
    ), ACTIVE_WORKFLOW_SCHEMA)

    result = execute_turn_transaction(transaction, runtime.as_dict())

    assert [q['field'] for q in result['query_results']] == ['pressure_Pa', 'feed_temperature_K']
    assert result['query_results'][0]['value'] == 101325  # reflects the WRITE that just happened


def test_side_reads_do_not_mutate_state_or_calculation_progress():
    runtime = _FakeRuntime()
    runtime.calculation = {'some': 'stale-but-still-valid result'}
    transaction = validate_turn_intent(_intent(queries=[_qry('pressure_Pa')]), ACTIVE_WORKFLOW_SCHEMA)

    execute_turn_transaction(transaction, runtime.as_dict())

    assert runtime.reset_calls == 0
    assert runtime.update_calls == [{}]  # the unconditional no-op WRITE, not a real mutation
    assert runtime.calculation == {'some': 'stale-but-still-valid result'}  # untouched by a query-only turn


def test_write_invalidates_stale_calculation_result():
    runtime = _FakeRuntime()
    runtime.calculation = {'stale': True}
    transaction = validate_turn_intent(_intent(updates=[_upd('pressure_Pa', 200000)]), ACTIVE_WORKFLOW_SCHEMA)

    result = execute_turn_transaction(transaction, runtime.as_dict())

    assert result['snapshot']['calculation'] is None


def test_action_evaluates_readiness_post_write():
    runtime = _FakeRuntime()
    transaction = validate_turn_intent(_intent(
        updates=[_upd('feed_temperature_K', 355)],
        action={'name': 'calculate_current_step'},
    ), ACTIVE_WORKFLOW_SCHEMA)

    result = execute_turn_transaction(transaction, runtime.as_dict())

    assert runtime.update_calls == [{'feed_temperature_K': 355}]  # WRITE happened before the action
    assert runtime.action_calls == [('calculate_current_step', {})]
    assert result['action_result'] == {'action': 'calculate_current_step', 'ran': True}


def test_reset_then_replacement_policy():
    runtime = _FakeRuntime()
    runtime.state['leftover'] = 'from a previous problem'
    transaction = validate_turn_intent(_intent(
        updates=[_upd('pressure_Pa', 101325)],
        action={'name': 'reset_current_problem'},
    ), ACTIVE_WORKFLOW_SCHEMA)

    execute_turn_transaction(transaction, runtime.as_dict())

    assert runtime.reset_calls == 1
    # RESET ran, then the WRITE -- the leftover field is gone, the new one is present.
    assert 'leftover' not in runtime.state
    assert runtime.state['pressure_Pa'] == 101325


def test_incompatible_action_rejected_deterministically_via_agent_registry():
    """Using the REAL ACTIVE_WORKFLOW_SCHEMA (imported above, which binds
    the real ACTION_REGISTRY): an action name not in the registry is
    rejected at validation time, before execution ever sees it."""
    transaction = validate_turn_intent(_intent(action={'name': 'not_a_real_action'}), ACTIVE_WORKFLOW_SCHEMA)
    assert transaction['action'] is None
    assert transaction['action_error']['error'] == 'unknown_action'


# ---------------------------------------------------------------------------
# Fast-path transaction builders (Part 6) -- must produce the same
# TurnTransaction shape the model-driven path does.
# ---------------------------------------------------------------------------

def test_make_raw_update_transaction_shape():
    transaction = make_raw_update_transaction({'xD': 0.9, 'xB': 0.1})
    assert transaction['update_kwargs'] == {'xD': 0.9, 'xB': 0.1}
    assert is_empty_transaction(transaction) is False


def test_make_action_transaction_shape():
    transaction = make_action_transaction('read_calculation_status')
    assert transaction['action'] == {'name': 'read_calculation_status', 'arguments': {}}
    assert transaction['update_kwargs'] == {}
