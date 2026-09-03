"""
Regression tests for tools/binary-distillation-issues-9-1-2026-eighth.md
("Fix the Current Binary-Distillation Workflow Without Making the
Architecture Brittle").

Covers the four fixed problems, one test group per problem (the doc's own
Step 8 grouping):
  A -- an unresolved pending question always wins over a generic short
       reply ("yes", "sure", "go ahead", ...); it must never accidentally
       trigger a calculation.
  B -- feed screening now requires `reflux_condition` (agrees with
       design_assessment/pending_request instead of contradicting them).
  C -- only the small, stable ACTION_REGISTRY verbs are ever accepted as a
       model-proposed action; internal Python function names are rejected
       and never appear in the model-facing prompt.
  D -- a workflow-DEFINITION question ("what does Case A need?", "what are
       the inputs for the four cases?") is answered from the deterministic
       Case A-D definitions, never treated as a lookup of a nonexistent
       stored variable.

Plus one scripted, end-to-end replay of the Step 9 acceptance conversation
(everything Python can decide deterministically; the one turn that
genuinely requires interpretation -- "reflux is saturated liquid" -- is
scripted rather than live-Qwen, per this file's convention elsewhere of not
depending on a running Ollama server).

Run with:
    pytest tools/chopper/test_binary_distillation_issues_eighth.py -v
"""
import pytest

import binary_distillation_workflow_agent as agent
from binary_distillation_workflow import assess_binary_distillation_problem
from problem_field_registry import ACTION_REGISTRY, ACTIVE_WORKFLOW_SCHEMA, PROBLEM_FIELD_REGISTRY
from problem_spec import CASE_FIELD_SUMMARY
from turn_intent import build_field_catalog_prompt
from turn_intent_test_fakes import ScriptedClient, final, intent_response
from turn_transaction import validate_turn_intent

PRESSURE = 101325
REFLUX = 'saturated_liquid'

FEED_NO_REFLUX = dict(
    component_names=['Water', 'Ethanol'],
    component_flows={'Water': 50, 'Ethanol': 50}, component_flow_units='kmol/hr',
    pressure_Pa=PRESSURE, feed_temperature_K=355.0,
)


@pytest.fixture(autouse=True)
def _reset_state():
    agent.reset_workflow_session()
    yield
    agent.reset_workflow_session()


def _base_messages():
    return [{'role': 'system', 'content': agent.SYSTEM_PROMPT}]


def _tool_result_names(messages):
    return [m['tool_name'] for m in messages if isinstance(m, dict) and m.get('role') == 'tool']


# ---------------------------------------------------------------------------
# Test Group A -- unanswered question has priority (Step 1/8).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('reply', ['Yes', 'yeah', 'sure', 'okay', 'go ahead'])
def test_generic_short_reply_never_bypasses_a_pending_string_choice(reply):
    state = agent.update_binary_distillation_problem(**FEED_NO_REFLUX)
    assert state['pending_request'] == {
        'field': 'reflux_condition', 'request_type': 'string_choice',
        'prompt': state['pending_request']['prompt'],
        'allowed_values': ['saturated_liquid'],
    }
    assert state['feed_screening']['ready'] is False

    # NO scripted responses -- if `ask()` reached the model at all (fast
    # path failed to intercept), ScriptedClient raises instead of silently
    # returning something plausible-looking.
    client = ScriptedClient([])
    messages = _base_messages() + [{'role': 'user', 'content': reply}]

    result = agent.ask(client, messages)

    assert client.calls == []
    assert _tool_result_names(messages) == []  # no WRITE, no CALCULATE ran
    assert result == state['pending_request']['prompt']

    post_state = agent.get_binary_distillation_problem()
    assert post_state['feed']['component_names'] == ['Water', 'Ethanol']  # unchanged
    assert post_state.get('reflux_condition') is None or 'reflux_condition' not in post_state
    assert post_state['feed_screening']['ready'] is False
    assert agent.get_binary_distillation_calculation_status()['calculation_available'] is False


