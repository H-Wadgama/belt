"""
Mocked-agent conversation tests for `multicomponent_distillation_agent.py`'s
`ask()` tool-dispatch loop -- no running Ollama server required. See
tools/multicomponent-distillation-feed-phase-plan.md "Tests": "Finish with
mocked-agent conversations that verify multi-turn collection, then one
live Ollama smoke test." (The live smoke test is documented in the
agent's module docstring instead of automated here, matching how this
toolkit keeps live-model runs manual.)

These tests script a fake `ollama.Client` so the model's own reasoning is
never exercised -- they verify only that `ask()` correctly dispatches tool
calls to `multicomponent_feed_tool.py`, feeds results back, and that the
tool's own accumulated state persists across separate `ask()` calls the
way separate conversation turns would.

Run with:
    pytest tools/chopper/test_multicomponent_distillation_agent.py -v
"""
import types

import pytest

import multicomponent_distillation_agent as agent
import multicomponent_feed_tool as tool


class FakeCall:
    def __init__(self, name, arguments):
        self.function = types.SimpleNamespace(name=name, arguments=arguments)


class FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class FakeResponse:
    def __init__(self, message):
        self.message = message


class ScriptedClient:
    """Returns each response in `responses`, in order, one per `.chat()` call."""

    def __init__(self, responses):
        self._responses = list(responses)

    def chat(self, model, messages, tools, think=False):
        return self._responses.pop(0)


@pytest.fixture(autouse=True)
def _reset():
    tool.reset_multicomponent_feed_session()
    yield
    tool.reset_multicomponent_feed_session()


def _base_messages():
    return [{'role': 'system', 'content': agent.SYSTEM_PROMPT}]


def test_single_turn_dispatches_tool_call_and_returns_final_reply():
    client = ScriptedClient([
        FakeResponse(FakeMessage(tool_calls=[
            FakeCall('update_multicomponent_feed', {
                'component_names': ['Water', 'Ethanol', 'Methanol'],
            }),
        ])),
        FakeResponse(FakeMessage(content='Which components? Please give the feed quantity and composition.')),
    ])
    messages = _base_messages() + [
        {'role': 'user', 'content': 'I want to separate water, ethanol, and methanol.'},
    ]

    reply = agent.ask(client, messages)

    assert reply == 'Which components? Please give the feed quantity and composition.'
    tool_messages = [m for m in messages if isinstance(m, dict) and m.get('role') == 'tool']
    assert len(tool_messages) == 1
    assert tool_messages[0]['tool_name'] == 'update_multicomponent_feed'
    assert 'pending_request' in tool_messages[0]['content']


def test_state_persists_across_separate_ask_calls():
    """Simulates two separate conversation turns (two separate ask() calls,
    as a REPL would make) and verifies the SECOND call's tool invocation
    builds on what the FIRST call already established, exactly as the
    module-level accumulated state in multicomponent_feed_tool.py intends."""
    # Turn 1: establish components.
    client_1 = ScriptedClient([
        FakeResponse(FakeMessage(tool_calls=[
            FakeCall('update_multicomponent_feed', {
                'component_names': ['Water', 'Ethanol', 'Methanol'],
            }),
        ])),
        FakeResponse(FakeMessage(content='What is the feed quantity and composition?')),
    ])
    messages = _base_messages() + [
        {'role': 'user', 'content': 'Water, ethanol, methanol.'},
    ]
    agent.ask(client_1, messages)

    # Turn 2: answer with flows only -- no need to resend component_names.
    client_2 = ScriptedClient([
        FakeResponse(FakeMessage(tool_calls=[
            FakeCall('update_multicomponent_feed', {
                'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30},
                'component_flow_units': 'kmol/hr',
            }),
        ])),
        FakeResponse(FakeMessage(content='What is the feed pressure?')),
    ])
    messages.append({'role': 'user', 'content': '30, 40, 30 kmol/hr.'})
    reply = agent.ask(client_2, messages)

    assert reply == 'What is the feed pressure?'
    # The accumulated state module-level to multicomponent_feed_tool.py
    # must already know all three component names from turn 1.
    assert tool._feed_state['component_names'] == ['Water', 'Ethanol', 'Methanol']
    assert tool._feed_state['total_flow'] == 100


def test_full_conversation_ends_with_only_phase_and_fractions():
    """Drives the tool all the way to completion across several scripted
    ask() turns and checks the LAST tool result exposed to the model is
    restricted to phase/vapor_fraction/liquid_fraction, per the output
    boundary in tools/multicomponent-distillation-context.md."""
    turns = [
        {'component_names': ['Water', 'Ethanol', 'Methanol']},
        {'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30}, 'component_flow_units': 'kmol/hr'},
        {'pressure': 1.0, 'pressure_units': 'atm'},
        {'feed_quality': 0.5},
    ]
    messages = _base_messages()
    last_tool_content = None
    for i, args in enumerate(turns):
        client = ScriptedClient([
            FakeResponse(FakeMessage(tool_calls=[FakeCall('update_multicomponent_feed', args)])),
            FakeResponse(FakeMessage(content=f'turn {i} ack')),
        ])
        messages.append({'role': 'user', 'content': f'turn {i}'})
        agent.ask(client, messages)
        tool_messages = [m for m in messages if isinstance(m, dict) and m.get('role') == 'tool']
        last_tool_content = tool_messages[-1]['content']

    import json
    result = json.loads(last_tool_content)
    assert result['complete'] is True
    assert set(result.keys()) == {'complete', 'valid', 'phase', 'vapor_fraction', 'liquid_fraction', 'message'}
    assert result['vapor_fraction'] == pytest.approx(0.5, abs=1e-6)
