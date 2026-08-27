"""
Acceptance tests for tools/binary-distillation-pending-truth.md.

Two layers are exercised:
  - `binary_distillation_workflow.assess_binary_distillation_problem`'s
    deterministic `pending_request` generation (no LLM, no agent).
  - `binary_distillation_workflow_agent`'s deterministic pending-reply
    resolver and the `ask()` short-circuit that wires it in, using the same
    fake/scripted Ollama client style as
    `test_binary_distillation_workflow_agent.py` -- no running Ollama
    server is required.

Run with:
    pytest tools/chopper/test_binary_distillation_pending_truth.py -v
"""
import pytest

import binary_distillation_workflow_agent as agent
from binary_distillation_workflow import assess_binary_distillation_problem

PRESSURE = 101325
TEMP = 350.0
REFLUX = 'saturated_liquid'

ESSENTIALS = {
    'component_names': ['Methanol', 'Water'],
    'component_flows': {'Methanol': 40, 'Water': 60},
    'pressure_Pa': PRESSURE,
    'feed_temperature_K': TEMP,
    'reflux_condition': REFLUX,
}


# ---------------------------------------------------------------------------
# `assess_binary_distillation_problem` pending_request generation
# ---------------------------------------------------------------------------

def test_pending_request_none_when_not_narrowed():
    """No case signal given at all -> too many candidates to guess a single pending field."""
    result = assess_binary_distillation_problem(dict(ESSENTIALS))
    assert result['status'] == 'need_case_definition'
    assert result['pending_request'] is None


def test_pending_request_optimum_feed_plate():
    """Case D otherwise complete, only optimum-feed-plate left -- Test 1's setup."""
    spec = dict(ESSENTIALS, xD=0.99, xB=0.01, boilup_ratio_VB=2.0)
    result = assess_binary_distillation_problem(spec)
    assert result['status'] == 'need_case_inputs'
    assert result['pending_request'] == {
        'field': 'use_optimum_feed_plate',
        'request_type': 'boolean_confirmation',
        'prompt': 'Should the design use the optimum feed plate?',
        'allowed_values': [True, False],
    }


def test_pending_request_single_numeric_field():
    """Test 6 -- Case D with only xD missing (xB and boilup already given)."""
    spec = dict(ESSENTIALS, xB=0.01, boilup_ratio_VB=2.0)
    result = assess_binary_distillation_problem(spec)
    assert result['case_candidates'] == ['D']
    assert result['pending_request']['field'] == 'xD'
    assert result['pending_request']['request_type'] == 'float'


def test_pending_request_ordered_group():
    """Test 7/13 -- boilup ratio given, xD and xB both still missing -- Case D is the sole candidate."""
    spec = dict(ESSENTIALS, boilup_ratio_VB=2.0)
    result = assess_binary_distillation_problem(spec)
    assert result['case_candidates'] == ['D']
    assert result['pending_request'] == {
        'fields': ['xD', 'xB'],
        'request_type': 'ordered_float_group',
        'prompt': 'Please provide xD, then xB.',
    }


def test_pending_request_none_when_choice_involved():
    """Case C's missing fields are all 'X or Y' choices -- never guess which one the user means."""
    spec = dict(ESSENTIALS, distillate_flow=40.0, xD=0.99)
    result = assess_binary_distillation_problem(spec)
    assert result['case_candidates'] == ['C']
    assert result['pending_request'] is None


def test_pending_request_none_when_multiple_candidates():
    spec = dict(ESSENTIALS, external_reflux_ratio_LD=3.0)
    result = assess_binary_distillation_problem(spec)
    assert set(result['case_candidates']) == {'A', 'B', 'C'}
    assert result['pending_request'] is None


def test_pending_request_essential_pressure():
    spec = {
        'component_names': ['Methanol', 'Water'],
        'component_flows': {'Methanol': 40, 'Water': 60},
        'feed_temperature_K': TEMP, 'reflux_condition': REFLUX,
    }
    result = assess_binary_distillation_problem(spec)
    assert result['status'] == 'need_essential_inputs'
    assert result['pending_request'] == {
        'field': 'pressure_Pa', 'request_type': 'float',
        'prompt': 'What is the column pressure, in Pa?',
    }


