"""
Calculation-progress state layer tests -- tools/binary-distillation-whats-next.md
Steps 23-30.

Covers `binary_distillation_calculation.py`'s `calculation_progress` schema
directly (Steps 23-24), and `binary_distillation_workflow_agent.py`'s
`_last_calculation_result` store, `get_binary_distillation_calculation_status`
READ tool, reset/WRITE invalidation, and deterministic "what next?"/
"continue"/"what remains?" routing (Steps 25-30).

Run with:
    pytest tools/chopper/test_binary_distillation_calculation_progress.py -v
"""
import json

import pytest

import binary_distillation_calculation as calc
import binary_distillation_workflow_agent as agent
from binary_distillation_calculation import calculate_binary_distillation_problem

INCOMPLETE_SPEC = {'component_names': ['Butane', 'Acetaldehyde']}

# Case B (Lr/Hr + external_reflux_ratio_LD) -- matches
# test_binary_distillation_calculation.py's COMPLETE_SPEC.
COMPLETE_SPEC_CASE_B = {
    'component_names': ['Butane', 'Acetaldehyde'],
    'component_flows': {'Butane': 50, 'Acetaldehyde': 50},
    'component_flow_units': 'kmol/hr',
    'pressure_Pa': 101325,
    'feed_temperature_K': 405,
    'reflux_condition': 'saturated_liquid',
    'Lr': 0.99, 'Hr': 0.99,
    'external_reflux_ratio_LD': 5.0,
    'use_optimum_feed_plate': True,
}

# Case D (xD/xB + boilup_ratio_VB) -- the exact worked example from the doc.
PRESSURE = 101325
TEMP = 400.0
REFLUX = 'saturated_liquid'
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
# Test 1 -- successful feed phase marks completed (Step 23).
# ---------------------------------------------------------------------------

def test_successful_feed_phase_marks_completed():
    result = calculate_binary_distillation_problem(COMPLETE_SPEC_CASE_B)
    progress = result['calculation_progress']
    # COMPLETE_SPEC_CASE_B's feed is vapor at 405 K, so per
    # tools/binary-distillation-feed-vapor-liquid.md the 313.15 K
    # reference-temperature screen also runs and completes.
    assert progress['completed_steps'] == [calc.STEP_FEED_PHASE, calc.STEP_VAPOR_CONDENSATION_SCREEN]


# ---------------------------------------------------------------------------
# Test 2 -- Case D's feed is vapor and fully (not merely partially) condenses
# at 313.15 K (liquid_fraction == 1.0, vapor_fraction == 0.0), so per
# tools/binary-distillation-condensation-edge-case.md's complete-condensation
# edge case, deterministic phase routing reports ONLY the future liquid-phase
# separation pathway -- no vapor-phase step remains, since no meaningful
# vapor phase remains. This supersedes the old case-design assumption once
# feed-phase evaluation succeeds (Step 12).
# ---------------------------------------------------------------------------

def test_case_d_has_no_executable_next_step():
    spec = dict(READY_CASE_D)
    result = calculate_binary_distillation_problem(spec)
    progress = result['calculation_progress']
    assert progress['next_step'] is None
    assert progress['next_step_available'] is False
    assert progress['remaining_steps'] == [calc.STEP_LIQUID_PHASE_SEPARATION]
    assert calc.STEP_VAPOR_PHASE_SEPARATION not in progress['remaining_steps']
    assert progress['blocked_reason'] == 'not_implemented'
    assert result['checks']['vapor_condensation_screen']['route'] == 'liquid_phase_separation'


# ---------------------------------------------------------------------------
# Test 3 -- incomplete workflow reports blocked (Step 23).
# ---------------------------------------------------------------------------

def test_incomplete_workflow_reports_blocked():
    result = calculate_binary_distillation_problem(INCOMPLETE_SPEC)
    progress = result['calculation_progress']
    assert progress['blocked_reason'] == 'workflow_not_ready'
    assert progress['completed_steps'] == []
    assert progress['next_step_available'] is False


# ---------------------------------------------------------------------------
# Test 4 -- no `would_calculate`-equivalent output list exists yet for the
# phase-routing pathways, so `remaining_outputs` is empty even though
# `remaining_steps` is non-empty (tools/binary-distillation-feed-vapor-liquid.md
# Step 12).
# ---------------------------------------------------------------------------