def test_explicit_reflux_restatement_is_saved_not_treated_as_generic_reply():
    agent.update_binary_distillation_problem(**FEED_NO_REFLUX)

    client = ScriptedClient([
        intent_response(updates=[{'field': 'reflux_condition', 'value': 'saturated_liquid'}]),
        final('Reflux condition saved; feed screening is now ready.'),
    ])
    messages = _base_messages() + [{'role': 'user', 'content': 'reflux is saturated liquid'}]

    agent.ask(client, messages)

    state = agent.get_binary_distillation_problem()
    assert state['design_assessment']['reflux_condition_given'] is True
    assert state['design_assessment']['reflux_condition_valid'] is True
    assert state['feed_screening']['ready'] is True


def test_existing_boolean_and_float_pending_replies_still_resolve_deterministically():
    # boolean_confirmation pending -- unaffected by the new generic-reply gate.
    agent.update_binary_distillation_problem(
        component_names=['Methanol', 'Water'], component_flows={'Methanol': 50, 'Water': 50},
        component_flow_units='kmol/hr', pressure_Pa=PRESSURE, feed_temperature_K=400.0,
        reflux_condition=REFLUX, xD=0.95, xB=0.01, boilup_ratio_VB=1.2,
    )
    assert agent.get_binary_distillation_problem()['pending_request']['field'] == 'use_optimum_feed_plate'

    client = ScriptedClient([final('Optimum feed plate: confirmed.')])
    messages = _base_messages() + [{'role': 'user', 'content': 'yes'}]
    agent.ask(client, messages)

    assert _tool_result_names(messages) == ['update_binary_distillation_problem']
    assert agent.get_binary_distillation_problem()['optimum_feed_plate_confirmed'] is True


def test_float_pending_reply_still_resolves_deterministically():
    agent.update_binary_distillation_problem(
        component_names=['Methanol', 'Water'], component_flows={'Methanol': 50, 'Water': 50},
        component_flow_units='kmol/hr', pressure_Pa=PRESSURE, feed_temperature_K=400.0,
        reflux_condition=REFLUX, Lr=0.99, external_reflux_ratio_LD=3.0,
    )
    assert agent.get_binary_distillation_problem()['pending_request']['field'] == 'Hr'

    client = ScriptedClient([final('Hr recorded.')])
    messages = _base_messages() + [{'role': 'user', 'content': '0.98'}]
    agent.ask(client, messages)

    assert _tool_result_names(messages) == ['update_binary_distillation_problem']
    assert agent._workflow_state['Hr'] == 0.98


def test_pending_reask_never_fires_when_nothing_is_pending():
    """A generic 'yes' with NO live pending_request and a feed-ready state
    is still read as 'proceed' (Step 1's own rule 5) -- this is the existing
    `_PROCEED_PHRASES` behavior, unaffected by the new gate."""
    agent.update_binary_distillation_problem(**dict(FEED_NO_REFLUX, reflux_condition=REFLUX))
    state = agent.get_binary_distillation_problem()
    assert state['pending_request'] is None
    assert state['feed_screening']['ready'] is True

    client = ScriptedClient([final('Feed-phase check complete.')])
    messages = _base_messages() + [{'role': 'user', 'content': 'yes'}]
    agent.ask(client, messages)

    assert _tool_result_names(messages) == ['calculate_current_binary_distillation_problem']


# ---------------------------------------------------------------------------
# Test Group B -- feed screening requires reflux_condition (Step 2/8).
# ---------------------------------------------------------------------------

def test_feed_screening_not_ready_without_reflux_condition():
    result = assess_binary_distillation_problem(dict(FEED_NO_REFLUX))
    assert result['feed_screening']['ready'] is False
    assert 'reflux_condition' in result['feed_screening']['missing_inputs']
    assert result['feed_screening']['status'] == 'need_reflux_condition'


def test_feed_screening_ready_once_reflux_condition_given():
    result = assess_binary_distillation_problem(dict(FEED_NO_REFLUX, reflux_condition=REFLUX))
    assert result['feed_screening']['ready'] is True
    assert result['feed_screening']['missing_inputs'] == []


def test_feed_screening_rejects_unsupported_reflux_condition_no_silent_substitution():
    result = assess_binary_distillation_problem(dict(FEED_NO_REFLUX, reflux_condition='total_reflux'))
    assert result['feed_screening']['ready'] is False
    assert 'reflux_condition_invalid' in result['feed_screening']['missing_inputs']
    # Never silently substituted with the one supported value.
    assert result['feed']['component_names'] == ['Water', 'Ethanol']  # sanity: feed itself untouched


