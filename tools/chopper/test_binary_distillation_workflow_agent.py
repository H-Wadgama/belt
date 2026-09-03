"""
Agent-level regression tests for `ask()`'s TurnIntent/TurnTransaction
dispatch -- tools/binary-distillation-issues-9-1-2026-fifth.md.

Round 2 retired the native-tool-calling per-turn controller this file used
to test (`_select_allowed_calls`/`_fingerprint`/`MAX_TOOL_CALLS_PER_TURN`
-- see `git log` for the pre-Round-2 version). `ask()` now calls
`client.chat(..., format=<schema>, ...)` for interpretation (never
`tools=`) and validates/executes the result through
`turn_transaction.validate_turn_intent`/the module's own
`_dispatch_transaction`. These tests use `turn_intent_test_fakes.ScriptedClient`
-- no running Ollama server is required.

Run with:
    pytest tools/chopper/test_binary_distillation_workflow_agent.py -v
"""
import json

import pytest

import binary_distillation_workflow_agent as agent
from turn_intent_test_fakes import FakeMessage, FakeResponse, ScriptedClient, StubbornInterpretationClient, final, intent_response


def _tool_result_names(messages):
    return [m['tool_name'] for m in messages if isinstance(m, dict) and m.get('role') == 'tool']


def _tool_result_content(messages, tool_name):
    for m in messages:
        if isinstance(m, dict) and m.get('role') == 'tool' and m.get('tool_name') == tool_name:
            return json.loads(m['content'])
    return None


@pytest.fixture(autouse=True)
def _reset_state():
    agent.reset_workflow_session()
    yield
    agent.reset_workflow_session()


def _base_messages():
    return [{'role': 'system', 'content': agent.SYSTEM_PROMPT}]


# ---------------------------------------------------------------------------
# Test 1 -- a WRITE-only turn (proposed by the model) narrates the resulting
# assessment via one further no-format chat call.
# ---------------------------------------------------------------------------

def test_write_only_turn_narrates_result():
    client = ScriptedClient([
        intent_response(updates=[{'field': 'component_names', 'value': ['Methanol', 'Water']}]),
        final('Got it -- Methanol and Water.'),
    ])
    messages = _base_messages() + [{'role': 'user', 'content': 'separate methanol and water'}]

    result = agent.ask(client, messages)

    assert _tool_result_names(messages) == ['update_binary_distillation_problem']
    assert client.calls == [{'format': True, 'tools': False}, {'format': False, 'tools': False}]
    assert result == 'Got it -- Methanol and Water.'
    assert agent.get_binary_distillation_problem()['feed']['component_names'] == ['Methanol', 'Water']


# ---------------------------------------------------------------------------
# Test 2 -- a READ-only turn (a query) is TERMINAL: no narration call.
# ---------------------------------------------------------------------------

def test_read_only_turn_is_terminal():
    agent.update_binary_distillation_problem(pressure_Pa=101325)

    client = ScriptedClient([
        intent_response(queries=[{'field': 'pressure_Pa'}]),
    ])
    messages = _base_messages() + [{'role': 'user', 'content': 'what pressure did I specify?'}]

    result = agent.ask(client, messages)

    assert _tool_result_names(messages) == ['update_binary_distillation_problem']
    assert client.calls == [{'format': True, 'tools': False}]  # one call: interpretation only
    assert result == 'The column pressure is 101325 Pa.'


# ---------------------------------------------------------------------------
# Test 3 -- mixed WRITE+READ turn: WRITE applies first, the query resolves
# from the post-WRITE state, both TERMINAL in one response (Part 11).
# ---------------------------------------------------------------------------

