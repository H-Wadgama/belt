"""
Acceptance tests for
tools/binary-distillation-separating-feed-phase-from-options-a-d.md --
feed-phase screening and Design Option A-D assessment are independent
deterministic branches over the CASE-DEFINING fields (xD/xB/Lr/Hr, a
product flow, a boilup ratio) and `use_optimum_feed_plate` -- neither
gates the other over those.

Updated by tools/binary-distillation-issues-9-1-2026-eighth.md Step 2:
`reflux_condition` is no longer exclusive to `design_assessment` -- feed
screening now also requires it (a report must never say feed screening is
"ready" while elsewhere still asking for reflux condition). See
`test_binary_distillation_issues_eighth.py` for the dedicated regression
tests covering that change; this file's fixtures below all supply
`reflux_condition` for that reason, except where a test is specifically
about its absence.

Run with:
    pytest tools/chopper/test_binary_distillation_feed_design_separation.py -v
"""
import pytest

import binary_distillation_workflow_agent as agent
from binary_distillation_calculation import calculate_binary_distillation_problem
from binary_distillation_workflow import assess_binary_distillation_problem
from biosteam_feed import BiosteamFeedError, build_biosteam_feed

PRESSURE = 101325
REFLUX = 'saturated_liquid'

# The exact worked example from the task doc's Step 30/Step 31 -- feed
# fully specified, reflux condition given, NO other Design Option field at
# all.
WATER_ETHANOL_355K = {
    'component_names': ['Water', 'Ethanol'],
    'component_flows': {'Water': 50, 'Ethanol': 50},
    'component_flow_units': 'kmol/hr',
    'pressure_Pa': PRESSURE,
    'feed_temperature_K': 355.0,
    'reflux_condition': REFLUX,
}

# Case D worked example from the task doc's Step 34 -- feed AND design both
# fully specified.
METHANOL_WATER_400K_CASE_D = {
    'component_names': ['Methanol', 'Water'],
    'component_flows': {'Methanol': 50, 'Water': 50},
    'component_flow_units': 'kmol/hr',
    'pressure_Pa': PRESSURE,
    'feed_temperature_K': 400.0,
    'reflux_condition': REFLUX,
    'xD': 0.95, 'xB': 0.01, 'boilup_ratio_VB': 1.2,
    'use_optimum_feed_plate': True,
}


# ---------------------------------------------------------------------------
# 1 -- feed ready + no design signal at all (Step 30).
# ---------------------------------------------------------------------------

def test_feed_ready_no_design_signal():
    result = assess_binary_distillation_problem(dict(WATER_ETHANOL_355K))
    assert result['feed_screening']['ready'] is True
    assert result['feed_screening']['missing_inputs'] == []

    da = result['design_assessment']
    assert da['complete'] is False
    assert da['design_option'] is None
    assert set(da['design_option_candidates']) == {'A', 'B', 'C', 'D'}


# ---------------------------------------------------------------------------
# 2 -- feed ready + partial design (xD only) -- Step 33.
# ---------------------------------------------------------------------------

def test_feed_ready_partial_design():
    spec = dict(WATER_ETHANOL_355K, xD=0.95)
    result = assess_binary_distillation_problem(spec)
    assert result['feed_screening']['ready'] is True

    da = result['design_assessment']
    assert da['complete'] is False
    assert da['design_option'] is None
    # xD alone (comp_given == 1) keeps Case C viable too (it needs only ONE
    # composition), matching identify_case()'s existing candidate logic.
    assert set(da['design_option_candidates']) == {'A', 'C', 'D'}


# ---------------------------------------------------------------------------
# 3 -- feed ready + complete design (Case D) -- Step 34.
# ---------------------------------------------------------------------------

def test_feed_ready_and_design_complete_simultaneously():
    result = assess_binary_distillation_problem(dict(METHANOL_WATER_400K_CASE_D))
    assert result['feed_screening']['ready'] is True

    da = result['design_assessment']
    assert da['design_option'] == 'D'
    assert da['complete'] is True
    # Legacy field still agrees, for good measure.
    assert result['status'] == 'ready_for_calculation'