def test_feed_screening_and_top_level_status_never_disagree_about_reflux_condition():
    """The exact contradiction the issue doc complains about: feed_screening
    must never report ready while the legacy `status`/`pending_request`
    (or `design_assessment`) is still asking for reflux_condition."""
    result = assess_binary_distillation_problem(dict(FEED_NO_REFLUX))
    assert result['feed_screening']['ready'] is False
    assert result['status'] == 'need_essential_inputs'
    assert result['pending_request']['field'] == 'reflux_condition'
    assert result['design_assessment']['reflux_condition_given'] is False


# ---------------------------------------------------------------------------
# Test Group C -- only stable ACTION_REGISTRY verbs are ever accepted
# (Step 3/8). Most of this was already true going into this round (Round 2's
# TurnIntent/ACTION_REGISTRY design) -- these tests pin it down explicitly
# against the exact internal function name that leaked in the live failure.
# ---------------------------------------------------------------------------

_INTERNAL_FUNCTION_NAME = 'calculate_current_binary_distillation_problem'


def test_calculate_current_step_is_accepted():
    transaction = validate_turn_intent(
        {'version': 1, 'updates': [], 'queries': [], 'action': {'name': 'calculate_current_step'}},
        ACTIVE_WORKFLOW_SCHEMA,
    )
    assert transaction['action'] == {'name': 'calculate_current_step', 'arguments': {}}
    assert transaction['action_error'] is None


def test_internal_function_name_is_rejected_as_an_action():
    transaction = validate_turn_intent(
        {'version': 1, 'updates': [], 'queries': [], 'action': {'name': _INTERNAL_FUNCTION_NAME}},
        ACTIVE_WORKFLOW_SCHEMA,
    )
    assert transaction['action'] is None
    assert transaction['action_error'] == {'error': 'unknown_action', 'name': _INTERNAL_FUNCTION_NAME}


def test_internal_function_name_never_appears_in_the_interpretation_prompt():
    """The interpretation call (`propose_turn_intent`, format-constrained
    structured output) is the ONE channel where Qwen actually decides an
    action name -- its system prompt is built entirely from
    `build_field_catalog_prompt()` (tools/binary-distillation-issues-9-1-
    2026-fifth.md deliberately excludes the narration-oriented SYSTEM_PROMPT
    from it). That is where the internal name must never appear. (The
    narration-only `SYSTEM_PROMPT` legitimately mentions these Python
    function names as human-readable reference text -- narration turns never
    have `tools=`/`format=`, so the model is never asked to choose one.)"""
    catalog = build_field_catalog_prompt()
    assert _INTERNAL_FUNCTION_NAME not in catalog
    # The only names the model is ever told it may PROPOSE are ACTION_REGISTRY's own.
    for name in ACTION_REGISTRY:
        assert name in catalog


# ---------------------------------------------------------------------------
# Test Group D -- state queries (Type A) vs. workflow-definition questions
# (Type B) (Step 4/5/8).
# ---------------------------------------------------------------------------

def test_type_a_state_query_reads_a_saved_value():
    agent.update_binary_distillation_problem(pressure_Pa=PRESSURE)

    client = ScriptedClient([intent_response(queries=[{'field': 'pressure_Pa'}])])
    messages = _base_messages() + [{'role': 'user', 'content': 'what pressure did I specify?'}]
    result = agent.ask(client, messages)

    assert result == f'The column pressure is {PRESSURE} Pa.'


def test_type_b_single_case_question_reads_the_deterministic_definition():
    client = ScriptedClient([
        intent_response(queries=[{'field': 'design_option_requirements', 'entity': 'A', 'raw_reference': 'Case A'}]),
    ])
    messages = _base_messages() + [{'role': 'user', 'content': 'What does Case A require?'}]
    result = agent.ask(client, messages)

    assert result == f'Design Option A requires: {CASE_FIELD_SUMMARY["A"]}.'
    # Never produced as a fabricated/guessed answer, never unknown_problem_field.
    assert 'not a recognized' not in result
    assert 'unknown_problem_field' not in result


