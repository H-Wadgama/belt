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
    'component_flow_units': 'kmol/hr',
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
    assert 'not yet implemented' in result['message']


def test_pending_request_cleared_after_resolution():
    """Test 8 -- once optimum-feed-plate is answered, nothing else pending for a complete case."""
    spec = dict(ESSENTIALS, xD=0.99, xB=0.01, boilup_ratio_VB=2.0, use_optimum_feed_plate=True)
    result = assess_binary_distillation_problem(spec)
    assert result['pending_request'] is None


def test_pending_request_component_flow_units():
    """tools/binary-distillation-flow-units.md Step 15 -- component_flow_units is the only missing calculation input."""
    spec = {
        'component_names': ['Methanol', 'Water'],
        'component_flows': {'Methanol': 40, 'Water': 60},
        'pressure_Pa': PRESSURE, 'feed_temperature_K': TEMP, 'reflux_condition': REFLUX,
        'xD': 0.99, 'xB': 0.01, 'boilup_ratio_VB': 2.0, 'use_optimum_feed_plate': True,
    }
    result = assess_binary_distillation_problem(spec)
    assert result['status'] == 'need_calculation_inputs'
    assert result['pending_request'] == {
        'field': 'component_flow_units',
        'request_type': 'flow_units',
        'prompt': 'What units are the component flow rates in?',
    }


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
# tools/binary-distillation-flow-units.md Step 5/15 -- normalize_units_reply
# and resolve_pending_reply(request_type='flow_units').
# ---------------------------------------------------------------------------

COMPONENT_FLOW_UNITS_PENDING = {
    'field': 'component_flow_units', 'request_type': 'flow_units',
    'prompt': 'What units are the component flow rates in?',
}
TOTAL_FLOW_UNITS_PENDING = {
    'field': 'total_flow_units', 'request_type': 'flow_units',
    'prompt': 'What units is the total feed flow rate in?',
}


@pytest.mark.parametrize('raw', [
    'KMOL/HR', 'kmol/hr', 'kmol per hour', 'KMOL PER HR', 'kilomoles per hour',
    'kmol per hr', 'Kilomol/hr',
])
def test_normalize_units_reply_kmol_hr_variants(raw):
    assert agent.normalize_units_reply(raw) == 'kmol/hr'


@pytest.mark.parametrize('raw', [
    'kg/hr', 'KG/HR', 'kg per hour', 'kilograms per hour', 'kg per hr',
])
def test_normalize_units_reply_kg_hr_variants(raw):
    assert agent.normalize_units_reply(raw) == 'kg/hr'


def test_normalize_units_reply_unknown_returns_none():
    assert agent.normalize_units_reply('furlongs per fortnight') is None


def test_resolve_flow_units_component_flow_units():
    assert agent.resolve_pending_reply(COMPONENT_FLOW_UNITS_PENDING, 'KMOL/HR') == {
        'component_flow_units': 'kmol/hr',
    }


def test_resolve_flow_units_total_flow_units():
    assert agent.resolve_pending_reply(TOTAL_FLOW_UNITS_PENDING, 'kilograms per hour') == {
        'total_flow_units': 'kg/hr',
    }


def test_resolve_flow_units_unrecognized_does_not_resolve():
    assert agent.resolve_pending_reply(COMPONENT_FLOW_UNITS_PENDING, 'furlongs per fortnight') is None


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

    def chat(self, model, messages, tools=None, think=False, format=None, options=None):
        self.calls.append(tools is not None)
        if not self._responses:
            raise AssertionError('ScriptedClient ran out of scripted responses')
        return self._responses.pop(0)


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
        component_flow_units='kmol/hr',
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
    """"hello" matches no exclusive fast path and no field/action, so the
    model's TurnIntent proposal comes back empty -- ask() then falls
    through to the broad, grounded elaboration path (one further no-format
    narration call)."""
    import json
    client = ScriptedClient([
        FakeResponse(FakeMessage(content=json.dumps({'version': 1, 'updates': [], 'queries': [], 'action': None}))),
        final('Please tell me the two components.'),
    ])
    messages = _base_messages() + [{'role': 'user', 'content': 'hello'}]

    result = agent.ask(client, messages)

    assert _tool_result_names(messages) == ['get_binary_distillation_problem']
    assert result == 'Please tell me the two components.'


def test_ask_ready_state_proceed_runs_calculation_deterministically():
    """tools/binary-distillation-connecting-feed-calculation.md Step 13 -- 'go ahead' after
    ready_for_calculation no longer returns the old fixed refusal; it deterministically runs
    calculate_current_binary_distillation_problem (never left to the model to decide whether
    to call it) and finalizes with a single no-tools model call to explain the result."""
    agent.update_binary_distillation_problem(
        component_names=['Methanol', 'Water'], component_flows={'Methanol': 40, 'Water': 60},
        component_flow_units='kmol/hr',
        pressure_Pa=PRESSURE, feed_temperature_K=TEMP, reflux_condition=REFLUX,
        xD=0.99, xB=0.01, boilup_ratio_VB=2.0, use_optimum_feed_plate=True,
    )
    assert agent.get_binary_distillation_problem()['status'] == 'ready_for_calculation'

    client = ScriptedClient([final('The feed-phase check is done -- see the result.')])
    messages = _base_messages() + [{'role': 'user', 'content': 'go ahead'}]

    result = agent.ask(client, messages)

    assert _tool_result_names(messages) == ['calculate_current_binary_distillation_problem']
    assert client.calls == [False]  # finalization call has no tools exposed
    assert result == 'The feed-phase check is done -- see the result.'