# ---------------------------------------------------------------------------
# 4 -- complete design + missing feed thermal condition -- Step 32.
# ---------------------------------------------------------------------------

def test_design_complete_feed_incomplete_missing_thermal_condition():
    spec = dict(METHANOL_WATER_400K_CASE_D)
    del spec['feed_temperature_K']
    result = assess_binary_distillation_problem(spec)

    assert result['feed_screening']['ready'] is False
    assert result['design_assessment']['design_option'] == 'D'
    assert result['design_assessment']['complete'] is True


# ---------------------------------------------------------------------------
# 5 -- complete design + missing flow units.
# ---------------------------------------------------------------------------

def test_design_complete_feed_incomplete_missing_units():
    spec = dict(METHANOL_WATER_400K_CASE_D)
    del spec['component_flow_units']
    result = assess_binary_distillation_problem(spec)

    fs = result['feed_screening']
    assert fs['ready'] is False
    assert fs['status'] == 'need_feed_units'
    assert result['design_assessment']['design_option'] == 'D'
    assert result['design_assessment']['complete'] is True


# ---------------------------------------------------------------------------
# 6 -- missing reflux_condition blocks BOTH branches -- Step 36, updated by
# tools/binary-distillation-issues-9-1-2026-eighth.md Step 2 (feed screening
# and design assessment must never disagree about reflux_condition).
# ---------------------------------------------------------------------------

def test_feed_and_design_both_blocked_by_missing_reflux_condition():
    spec = dict(METHANOL_WATER_400K_CASE_D)
    del spec['reflux_condition']
    result = assess_binary_distillation_problem(spec)

    fs = result['feed_screening']
    assert fs['ready'] is False
    assert 'reflux_condition' in fs['missing_inputs']

    da = result['design_assessment']
    assert da['design_option'] == 'D'
    assert da['complete'] is False
    assert da['reflux_condition_given'] is False
    assert 'reflux_condition' in da['missing_inputs']


# ---------------------------------------------------------------------------
# 7 -- feed ready + missing optimum-feed-plate confirmation -- Step 37.
# ---------------------------------------------------------------------------

def test_feed_ready_missing_optimum_feed_plate():
    spec = dict(METHANOL_WATER_400K_CASE_D)
    del spec['use_optimum_feed_plate']
    result = assess_binary_distillation_problem(spec)

    assert result['feed_screening']['ready'] is True
    da = result['design_assessment']
    assert da['design_option'] == 'D'
    assert da['complete'] is False
    assert da['optimum_feed_plate_confirmed'] is None
    assert 'use_optimum_feed_plate' in da['missing_inputs']


# ---------------------------------------------------------------------------
# 8 -- no default to Design Option A -- Step 38.
# ---------------------------------------------------------------------------

def test_no_default_to_design_option_a():
    result = assess_binary_distillation_problem(dict(WATER_ETHANOL_355K))
    da = result['design_assessment']
    assert da['design_option'] != 'A'
    assert da['design_option'] is None
    for letter in ('A', 'B', 'C', 'D'):
        assert letter in da['design_option_candidates']


# ---------------------------------------------------------------------------
# 9 -- CORE ACCEPTANCE TEST (Step 31): a feed-ready/no-Design-Option problem
# actually runs the real BioSTEAM feed-phase evaluation.
# ---------------------------------------------------------------------------

def test_calculate_runs_real_biosteam_with_no_design_option():
    result = calculate_binary_distillation_problem(dict(WATER_ETHANOL_355K))

    assert result['calculation_performed'] is True
    assert result['workflow']['feed_screening']['ready'] is True
    assert result['workflow']['design_assessment']['complete'] is False
    assert result['workflow']['design_assessment']['design_option'] is None

    feed_phase = result['checks']['feed_phase']
    assert feed_phase['valid'] is True
    assert feed_phase['phase'] in {'liquid', 'vapor', 'vapor_liquid'}


