"""
Pipeline-level tests for the deterministic post-feed-phase routing added in
`binary_distillation_calculation.py` -- see
`tools/binary-distillation-feed-vapor-liquid.md` Step 16 and
`tools/binary-distillation-vapor-liquid-dead-end.md` Step 16, Tests A-D, F-K
(module-level HX-screen behavior lives in `test_feed_partial_condensation.py`).
"""
import feed_partial_condensation as fpc
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

# Water/Ethanol at 355 K, 1 atm -- tools/binary-distillation-vapor-liquid-
# dead-end.md Step 17's worked example. Genuinely vapor_liquid at the stated
# feed conditions (~25.5 mol% liquid / ~74.5 mol% vapor), and cooling the
# overall feed to 313.15 K fully condenses it (conditioned liquid_fraction
# == 1.0), landing in the >=50% branch.
TWO_PHASE_SPEC = dict(
    component_names=['Water', 'Ethanol'],
    component_flows={'Water': 50, 'Ethanol': 50},
    component_flow_units='kmol/hr',
    pressure_Pa=PRESSURE,
    feed_temperature_K=355.0,
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
# tools/binary-distillation-vapor-liquid-dead-end.md Step 16 -- an initially
# two-phase feed no longer dead-ends; it runs the same reference-temperature
# conditioning pathway as an initially vapor feed.
# ---------------------------------------------------------------------------

# Test A -- initially two-phase feed no longer stops: the HX screen IS
# called, the old immediate `two_phase_feed` route is gone, and routing is
# based on the conditioned split.
def test_two_phase_feed_no_longer_stops_and_routes_through_conditioning(monkeypatch):
    calls = []
    real_fn = calc.evaluate_vapor_feed_at_reference_temperature

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return real_fn(*args, **kwargs)

    monkeypatch.setattr(calc, 'evaluate_vapor_feed_at_reference_temperature', spy)

    result = calculate_binary_distillation_problem(TWO_PHASE_SPEC)

    assert result['checks']['feed_phase']['phase'] == 'vapor_liquid'
    assert len(calls) == 1

    screen = result['checks']['vapor_condensation_screen']
    assert screen['valid'] is True

    routing = result['checks']['routing']
    assert routing['route'] != 'two_phase_feed'
    assert routing['route'] == screen['route']
    assert routing['liquid_fraction'] == screen['liquid_fraction']


# Test B -- the original feed-phase result (at the stated feed conditions)
# remains stored and inspectable, distinct from the conditioned result.
def test_two_phase_feed_preserves_original_feed_phase_result():
    result = calculate_binary_distillation_problem(TWO_PHASE_SPEC)

    feed_phase = result['checks']['feed_phase']
    assert feed_phase['phase'] == 'vapor_liquid'
    assert feed_phase['liquid_fraction'] == pytest.approx(0.254561370585366)
    assert feed_phase['vapor_fraction'] == pytest.approx(0.745438629414634)

    # The conditioned split is a materially different, separately-reported
    # result -- not the same numbers reused/overwritten.
    screen = result['checks']['vapor_condensation_screen']
    assert screen['liquid_fraction'] != feed_phase['liquid_fraction']


# Test C -- conditioned liquid fraction >= 50%: both future-separation
# pathways are reported, neither implemented.
def test_two_phase_feed_conditioned_high_liquid_fraction_routes_to_both_pathways():
    result = calculate_binary_distillation_problem(TWO_PHASE_SPEC)

    screen = result['checks']['vapor_condensation_screen']
    assert screen['liquid_fraction'] >= 0.50

    routing = result['checks']['routing']
    assert routing['route'] == 'liquid_and_vapor_separation_future'
    assert routing['implemented'] is False

    progress = result['calculation_progress']
    assert progress['completed_steps'] == [calc.STEP_FEED_PHASE, calc.STEP_VAPOR_CONDENSATION_SCREEN]
    assert progress['remaining_steps'] == [calc.STEP_LIQUID_PHASE_SEPARATION, calc.STEP_VAPOR_PHASE_SEPARATION]
    assert progress['blocked_reason'] == 'not_implemented'
    assert not hasattr(calc, 'STEP_TWO_PHASE_ROUTING')


# Test D -- conditioned liquid fraction < 50%: vapor-phase separation
# advisable, marked unimplemented. Uses a canned two-phase HX outlet split
# (via the module's own `bst.units.HXutility` seam) rather than hunting for a
# real binary pair whose overall feed happens to stay mostly vapor after
# cooling to 313.15 K.
def test_two_phase_feed_conditioned_low_liquid_fraction_routes_to_vapor_pathway(monkeypatch):
    mol = {('g', 'Water'): 10.0, ('g', 'Ethanol'): 60.0, ('l', 'Water'): 20.0, ('l', 'Ethanol'): 10.0}
    monkeypatch.setattr(fpc.bst.units, 'HXutility', _fake_hx_factory(mol))

    result = calculate_binary_distillation_problem(TWO_PHASE_SPEC)

    screen = result['checks']['vapor_condensation_screen']
    assert screen['valid'] is True
    assert screen['liquid_fraction'] == pytest.approx(0.30)
    assert screen['route'] == 'vapor_separation_advisable'
    assert screen['implemented'] is False

    routing = result['checks']['routing']
    assert routing['route'] == 'vapor_separation_advisable'

    progress = result['calculation_progress']
    assert progress['remaining_steps'] == [calc.STEP_VAPOR_PHASE_SEPARATION]
    assert progress['blocked_reason'] == 'not_implemented'


# Test E -- exactly 50% conditioned liquid enters the >= 0.50 branch, even
# for an initially two-phase feed.
def test_two_phase_feed_conditioned_exactly_50_percent_liquid(monkeypatch):
    mol = {('g', 'Water'): 50.0, ('g', 'Ethanol'): 0.0, ('l', 'Water'): 0.0, ('l', 'Ethanol'): 50.0}
    monkeypatch.setattr(fpc.bst.units, 'HXutility', _fake_hx_factory(mol))

    result = calculate_binary_distillation_problem(TWO_PHASE_SPEC)

    screen = result['checks']['vapor_condensation_screen']
    assert screen['liquid_fraction'] == pytest.approx(0.50)
    assert screen['route'] == 'liquid_and_vapor_separation_future'

    routing = result['checks']['routing']
    assert routing['route'] == 'liquid_and_vapor_separation_future'


def _fake_hx_factory(mol):
    class FakeOutlet:
        def __init__(self, mol):
            self.imol = mol

    class FakeHX:
        def __init__(self, outlet):
            self.outs = [outlet]

        def simulate(self):
            pass

    def factory(*, ins, T, rigorous=True):
        return FakeHX(FakeOutlet(mol))
    return factory


# Test F -- the original feed state is untouched by conditioning an initially
# two-phase feed (checked here at the workflow-spec level: repeating the
# calculation from the same spec reproduces the same original feed-phase
# numbers -- the underlying immutability guarantee itself is exercised
# directly in test_feed_partial_condensation.py).
def test_two_phase_feed_original_spec_reproducible():
    first = calculate_binary_distillation_problem(TWO_PHASE_SPEC)
    second = calculate_binary_distillation_problem(TWO_PHASE_SPEC)
    assert first['checks']['feed_phase']['liquid_fraction'] == second['checks']['feed_phase']['liquid_fraction']
    assert first['checks']['feed_phase']['temperature_K'] == second['checks']['feed_phase']['temperature_K'] == 355.0


# Test I -- a conditioning failure for an initially two-phase feed is
# reported deterministically; no downstream route is fabricated.
def test_two_phase_feed_conditioning_failure_is_deterministic(monkeypatch):
    def raising_factory(*, ins, T, rigorous=True):
        raise RuntimeError('boom')
    monkeypatch.setattr(fpc.bst.units, 'HXutility', raising_factory)

    result = calculate_binary_distillation_problem(TWO_PHASE_SPEC)

    screen = result['checks']['vapor_condensation_screen']
    assert screen['valid'] is False
    assert 'boom' in screen['message']
    assert 'routing' not in result['checks']

    progress = result['calculation_progress']
    assert progress['blocked_reason'] == 'calculation_failed'
    assert progress['remaining_steps'] == []


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


# Test K -- "what next?" continuity after a two-phase -> conditioning route
# uses the stored conditioned result, without rerunning the HX screen.
def test_what_next_after_two_phase_conditioning_route_uses_stored_result():
    agent.update_binary_distillation_problem(**TWO_PHASE_SPEC)
    calc_result = agent.calculate_current_binary_distillation_problem()
    assert calc_result['checks']['routing']['route'] == 'liquid_and_vapor_separation_future'

    client = ScriptedClient([final(
        '100% of the feed liquefies at 313.15 K; both a future liquid-phase '
        'and a future vapor-phase separation are indicated, neither '
        'implemented yet.'
    )])
    messages = _base_messages() + [{'role': 'user', 'content': 'what next?'}]
    agent.ask(client, messages)

    assert _tool_result_names(messages) == ['get_binary_distillation_calculation_status']
    assert 'update_binary_distillation_problem' not in _tool_result_names(messages)


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
