"""
tools/binary-distillation-turn-diagnostics-plan.md Steps 8-9 -- diagnostic
data model, `ask()`/`_dispatch_transaction()` diagnostic threading, the
duplicate-rejection-sentence fix, and the exact reported-prompt regression.
Scripted (fake) Ollama responses only -- no running Ollama server required.

Run with:
    pytest tools/chopper/test_turn_diagnostics.py -v
"""
import json
import os

import pytest

import binary_distillation_workflow_agent as agent
import turn_diagnostics
from problem_field_registry import ACTIVE_WORKFLOW_SCHEMA
from turn_intent import propose_turn_intent
from turn_intent_test_fakes import FakeMessage, FakeResponse, ScriptedClient, final, intent_response, query, update
from turn_transaction import validate_turn_intent


@pytest.fixture(autouse=True)
def _reset_state():
    agent.reset_workflow_session()
    yield
    agent.reset_workflow_session()


def _base_messages():
    return [{'role': 'system', 'content': agent.SYSTEM_PROMPT}]


def _intent(updates=None, queries=None, action=None):
    return {'version': 1, 'updates': updates or [], 'queries': queries or [], 'action': action}


class _RecordingClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def chat(self, model, messages, tools=None, think=False, format=None, options=None):
        self.calls.append({'tools': tools, 'format': format})
        return self._responses.pop(0)


# ---------------------------------------------------------------------------
# 1/2 -- raw interpretation attempts (turn_intent.propose_turn_intent)
# ---------------------------------------------------------------------------

def test_successful_parse_retains_exact_raw_response():
    raw_payload = json.dumps({'version': 1, 'updates': [{'field': 'pressure_Pa', 'value': 101325}], 'queries': [], 'action': None})
    client = _RecordingClient([FakeResponse(FakeMessage(content=raw_payload))])

    result = propose_turn_intent(client, [{'role': 'user', 'content': 'pressure is 101325 Pa'}], 'fake-model')

    assert result['ok'] is True
    assert result['retry_used'] is False
    assert len(result['attempts']) == 1
    assert result['attempts'][0]['raw'] == raw_payload
    assert result['attempts'][0]['parse_result']['ok'] is True


def test_parsing_retry_retains_both_attempts_in_order():
    bad_raw = 'not valid json at all'
    good_raw = json.dumps({'version': 1, 'updates': [], 'queries': [{'field': 'xD'}], 'action': None})
    client = _RecordingClient([FakeResponse(FakeMessage(content=bad_raw)), FakeResponse(FakeMessage(content=good_raw))])

    result = propose_turn_intent(client, [{'role': 'user', 'content': 'what is xD?'}], 'fake-model')

    assert result['ok'] is True
    assert result['retry_used'] is True
    assert len(result['attempts']) == 2
    assert result['attempts'][0]['raw'] == bad_raw
    assert result['attempts'][0]['parse_result']['ok'] is False
    assert result['attempts'][1]['raw'] == good_raw
    assert result['attempts'][1]['parse_result']['ok'] is True
    # No recursive structure -- neither attempt's parse_result carries the
    # enclosing attempts list back inside it.
    assert 'attempts' not in result['attempts'][0]['parse_result']
    assert 'attempts' not in result['attempts'][1]['parse_result']


def test_both_attempts_retained_on_a_fully_failed_parse():
    client = _RecordingClient([FakeResponse(FakeMessage(content='nope')), FakeResponse(FakeMessage(content='still nope'))])

    result = propose_turn_intent(client, [{'role': 'user', 'content': 'asdkjasdj'}], 'fake-model')

    assert result['ok'] is False
    assert result['retry_used'] is True
    assert len(result['attempts']) == 2
    assert result['attempts'][0]['raw'] == 'nope'
    assert result['attempts'][1]['raw'] == 'still nope'


# ---------------------------------------------------------------------------
# 3/4/5 -- validator diagnostics (turn_transaction.validate_turn_intent)
# ---------------------------------------------------------------------------

def test_missing_entity_invalid_updates_include_index_and_safe_field_metadata():
    transaction = validate_turn_intent(_intent(updates=[
        update('component_flows', 50, units='kmol/hr'),
        update('component_flows', 50, units='kmol/hr'),
    ]), ACTIVE_WORKFLOW_SCHEMA)

    invalid = transaction['invalid_updates']
    assert len(invalid) == 2
    assert [i['update_index'] for i in invalid] == [0, 1]
    for i in invalid:
        assert i['reason'] == 'missing_entity'
        assert i['effect'] == 'entire_update_batch_rejected'
        assert i['field_metadata'] == {
            'keyed': True, 'entity_type': 'component',
            'value_type': 'number', 'write_binding': 'component_flows',
        }


