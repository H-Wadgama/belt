"""
Agent-level tests for the calculation-tool connection --
tools/binary-distillation-connecting-feed-calculation.md Steps 15-16.

These exercise `binary_distillation_workflow_agent.py`'s new
`calculate_current_binary_distillation_problem` (CALCULATION) tool: its
registration, its deterministic feed-phase-question routing, its
interaction with the bounded per-turn controller, and (in the final test)
the real calculation pipeline end to end. Fakes/scripted clients are used
throughout except the last test, which calls the real deterministic
calculation layer (BioSTEAM included) directly -- no running Ollama server
is required anywhere in this file.

Run with:
    pytest tools/chopper/test_binary_distillation_workflow_agent_calculation.py -v
"""
import inspect
import json

import pytest

import binary_distillation_workflow_agent as agent

PRESSURE = 101325
TEMP = 400.0
REFLUX = 'saturated_liquid'

# A complete, ready_for_calculation Case D problem (matches the worked
# example in tools/binary-distillation-connecting-feed-calculation.md).
READY_CASE_D = dict(
    component_names=['Methanol', 'Water'],
    component_flows={'Methanol': 50, 'Water': 50},
    component_flow_units='kmol/hr',
    pressure_Pa=PRESSURE,
    feed_temperature_K=TEMP,
    reflux_condition=REFLUX,
    xD=0.95, xB=0.01, boilup_ratio_VB=1.2,
    use_optimum_feed_plate=True,
)


# ---------------------------------------------------------------------------
# Fakes -- no ollama import required (same shape as
# test_binary_distillation_workflow_agent.py).
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


def with_calls(*tool_calls):
    return FakeResponse(FakeMessage(content=None, tool_calls=list(tool_calls)))


def calc_call():
    return FakeToolCall('calculate_current_binary_distillation_problem')


def read_call():
    return FakeToolCall('get_binary_distillation_problem')


def write_call(**kwargs):
    return FakeToolCall('update_binary_distillation_problem', kwargs)