def test_mixed_write_and_read_turn_is_terminal_and_ordered():
    agent.update_binary_distillation_problem(
        component_names=['Ethanol', 'Water'],
        component_flows={'Ethanol': 50, 'Water': 50}, component_flow_units='kmol/hr',
    )

    client = ScriptedClient([
        intent_response(
            updates=[{'field': 'reflux_condition', 'value': 'saturated_liquid'}],
            queries=[{'field': 'total_flow', 'raw_reference': 'total feed flow'}],
        ),
    ])
    messages = _base_messages() + [{
        'role': 'user',
        'content': 'reflux condition is saturated liquid, also what was the total flow rate of the feed?',
    }]

    result = agent.ask(client, messages)

    assert client.calls == [{'format': True, 'tools': False}]
    assert result == 'The reflux condition is now saturated_liquid. The total feed flow rate is 100 kmol/hr.'
    assert agent.get_binary_distillation_problem()['design_assessment']['reflux_condition_given'] is True


# ---------------------------------------------------------------------------
# Test 3b -- a redundant "write" the model proposes for a field it is ALSO
# querying this same turn (e.g. total_flow -- read-only) is silently
# absorbed by the query answer, not surfaced as a rejection note (live-
# probed live-model behavior: qwen3:8b sometimes proposes both).
# ---------------------------------------------------------------------------

def test_redundant_readonly_update_alongside_its_own_query_is_silent():
    agent.update_binary_distillation_problem(
        component_names=['Ethanol', 'Water'],
        component_flows={'Ethanol': 50, 'Water': 50}, component_flow_units='kmol/hr',
    )

    client = ScriptedClient([
        intent_response(
            updates=[{'field': 'total_flow', 'value': 100, 'units': 'kmol/hr'}],  # read-only, invalid
            queries=[{'field': 'total_flow', 'raw_reference': 'total flow rate'}],
        ),
    ])
    messages = _base_messages() + [{'role': 'user', 'content': 'also what was the total flow rate of the feed?'}]

    result = agent.ask(client, messages)

    assert result == 'The total feed flow rate is 100 kmol/hr.'
    assert "couldn't apply" not in result.lower()


# ---------------------------------------------------------------------------
# Test 4 -- RESET then WRITE in one transaction, and nothing more.
# ---------------------------------------------------------------------------

def test_reset_then_write_narrates_result():
    agent.update_binary_distillation_problem(component_names=['Acetone'])

    client = ScriptedClient([
        intent_response(
            updates=[{'field': 'component_names', 'value': ['Ethanol', 'Water']}],
            action={'name': 'reset_current_problem'},
        ),
        final('Starting a new problem: Ethanol and Water.'),
    ])
    messages = _base_messages() + [{'role': 'user', 'content': "let's start over with ethanol and water"}]

    agent.ask(client, messages)

    assert _tool_result_names(messages) == ['update_binary_distillation_problem']
    state = agent.get_binary_distillation_problem()
    assert state['feed']['component_names'] == ['Ethanol', 'Water']  # Acetone was cleared by the reset


# ---------------------------------------------------------------------------
# Test 5 -- an unknown field is bounded, never falls through to a model
# guess (Failure 3).
# ---------------------------------------------------------------------------

def test_unknown_field_query_is_bounded():
    client = ScriptedClient([
        intent_response(queries=[{'field': 'zB', 'raw_reference': 'zB'}]),
    ])
    messages = _base_messages() + [{'role': 'user', 'content': 'What is zB?'}]

    result = agent.ask(client, messages)

    assert client.calls == [{'format': True, 'tools': False}]  # no narration call at all
    assert 'zB' in result
    assert 'not a recognized variable' in result


# ---------------------------------------------------------------------------
# Test 6 -- a malformed/unparseable interpretation response is a bounded
# error, never a crash, and never silently retried forever.
# ---------------------------------------------------------------------------

def test_malformed_intent_response_is_bounded():
    client = ScriptedClient([
        final('not valid json'),  # first attempt
        final('still not valid json'),  # one retry
    ])
    messages = _base_messages() + [{'role': 'user', 'content': 'asdkjasdj'}]

    result = agent.ask(client, messages)

    assert client.calls == [{'format': True, 'tools': False}, {'format': True, 'tools': False}]
    assert "couldn't interpret" in result.lower()