def test_pending_request_none_when_feed_incomplete():
    """Feed quantity missing is multi-field/complex -- no single-field guess."""
    result = assess_binary_distillation_problem({'component_names': ['Methanol', 'Water']})
    assert result['status'] == 'need_essential_inputs'
    assert result['pending_request'] is None


def test_pending_request_none_at_ready_for_calculation():
    """Test 11 -- nothing pending once fully specified."""
    spec = dict(ESSENTIALS, xD=0.99, xB=0.01, boilup_ratio_VB=2.0, use_optimum_feed_plate=True)
    result = assess_binary_distillation_problem(spec)
    assert result['status'] == 'ready_for_calculation'
    assert result['pending_request'] is None
    assert 'workflow-only agent stops at problem definition' in result['message']


def test_pending_request_cleared_after_resolution():
    """Test 8 -- once optimum-feed-plate is answered, nothing else pending for a complete case."""
    spec = dict(ESSENTIALS, xD=0.99, xB=0.01, boilup_ratio_VB=2.0, use_optimum_feed_plate=True)
    result = assess_binary_distillation_problem(spec)
    assert result['pending_request'] is None


def test_pending_request_invalidated_by_problem_replacement():
    """Test 10 -- naming a wholly different feed leaves no stale pending_request from the old one."""
    old = assess_binary_distillation_problem(dict(ESSENTIALS, boilup_ratio_VB=2.0))
    assert old['pending_request'] is not None

    new = assess_binary_distillation_problem({'component_names': ['Ethanol', 'Water']})
    assert new['pending_request'] is None
    assert new['status'] == 'need_essential_inputs' or new['status'] == 'need_components'


# ---------------------------------------------------------------------------
# Agent-level: normalize_short_reply
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('raw,expected', [
    ('Ofcourse!@', 'ofcourse'),
    ('YES!!!', 'yes'),
    ('nope.', 'nope'),
    ('0.99', '0.99'),
    ('  Yes  ', 'yes'),
])
def test_normalize_short_reply(raw, expected):
    assert agent.normalize_short_reply(raw) == expected


# ---------------------------------------------------------------------------
# Agent-level: resolve_pending_reply
# ---------------------------------------------------------------------------

OFP_PENDING = {
    'field': 'use_optimum_feed_plate', 'request_type': 'boolean_confirmation',
    'prompt': 'Should the design use the optimum feed plate?', 'allowed_values': [True, False],
}
XD_PENDING = {'field': 'xD', 'request_type': 'float', 'prompt': 'xD?'}
XD_XB_PENDING = {'fields': ['xD', 'xB'], 'request_type': 'ordered_float_group', 'prompt': '...'}


def test_resolve_affirmative_confirmation():
    """Test 1 -- 'Of course!' resolves to use_optimum_feed_plate=True."""
    assert agent.resolve_pending_reply(OFP_PENDING, 'Of course!') == {'use_optimum_feed_plate': True}


def test_resolve_noisy_affirmative():
    """Test 2 -- 'Ofcourse!@' still resolves to True."""
    assert agent.resolve_pending_reply(OFP_PENDING, 'Ofcourse!@') == {'use_optimum_feed_plate': True}


def test_resolve_negative_confirmation():
    """Test 3 -- 'No, don't use it.' resolves to False."""
    assert agent.resolve_pending_reply(OFP_PENDING, "No, don't use it.") == {'use_optimum_feed_plate': False}


def test_resolve_does_not_hijack_unrelated_longer_message():
    """A longer message starting with a negative word must NOT be misread as the pending answer."""
    text = "No, actually let's start over with ethanol and water instead"
    assert agent.resolve_pending_reply(OFP_PENDING, text) is None


def test_resolve_numeric_pending_field():
    """Test 6 -- a bare '0.99' resolves the pending xD field."""
    assert agent.resolve_pending_reply(XD_PENDING, '0.99') == {'xD': 0.99}


def test_resolve_ordered_field_group():
    """Test 7 -- '0.99 and 0.01' maps to xD, xB in that order."""
    assert agent.resolve_pending_reply(XD_XB_PENDING, '0.99 and 0.01') == {'xD': 0.99, 'xB': 0.01}


