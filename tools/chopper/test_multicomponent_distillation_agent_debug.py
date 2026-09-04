"""
Tests for the optional turn-by-turn diagnostics added to
`multicomponent_distillation_agent.py` -- no running Ollama server
required. See tools/multicomponent-distillation-debugging-plan.md
"Required Tests" and "Manual Acceptance Check".

Reuses the `ScriptedClient`/`FakeResponse`/`_proposal_response` fakes from
test_multicomponent_distillation_agent.py rather than redefining them.
"""
import json

import pytest

import multicomponent_distillation_agent as agent
import multicomponent_feed_tool as tool
from test_multicomponent_distillation_agent import (
    FakeResponse,
    ScriptedClient,
    _proposal_response,
)


@pytest.fixture(autouse=True)
def _reset():
    tool.reset_multicomponent_feed_session()
    yield
    tool.reset_multicomponent_feed_session()


def _debug_lines(capsys):
    return capsys.readouterr().err.strip('\n')


def _debug_json_records(capsys):
    err = capsys.readouterr().err.strip('\n')
    return [json.loads(line) for line in err.splitlines() if line.strip()]


# --- 1. Debugging disabled: no diagnostic output, no behavior change -------

def test_debug_disabled_by_default_produces_no_stderr_output(capsys):
    client = ScriptedClient([
        _proposal_response(component_names=['Water', 'Ethanol', 'Methanol']),
    ])
    messages = [{'role': 'system', 'content': agent.SYSTEM_PROMPT}]

    reply = agent.process_turn(client, messages, 'water, ethanol, methanol')

    captured = capsys.readouterr()
    assert captured.err == ''
    assert isinstance(reply, str) and reply


def test_debug_disabled_gives_identical_reply_to_debug_enabled():
    tool.reset_multicomponent_feed_session()
    client_a = ScriptedClient([
        _proposal_response(component_names=['Water', 'Ethanol', 'Methanol']),
    ])
    messages_a = [{'role': 'system', 'content': agent.SYSTEM_PROMPT}]
    reply_a = agent.process_turn(client_a, messages_a, 'water, ethanol, methanol')

    tool.reset_multicomponent_feed_session()
    client_b = ScriptedClient([
        _proposal_response(component_names=['Water', 'Ethanol', 'Methanol']),
    ])
    messages_b = [{'role': 'system', 'content': agent.SYSTEM_PROMPT}]
    reply_b = agent.process_turn(client_b, messages_b, 'water, ethanol, methanol', debug_mode='json')

    assert reply_a == reply_b


# --- 2. --debug writes a human-readable record to stderr -------------------

def test_debug_human_mode_writes_trace_to_stderr_reply_unaffected(capsys):
    client = ScriptedClient([
        _proposal_response(component_names=['Water', 'Ethanol', 'Methanol']),
    ])
    messages = [{'role': 'system', 'content': agent.SYSTEM_PROMPT}]

    reply = agent.process_turn(client, messages, 'water, ethanol, methanol', debug_mode='human')

    err = _debug_lines(capsys)
    assert '[debug turn 1]' in err
    assert '[exit path] pending_request' in err
    assert f'[reply] {reply}' in err
    assert isinstance(reply, str) and 'feed quantity' in reply.lower()


# --- 3. --debug-json emits valid JSON with required top-level fields -------

def test_debug_json_mode_emits_one_valid_json_object_with_required_fields(capsys):
    client = ScriptedClient([
        _proposal_response(component_names=['Water', 'Ethanol', 'Methanol']),
    ])
    messages = [{'role': 'system', 'content': agent.SYSTEM_PROMPT}]

    agent.process_turn(client, messages, 'water, ethanol, methanol', debug_mode='json')

    records = _debug_json_records(capsys)
    assert len(records) == 1
    record = records[0]
    for key in (
        'turn', 'user_message', 'pending_before', 'state_before', 'model',
        'prechecks', 'grounding', 'function_calls', 'state_after',
        'state_diff', 'reply', 'exit_path',
    ):
        assert key in record


# --- 4. CLI flags are not folded into the one-shot prompt -------------------