def test_remaining_outputs_empty_for_phase_routing_pathways():
    spec = dict(READY_CASE_D)
    result = calculate_binary_distillation_problem(spec)
    progress = result['calculation_progress']
    assert progress['remaining_steps']
    assert progress['remaining_outputs'] == []


# ---------------------------------------------------------------------------
# Test 24 -- get_binary_distillation_calculation_status() READ.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_agent_state():
    agent.reset_workflow_session()
    yield
    agent.reset_workflow_session()


def test_calculation_status_unavailable_before_any_calculation():
    result = agent.get_binary_distillation_calculation_status()
    assert result['calculation_available'] is False
    assert result['latest_calculation'] is None


def test_calculation_status_available_after_calculation():
    agent.update_binary_distillation_problem(**READY_CASE_D)
    calc_result = agent.calculate_current_binary_distillation_problem()

    status = agent.get_binary_distillation_calculation_status()
    assert status['calculation_available'] is True
    assert status['latest_calculation'] == calc_result
    assert status['message'] == calc_result['calculation_progress']['message']


# ---------------------------------------------------------------------------
# Test 25 -- reset invalidation.
# ---------------------------------------------------------------------------

def test_reset_invalidates_calculation_status():
    agent.update_binary_distillation_problem(**READY_CASE_D)
    agent.calculate_current_binary_distillation_problem()
    assert agent.get_binary_distillation_calculation_status()['calculation_available'] is True

    agent.reset_workflow_session()

    assert agent.get_binary_distillation_calculation_status()['calculation_available'] is False


# ---------------------------------------------------------------------------
# Test 26 -- WRITE invalidation: a changed engineering input after a
# calculation must not leave a stale result standing as authoritative.
# ---------------------------------------------------------------------------

def test_write_invalidates_stale_calculation_status():
    agent.update_binary_distillation_problem(**READY_CASE_D)
    agent.calculate_current_binary_distillation_problem()
    assert agent.get_binary_distillation_calculation_status()['calculation_available'] is True

    agent.update_binary_distillation_problem(feed_temperature_K=410.0)

    assert agent.get_binary_distillation_calculation_status()['calculation_available'] is False


