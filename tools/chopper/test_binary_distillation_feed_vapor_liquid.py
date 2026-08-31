"""
Pipeline-level tests for the deterministic post-feed-phase routing added in
`binary_distillation_calculation.py` -- see
`tools/binary-distillation-feed-vapor-liquid.md` Step 16, Tests A, G, K
(module-level HX-screen behavior lives in `test_feed_partial_condensation.py`).
"""
import pytest

import binary_distillation_calculation as calc
import binary_distillation_workflow_agent as agent
from binary_distillation_calculation import calculate_binary_distillation_problem

PRESSURE = 101325
REFLUX = 'saturated_liquid'

# Water/Methanol at 300 K, 1 atm -- both well below their normal boiling
# points (373.1 K / 337.7 K), so this is genuinely liquid, not merely
# assumed to be.
LIQUID_SPEC = dict(
    component_names=['Water', 'Methanol'],
    component_flows={'Water': 50, 'Methanol': 50},
    component_flow_units='kmol/hr',
    pressure_Pa=PRESSURE,
    feed_temperature_K=300.0,
    reflux_condition=REFLUX,
    Lr=0.99, Hr=0.99,
    external_reflux_ratio_LD=5.0,
    use_optimum_feed_plate=True,
)

# Butane/Acetaldehyde at 405 K -- both boiling points (272.6 K / 293.4 K)
# well below 313.15 K, so this is genuinely vapor both at feed conditions
# and after the 313.15 K screen (<50% liquid -> vapor_separation_advisable).
VAPOR_LOW_LIQUID_SPEC = dict(
    component_names=['Butane', 'Acetaldehyde'],
    component_flows={'Butane': 50, 'Acetaldehyde': 50},
    component_flow_units='kmol/hr',
    pressure_Pa=PRESSURE,
    feed_temperature_K=405.0,
    reflux_condition=REFLUX,
    Lr=0.99, Hr=0.99,
    external_reflux_ratio_LD=5.0,
    use_optimum_feed_plate=True,
)


# ---------------------------------------------------------------------------
# Test A -- initial liquid feed: feed-phase succeeds, the HX screen is never
# called, route is liquid_phase_separation, implemented is False, progress
# stops after feed_phase.
# ---------------------------------------------------------------------------

def test_liquid_feed_skips_hx_screen_and_routes_to_liquid_pathway(monkeypatch):
    calls = []
    monkeypatch.setattr(
        calc, 'evaluate_vapor_feed_at_reference_temperature',
        lambda *a, **kw: calls.append((a, kw)) or (_ for _ in ()).throw(
            AssertionError('HX reference-temperature screen must not run for a liquid feed'),
        ),
    )

    result = calculate_binary_distillation_problem(LIQUID_SPEC)

    assert calls == []
    assert result['checks']['feed_phase']['valid'] is True
    assert result['checks']['feed_phase']['phase'] == 'liquid'
    assert 'vapor_condensation_screen' not in result['checks']

    routing = result['checks']['routing']
    assert routing['route'] == 'liquid_phase_separation'
    assert routing['implemented'] is False

    progress = result['calculation_progress']
    assert progress['completed_steps'] == [calc.STEP_FEED_PHASE]
    assert progress['remaining_steps'] == [calc.STEP_LIQUID_PHASE_SEPARATION]
    assert progress['blocked_reason'] == 'not_implemented'


# ---------------------------------------------------------------------------
# Vapor feed, <50% liquid at 313.15 K -- real end-to-end BioSTEAM run.
# ---------------------------------------------------------------------------