def test_cli_debug_flags_are_not_included_in_one_shot_prompt():
    args = agent._build_arg_parser().parse_args(['--debug', 'water', 'ethanol', 'methanol'])
    assert args.debug is True
    assert args.debug_json is False
    assert args.prompt == ['water', 'ethanol', 'methanol']


def test_cli_debug_and_debug_json_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        agent._build_arg_parser().parse_args(['--debug', '--debug-json', 'hi'])


def test_cli_no_flags_leaves_prompt_untouched():
    args = agent._build_arg_parser().parse_args(['hello', 'world'])
    assert args.debug is False
    assert args.debug_json is False
    assert args.prompt == ['hello', 'world']


# --- 5. State snapshots are deep copies -------------------------------------

def test_get_multicomponent_feed_state_returns_a_deep_copy():
    tool.update_multicomponent_feed(component_names=['Water', 'Ethanol', 'Methanol'])
    snapshot = tool.get_multicomponent_feed_state()
    snapshot['component_names'].append('Propanol')
    snapshot['component_flows']['Water'] = 999

    assert tool._feed_state['component_names'] == ['Water', 'Ethanol', 'Methanol']
    assert 'Water' not in tool._feed_state['component_flows']


def test_get_pending_request_does_not_mutate_state():
    before = tool.get_multicomponent_feed_state()
    tool.get_pending_request()
    after = tool.get_multicomponent_feed_state()
    assert before == after


# --- 6 & 7. Raw response / parsed proposal / accepted / rejected fields, and
# the exact fabricated-335K-pressure example -----------------------------

def test_fabricated_pressure_shown_under_proposal_and_rejection_never_accepted(capsys):
    client = ScriptedClient([
        _proposal_response(
            component_names=['Ethanol', 'Methanol', 'Water'],
            feed_temperature=335, feed_temperature_units='K',
            pressure=101325, pressure_units='Pa',
            component_flows={'Ethanol': 30, 'Methanol': 30, 'Water': 40},
        ),
    ])
    messages = [{'role': 'system', 'content': agent.SYSTEM_PROMPT}]

    agent.process_turn(
        client, messages, 'separate Ethanol, Methanol, and Water at 335 K', debug_mode='json',
    )

    record = _debug_json_records(capsys)[0]
    assert record['model']['parsed_proposal']['pressure'] == 101325
    assert 'pressure' in record['grounding']['rejected']
    assert 'pressure' not in record['grounding']['accepted']
    assert record['model']['raw_responses']
    assert record['grounding']['accepted']['feed_temperature'] == 335


# --- 8. Partial-flow / component-list replacement is recorded, not fixed ---

def test_component_identity_replacement_is_recorded_in_state_diff(capsys):
    messages = [{'role': 'system', 'content': agent.SYSTEM_PROMPT}]

    client_1 = ScriptedClient([
        _proposal_response(component_names=['Methanol', 'Ethanol', 'Water']),
    ])
    agent.process_turn(client_1, messages, 'separate methanol, ethanol, water', debug_mode='json')
    capsys.readouterr()  # discard turn 1's record

    client_2 = ScriptedClient([
        _proposal_response(component_flows={'Methanol': 30}, component_flow_units='kg/hr'),
    ])
    agent.process_turn(client_2, messages, 'methanol = 30 kg/hr', debug_mode='json', turn_number=2)

    record = _debug_json_records(capsys)[0]
    assert record['function_calls'][0]['name'] == 'update_multicomponent_feed'
    assert record['function_calls'][0]['arguments'] == {
        'component_flows': {'Methanol': 30}, 'component_flow_units': 'kg/hr',
    }
    assert record['state_diff']['changed']['component_flow_units']['after'] == 'kg/hr'
    assert record['state_diff']['added'].get('component_flows.Methanol') == 30 \
        or record['state_diff']['changed'].get('component_flows.Methanol', {}).get('after') == 30


# --- 9. Mixed-unit early return still emits exactly one complete record ----

