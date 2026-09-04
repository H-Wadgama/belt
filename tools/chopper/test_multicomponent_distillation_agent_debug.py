"""
Tests for the turn-by-turn diagnostics in
`multicomponent_distillation_agent.py` -- no running Ollama server
required. See tools/multicomponent-distillation-dialogue-robustness-plan.md
Section 12.

Reuses the `ScriptedClient`/`FakeResponse`/`_resp` fakes from
test_multicomponent_distillation_agent.py rather than redefining them.
"""
import json

import pytest

import multicomponent_dialogue as dlg
import multicomponent_distillation_agent as agent
from test_multicomponent_distillation_agent import FakeResponse, ScriptedClient, _resp


def _debug_lines(capsys):
    return capsys.readouterr().err.strip('\n')


def _debug_json_records(capsys):
    err = capsys.readouterr().err.strip('\n')
    return [json.loads(line) for line in err.splitlines() if line.strip()]


# --- 1. Debugging disabled: no diagnostic output, no behavior change -------

def test_debug_disabled_by_default_produces_no_stderr_output(capsys):
    session = dlg.create_session()
    client = ScriptedClient([_resp(component_names=['Water', 'Ethanol', 'Methanol'])])

    reply = agent.process_turn(client, session, 'water, ethanol, methanol')

    captured = capsys.readouterr()
    assert captured.err == ''
    assert isinstance(reply, str) and reply


def test_debug_disabled_gives_identical_reply_to_debug_enabled():
    session_a = dlg.create_session()
    client_a = ScriptedClient([_resp(component_names=['Water', 'Ethanol', 'Methanol'])])
    reply_a = agent.process_turn(client_a, session_a, 'water, ethanol, methanol')

    session_b = dlg.create_session()
    client_b = ScriptedClient([_resp(component_names=['Water', 'Ethanol', 'Methanol'])])
    reply_b = agent.process_turn(client_b, session_b, 'water, ethanol, methanol', debug_mode='json')

    assert reply_a == reply_b


# --- 2. --debug writes a human-readable record to stderr -------------------

def test_debug_human_mode_writes_trace_to_stderr_reply_unaffected(capsys):
    session = dlg.create_session()
    client = ScriptedClient([_resp(component_names=['Water', 'Ethanol', 'Methanol'])])

    reply = agent.process_turn(client, session, 'water, ethanol, methanol', debug_mode='human')

    err = _debug_lines(capsys)
    assert '[debug turn 1]' in err
    assert '[exit path] pending_request' in err
    assert f'[reply] {reply}' in err
    assert isinstance(reply, str) and 'feed quantity' in reply.lower()


# --- 3. --debug-json emits valid JSON with required top-level fields -------