# ---------------------------------------------------------------------------
# 10 -- the inverse: design-complete/feed-incomplete never touches BioSTEAM.
# ---------------------------------------------------------------------------

def test_calculate_does_not_run_when_design_complete_but_feed_incomplete():
    spec = dict(METHANOL_WATER_400K_CASE_D)
    del spec['feed_temperature_K']
    result = calculate_binary_distillation_problem(spec)

    assert result['calculation_performed'] is False
    assert result['checks'] == {}
    assert result['workflow']['design_assessment']['design_option'] == 'D'
    assert result['workflow']['design_assessment']['complete'] is True
    assert result['workflow']['feed_screening']['ready'] is False


# ---------------------------------------------------------------------------
# 11 -- build_biosteam_feed gate.
# ---------------------------------------------------------------------------

def test_build_biosteam_feed_succeeds_with_feed_ready_design_incomplete():
    spec = dict(WATER_ETHANOL_355K)
    assessment = assess_binary_distillation_problem(spec)
    assert assessment['design_assessment']['complete'] is False

    feed = build_biosteam_feed(spec, assessment)
    assert feed is not None
    assert set(feed.chemicals.IDs) >= {'Water', 'Ethanol'}


def test_build_biosteam_feed_raises_when_feed_screening_not_ready():
    spec = dict(METHANOL_WATER_400K_CASE_D)
    del spec['feed_temperature_K']
    assessment = assess_binary_distillation_problem(spec)
    assert assessment['feed_screening']['ready'] is False

    with pytest.raises(BiosteamFeedError):
        build_biosteam_feed(spec, assessment)


# ---------------------------------------------------------------------------
# 12 -- early Design Option facts retained once feed later completes.
# ---------------------------------------------------------------------------

def test_early_design_facts_retained_across_turns():
    spec = {'xD': 0.95, 'xB': 0.01}
    spec.update(component_names=['Methanol', 'Water'])
    spec.update(component_flows={'Methanol': 50, 'Water': 50}, component_flow_units='kmol/hr')
    spec.update(pressure_Pa=PRESSURE, feed_temperature_K=400.0)
    spec.update(boilup_ratio_VB=1.2)

    result = assess_binary_distillation_problem(spec)
    # No reflux_condition given yet -- feed screening is NOT ready (Step 2).
    assert result['feed_screening']['ready'] is False
    assert 'reflux_condition' in result['feed_screening']['missing_inputs']
    assert result['design_assessment']['design_option'] == 'D'
    # Still not complete -- reflux_condition and optimum-feed-plate remain.
    assert result['design_assessment']['complete'] is False

    result = assess_binary_distillation_problem(dict(spec, reflux_condition=REFLUX))
    # Once reflux_condition is supplied, feed screening becomes ready even
    # though optimum-feed-plate confirmation (a design-only field) is still
    # missing -- the two branches remain independent over THAT dimension.
    assert result['feed_screening']['ready'] is True
    assert result['design_assessment']['complete'] is False
    assert result['design_assessment']['optimum_feed_plate_confirmed'] is None


# ---------------------------------------------------------------------------
# 13 -- terminology: "Design Option" appears, "Wankat Case" does not, in
# user-facing text; Wankat provenance remains intact.
# ---------------------------------------------------------------------------

def test_ready_for_calculation_message_uses_design_option_terminology():
    result = assess_binary_distillation_problem(dict(METHANOL_WATER_400K_CASE_D))
    assert result['status'] == 'ready_for_calculation'
    assert 'Design Option D' in result['message']
    assert 'Wankat Case' not in result['message']


def test_need_design_definition_message_uses_design_option_terminology():
    result = assess_binary_distillation_problem(dict(WATER_ETHANOL_355K))
    assert 'Design Option' in result['design_assessment']['message']
    assert 'Wankat Case' not in result['design_assessment']['message']


