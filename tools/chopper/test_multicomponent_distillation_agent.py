"""
Mocked-agent tests for `multicomponent_distillation_agent.py`'s
`process_turn()` -- no running Ollama server required. See
tools/multicomponent-distillation-feed-phase-plan.md "Required Tests"
items 19-25 (architectural regression) and "One State Update Per User
Turn".

These tests script a fake `ollama.Client` whose `.chat()` returns
structured-output JSON content (never native tool calls -- this agent
never exposes a `tools=` channel to the model). They verify: the model is
called at most once (plus a bounded malformed-JSON retry) per turn; the
grounding boundary discards anything the proposal states that the raw user
message doesn't; only grounded fields reach
`multicomponent_feed_tool.update_multicomponent_feed`; and the final reply
contains only phase/vapor_fraction/liquid_fraction information.

Run with:
    pytest tools/chopper/test_multicomponent_distillation_agent.py -v
"""
import json
import types

import pytest

import multicomponent_distillation_agent as agent
import multicomponent_feed_tool as tool


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeResponse:
    def __init__(self, content):
        self.message = FakeMessage(content)


class ScriptedClient:
    """Returns each response in `responses`, in order, one per `.chat()`
    call. Records every call's messages/kwargs so tests can assert on how
    many times (and how) the model was actually invoked this turn."""

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


def _proposal_response(**fields):
    full = {
        'component_names': None, 'add_component_names': None,
        'component_flows': None, 'component_flow_units': None,
        'total_flow': None, 'total_flow_units': None,
        'composition': None, 'composition_basis': None,
        'pressure': None, 'pressure_units': None,
        'feed_temperature': None, 'feed_temperature_units': None,
        'reset': False,
    }
    full.update(fields)
    return FakeResponse(json.dumps(full))


@pytest.fixture(autouse=True)
def _reset():
    tool.reset_multicomponent_feed_session()
    yield
    tool.reset_multicomponent_feed_session()


# --- One model call per turn; deterministic pending-question reply ---------

def test_single_turn_calls_model_once_and_returns_pending_question():
    client = ScriptedClient([
        _proposal_response(component_names=['Water', 'Ethanol', 'Methanol']),
    ])
    messages = [{'role': 'system', 'content': agent.SYSTEM_PROMPT}]

    reply = agent.process_turn(client, messages, 'I want to separate water, ethanol, and methanol.')

    assert len(client.calls) == 1
    assert 'feed quantity' in reply.lower() or 'composition' in reply.lower()
    assert tool._feed_state['component_names'] == ['Water', 'Ethanol', 'Methanol']


# --- Fabricated values rejected by the grounding boundary -------------------

def test_fabricated_pressure_and_flows_are_never_applied():
    client = ScriptedClient([
        _proposal_response(
            component_names=['Ethanol', 'Methanol', 'Water'],
            feed_temperature=335, feed_temperature_units='K',
            pressure=101325, pressure_units='Pa',
            component_flows={'Ethanol': 30, 'Methanol': 30, 'Water': 40},
        ),
    ])
    messages = [{'role': 'system', 'content': agent.SYSTEM_PROMPT}]

    agent.process_turn(client, messages, 'separate Ethanol, Methanol, and Water at 335 K')

    assert tool._feed_state['component_names'] == ['Ethanol', 'Methanol', 'Water']
    assert tool._feed_state['feed_temperature'] == 335
    assert tool._feed_state['pressure'] is None
    assert tool._feed_state['component_flows'] == {}


# --- State persists across separate turns; no resend needed ----------------

def test_state_persists_across_separate_turns():
    messages = [{'role': 'system', 'content': agent.SYSTEM_PROMPT}]

    client_1 = ScriptedClient([
        _proposal_response(component_names=['Water', 'Ethanol', 'Methanol']),
    ])
    agent.process_turn(client_1, messages, 'Water, ethanol, methanol.')

    client_2 = ScriptedClient([
        _proposal_response(
            component_flows={'Water': 30, 'Ethanol': 40, 'Methanol': 30},
            component_flow_units='kmol/hr',
        ),
    ])
    reply = agent.process_turn(client_2, messages, '30, 40, 30 kmol/hr.')

    assert 'pressure' in reply.lower()
    assert tool._feed_state['component_names'] == ['Water', 'Ethanol', 'Methanol']
    assert tool._feed_state['total_flow'] == 100


# --- Full conversation ends with only phase/fraction information -----------

def test_full_conversation_ends_with_only_phase_and_fractions():
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
    reply = None
    for user_text, response in turns:
        client = ScriptedClient([response])
        reply = agent.process_turn(client, messages, user_text)

    assert 'phase' in reply.lower()
    assert 'vapor fraction' in reply.lower()
    assert 'liquid fraction' in reply.lower()
    # Output boundary: no design/routing vocabulary leaks into the reply.
    for forbidden in ('column', 'reflux', 'design', 'separation'):
        assert forbidden not in reply.lower()


# --- Malformed model output: bounded retry, never mutates state ------------

def test_malformed_response_triggers_one_retry_then_gives_up_gracefully():
    client = ScriptedClient([
        FakeResponse('not json'),
        FakeResponse('still not json'),
    ])
    messages = [{'role': 'system', 'content': agent.SYSTEM_PROMPT}]

    reply = agent.process_turn(client, messages, 'water, ethanol, methanol')

    assert len(client.calls) == 2
    assert tool._feed_state['component_names'] == []
    assert isinstance(reply, str) and reply


# --- Mixed units / mixed basis produce a dedicated restate-request ---------

def test_mixed_flow_units_message_is_rejected_with_common_unit_request():
    client = ScriptedClient([
        _proposal_response(
            component_names=['Water', 'Ethanol', 'Methanol'],
            component_flows={'Water': 30, 'Ethanol': 40, 'Methanol': 30},
            component_flow_units='kg/hr',
        ),
    ])
    messages = [{'role': 'system', 'content': agent.SYSTEM_PROMPT}]
    tool.update_multicomponent_feed(component_names=['Water', 'Ethanol', 'Methanol'])

    reply = agent.process_turn(
        client, messages,
        'Water is 30 kg/hr, Ethanol is 40 mol/hr, Methanol is 30 kmol/hr',
    )

    assert 'common unit' in reply.lower()
    assert tool._feed_state['component_flows'] == {}


def test_reset_flag_clears_session():
    tool.update_multicomponent_feed(component_names=['Water', 'Ethanol', 'Methanol'])
    client = ScriptedClient([_proposal_response(reset=True)])
    messages = [{'role': 'system', 'content': agent.SYSTEM_PROMPT}]

    reply = agent.process_turn(client, messages, "let's start over with a different feed")

    assert tool._feed_state['component_names'] == []
    assert 'new feed' in reply.lower() or 'components' in reply.lower()
