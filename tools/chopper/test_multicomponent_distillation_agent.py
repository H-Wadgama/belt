"""
Mocked-agent tests for `multicomponent_distillation_agent.py`'s
`process_turn()` -- no running Ollama server required. See
tools/multicomponent-distillation-dialogue-robustness-plan.md.

These tests script a fake `ollama.Client` whose `.chat()` returns
structured-output JSON content matching the TurnIntent schema (never
native tool calls). They verify: the model is called at most once (plus a
bounded malformed-JSON retry) per turn; a session is threaded explicitly
(no module-global feed state); the numeric-collision fix (a bare reply
answering one pending question can't also ground an unrelated hallucinated
field); component identity protection; read-only queries; and that the
final reply contains only phase/vapor_fraction/liquid_fraction information.

Run with:
    pytest tools/chopper/test_multicomponent_distillation_agent.py -v
"""
import json

import pytest

import multicomponent_distillation_agent as agent
import multicomponent_dialogue as dlg
from multicomponent_feed_state import record_value


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeResponse:
    def __init__(self, content):
        self.message = FakeMessage(content)


class ScriptedClient:
    """Returns each response in `responses`, in order, one per `.chat()`
    call. Records every call so tests can assert on how many times (and
    how) the model was actually invoked this turn."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def chat(self, model, messages, format=None, think=False, options=None):
        self.calls.append({'model': model, 'messages': messages, 'format': format})
        if not self._responses:
            raise AssertionError('ScriptedClient called more times than scripted -- '
                                  'the agent must not call the model again after '
                                  'the extraction call on the same turn.')
        return self._responses.pop(0)


def _resp(**fields):
    full = agent._empty_intent_result()
    full.update(fields)
    if 'intent' not in fields:
        full['intent'] = 'provide_information'
    return FakeResponse(json.dumps(full))


# --- One model call per turn; deterministic pending-question reply ---------

def test_single_turn_calls_model_once_and_returns_pending_question():
    session = dlg.create_session()
    client = ScriptedClient([_resp(component_names=['Water', 'Ethanol', 'Methanol'])])

    reply = agent.process_turn(client, session, 'I want to separate water, ethanol, and methanol.')

    assert len(client.calls) == 1
    assert 'feed quantity' in reply.lower() or 'composition' in reply.lower()
    assert session['feed_state']['component_names'] == ['Water', 'Ethanol', 'Methanol']


# --- Fabricated values rejected by the grounding boundary -------------------

def test_fabricated_pressure_and_flows_are_never_applied():
    session = dlg.create_session()
    client = ScriptedClient([_resp(
        component_names=['Ethanol', 'Methanol', 'Water'],
        feed_temperature=335, feed_temperature_units='K',
        pressure=101325, pressure_units='Pa',
        component_flows={'Ethanol': 30, 'Methanol': 30, 'Water': 40},
    )])

    agent.process_turn(client, session, 'separate Ethanol, Methanol, and Water at 335 K')

    state = session['feed_state']
    assert state['component_names'] == ['Ethanol', 'Methanol', 'Water']
    assert record_value(state['feed_temperature']) == 335
    assert state['pressure'] is None
    assert state['component_flows'] == {}


# --- State persists across separate turns; no resend needed ----------------

def test_state_persists_across_separate_turns():
    session = dlg.create_session()

    client_1 = ScriptedClient([_resp(component_names=['Water', 'Ethanol', 'Methanol'])])
    agent.process_turn(client_1, session, 'Water, ethanol, methanol.')

    client_2 = ScriptedClient([_resp(
        component_flows={'Water': 30, 'Ethanol': 40, 'Methanol': 30},
        component_flow_units='kmol/hr',
    )])
    reply = agent.process_turn(client_2, session, '30, 40, 30 kmol/hr.')

    assert 'pressure' in reply.lower()
    assert session['feed_state']['component_names'] == ['Water', 'Ethanol', 'Methanol']
    assert record_value(session['feed_state']['total_flow']) == 100


# --- The numeric-collision fix, end to end ------------------------------------

def test_bare_pressure_answer_never_grounds_a_hallucinated_field():
    """The exact reported failure: answering "1" to a pressure question
    must commit ONLY pressure=1, even when the model's same response also
    hallucinates a value for an unrelated field."""
    session = dlg.create_session()
    client0 = ScriptedClient([_resp(
        component_names=['Water', 'Ethanol', 'Methanol'],
    )])
    agent.process_turn(client0, session, 'separate water, ethanol, methanol')
    client1 = ScriptedClient([_resp(
        component_flows={'Water': 30, 'Ethanol': 40, 'Methanol': 30}, component_flow_units='kmol/hr',
    )])
    agent.process_turn(client1, session, '30, 40, 30 kmol/hr')

    assert session['pending_request']['field'] == 'pressure'

    client2 = ScriptedClient([_resp(
        intent='answer_pending_request', pressure=1,
        component_flows={'Water': 1.0},  # hallucinated, must never land
    )])
    reply = agent.process_turn(client2, session, '1')

    assert record_value(session['feed_state']['pressure']) == 1
    assert record_value(session['feed_state']['component_flows']['Water']) == 30
    assert 'units' in reply.lower()

    client3 = ScriptedClient([_resp(intent='answer_pending_request', pressure_units='atm')])
    agent.process_turn(client3, session, 'atm')
    assert record_value(session['feed_state']['pressure']) == 1
    from multicomponent_feed_state import record_unit
    assert record_unit(session['feed_state']['pressure']) == 'atm'


# --- Component identity protection --------------------------------------------

def test_flow_only_statement_does_not_shrink_established_identity():
    session = dlg.create_session()
    client0 = ScriptedClient([_resp(component_names=['Ethanol', 'Methanol', 'Water'])])
    agent.process_turn(client0, session, 'separate ethanol, methanol, water')

    client1 = ScriptedClient([_resp(component_flows={'Methanol': 30}, component_flow_units='kg/hr')])
    agent.process_turn(client1, session, 'methanol = 30 kg/hr')

    assert session['feed_state']['component_names'] == ['Ethanol', 'Methanol', 'Water']
    assert record_value(session['feed_state']['component_flows']['Methanol']) == 30


def test_partial_flows_with_changed_capitalization_advance_past_quantity():
    """Regression for the live loop where initial ``ethanol`` and a later
    model key ``Ethanol`` were stored as two different components."""
    session = dlg.create_session()

    client0 = ScriptedClient([_resp(
        target_field='component_names', component_identity_action='add',
        component_names=['methanol', 'ethanol', 'water'],
    )])
    agent.process_turn(client0, session, 'separate methanol, ethanol, water')

    client1 = ScriptedClient([_resp(
        target_field='component_flows',
        component_flows={'water': 50, 'Ethanol': 20},
        component_flow_units='kmol/hr',
    )])
    agent.process_turn(client1, session, 'water = 50 kmol/hr, Ethanol = 20 kmol/hr')

    # Match the noisy live proposal: it copied earlier flow values even
    # though only methanol was stated in this message. Grounding still drops
    # the absent 20; case normalization keeps all accepted keys aligned with
    # the original identity list.
    client2 = ScriptedClient([_resp(
        target_field='component_flows', component_identity_action='add',
        component_names=['methanol', 'ethanol', 'water'],
        component_flows={'methanol': 50, 'ethanol': 20, 'water': 50},
        component_flow_units='kmol/hr',
    )])
    reply = agent.process_turn(client2, session, 'methanol=50 kmol/hr')

    assert session['feed_state']['component_names'] == ['methanol', 'ethanol', 'water']
    assert set(session['feed_state']['component_flows']) == {'methanol', 'ethanol', 'water'}
    assert record_value(session['feed_state']['total_flow']) == 120
    assert 'pressure' in reply.lower()


# --- Full conversation ends with only phase/fraction information -----------

def test_full_conversation_ends_with_only_phase_and_fractions():
    session = dlg.create_session()
    turns = [
        ('Water, ethanol, methanol.', _resp(component_names=['Water', 'Ethanol', 'Methanol'])),
        ('30, 40, 30 kmol/hr.', _resp(
            component_flows={'Water': 30, 'Ethanol': 40, 'Methanol': 30},
            component_flow_units='kmol/hr')),
        ('1 atm.', _resp(pressure=1, pressure_units='atm')),
        ('350 K.', _resp(feed_temperature=350, feed_temperature_units='K')),
    ]
    reply = None
    for user_text, response in turns:
        client = ScriptedClient([response])
        reply = agent.process_turn(client, session, user_text)

    assert 'phase' in reply.lower()
    assert 'vapor fraction' in reply.lower()
    assert 'liquid fraction' in reply.lower()
    for forbidden in ('column', 'reflux', 'design', 'separation'):
        assert forbidden not in reply.lower()


# --- Malformed model output: bounded retry, never mutates state ------------

def test_malformed_response_triggers_one_retry_then_gives_up_gracefully():
    session = dlg.create_session()
    client = ScriptedClient([FakeResponse('not json'), FakeResponse('still not json')])

    reply = agent.process_turn(client, session, 'water, ethanol, methanol')

    assert len(client.calls) == 2
    assert session['feed_state']['component_names'] == []
    assert isinstance(reply, str) and reply


# --- Mixed units / mixed basis produce a dedicated restate-request ---------

def test_mixed_flow_units_message_is_rejected_with_common_unit_request():
    session = dlg.create_session()
    client0 = ScriptedClient([_resp(component_names=['Water', 'Ethanol', 'Methanol'])])
    agent.process_turn(client0, session, 'separate water ethanol methanol')

    client = ScriptedClient([_resp(
        component_flows={'Water': 30, 'Ethanol': 40, 'Methanol': 30},
        component_flow_units='kg/hr',
    )])
    reply = agent.process_turn(
        client, session,
        'Water is 30 kg/hr, Ethanol is 40 mol/hr, Methanol is 30 kmol/hr',
    )

    assert 'common unit' in reply.lower()
    assert session['feed_state']['component_flows'] == {}


def test_reset_intent_clears_session():
    session = dlg.create_session()
    client0 = ScriptedClient([_resp(component_names=['Water', 'Ethanol', 'Methanol'])])
    agent.process_turn(client0, session, 'separate water ethanol methanol')

    client = ScriptedClient([_resp(intent='reset')])
    reply = agent.process_turn(client, session, "let's start over with a different feed")

    assert session['feed_state']['component_names'] == []
    assert session['pending_request'] is None
    assert 'new feed' in reply.lower() or 'components' in reply.lower()


# --- Read-only queries ----------------------------------------------------------

def test_query_reports_stored_pressure_without_mutating_state():
    session = dlg.create_session()
    client0 = ScriptedClient([_resp(component_names=['Water', 'Ethanol', 'Methanol'])])
    agent.process_turn(client0, session, 'separate water ethanol methanol')
    client1 = ScriptedClient([_resp(pressure=2, pressure_units='bar')])
    agent.process_turn(client1, session, 'pressure is 2 bar')

    client2 = ScriptedClient([_resp(intent='query_current_state', target_field='pressure')])
    reply = agent.process_turn(client2, session, 'what is the feed pressure?')

    assert '2 bar' in reply
    assert record_value(session['feed_state']['pressure']) == 2


def test_query_with_unverifiable_target_field_asks_for_clarification():
    """The model claiming target_field='pressure' for a message that never
    actually mentions pressure must not be trusted."""
    session = dlg.create_session()
    client = ScriptedClient([_resp(intent='query_current_state', target_field='pressure')])
    reply = agent.process_turn(client, session, 'what is the total flow?')
    assert 'not sure' in reply.lower()