# ---------------------------------------------------------------------------
# Fakes for agent-level `ask()` regression tests (Steps 27-30) -- same shape
# as test_binary_distillation_workflow_agent_calculation.py.
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
    """Raises if `ask()` calls `.chat()` more times than scripted -- proves
    a deterministically-routed turn never reaches the model for a tool-
    selection decision."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def chat(self, model, messages, tools=None, think=False):
        self.calls.append(tools is not None)
        if not self._responses:
            raise AssertionError('ScriptedClient ran out of scripted responses -- ask() called chat() more than expected')
        return self._responses.pop(0)


def _tool_result_names(messages):
    return [m['tool_name'] for m in messages if isinstance(m, dict) and m.get('role') == 'tool']


def _tool_result_content(messages, tool_name):
    for m in messages:
        if isinstance(m, dict) and m.get('role') == 'tool' and m.get('tool_name') == tool_name:
            return json.loads(m['content'])
    return None


def _base_messages():
    return [{'role': 'system', 'content': agent.SYSTEM_PROMPT}]


# ---------------------------------------------------------------------------
# Test 27 -- exact agent regression: complete Case D problem, "yes" runs the
# calculation, then "okay what next" routes to the calculation READ tool,
# never a fresh update_binary_distillation_problem WRITE.
# ---------------------------------------------------------------------------

def test_exact_agent_regression_ready_then_yes_then_what_next():
    state = agent.update_binary_distillation_problem(**READY_CASE_D)
    assert state['status'] == 'ready_for_calculation'

    yes_client = ScriptedClient([final('The feed is a liquid at these conditions.')])
    yes_messages = _base_messages() + [{'role': 'user', 'content': 'yes'}]
    agent.ask(yes_client, yes_messages)
    assert _tool_result_names(yes_messages) == ['calculate_current_binary_distillation_problem']

    next_client = ScriptedClient([final(
        'The feed-phase evaluation is complete. There is currently no '
        'further implemented calculation step. The remaining Case D design '
        'calculations are not yet implemented.'
    )])
    next_messages = _base_messages() + [{'role': 'user', 'content': 'okay what next'}]
    result = agent.ask(next_client, next_messages)

    assert _tool_result_names(next_messages) == ['get_binary_distillation_calculation_status']
    assert 'update_binary_distillation_problem' not in _tool_result_names(next_messages)

    progress = _tool_result_content(next_messages, 'get_binary_distillation_calculation_status')
    assert progress['calculation_available'] is True
    # READY_CASE_D's feed is vapor and fully condenses at 313.15 K, so the
    # reference-temperature screen also completes (Step 12); complete
    # condensation routes to liquid-phase separation only (Step 2 above).
    assert progress['latest_calculation']['calculation_progress']['completed_steps'] == [
        calc.STEP_FEED_PHASE, calc.STEP_VAPOR_CONDENSATION_SCREEN,
    ]
    assert progress['latest_calculation']['calculation_progress']['next_step_available'] is False
    assert progress['latest_calculation']['calculation_progress']['remaining_steps'] == [
        calc.STEP_LIQUID_PHASE_SEPARATION,
    ]
    assert progress['latest_calculation']['calculation_progress']['blocked_reason'] == 'not_implemented'

    assert 'update_binary_distillation_problem' not in result


# ---------------------------------------------------------------------------
# Test 28 -- "what next" after calculation must not re-ask for any stored
# input.
# ---------------------------------------------------------------------------

_STORED_INPUT_WORDS = (
    'components', 'feed flow', 'composition', 'temperature', 'pressure',
    'xd', 'xb', 'boilup ratio', 'reflux condition', 'optimum feed plate',
)


def test_what_next_does_not_request_stored_inputs():
    agent.update_binary_distillation_problem(**READY_CASE_D)
    agent.calculate_current_binary_distillation_problem()

    client = ScriptedClient([final(
        'Feed-phase evaluation is complete; the remaining Case D design '
        'calculation is not yet implemented.'
    )])
    messages = _base_messages() + [{'role': 'user', 'content': 'what next?'}]
    result = agent.ask(client, messages)

    lowered = result.lower()
    for word in _STORED_INPUT_WORDS:
        assert word not in lowered, f"response re-asked for '{word}': {result!r}"


# ---------------------------------------------------------------------------
# Test 29 -- progress query before any calculation has run: "what next?"
# reports feed_phase as the next available step, deterministically, without
# rerunning state collection.
# ---------------------------------------------------------------------------

def test_what_next_before_calculation_reports_feed_phase_available():
    agent.update_binary_distillation_problem(**READY_CASE_D)
    assert agent.get_binary_distillation_problem()['status'] == 'ready_for_calculation'
    assert agent.get_binary_distillation_calculation_status()['calculation_available'] is False

    client = ScriptedClient([final('The next step is a feed-phase evaluation.')])
    messages = _base_messages() + [{'role': 'user', 'content': 'what next?'}]
    agent.ask(client, messages)

    assert _tool_result_names(messages) == ['get_precalculation_progress']
    progress = _tool_result_content(messages, 'get_precalculation_progress')
    assert progress['calculation_progress']['next_step'] == calc.STEP_FEED_PHASE
    assert progress['calculation_progress']['next_step_available'] is True

    # Still not calculated -- a progress READ never executes anything.
    assert agent.get_binary_distillation_calculation_status()['calculation_available'] is False


# ---------------------------------------------------------------------------
# Test 30 -- "continue" after calculation reports no further implemented
# step, and must never silently pretend to perform Case D design.
# ---------------------------------------------------------------------------

def test_continue_after_calculation_reports_no_further_step():
    agent.update_binary_distillation_problem(**READY_CASE_D)
    agent.calculate_current_binary_distillation_problem()

    client = ScriptedClient([final(
        'No further implemented calculation step is available for this Case D problem.'
    )])
    messages = _base_messages() + [{'role': 'user', 'content': 'continue'}]
    agent.ask(client, messages)

    assert _tool_result_names(messages) == ['get_binary_distillation_calculation_status']
    progress = _tool_result_content(messages, 'get_binary_distillation_calculation_status')
    progress_state = progress['latest_calculation']['calculation_progress']
    assert progress_state['next_step_available'] is False
    assert progress_state['blocked_reason'] == 'not_implemented'