class ScriptedClient:
    """Returns responses from a fixed list, one per `.chat()` call. Raises
    if `ask()` calls `.chat()` more times than scripted -- proves a
    deterministically-routed turn never reaches the model for a tool-
    selection decision. Accepts (and ignores, for bookkeeping) the
    `format=`/`options=` kwargs `ask()`'s interpretation call passes."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []  # one bool per call: whether `tools` was exposed

    def chat(self, model, messages, tools=None, think=False, format=None, options=None):
        self.calls.append(tools is not None)
        if not self._responses:
            raise AssertionError('ScriptedClient ran out of scripted responses -- ask() called chat() more than expected')
        return self._responses.pop(0)


class StubbornCalculationClient:
    """A pathological client that always proposes the calculate_current_step
    action on every interpretation call, regardless of context. Used to
    prove ask() still terminates and runs the calculation at most once per
    turn."""

    def __init__(self, max_calls=6):
        self.max_calls = max_calls
        self.n_calls = 0

    def chat(self, model, messages, tools=None, think=False, format=None, options=None):
        self.n_calls += 1
        if self.n_calls > self.max_calls:
            raise AssertionError(f'ask() called chat() more than {self.max_calls} times -- looks unbounded')
        return FakeResponse(FakeMessage(content=json.dumps(
            {'version': 1, 'updates': [], 'queries': [], 'action': {'name': 'calculate_current_step'}}
        )))


def _tool_result_names(messages):
    return [m['tool_name'] for m in messages if isinstance(m, dict) and m.get('role') == 'tool']


def _tool_result_content(messages, tool_name):
    for m in messages:
        if isinstance(m, dict) and m.get('role') == 'tool' and m.get('tool_name') == tool_name:
            return json.loads(m['content'])
    return None


def _base_messages():
    return [{'role': 'system', 'content': agent.SYSTEM_PROMPT}]


@pytest.fixture(autouse=True)
def _reset_state():
    agent.reset_workflow_session()
    yield
    agent.reset_workflow_session()


def _establish_ready_case_d():
    result = agent.update_binary_distillation_problem(**READY_CASE_D)
    assert result['status'] == 'ready_for_calculation'
    return result


# ---------------------------------------------------------------------------
# Test 1 -- ready problem + feed-phase question routes deterministically,
# without a get_binary_distillation_problem call as the model-selected op.
# ---------------------------------------------------------------------------

def test_ready_problem_feed_phase_question_routes_to_calculation():
    _establish_ready_case_d()

    # Only one scripted response: the finalization call. If ask() were to
    # give the model a tool-selection turn first, ScriptedClient would run
    # out of responses and raise.
    client = ScriptedClient([final('The feed is a liquid at these conditions.')])
    messages = _base_messages() + [{'role': 'user', 'content': 'what is the feed phase?'}]

    result = agent.ask(client, messages)

    assert _tool_result_names(messages) == ['calculate_current_binary_distillation_problem']
    assert client.calls == [False]  # finalization call has no tools exposed
    assert result == 'The feed is a liquid at these conditions.'


# ---------------------------------------------------------------------------
# Test 2 -- the calculation result (not the model) controls what's grounded
# in the conversation before the model ever gets a turn to explain it.
# ---------------------------------------------------------------------------

def test_calculation_result_is_in_context_before_finalization(monkeypatch):
    _establish_ready_case_d()

    mock_result = {
        'calculation_performed': True,
        'workflow': agent.get_binary_distillation_problem(),
        'checks': {
            'feed_phase': {
                'check': 'feed_phase', 'valid': True,
                'phase': 'vapor', 'vapor_fraction': 1.0,
            },
        },
    }
    monkeypatch.setattr(agent, 'calculate_current_binary_distillation_problem', lambda: mock_result)

    client = ScriptedClient([final('The feed is fully vaporized.')])
    messages = _base_messages() + [{'role': 'user', 'content': 'what is the vapor fraction?'}]

    result = agent.ask(client, messages)

    assert _tool_result_content(messages, 'calculate_current_binary_distillation_problem') == mock_result
    # The tool result (mocked, but standing in for the real calculation) is
    # appended to `messages` BEFORE the finalization call is made -- the
    # model's answer is only ever generated from a result already fixed.
    assert result == 'The feed is fully vaporized.'


# ---------------------------------------------------------------------------
# Test 3 -- an incomplete problem never triggers BioSTEAM, even when the
# model itself chooses to call the calculation tool.
# ---------------------------------------------------------------------------

def test_incomplete_problem_does_not_calculate():
    # Missing feed_temperature_K/feed_quality/feed_enthalpy_kJ_per_hr.
    agent.update_binary_distillation_problem(
        component_names=['Methanol', 'Water'], component_flows={'Methanol': 50, 'Water': 50},
        pressure_Pa=PRESSURE, reflux_condition=REFLUX,
    )
    assert agent.get_binary_distillation_problem()['status'] != 'ready_for_calculation'

    # Not ready, so the deterministic feed-phase fast path does not
    # intercept -- this reaches the model's TurnIntent proposal, where the
    # (scripted) model decides to propose the calculate_current_step action
    # anyway.
    client = ScriptedClient([
        FakeResponse(FakeMessage(content=json.dumps(
            {'version': 1, 'updates': [], 'queries': [], 'action': {'name': 'calculate_current_step'}}
        ))),
        final('The feed thermal condition is still missing, so I cannot determine the feed phase yet.'),
    ])
    messages = _base_messages() + [{'role': 'user', 'content': 'what is the feed phase?'}]

    result = agent.ask(client, messages)

    calc_result = _tool_result_content(messages, 'calculate_current_binary_distillation_problem')
    assert calc_result['calculation_performed'] is False
    assert calc_result['checks'] == {}
    assert 'feed' in calc_result['workflow']['message'].lower() or calc_result['workflow']['missing_essential_inputs']
    assert 'missing' in result.lower()


# ---------------------------------------------------------------------------
# Test 4 -- a model attempting qualitative phase inference cannot bypass
# the deterministic calculation once the problem is ready: the real
# calculation result is always computed and placed in context first.
# ---------------------------------------------------------------------------

def test_no_qualitative_phase_inference_when_ready():
    _establish_ready_case_d()

    # Even if the (fake) model's only scripted reply attempts unqualified
    # qualitative reasoning, ask() never gives it the chance to skip the
    # calculation tool -- the deterministic router calls the real
    # calculation BEFORE this text is ever produced, and the real result is
    # already fixed in `messages` by the time this content is returned.
    client = ScriptedClient([
        final("400 K is above methanol's boiling point, so the feed is vapor."),
    ])
    messages = _base_messages() + [{'role': 'user', 'content': 'is the feed vapor?'}]

    agent.ask(client, messages)

    calc_result = _tool_result_content(messages, 'calculate_current_binary_distillation_problem')
    assert calc_result['calculation_performed'] is True
    assert calc_result['checks']['feed_phase']['valid'] is True
    assert calc_result['checks']['feed_phase']['phase'] in {'liquid', 'vapor', 'vapor_liquid'}
    # Grounded in the real BioSTEAM VLE result, not the model's qualitative
    # boiling-point reasoning above.
    assert client.calls == [False]


# ---------------------------------------------------------------------------
# Test 5 -- vapor-fraction question routes to calculation.
# ---------------------------------------------------------------------------

def test_vapor_fraction_question_routes_to_calculation():
    _establish_ready_case_d()

    client = ScriptedClient([final('Vapor fraction reported.')])
    messages = _base_messages() + [{'role': 'user', 'content': 'what is the vapor fraction?'}]

    agent.ask(client, messages)

    assert _tool_result_names(messages) == ['calculate_current_binary_distillation_problem']


# ---------------------------------------------------------------------------
# Test 6 -- liquid/vapor yes-no question routes to calculation.
# ---------------------------------------------------------------------------

def test_liquid_vapor_yes_no_question_routes_to_calculation():
    _establish_ready_case_d()

    client = ScriptedClient([final('Phase reported.')])
    messages = _base_messages() + [{'role': 'user', 'content': 'is the feed vapor?'}]

    agent.ask(client, messages)

    assert _tool_result_names(messages) == ['calculate_current_binary_distillation_problem']


# ---------------------------------------------------------------------------
# Test 7 -- a pending confirmation still wins over calculation routing.
# ---------------------------------------------------------------------------

def test_pending_confirmation_wins_over_calculation():
    # Case D, everything given except the optimum-feed-plate confirmation.
    state = agent.update_binary_distillation_problem(
        component_names=['Methanol', 'Water'], component_flows={'Methanol': 50, 'Water': 50},
        component_flow_units='kmol/hr',
        pressure_Pa=PRESSURE, feed_temperature_K=TEMP, reflux_condition=REFLUX,
        xD=0.95, xB=0.01, boilup_ratio_VB=1.2,
    )
    assert state['status'] == 'need_case_inputs'
    assert state['pending_request']['field'] == 'use_optimum_feed_plate'

    client = ScriptedClient([final('Optimum feed plate: confirmed.')])
    messages = _base_messages() + [{'role': 'user', 'content': 'yes'}]

    agent.ask(client, messages)

    assert _tool_result_names(messages) == ['update_binary_distillation_problem']
    post_state = agent.get_binary_distillation_problem()
    assert post_state['optimum_feed_plate_confirmed'] is True
    assert post_state['status'] == 'ready_for_calculation'


# ---------------------------------------------------------------------------
# Test 8 -- the calculation operation takes zero arguments and is wired into
# the ACTION_REGISTRY as 'calculate_current_step' (Round 2 -- native
# tool-calling exposure is retired, so there is no more TOOLS/TOOL_FUNCTIONS
# list to check against).
# ---------------------------------------------------------------------------

def test_calculation_tool_takes_zero_arguments():
    sig = inspect.signature(agent.calculate_current_binary_distillation_problem)
    assert list(sig.parameters) == []
    assert agent.ACTION_REGISTRY['calculate_current_step']['run'] is agent.calculate_current_binary_distillation_problem


# ---------------------------------------------------------------------------
# Test 9 -- no repeated calculation loop within a single turn. Round 2
# retired the native-tool-calling loop entirely -- there is no longer a
# mechanism by which the model could even ask to call the calculation
# operation more than once per turn (at most one interpretation call and,
# for an action turn, exactly one narration call follow it). This proves
# that invariant holds even against a pathological client that always
# proposes the same action.
# ---------------------------------------------------------------------------

def test_no_repeated_calculation_loop():
    _establish_ready_case_d()

    # A user message that does NOT match any exclusive fast path, so this
    # reaches the model's TurnIntent proposal -- where the pathological
    # client keeps proposing the calculate_current_step action every round.
    client = StubbornCalculationClient(max_calls=6)
    messages = _base_messages() + [{'role': 'user', 'content': 'tell me something about this problem'}]

    agent.ask(client, messages)

    executed = _tool_result_names(messages)
    assert executed.count('calculate_current_binary_distillation_problem') <= 1
    assert client.n_calls <= 2


# ---------------------------------------------------------------------------
# Step 16 -- integration test using the REAL calculation pipeline (BioSTEAM
# included), no mocking, no scripted client.
# ---------------------------------------------------------------------------

def test_real_calculation_pipeline_end_to_end():
    _establish_ready_case_d()

    result = agent.calculate_current_binary_distillation_problem()

    assert result['calculation_performed'] is True
    assert result['checks']['feed_phase']['valid'] is True
    assert result['checks']['feed_phase']['phase'] in {'liquid', 'vapor', 'vapor_liquid'}


# ---------------------------------------------------------------------------
# tools/binary-distillation-flow-units.md Step 16 -- reproduce the exact
# failure this doc fixes: a complete Case D problem missing only
# component_flow_units must report need_calculation_inputs (never
# ready_for_calculation), and a deterministic "KMOL/HR" reply must perform a
# real WRITE that makes it ready -- never a READ, never a guessed default.
# ---------------------------------------------------------------------------

def test_missing_units_blocks_ready_then_units_reply_performs_write():
    state = agent.update_binary_distillation_problem(
        component_names=['Methanol', 'Water'], component_flows={'Methanol': 50, 'Water': 50},
        pressure_Pa=PRESSURE, feed_temperature_K=TEMP, reflux_condition=REFLUX,
        xD=0.95, xB=0.01, boilup_ratio_VB=1.2, use_optimum_feed_plate=True,
    )
    assert state['status'] == 'need_calculation_inputs'
    assert state['missing_calculation_inputs'] == ['component_flow_units']
    assert state['pending_request'] == {
        'field': 'component_flow_units', 'request_type': 'flow_units',
        'prompt': 'What units are the component flow rates in?',
    }

    client = ScriptedClient([final('Units recorded.')])
    messages = _base_messages() + [{'role': 'user', 'content': 'KMOL/HR'}]

    agent.ask(client, messages)

    assert _tool_result_names(messages) == ['update_binary_distillation_problem']
    write_result = _tool_result_content(messages, 'update_binary_distillation_problem')
    assert write_result['status'] == 'ready_for_calculation'

    post_state = agent.get_binary_distillation_problem()
    assert post_state['feed']['component_flow_units'] == 'kmol/hr'
    assert post_state['status'] == 'ready_for_calculation'


# ---------------------------------------------------------------------------
# tools/binary-distillation-flow-units.md Step 17 -- once units are supplied
# via the deterministic resolver, a feed-phase question must run the real
# calculation immediately, never asking for units a second time.
# ---------------------------------------------------------------------------

def test_feed_phase_question_after_units_reply_runs_calculation():
    agent.update_binary_distillation_problem(
        component_names=['Methanol', 'Water'], component_flows={'Methanol': 50, 'Water': 50},
        pressure_Pa=PRESSURE, feed_temperature_K=TEMP, reflux_condition=REFLUX,
        xD=0.95, xB=0.01, boilup_ratio_VB=1.2, use_optimum_feed_plate=True,
    )
    assert agent.get_binary_distillation_problem()['status'] == 'need_calculation_inputs'

    units_client = ScriptedClient([final('Units recorded.')])
    units_messages = _base_messages() + [{'role': 'user', 'content': 'KMOL/HR'}]
    agent.ask(units_client, units_messages)
    assert agent.get_binary_distillation_problem()['status'] == 'ready_for_calculation'

    phase_client = ScriptedClient([final('The feed is a liquid at these conditions.')])
    phase_messages = _base_messages() + [{'role': 'user', 'content': 'What is the feed phase?'}]
    result = agent.ask(phase_client, phase_messages)

    assert _tool_result_names(phase_messages) == ['calculate_current_binary_distillation_problem']
    calc_result = _tool_result_content(phase_messages, 'calculate_current_binary_distillation_problem')
    assert calc_result['calculation_performed'] is True
    assert calc_result['checks']['feed_phase']['valid'] is True
    assert result == 'The feed is a liquid at these conditions.'


# ---------------------------------------------------------------------------
# tools/binary-distillation-flow-units.md Step 18 -- extraction regression
# guard. Real LLM extraction quality can't be pinned down by a scripted
# test, so this checks the guidance that reduces how often the deterministic
# units fallback is needed is actually present -- the deterministic tests
# above (Step 16/17) remain the real reliability safeguard regardless of
# what the model extracts.
# ---------------------------------------------------------------------------

def test_system_prompt_carries_flow_unit_extraction_rule():
    assert 'FLOW-UNIT EXTRACTION RULE' in agent.SYSTEM_PROMPT
    assert 'component_flow_units' in agent.SYSTEM_PROMPT
    assert 'need_calculation_inputs' in agent.SYSTEM_PROMPT


def test_write_call_with_flows_and_units_together_reaches_ready_immediately():
    """A model that correctly follows the extraction rule -- proposing
    component_flows updates with units in the SAME TurnIntent, as if
    extracted from 'Each component has a flow rate of 50 kmol per hour' --
    must reach ready_for_calculation without any follow-up units request."""
    proposed_intent = {
        'version': 1,
        'updates': [
            {'field': 'component_flows', 'entity': 'Methanol', 'value': 50, 'units': 'kmol/hr'},
            {'field': 'component_flows', 'entity': 'Water', 'value': 50, 'units': 'kmol/hr'},
            {'field': 'pressure_Pa', 'value': PRESSURE},
            {'field': 'feed_temperature_K', 'value': TEMP},
            {'field': 'reflux_condition', 'value': REFLUX},
            {'field': 'xD', 'value': 0.95},
            {'field': 'xB', 'value': 0.01},
            {'field': 'boilup_ratio_VB', 'value': 1.2},
            {'field': 'use_optimum_feed_plate', 'value': True},
        ],
        'queries': [], 'action': None,
    }
    client = ScriptedClient([
        FakeResponse(FakeMessage(content=json.dumps(proposed_intent))),
        final('Your problem is fully specified.'),
    ])
    messages = _base_messages() + [{
        'role': 'user',
        'content': 'Each component has a flow rate of 50 kmol per hour, separate methanol and water at 400 K and 101325 Pa, saturated liquid reflux, boilup ratio 1.2, xD=0.95, xB=0.01, use the optimum feed plate.',
    }]

    agent.ask(client, messages)

    write_result = _tool_result_content(messages, 'update_binary_distillation_problem')
    assert write_result['status'] == 'ready_for_calculation'
    assert write_result['missing_calculation_inputs'] == []