def test_vapor_feed_low_liquid_fraction_routes_to_vapor_pathway():
    result = calculate_binary_distillation_problem(VAPOR_LOW_LIQUID_SPEC)

    assert result['checks']['feed_phase']['phase'] == 'vapor'
    screen = result['checks']['vapor_condensation_screen']
    assert screen['valid'] is True
    assert screen['liquid_fraction'] < 0.50
    assert screen['route'] == 'vapor_separation_advisable'
    assert screen['implemented'] is False

    routing = result['checks']['routing']
    assert routing['route'] == 'vapor_separation_advisable'

    progress = result['calculation_progress']
    assert progress['completed_steps'] == [calc.STEP_FEED_PHASE, calc.STEP_VAPOR_CONDENSATION_SCREEN]
    assert progress['remaining_steps'] == [calc.STEP_VAPOR_PHASE_SEPARATION]
    assert progress['blocked_reason'] == 'not_implemented'


# ---------------------------------------------------------------------------
# Test G -- initially two-phase feed: no vapor-feed screening occurs, the
# existing liquid/vapor percentages are reported, route is unimplemented,
# no downstream separator runs.
# ---------------------------------------------------------------------------

def test_two_phase_feed_reports_existing_fractions_without_screening(monkeypatch):
    canned_phase_result = {
        'check': 'feed_phase', 'valid': True, 'phase': 'vapor_liquid',
        'vapor_fraction': 0.37, 'liquid_fraction': 0.63,
        'temperature_K': 350.0, 'pressure_Pa': PRESSURE,
        'components': ['Water', 'Methanol'],
        'vapor_mol': {'Water': 10.0, 'Methanol': 27.0},
        'liquid_mol': {'Water': 40.0, 'Methanol': 23.0},
        'calculation': {'type': 'VLE', 'specification': 'T_P'},
        'message': 'Feed is a vapor-liquid mixture at the specified feed conditions.',
    }
    monkeypatch.setattr(calc, 'evaluate_feed_phase', lambda *a, **kw: canned_phase_result)

    calls = []
    monkeypatch.setattr(
        calc, 'evaluate_vapor_feed_at_reference_temperature',
        lambda *a, **kw: calls.append((a, kw)) or (_ for _ in ()).throw(
            AssertionError('HX reference-temperature screen must not run for an already two-phase feed'),
        ),
    )

    result = calculate_binary_distillation_problem(LIQUID_SPEC)

    assert calls == []
    assert 'vapor_condensation_screen' not in result['checks']

    routing = result['checks']['routing']
    assert routing['route'] == 'two_phase_feed'
    assert routing['implemented'] is False
    assert routing['liquid_fraction'] == 0.63
    assert routing['vapor_fraction'] == 0.37

    progress = result['calculation_progress']
    assert progress['remaining_steps'] == [calc.STEP_TWO_PHASE_ROUTING]
    assert progress['blocked_reason'] == 'not_implemented'


# ---------------------------------------------------------------------------
# Test K -- "what next?" continuity after a liquid-route calculation: the
# stored result answers the follow-up without rebuilding the problem,
# re-asking for inputs, or rerunning BioSTEAM.
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

    def chat(self, model, messages, tools=None, think=False):
        if not self._responses:
            raise AssertionError('ScriptedClient ran out of scripted responses')
        return self._responses.pop(0)


def _tool_result_names(messages):
    return [m['tool_name'] for m in messages if isinstance(m, dict) and m.get('role') == 'tool']


def _base_messages():
    return [{'role': 'system', 'content': agent.SYSTEM_PROMPT}]


@pytest.fixture(autouse=True)
def _reset_agent_state():
    agent.reset_workflow_session()
    yield
    agent.reset_workflow_session()


def test_what_next_after_liquid_route_uses_stored_result():
    agent.update_binary_distillation_problem(**LIQUID_SPEC)
    calc_result = agent.calculate_current_binary_distillation_problem()
    assert calc_result['checks']['routing']['route'] == 'liquid_phase_separation'

    client = ScriptedClient([final(
        'The feed is liquid; it should proceed to the (not yet implemented) '
        'liquid-phase separation pathway.'
    )])
    messages = _base_messages() + [{'role': 'user', 'content': 'what next?'}]
    agent.ask(client, messages)

    assert _tool_result_names(messages) == ['get_binary_distillation_calculation_status']
    assert 'update_binary_distillation_problem' not in _tool_result_names(messages)


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
