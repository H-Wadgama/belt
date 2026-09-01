"""
tools/binary-distillation-turn-diagnostics-plan.md Step 10 -- the bounded
semantic TurnIntent repair retry, gated behind `ask(..., semantic_retry=True)`
(wired to the `--semantic-retry` CLI flag). Off by default. Scripted (fake)
Ollama responses only -- no running Ollama server required.

Run with:
    pytest tools/chopper/test_binary_distillation_semantic_retry.py -v
"""
import pytest

import binary_distillation_workflow_agent as agent
import turn_diagnostics
from problem_field_registry import ACTIVE_WORKFLOW_SCHEMA
from turn_intent_test_fakes import ScriptedClient, final, intent_response, update
from turn_transaction import validate_turn_intent


@pytest.fixture(autouse=True)
def _reset_state():
    agent.reset_workflow_session()
    yield
    agent.reset_workflow_session()


def _base_messages():
    return [{'role': 'system', 'content': agent.SYSTEM_PROMPT}]


def _intent(updates=None):
    return {'version': 1, 'updates': updates or [], 'queries': [], 'action': None}


_REPORTED_PROMPT = (
    'Separate water and ethanol at 355 K and 101325 Pa pressure. '
    'The feed composition is 50 kmol/hr ethanol and 50 kmol/hr water'
)

_BROKEN_UPDATES = [
    update('component_flows', 50, units='kmol/hr'),
    update('component_flows', 50, units='kmol/hr'),
    update('feed_temperature_K', 355),
    update('pressure_Pa', 101325),
]

_REPAIRED_UPDATES = [
    update('component_flows', 50, entity='Ethanol', units='kmol/hr'),
    update('component_flows', 50, entity='Water', units='kmol/hr'),
    update('feed_temperature_K', 355),
    update('pressure_Pa', 101325),
]


def test_known_missing_entity_failure_can_be_repaired():
    client = ScriptedClient([
        intent_response(updates=_BROKEN_UPDATES),   # interpretation -- rejected
        intent_response(updates=_REPAIRED_UPDATES),  # semantic repair -- valid
        final('Recorded ethanol and water.'),        # WRITE narration
    ])
    diagnostic = turn_diagnostics.new_turn_record('sr1', None)
    messages = _base_messages() + [{'role': 'user', 'content': _REPORTED_PROMPT}]

    agent.ask(client, messages, diagnostic=diagnostic, semantic_retry=True)

    state = agent.get_binary_distillation_problem()
    assert state['feed']['component_flows'] == {'Ethanol': 50.0, 'Water': 50.0}
    assert diagnostic['validation']['semantic_retry']['repaired'] is True
    assert len(client.calls) == 3


def test_retry_is_capped_at_one():
    """If the REPAIRED proposal is itself still rejected (still missing
    entity), no second repair attempt is made -- only two chat() calls
    total (interpretation + one repair), never a third."""
    client = ScriptedClient([
        intent_response(updates=_BROKEN_UPDATES),
        intent_response(updates=_BROKEN_UPDATES),  # repair still broken
    ])
    diagnostic = turn_diagnostics.new_turn_record('sr2', None)
    messages = _base_messages() + [{'role': 'user', 'content': _REPORTED_PROMPT}]

    agent.ask(client, messages, diagnostic=diagnostic, semantic_retry=True)

    assert len(client.calls) == 2  # never a third (would-be second repair) call


def test_retry_never_follows_a_mutation():
    """Eligibility is False outright whenever ANY update already validated
    (update_kwargs non-empty) -- the atomic-batch design means this can
    only be tested directly on the eligibility gate, since a transaction
    with any invalid update always has update_kwargs == {}."""
    valid_transaction = validate_turn_intent(_intent(updates=[update('pressure_Pa', 101325)]), ACTIVE_WORKFLOW_SCHEMA)
    assert valid_transaction['update_kwargs'] == {'pressure_Pa': 101325}
    assert agent._is_semantic_retry_eligible(valid_transaction) is False


def test_non_allowlisted_failure_does_not_retry():
    client = ScriptedClient([
        intent_response(updates=[update('not_a_real_field', 5)]),  # unknown_field -- not repairable
    ])
    diagnostic = turn_diagnostics.new_turn_record('sr3', None)
    messages = _base_messages() + [{'role': 'user', 'content': 'set not_a_real_field to 5'}]

    agent.ask(client, messages, diagnostic=diagnostic, semantic_retry=True)

    assert len(client.calls) == 1  # no repair call attempted
    assert diagnostic['validation'].get('semantic_retry') is None


def test_failed_repair_leaves_state_unchanged():
    client = ScriptedClient([
        intent_response(updates=_BROKEN_UPDATES),
        intent_response(updates=_BROKEN_UPDATES),  # repair still broken
    ])
    diagnostic = turn_diagnostics.new_turn_record('sr4', None)
    messages = _base_messages() + [{'role': 'user', 'content': _REPORTED_PROMPT}]

    agent.ask(client, messages, diagnostic=diagnostic, semantic_retry=True)

    state = agent.get_binary_distillation_problem()
    assert state['feed']['component_flows'] == {}
    assert diagnostic['validation']['semantic_retry']['repaired'] is False


def test_disabling_the_flag_preserves_non_retry_behavior():
    """Same broken proposal, `semantic_retry` left at its default (False):
    exactly one chat() call, no repair attempted, state unchanged."""
    client = ScriptedClient([intent_response(updates=_BROKEN_UPDATES)])
    diagnostic = turn_diagnostics.new_turn_record('sr5', None)
    messages = _base_messages() + [{'role': 'user', 'content': _REPORTED_PROMPT}]

    agent.ask(client, messages, diagnostic=diagnostic)  # semantic_retry defaults to False

    assert len(client.calls) == 1
    assert diagnostic['validation'].get('semantic_retry') is None
    assert agent.get_binary_distillation_problem()['feed']['component_flows'] == {}