def test_system_prompt_uses_design_option_not_wankat_case():
    assert 'Design Option' in agent.SYSTEM_PROMPT
    assert 'Wankat Case' not in agent.SYSTEM_PROMPT
    assert 'Wankat case' not in agent.SYSTEM_PROMPT


def test_wankat_provenance_remains():
    result = assess_binary_distillation_problem(dict(WATER_ETHANOL_355K))
    provenance = result['provenance']
    assert 'Wankat' in provenance['source']
    assert 'Wankat' in provenance['essential_inputs']
    assert 'Wankat' in provenance['design_cases']


# ---------------------------------------------------------------------------
# 14 -- agent-level: "what next?" before any calculation reports feed_phase
# available as soon as feed screening alone is ready (design incomplete).
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_agent_state():
    agent.reset_workflow_session()
    yield
    agent.reset_workflow_session()


def test_precalculation_progress_available_with_design_incomplete():
    agent.update_binary_distillation_problem(**WATER_ETHANOL_355K)
    state = agent.get_binary_distillation_problem()
    assert state['feed_screening']['ready'] is True
    assert state['design_assessment']['complete'] is False

    progress = agent.get_precalculation_progress()
    assert progress['calculation_progress']['next_step_available'] is True
    assert progress['calculation_progress']['next_step'] == 'feed_phase'


# ---------------------------------------------------------------------------
# 15 -- agent-level: a plain feed-phase question runs the calculation once
# feed screening alone is ready, without requiring reflux_condition or a
# completed Design Option.
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


def _tool_result_names(messages):
    return [m['tool_name'] for m in messages if isinstance(m, dict) and m.get('role') == 'tool']


def _base_messages():
    return [{'role': 'system', 'content': agent.SYSTEM_PROMPT}]


def test_feed_phase_question_runs_calculation_without_design_option():
    agent.update_binary_distillation_problem(**WATER_ETHANOL_355K)
    assert agent.get_binary_distillation_problem()['status'] != 'ready_for_calculation'

    client = ScriptedClient([final('The feed is a liquid-vapor mixture at these conditions.')])
    messages = _base_messages() + [{'role': 'user', 'content': 'what is the feed phase?'}]

    result = agent.ask(client, messages)

    assert _tool_result_names(messages) == ['calculate_current_binary_distillation_problem']
    assert client.calls == [False]
    assert result == 'The feed is a liquid-vapor mixture at these conditions.'


def test_go_ahead_runs_calculation_without_design_option():
    agent.update_binary_distillation_problem(**WATER_ETHANOL_355K)

    client = ScriptedClient([final('Feed-phase check complete.')])
    messages = _base_messages() + [{'role': 'user', 'content': 'go ahead'}]

    agent.ask(client, messages)

    assert _tool_result_names(messages) == ['calculate_current_binary_distillation_problem']


# ---------------------------------------------------------------------------
# 16 -- pending-request resolution still wins over the feed-ready-gated
# proceed trigger (regression on the reordered ask()).
# ---------------------------------------------------------------------------

def test_pending_optimum_feed_plate_wins_over_proceed_trigger():
    state = agent.update_binary_distillation_problem(
        component_names=['Methanol', 'Water'], component_flows={'Methanol': 50, 'Water': 50},
        component_flow_units='kmol/hr',
        pressure_Pa=PRESSURE, feed_temperature_K=400.0, reflux_condition=REFLUX,
        xD=0.95, xB=0.01, boilup_ratio_VB=1.2,
    )
    assert state['feed_screening']['ready'] is True
    assert state['pending_request']['field'] == 'use_optimum_feed_plate'

    client = ScriptedClient([final('Optimum feed plate: confirmed.')])
    messages = _base_messages() + [{'role': 'user', 'content': 'yes'}]

    agent.ask(client, messages)

    assert _tool_result_names(messages) == ['update_binary_distillation_problem']
    post_state = agent.get_binary_distillation_problem()
    assert post_state['optimum_feed_plate_confirmed'] is True


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
