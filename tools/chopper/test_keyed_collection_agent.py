"""
tools/binary-distillation-issues-9-1-2026-sixth.md Part 12 -- scripted-model
(fake Ollama client, no live LLM) test proving a single model-proposed
`items`-collection TurnIntent update produces exactly one WRITE, with the
expected compiled kwargs, through the real `ask()` pipeline end to end.

Run with:
    pytest tools/chopper/test_keyed_collection_agent.py -v
"""
import json

import pytest

import binary_distillation_workflow_agent as agent
from turn_intent_test_fakes import ScriptedClient, final, intent_response


@pytest.fixture(autouse=True)
def _reset_state():
    agent.reset_workflow_session()
    yield
    agent.reset_workflow_session()


def _base_messages():
    return [{'role': 'system', 'content': agent.SYSTEM_PROMPT}]


def _tool_result_content(messages, tool_name):
    for m in messages:
        if isinstance(m, dict) and m.get('role') == 'tool' and m.get('tool_name') == tool_name:
            return json.loads(m['content'])
    return None


def test_collection_update_produces_exactly_one_write_with_compiled_kwargs():
    client = ScriptedClient([
        intent_response(updates=[
            {
                'field': 'component_flows',
                'items': [
                    {'entity': 'Ethanol', 'value': 50, 'units': 'kmol/hr'},
                    {'entity': 'Water', 'value': 50, 'units': 'kmol/hr'},
                ],
            },
            {'field': 'feed_temperature_K', 'value': 355},
            {'field': 'pressure_Pa', 'value': 101325},
        ]),
        final('Got it.'),
    ])
    messages = _base_messages() + [{
        'role': 'user',
        'content': (
            'Separate water and ethanol at 355 K and 101325 Pa pressure. '
            'The feed flow rates are 50 kmol/hr ethanol and 50 kmol/hr water.'
        ),
    }]

    agent.ask(client, messages)

    tool_calls = [m for m in messages if isinstance(m, dict) and m.get('role') == 'assistant' and m.get('tool_calls')]
    write_calls = [
        tc for m in tool_calls for tc in m['tool_calls']
        if tc['function']['name'] == 'update_binary_distillation_problem'
    ]
    assert len(write_calls) == 1
    assert write_calls[0]['function']['arguments'] == {
        'component_flows': {'Ethanol': 50.0, 'Water': 50.0},
        'component_flow_units': 'kmol/hr',
        'feed_temperature_K': 355,
        'pressure_Pa': 101325,
    }

    final_state = agent.get_binary_distillation_problem()
    assert final_state['feed']['component_flows'] == {'Ethanol': 50.0, 'Water': 50.0}
    assert final_state['feed']['component_flow_units'] == 'kmol/hr'
    assert final_state['feed']['total_flow'] == 100.0