def test_unknown_field_invalid_update_has_no_field_metadata():
    transaction = validate_turn_intent(_intent(updates=[update('not_a_real_field', 5)]), ACTIVE_WORKFLOW_SCHEMA)
    assert transaction['invalid_updates'][0]['field_metadata'] is None


def test_invalid_update_diagnostics_are_json_serializable_and_leak_no_callables():
    transaction = validate_turn_intent(_intent(updates=[
        update('component_flows', 50, units='kmol/hr'),
        update('pressure_Pa', 'not-a-number'),
    ]), ACTIVE_WORKFLOW_SCHEMA)

    # Must round-trip through json.dumps with no TypeError -- proves no
    # callable registry accessor (read_accessor/units_accessor/etc.) leaked.
    serialized = json.dumps(transaction['invalid_updates'])
    reloaded = json.loads(serialized)
    assert reloaded == transaction['invalid_updates']
    for invalid in transaction['invalid_updates']:
        meta = invalid['field_metadata']
        if meta is not None:
            for value in meta.values():
                assert not callable(value)


# ---------------------------------------------------------------------------
# 6/7/8/9/10/14 -- diagnostic threading through ask()/_dispatch_transaction
# ---------------------------------------------------------------------------

def test_fully_rejected_atomic_batch_reports_write_performed_false():
    """The reported-failure shape: two component_flows updates with no
    entity. The atomic batch is rejected, so `write_performed` is False and
    `write_kwargs` is empty, even though the underlying WRITE function was
    still called with an empty no-op kwargs dict."""
    client = ScriptedClient([
        intent_response(updates=[
            update('component_flows', 50, units='kmol/hr'),
            update('component_flows', 50, units='kmol/hr'),
        ]),
    ])
    diagnostic = turn_diagnostics.new_turn_record('t1', None)
    messages = _base_messages() + [{'role': 'user', 'content': (
        'Separate water and ethanol at 355 K and 101325 Pa pressure. '
        'The feed composition is 50 kmol/hr ethanol and 50 kmol/hr water'
    )}]

    agent.ask(client, messages, diagnostic=diagnostic)

    assert diagnostic['execution']['write_performed'] is False
    assert diagnostic['execution']['write_kwargs'] == {}
    assert len(diagnostic['validation']['invalid_updates']) == 2  # both entries retained
    assert agent.get_binary_distillation_problem()['feed']['component_flows'] == {}  # state unchanged


def test_valid_batch_reports_exact_dispatched_write_kwargs():
    client = ScriptedClient([
        intent_response(updates=[
            update('component_flows', 50, entity='Ethanol', units='kmol/hr'),
            update('component_flows', 50, entity='Water', units='kmol/hr'),
            update('feed_temperature_K', 355),
            update('pressure_Pa', 101325),
        ]),
        final('Got it.'),
    ])
    diagnostic = turn_diagnostics.new_turn_record('t2', None)
    messages = _base_messages() + [{'role': 'user', 'content': 'separate ethanol and water, 50/50 kmol/hr, 355 K, 101325 Pa'}]

    agent.ask(client, messages, diagnostic=diagnostic)

    assert diagnostic['execution']['write_performed'] is True
    assert diagnostic['execution']['write_kwargs'] == {
        'component_flows': {'Ethanol': 50.0, 'Water': 50.0},
        'component_flow_units': 'kmol/hr',
        'feed_temperature_K': 355,
        'pressure_Pa': 101325,
    }
    assert 'update_binary_distillation_problem' in diagnostic['execution']['operations']


def test_state_diff_includes_changed_and_excludes_unchanged_fields():
    client = ScriptedClient([intent_response(updates=[update('pressure_Pa', 101325)]), final('Got it.')])
    diagnostic = turn_diagnostics.new_turn_record('t3', None)
    messages = _base_messages() + [{'role': 'user', 'content': 'pressure is 101325 Pa'}]

    agent.ask(client, messages, diagnostic=diagnostic)

    changed_field_names = {c['field'] for c in diagnostic['state']['changed_fields']}
    assert 'pressure_Pa' in changed_field_names
    pressure_change = next(c for c in diagnostic['state']['changed_fields'] if c['field'] == 'pressure_Pa')
    assert pressure_change['before'] is None
    assert pressure_change['after'] == 101325
    # A field that never changes (still empty on both sides) must not appear.
    assert not any(c['field'].startswith('feed.component_names') for c in diagnostic['state']['changed_fields'])