def test_debug_json_mode_emits_one_valid_json_object_with_required_fields(capsys):
    session = dlg.create_session()
    client = ScriptedClient([_resp(component_names=['Water', 'Ethanol', 'Methanol'])])

    agent.process_turn(client, session, 'water, ethanol, methanol', debug_mode='json')

    records = _debug_json_records(capsys)
    assert len(records) == 1
    record = records[0]
    for key in (
        'turn', 'user_message', 'intent', 'target_field', 'active_request_before',
        'active_request_after', 'pending_before', 'state_before', 'model',
        'prechecks', 'evidence', 'binding_decision', 'grounding', 'candidate_state',
        'accepted_groups', 'rejected_groups', 'committed_state', 'rollback',
        'query_result', 'function_calls', 'state_after', 'state_diff', 'reply', 'exit_path',
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


# --- 5. intent/target_field and grounded/rejected shown -----------------------

def test_fabricated_pressure_shown_under_proposal_and_rejection_never_accepted(capsys):
    session = dlg.create_session()
    client = ScriptedClient([_resp(
        component_names=['Ethanol', 'Methanol', 'Water'],
        feed_temperature=335, feed_temperature_units='K',
        pressure=101325, pressure_units='Pa',
        component_flows={'Ethanol': 30, 'Methanol': 30, 'Water': 40},
    )])

    agent.process_turn(
        client, session, 'separate Ethanol, Methanol, and Water at 335 K', debug_mode='json',
    )

    record = _debug_json_records(capsys)[0]
    assert record['model']['parsed_proposal']['pressure'] == 101325
    assert 'pressure' in record['grounding']['rejected']
    assert 'pressure' not in record['grounding']['accepted']
    assert record['model']['raw_responses']
    assert record['grounding']['accepted']['feed_temperature'] == 335


# --- 6. Component-identity protection is recorded as a clarification -------

def test_flow_only_statement_records_a_clarification_binding_decision(capsys):
    session = dlg.create_session()
    client_1 = ScriptedClient([_resp(component_names=['Methanol', 'Ethanol', 'Water'])])
    agent.process_turn(client_1, session, 'separate methanol, ethanol, water', debug_mode='json')
    capsys.readouterr()  # discard turn 1's record

    # Model hallucinates a full component_names replacement (not just a
    # flow statement) -- this must be recorded as a clarification, not
    # silently committed.
    client_2 = ScriptedClient([_resp(component_names=['Methanol'])])
    agent.process_turn(client_2, session, 'methanol = 30 kg/hr', debug_mode='json')

    record = _debug_json_records(capsys)[0]
    assert record['exit_path'] == 'clarification'
    assert record['function_calls'] == []
    assert session['feed_state']['component_names'] == ['Methanol', 'Ethanol', 'Water']


def test_component_flow_update_is_recorded_in_state_diff(capsys):
    session = dlg.create_session()
    client_1 = ScriptedClient([_resp(component_names=['Methanol', 'Ethanol', 'Water'])])
    agent.process_turn(client_1, session, 'separate methanol, ethanol, water', debug_mode='json')
    capsys.readouterr()

    client_2 = ScriptedClient([_resp(component_flows={'Methanol': 30}, component_flow_units='kg/hr')])
    agent.process_turn(client_2, session, 'methanol = 30 kg/hr', debug_mode='json')

    record = _debug_json_records(capsys)[0]
    assert record['function_calls'][0]['name'] == 'advance_feed_state'
    assert record['function_calls'][0]['arguments']['component_flows'] == {'Methanol': 30}
    diff = record['state_diff']
    flat = {**diff.get('added', {}), **{k: v.get('after') for k, v in diff.get('changed', {}).items()}}
    assert flat.get('component_flows.Methanol.value') == 30
    assert flat.get('component_flows.Methanol.unit') == 'kg/hr'


# --- 7. Mixed-unit early return still emits exactly one complete record ----

def test_mixed_flow_units_early_return_emits_exactly_one_record(capsys):
    session = dlg.create_session()
    client_1 = ScriptedClient([_resp(component_names=['Water', 'Ethanol', 'Methanol'])])
    agent.process_turn(client_1, session, 'separate water ethanol methanol')

    client = ScriptedClient([_resp(
        component_flows={'Water': 30, 'Ethanol': 40, 'Methanol': 30},
        component_flow_units='kg/hr',
    )])

    agent.process_turn(
        client, session,
        'Water is 30 kg/hr, Ethanol is 40 mol/hr, Methanol is 30 kmol/hr',
        debug_mode='json',
    )

    records = _debug_json_records(capsys)
    assert len(records) == 1
    assert records[0]['exit_path'] == 'mixed_flow_units'
    assert records[0]['function_calls'] == []


# --- 8. Reset path records the reset call and state removal ---------------

def test_reset_path_records_function_call_and_state_removal(capsys):
    session = dlg.create_session()
    client_0 = ScriptedClient([_resp(component_names=['Water', 'Ethanol', 'Methanol'])])
    agent.process_turn(client_0, session, 'separate water ethanol methanol')
    capsys.readouterr()

    client = ScriptedClient([_resp(intent='reset')])
    agent.process_turn(client, session, "let's start over with a different feed", debug_mode='json')

    record = _debug_json_records(capsys)[0]
    assert record['exit_path'] == 'reset'
    assert record['function_calls'][0]['name'] == 'reset_multicomponent_feed_session'
    assert record['state_diff']['changed']['component_names'] == {
        'before': ['Water', 'Ethanol', 'Methanol'], 'after': [],
    }


# --- 9. Malformed-output retry records both raw responses and call_count ---

def test_malformed_output_retry_records_both_raw_responses(capsys):
    session = dlg.create_session()
    client = ScriptedClient([FakeResponse('not json'), FakeResponse('still not json')])

    agent.process_turn(client, session, 'water, ethanol, methanol', debug_mode='json')

    record = _debug_json_records(capsys)[0]
    assert record['exit_path'] == 'model_parse_failure'
    assert record['model']['call_count'] == 2
    assert record['model']['retry_used'] is True
    assert record['model']['parse_succeeded'] is False
    assert record['model']['raw_responses'] == ['not json', 'still not json']


# --- 10. Completed phase calculation records a JSON-serializable result ----

def test_completed_calculation_result_is_json_serializable_and_reports_phase(capsys):
    session = dlg.create_session()
    turns = [
        ('Water, ethanol, methanol.', _resp(component_names=['Water', 'Ethanol', 'Methanol'])),
        ('30, 40, 30 kmol/hr.', _resp(
            component_flows={'Water': 30, 'Ethanol': 40, 'Methanol': 30},
            component_flow_units='kmol/hr')),
        ('1 atm.', _resp(pressure=1, pressure_units='atm')),
        ('350 K.', _resp(feed_temperature=350, feed_temperature_units='K')),
    ]
    for user_text, response in turns:
        client = ScriptedClient([response])
        agent.process_turn(client, session, user_text, debug_mode='json')

    records = _debug_json_records(capsys)
    final = records[-1]
    assert final['exit_path'] == 'complete_result'
    result = final['function_calls'][-1]['result']
    assert result['complete'] is True
    assert result['phase'] in {'liquid', 'vapor', 'vapor_liquid'}
    json.dumps(result)  # no BioSTEAM object leaked through


# --- 11. Read-only query is recorded without a state-changing function call

def test_query_turn_records_query_result_and_no_function_calls(capsys):
    session = dlg.create_session()
    client_0 = ScriptedClient([_resp(component_names=['Water', 'Ethanol', 'Methanol'])])
    agent.process_turn(client_0, session, 'separate water ethanol methanol')
    client_1 = ScriptedClient([_resp(pressure=2, pressure_units='bar')])
    agent.process_turn(client_1, session, 'pressure is 2 bar')
    capsys.readouterr()

    client_2 = ScriptedClient([_resp(intent='query_current_state', target_field='pressure')])
    agent.process_turn(client_2, session, 'what is the feed pressure?', debug_mode='json')

    record = _debug_json_records(capsys)[0]
    assert record['exit_path'] == 'query_answered'
    assert record['function_calls'] == []
    assert '2 bar' in record['query_result']


# --- 12. Rendering never touches Ollama, BioSTEAM, or a state-changing call

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