def test_resolve_none_when_no_pending_request():
    assert agent.resolve_pending_reply(None, 'yes') is None


def test_resolve_none_when_ambiguous_count_mismatch():
    assert agent.resolve_pending_reply(XD_XB_PENDING, '0.99') is None


# ---------------------------------------------------------------------------
# Agent-level: ask() wiring -- fakes, no live Ollama server required.
# ---------------------------------------------------------------------------

class FakeFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class FakeToolCall:
    def __init__(self, name, arguments=None):
        self.function = FakeFunction(name, arguments or {})


class FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []
        self.role = 'assistant'


class FakeResponse:
    def __init__(self, message):
        self.message = message


def final(content='ok'):
    return FakeResponse(FakeMessage(content=content, tool_calls=[]))


class ScriptedClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def chat(self, model, messages, tools=None, think=False):
        self.calls.append(tools is not None)
        if not self._responses:
            raise AssertionError('ScriptedClient ran out of scripted responses')
        return self._responses.pop(0)


class ExplodingClient:
    """Used to prove ask() never even calls the model for the ready-state boundary case."""

    def chat(self, model, messages, tools=None, think=False):
        raise AssertionError('client.chat() should not have been called')


def _tool_result_names(messages):
    return [m['tool_name'] for m in messages if isinstance(m, dict) and m.get('role') == 'tool']


def _base_messages():
    return [{'role': 'system', 'content': agent.SYSTEM_PROMPT}]


@pytest.fixture(autouse=True)
def _reset_state():
    agent.reset_workflow_session()
    yield
    agent.reset_workflow_session()


def test_ask_resolves_pending_boolean_deterministically():
    """Test 1/4 -- 'Of course!' to a live use_optimum_feed_plate pending_request performs a REAL WRITE, visible in a subsequent READ, before any model prose."""
    agent.update_binary_distillation_problem(
        component_names=['Methanol', 'Water'], component_flows={'Methanol': 40, 'Water': 60},
        pressure_Pa=PRESSURE, feed_temperature_K=TEMP, reflux_condition=REFLUX,
        xD=0.99, xB=0.01, boilup_ratio_VB=2.0,
    )
    pre_state = agent.get_binary_distillation_problem()
    assert pre_state['pending_request']['field'] == 'use_optimum_feed_plate'

    client = ScriptedClient([final('Optimum feed plate: confirmed.')])
    messages = _base_messages() + [{'role': 'user', 'content': 'Of course!'}]

    agent.ask(client, messages)

    assert _tool_result_names(messages) == ['update_binary_distillation_problem']
    # The finalization call must have no tools exposed (grounded synthesis only).
    assert client.calls == [False]

    post_state = agent.get_binary_distillation_problem()
    assert post_state['optimum_feed_plate_confirmed'] is True
    assert post_state['status'] == 'ready_for_calculation'


def test_ask_falls_through_to_model_when_nothing_pending():
    client = ScriptedClient([
        final('Please tell me the two components.'),
    ])
    messages = _base_messages() + [{'role': 'user', 'content': 'hello'}]

    result = agent.ask(client, messages)

    assert _tool_result_names(messages) == []
    assert result == 'Please tell me the two components.'


def test_ask_ready_state_proceed_is_fully_deterministic_no_model_call():
    """Test 11/12 -- 'go ahead' after ready_for_calculation never touches the model or mutates state."""
    agent.update_binary_distillation_problem(
        component_names=['Methanol', 'Water'], component_flows={'Methanol': 40, 'Water': 60},
        pressure_Pa=PRESSURE, feed_temperature_K=TEMP, reflux_condition=REFLUX,
        xD=0.99, xB=0.01, boilup_ratio_VB=2.0, use_optimum_feed_plate=True,
    )
    assert agent.get_binary_distillation_problem()['status'] == 'ready_for_calculation'

    client = ExplodingClient()
    messages = _base_messages() + [{'role': 'user', 'content': 'go ahead'}]

    result = agent.ask(client, messages)

    assert result == agent.READY_BOUNDARY_MESSAGE
    assert _tool_result_names(messages) == []