def test_fast_path_turn_records_fast_path_route():
    client = ScriptedClient([final('Nothing has been calculated yet.')])
    diagnostic = turn_diagnostics.new_turn_record('t4', None)
    messages = _base_messages() + [{'role': 'user', 'content': 'what next?'}]

    agent.ask(client, messages, diagnostic=diagnostic)

    assert diagnostic['route'] == 'fast_path'
    assert len(client.calls) == 1  # never reached interpretation


def test_model_interpreted_turn_records_model_interpretation_route():
    client = ScriptedClient([
        intent_response(updates=[{'field': 'component_names', 'value': ['Methanol', 'Water']}]),
        final('Got it.'),
    ])
    diagnostic = turn_diagnostics.new_turn_record('t5', None)
    messages = _base_messages() + [{'role': 'user', 'content': 'separate methanol and water'}]

    agent.ask(client, messages, diagnostic=diagnostic)

    assert diagnostic['route'] == 'model_interpretation'
    assert diagnostic['interpretation']['model'] == agent.MODEL
    assert len(diagnostic['interpretation']['attempts']) == 1


# ---------------------------------------------------------------------------
# 11 -- debug mode must not change final state or final response
# ---------------------------------------------------------------------------

def test_debug_mode_does_not_change_final_state_or_response():
    def _make_client():
        return ScriptedClient([
            intent_response(updates=[{'field': 'component_names', 'value': ['Ethanol', 'Water']}]),
            final('Recorded ethanol and water.'),
        ])

    messages_a = _base_messages() + [{'role': 'user', 'content': 'separate ethanol and water'}]
    reply_a = agent.ask(_make_client(), messages_a, diagnostic=None)
    state_a = agent.get_binary_distillation_problem()

    agent.reset_workflow_session()

    diagnostic = turn_diagnostics.new_turn_record('t6', None)
    messages_b = _base_messages() + [{'role': 'user', 'content': 'separate ethanol and water'}]
    reply_b = agent.ask(_make_client(), messages_b, diagnostic=diagnostic)
    state_b = agent.get_binary_distillation_problem()

    assert reply_a == reply_b
    assert state_a['feed']['component_names'] == state_b['feed']['component_names']


# ---------------------------------------------------------------------------
# 12 -- JSONL output
# ---------------------------------------------------------------------------

def test_jsonl_output_has_exactly_one_valid_json_object_per_turn(tmp_path):
    path = str(tmp_path / 'diag.jsonl')
    record1 = turn_diagnostics.new_turn_record('a', 'hello')
    record1['final_response'] = 'hi'
    record2 = turn_diagnostics.new_turn_record('b', 'bye')
    record2['final_response'] = 'goodbye'

    turn_diagnostics.append_jsonl(record1, path)
    turn_diagnostics.append_jsonl(record2, path)

    with open(path, encoding='utf-8') as f:
        lines = [line for line in f.read().splitlines() if line]
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]['turn_id'] == 'a'
    assert parsed[1]['turn_id'] == 'b'


def test_jsonl_write_failure_raises_clear_error_without_touching_state(tmp_path):
    agent.update_binary_distillation_problem(pressure_Pa=101325)
    state_before = agent.get_binary_distillation_problem()

    bad_path = str(tmp_path / 'does_not_exist' / 'diag.jsonl')
    record = turn_diagnostics.new_turn_record('x', 'hi')

    with pytest.raises(OSError):
        turn_diagnostics.append_jsonl(record, bad_path)

    assert agent.get_binary_distillation_problem() == state_before


# ---------------------------------------------------------------------------
# 13/14/15 -- the actual reported-failure fix, end to end.
# ---------------------------------------------------------------------------