# ---------------------------------------------------------------------------
# Test 7 -- a completely empty TurnIntent (small talk / broad question)
# falls back to grounded narration.
# ---------------------------------------------------------------------------

def test_empty_intent_falls_back_to_broad_narration():
    client = ScriptedClient([
        intent_response(),
        final('Please tell me the two components you want to separate.'),
    ])
    messages = _base_messages() + [{'role': 'user', 'content': 'hello'}]

    result = agent.ask(client, messages)

    assert _tool_result_names(messages) == ['get_binary_distillation_problem']
    assert result == 'Please tell me the two components you want to separate.'


# ---------------------------------------------------------------------------
# Test 8 -- a pathological model that keeps proposing the same action still
# terminates in a bounded number of chat() calls (no native tool-calling
# loop exists any more to bound).
# ---------------------------------------------------------------------------

def test_action_turn_terminates_in_two_chat_calls():
    client = StubbornInterpretationClient('read_calculation_status', max_calls=6)
    messages = _base_messages() + [{'role': 'user', 'content': 'what next?'}]

    agent.ask(client, messages)

    assert client.n_calls <= 1  # "what next?" is an exclusive fast path -- never reaches interpretation


def test_action_turn_via_model_terminates_in_two_chat_calls():
    client = StubbornInterpretationClient('read_calculation_status', max_calls=6)
    messages = _base_messages() + [{'role': 'user', 'content': 'tell me about the current status of things'}]

    agent.ask(client, messages)

    assert client.n_calls <= 2  # one interpretation call, one narration call


# ---------------------------------------------------------------------------
# tools/chopper/binary-distillation-incorrect-symbol-reading-issue.md --
# engineering-output grounding: a plain WRITE-only turn that just reached
# ready_for_calculation is narrated by the model from a tool result that
# actually carries QR/Qc's authoritative meaning, and the prompt must never
# itself encode the wrong definition.
# ---------------------------------------------------------------------------

def test_system_prompt_contains_engineering_output_grounding_rule():
    assert 'ENGINEERING OUTPUT GROUNDING RULE' in agent.SYSTEM_PROMPT
    assert 'would_calculate_details' in agent.SYSTEM_PROMPT
    assert 'never as "reflux flow rate"' in agent.SYSTEM_PROMPT
    assert 'label="reboiler duty"' in agent.SYSTEM_PROMPT


def test_system_prompt_instructs_no_bare_symbol_enrichment():
    assert 'do not invent a definition' in agent.SYSTEM_PROMPT.lower()


def test_ready_for_calculation_write_result_grounds_QR_as_reboiler_duty():
    """Complete Case A (xD=0.9, xB=0.1, L0/D=2, optimum feed plate) via one
    WRITE-only TurnIntent, then check the JSON actually appended to
    `messages` for the model -- not a hypothetical -- carries QR's
    authoritative meaning and never the wrong "reflux flow rate"."""
    proposed_intent = {
        'version': 1,
        'updates': [
            {'field': 'component_names', 'value': ['Methanol', 'Water']},
            {'field': 'component_flows', 'entity': 'Methanol', 'value': 40, 'units': 'kmol/hr'},
            {'field': 'component_flows', 'entity': 'Water', 'value': 60, 'units': 'kmol/hr'},
            {'field': 'pressure_Pa', 'value': 101325},
            {'field': 'feed_temperature_K', 'value': 350.0},
            {'field': 'reflux_condition', 'value': 'saturated_liquid'},
            {'field': 'xD', 'value': 0.9},
            {'field': 'xB', 'value': 0.1},
            {'field': 'external_reflux_ratio_LD', 'value': 2.0},
            {'field': 'use_optimum_feed_plate', 'value': True},
        ],
        'queries': [], 'action': None,
    }
    client = ScriptedClient([
        FakeResponse(FakeMessage(content=json.dumps(proposed_intent))),
        final('Your Case A design is fully specified.'),
    ])
    messages = _base_messages() + [{'role': 'user', 'content': 'design a methanol/water column'}]

    agent.ask(client, messages)

    content = _tool_result_content(messages, 'update_binary_distillation_problem')
    assert content['status'] == 'ready_for_calculation'
    symbols = {e['symbol']: e['label'] for e in content['would_calculate_details']}
    assert symbols['QR'] == 'reboiler duty'
    assert symbols['Qc'] == 'condenser duty'
    assert 'reflux flow rate' not in json.dumps(content)