def test_mixed_flow_units_early_return_emits_exactly_one_record(capsys):
    client = ScriptedClient([
        _proposal_response(
            component_names=['Water', 'Ethanol', 'Methanol'],
            component_flows={'Water': 30, 'Ethanol': 40, 'Methanol': 30},
            component_flow_units='kg/hr',
        ),
    ])
    messages = [{'role': 'system', 'content': agent.SYSTEM_PROMPT}]
    tool.update_multicomponent_feed(component_names=['Water', 'Ethanol', 'Methanol'])

    agent.process_turn(
        client, messages,
        'Water is 30 kg/hr, Ethanol is 40 mol/hr, Methanol is 30 kmol/hr',
        debug_mode='json',
    )

    records = _debug_json_records(capsys)
    assert len(records) == 1
    assert records[0]['exit_path'] == 'mixed_flow_units'
    assert records[0]['function_calls'] == []


# --- 10. Reset path records the reset call and state removal ---------------

def test_reset_path_records_function_call_and_state_removal(capsys):
    tool.update_multicomponent_feed(component_names=['Water', 'Ethanol', 'Methanol'])
    client = ScriptedClient([_proposal_response(reset=True)])
    messages = [{'role': 'system', 'content': agent.SYSTEM_PROMPT}]

    agent.process_turn(client, messages, "let's start over with a different feed", debug_mode='json')

    record = _debug_json_records(capsys)[0]
    assert record['exit_path'] == 'reset'
    assert record['function_calls'][0]['name'] == 'reset_multicomponent_feed_session'
    assert record['state_diff']['changed']['component_names'] == {
        'before': ['Water', 'Ethanol', 'Methanol'], 'after': [],
    }


# --- 11. Malformed-output retry records both raw responses and call_count -

def test_malformed_output_retry_records_both_raw_responses(capsys):
    client = ScriptedClient([
        FakeResponse('not json'),
        FakeResponse('still not json'),
    ])
    messages = [{'role': 'system', 'content': agent.SYSTEM_PROMPT}]

    agent.process_turn(client, messages, 'water, ethanol, methanol', debug_mode='json')

    record = _debug_json_records(capsys)[0]
    assert record['exit_path'] == 'model_parse_failure'
    assert record['model']['call_count'] == 2
    assert record['model']['retry_used'] is True
    assert record['model']['parse_succeeded'] is False
    assert record['model']['raw_responses'] == ['not json', 'still not json']


# --- 12. Completed phase calculation records a restricted, serializable result

def test_completed_calculation_result_is_restricted_and_json_serializable(capsys):
    messages = [{'role': 'system', 'content': agent.SYSTEM_PROMPT}]
    turns = [
        ('Water, ethanol, methanol.', _proposal_response(
            component_names=['Water', 'Ethanol', 'Methanol'])),
        ('30, 40, 30 kmol/hr.', _proposal_response(
            component_flows={'Water': 30, 'Ethanol': 40, 'Methanol': 30},
            component_flow_units='kmol/hr')),
        ('1 atm.', _proposal_response(pressure=1, pressure_units='atm')),
        ('350 K.', _proposal_response(feed_temperature=350, feed_temperature_units='K')),
    ]
    for i, (user_text, response) in enumerate(turns, start=1):
        client = ScriptedClient([response])
        agent.process_turn(client, messages, user_text, debug_mode='json', turn_number=i)

    records = _debug_json_records(capsys)
    final = records[-1]
    assert final['exit_path'] == 'complete_result'
    result = final['function_calls'][-1]['result']
    assert set(result.keys()) <= {'complete', 'valid', 'phase', 'vapor_fraction', 'liquid_fraction', 'message'}
    json.dumps(result)  # no BioSTEAM object leaked through


# --- 13. Rendering never touches Ollama, BioSTEAM, or a state-changing call

def test_rendering_a_crafted_record_touches_no_live_dependency():
    import multicomponent_diagnostics as diag
    record = diag.new_turn_record(1, 'hi')
    record['state_before'] = {'component_names': ['A', 'B', 'C']}
    record['state_after'] = {'component_names': ['A', 'B', 'C']}
    record['state_diff'] = diag.compute_state_diff(record['state_before'], record['state_after'])
    record['reply'] = 'ok'
    record['exit_path'] = 'pending_request'

    text = diag.render_human_readable(record)
    payload = diag.render_json(record)
    assert isinstance(text, str) and isinstance(payload, str)
    json.loads(payload)