def test_type_b_four_case_overview_question_is_fast_pathed_deterministically():
    """No LLM call at all -- Step 9's exact acceptance phrasing."""
    client = ScriptedClient([])  # any chat() call raises
    messages = _base_messages() + [
        {'role': 'user', 'content': 'What are the inputs required for the four cases you mentioned?'},
    ]
    result = agent.ask(client, messages)

    assert client.calls == []
    for letter, requirement in CASE_FIELD_SUMMARY.items():
        assert f'Design Option {letter} = {requirement}' in result


def test_type_b_question_never_creates_a_fake_engineering_state_field():
    entry = PROBLEM_FIELD_REGISTRY['design_option_requirements']
    assert entry['writable'] is False  # can never be WRITTEN into the problem state

    before_keys = set(agent._workflow_state.keys())
    client = ScriptedClient([])
    messages = _base_messages() + [
        {'role': 'user', 'content': 'What are the inputs required for the four cases you mentioned?'},
    ]
    agent.ask(client, messages)
    after_keys = set(agent._workflow_state.keys())

    assert after_keys == before_keys  # the query added no new key to accumulated state
    assert 'design_option_requirements' not in agent._workflow_state
    assert 'missing_case_inputs' not in agent._workflow_state


# ---------------------------------------------------------------------------
# Step 9 -- scripted replay of the full live-Qwen acceptance conversation.
# The one turn that genuinely requires interpretation ("reflux is saturated
# liquid") is scripted rather than live -- see this file's module docstring.
# ---------------------------------------------------------------------------

def test_step_9_acceptance_conversation_scripted():
    messages = _base_messages()

    # Turn 1 -- initial problem statement (WRITE, model-proposed).
    client = ScriptedClient([
        intent_response(updates=[
            {'field': 'component_names', 'value': ['Ethanol', 'Water']},
            {'field': 'component_flows', 'items': [
                {'entity': 'Ethanol', 'value': 50, 'units': 'kmol/hr'},
                {'entity': 'Water', 'value': 50, 'units': 'kmol/hr'},
            ]},
            {'field': 'pressure_Pa', 'value': PRESSURE},
            {'field': 'feed_temperature_K', 'value': 355.0},
        ]),
        final('Got your feed. I still need the reflux condition.'),
    ])
    messages.append({'role': 'user', 'content':
                      'Separate water and ethanol at 355 K and 101325 Pa pressure. '
                      'The feed flow rates are 50 kmol/hr ethanol and 50 kmol/hr water.'})
    agent.ask(client, messages)
    messages.append({'role': 'assistant', 'content': 'Got your feed. I still need the reflux condition.'})

    state = agent.get_binary_distillation_problem()
    assert state['feed_screening']['ready'] is False
    assert state['pending_request']['field'] == 'reflux_condition'

    # Turn 2 -- "Yes": no calculation, no state change, deterministic re-ask.
    client = ScriptedClient([])
    messages.append({'role': 'user', 'content': 'Yes'})
    reply = agent.ask(client, messages)
    messages.append({'role': 'assistant', 'content': reply})

    assert client.calls == []
    assert agent.get_binary_distillation_problem()['feed_screening']['ready'] is False

    # Turn 3 -- explicit reflux condition (WRITE, model-proposed).
    client = ScriptedClient([
        intent_response(updates=[{'field': 'reflux_condition', 'value': 'saturated_liquid'}]),
        final('Reflux condition saved. Feed screening is now ready.'),
    ])
    messages.append({'role': 'user', 'content': 'reflux is saturated liquid'})
    agent.ask(client, messages)
    messages.append({'role': 'assistant', 'content': 'Reflux condition saved. Feed screening is now ready.'})

    state = agent.get_binary_distillation_problem()
    assert state['feed_screening']['ready'] is True

    # Turn 4 -- workflow-definition question about all four cases.
    client = ScriptedClient([])
    messages.append({'role': 'user', 'content': 'What are the inputs required for the four cases you mentioned?'})
    reply = agent.ask(client, messages)

    assert client.calls == []
    for letter, requirement in CASE_FIELD_SUMMARY.items():
        assert f'Design Option {letter} = {requirement}' in reply


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