def test_legacy_bare_would_calculate_symbol_has_no_details_entry_mismatch():
    """Bare-symbol fallback: whenever `would_calculate` carries a symbol,
    `would_calculate_details` must carry its grounded counterpart -- so the
    model is never left needing to guess at a symbol that legitimately has
    a definition available."""
    proposed_intent = {
        'version': 1,
        'updates': [
            {'field': 'component_names', 'value': ['Methanol', 'Water']},
            {'field': 'component_flows', 'entity': 'Methanol', 'value': 40, 'units': 'kmol/hr'},
            {'field': 'component_flows', 'entity': 'Water', 'value': 60, 'units': 'kmol/hr'},
            {'field': 'pressure_Pa', 'value': 101325},
            {'field': 'feed_temperature_K', 'value': 350.0},
            {'field': 'reflux_condition', 'value': 'saturated_liquid'},
            {'field': 'xD', 'value': 0.9},
            {'field': 'xB', 'value': 0.1},
            {'field': 'external_reflux_ratio_LD', 'value': 2.0},
            {'field': 'use_optimum_feed_plate', 'value': True},
        ],
        'queries': [], 'action': None,
    }
    client = ScriptedClient([
        FakeResponse(FakeMessage(content=json.dumps(proposed_intent))),
        final('Your Case A design is fully specified.'),
    ])
    messages = _base_messages() + [{'role': 'user', 'content': 'design a methanol/water column'}]

    agent.ask(client, messages)

    result = _tool_result_content(messages, 'update_binary_distillation_problem')
    symbols_in_would_calculate = {s for s in result['would_calculate'] if s in ('D', 'B', 'QR', 'Qc', 'N')}
    symbols_with_details = {e['symbol'] for e in result['would_calculate_details']}
    assert symbols_in_would_calculate <= symbols_with_details


# ---------------------------------------------------------------------------
# Part 15 -- never require Design Option selection. A feed-ready/design-
# incomplete conversation (Water/Ethanol, 355 K, 101325 Pa, reflux_condition
# given, no OTHER Design Option field at all) must never produce a
# deterministic message asking the user to pick a Design Option letter --
# and the prompt-level instruction forbidding it must still be present.
# (reflux_condition is included here per tools/binary-distillation-issues-
# 9-1-2026-eighth.md Step 2 -- feed screening now requires it too.)
# ---------------------------------------------------------------------------

def test_feed_ready_design_incomplete_never_asks_for_a_design_option_letter():
    state = agent.update_binary_distillation_problem(
        component_names=['Water', 'Ethanol'],
        component_flows={'Water': 50, 'Ethanol': 50}, component_flow_units='kmol/hr',
        pressure_Pa=101325, feed_temperature_K=355.0, reflux_condition='saturated_liquid',
    )
    assert state['feed_screening']['ready'] is True
    assert state['design_assessment']['complete'] is False

    combined_text = (state['design_assessment']['message'] + ' ' + state.get('message', '')).lower()
    # Explaining the four specification sets (which legitimately mentions
    # "Design Option A/B/C/D = ...") is fine; asking the user to pick one by
    # letter is not.
    assert 'select design option' not in combined_text
    assert 'choose design option' not in combined_text
    assert 'name a design option' not in combined_text
    assert 'which design option' not in combined_text


def test_system_prompt_forbids_asking_for_a_design_option_letter():
    assert 'Do NOT ask the user to name a Design Option letter' in agent.SYSTEM_PROMPT