def test_two_identical_missing_entity_failures_produce_one_user_facing_sentence():
    client = ScriptedClient([
        intent_response(updates=[
            update('component_flows', 50, units='kmol/hr'),
            update('component_flows', 50, units='kmol/hr'),
            update('feed_temperature_K', 355),
            update('pressure_Pa', 101325),
        ]),
    ])
    diagnostic = turn_diagnostics.new_turn_record('t7', None)
    messages = _base_messages() + [{'role': 'user', 'content': (
        'Separate water and ethanol at 355 K and 101325 Pa pressure. '
        'The feed composition is 50 kmol/hr ethanol and 50 kmol/hr water'
    )}]

    reply = agent.ask(client, messages, diagnostic=diagnostic)

    # Old, reported behavior duplicated this sentence verbatim.
    assert reply.count('missing_entity') == 0  # never expose the bare internal token
    assert reply.count('I failed to associate') == 1
    # Both rejected updates are still fully retained for diagnosis.
    assert len(diagnostic['validation']['invalid_updates']) == 2


def test_reported_prompt_raw_qwen_response_visible_in_diagnostic_record():
    raw_payload = json.dumps({
        'version': 1,
        'updates': [
            {'field': 'component_flows', 'entity': None, 'value': 50, 'units': 'kmol/hr'},
            {'field': 'component_flows', 'entity': None, 'value': 50, 'units': 'kmol/hr'},
            {'field': 'feed_temperature_K', 'value': 355},
            {'field': 'pressure_Pa', 'value': 101325},
        ],
        'queries': [], 'action': None,
    })
    client = ScriptedClient([FakeResponse(FakeMessage(content=raw_payload))])
    diagnostic = turn_diagnostics.new_turn_record('t8', None)
    messages = _base_messages() + [{'role': 'user', 'content': (
        'Separate water and ethanol at 355 K and 101325 Pa pressure. '
        'The feed composition is 50 kmol/hr ethanol and 50 kmol/hr water'
    )}]

    agent.ask(client, messages, diagnostic=diagnostic)

    assert diagnostic['interpretation']['attempts'][0]['raw'] == raw_payload
    # The whole record must still be JSON-serializable end to end.
    json.dumps(turn_diagnostics.to_jsonable(diagnostic))


def test_reported_prompt_valid_proposal_writes_exact_expected_state():
    """The exact reported prompt, but with Qwen correctly filling in
    entities -- tools/binary-distillation-turn-diagnostics-plan.md Step 9,
    "Valid Qwen proposal" -- must compile into exactly the documented WRITE."""
    client = ScriptedClient([
        intent_response(updates=[
            update('component_flows', 50, entity='Ethanol', units='kmol/hr'),
            update('component_flows', 50, entity='Water', units='kmol/hr'),
            update('feed_temperature_K', 355),
            update('pressure_Pa', 101325),
        ]),
        final('Recorded.'),
    ])
    diagnostic = turn_diagnostics.new_turn_record('t9', None)
    messages = _base_messages() + [{'role': 'user', 'content': (
        'Separate water and ethanol at 355 K and 101325 Pa pressure. '
        'The feed composition is 50 kmol/hr ethanol and 50 kmol/hr water'
    )}]

    agent.ask(client, messages, diagnostic=diagnostic)

    assert diagnostic['execution']['write_kwargs'] == {
        'component_flows': {'Ethanol': 50.0, 'Water': 50.0},
        'component_flow_units': 'kmol/hr',
        'feed_temperature_K': 355,
        'pressure_Pa': 101325,
    }
    state = agent.get_binary_distillation_problem()
    assert state['feed']['component_flows'] == {'Ethanol': 50.0, 'Water': 50.0}
    # feed_screening is not yet ready -- reflux_condition was never part of
    # this scripted proposal (tools/binary-distillation-issues-9-1-2026-
    # eighth.md Step 2 folded it into feed screening); the WRITE itself is
    # this test's actual subject, so nothing else about the scripted intent
    # changes.
    assert state['feed_screening']['ready'] is False
    assert 'reflux_condition' in state['feed_screening']['missing_inputs']


def test_diagnostic_content_never_appended_to_conversation_history():
    client = ScriptedClient([
        intent_response(updates=[
            update('component_flows', 50, units='kmol/hr'),
            update('component_flows', 50, units='kmol/hr'),
        ]),
    ])
    diagnostic = turn_diagnostics.new_turn_record('t10', None)
    messages = _base_messages() + [{'role': 'user', 'content': 'the feed composition is 50 kmol/hr ethanol and 50 kmol/hr water'}]

    agent.ask(client, messages, diagnostic=diagnostic)

    for m in messages:
        assert isinstance(m, dict)
        assert 'turn_id' not in m
        content = m.get('content')
        if isinstance(content, str):
            assert '[TURN]' not in content
            assert 'update_index' not in content
