"""
tools/binary-distillation-issues-9-1-2026-fifth.md Part 5/14 -- the
TurnIntent interpretation boundary. Scripted (fake) Ollama responses only --
no running Ollama server is required.

Run with:
    pytest tools/chopper/test_turn_intent_parser.py -v
"""
import json

from turn_intent import build_field_catalog_prompt, parse_turn_intent_response, propose_turn_intent


def test_parse_one_update():
    result = parse_turn_intent_response(json.dumps({
        'version': 1, 'updates': [{'field': 'pressure_Pa', 'value': 101325}], 'queries': [], 'action': None,
    }))
    assert result['ok'] is True
    assert result['intent']['updates'] == [
        {'field': 'pressure_Pa', 'entity': None, 'subject': None, 'value': 101325, 'units': None, 'basis': None}
    ]


def test_parse_multiple_updates():
    result = parse_turn_intent_response(json.dumps({
        'version': 1,
        'updates': [{'field': 'xD', 'value': 0.9}, {'field': 'xB', 'value': 0.1}],
        'queries': [], 'action': None,
    }))
    assert result['ok'] is True
    assert len(result['intent']['updates']) == 2


def test_parse_one_query():
    result = parse_turn_intent_response(json.dumps({
        'version': 1, 'updates': [], 'queries': [{'field': 'total_flow'}], 'action': None,
    }))
    assert result['ok'] is True
    assert result['intent']['queries'] == [{'field': 'total_flow', 'entity': None, 'subject': None, 'raw_reference': None}]


def test_parse_multiple_queries():
    result = parse_turn_intent_response(json.dumps({
        'version': 1, 'updates': [],
        'queries': [{'field': 'feed_temperature_K'}, {'field': 'pressure_Pa'}],
        'action': None,
    }))
    assert result['ok'] is True
    assert [q['field'] for q in result['intent']['queries']] == ['feed_temperature_K', 'pressure_Pa']


def test_parse_mixed_update_and_query():
    result = parse_turn_intent_response(json.dumps({
        'version': 1,
        'updates': [{'field': 'reflux_condition', 'value': 'saturated_liquid'}],
        'queries': [{'field': 'total_flow', 'raw_reference': 'total feed flow'}],
        'action': None,
    }))
    assert result['ok'] is True
    assert result['intent']['updates'][0]['field'] == 'reflux_condition'
    assert result['intent']['queries'][0]['field'] == 'total_flow'


def test_parse_update_with_compatible_action():
    result = parse_turn_intent_response(json.dumps({
        'version': 1,
        'updates': [{'field': 'feed_temperature_K', 'value': 355}],
        'queries': [], 'action': {'name': 'calculate_current_step'},
    }))
    assert result['ok'] is True
    assert result['intent']['action'] == {'name': 'calculate_current_step'}


def test_parse_keyed_entity_and_subject():
    result = parse_turn_intent_response(json.dumps({
        'version': 1,
        'updates': [{
            'field': 'component_flows', 'entity': 'Ethanol', 'value': 50, 'units': 'kmol/hr',
            'subject': {'kind': 'feed', 'id': 'feed'},
        }],
        'queries': [], 'action': None,
    }))
    assert result['ok'] is True
    update = result['intent']['updates'][0]
    assert update['entity'] == 'Ethanol'
    assert update['subject'] == {'kind': 'feed', 'id': 'feed'}


def test_parse_collection_update_preserves_items_verbatim():
    """tools/binary-distillation-issues-9-1-2026-sixth.md Part 2/8 -- a
    collection update's `items` must survive parsing verbatim (never
    collapsed into a scalar entity/value), so the model-proposed
    representation is still visible downstream (diagnostics) and can be
    normalized/validated without loss."""
    result = parse_turn_intent_response(json.dumps({
        'version': 1,
        'updates': [{
            'field': 'component_flows',
            'items': [
                {'entity': 'Ethanol', 'value': 50, 'units': 'kmol/hr'},
                {'entity': 'Water', 'value': 50, 'units': 'kmol/hr'},
            ],
        }],
        'queries': [], 'action': None,
    }))
    assert result['ok'] is True
    update = result['intent']['updates'][0]
    assert update['field'] == 'component_flows'
    assert 'value' not in update
    assert 'entity' not in update
    assert update['items'] == [
        {'entity': 'Ethanol', 'value': 50, 'units': 'kmol/hr', 'basis': None},
        {'entity': 'Water', 'value': 50, 'units': 'kmol/hr', 'basis': None},
    ]


def test_parse_collection_update_with_missing_item_entity_still_parses():
    """A malformed item (missing its own entity) does not sink the whole
    TurnIntent as malformed_turn_intent -- it structurally parses so
    turn_transaction.normalize_turn_intent_updates/validate_turn_intent can
    reject it as one specific, atomic-batch-rejecting invalid update."""
    result = parse_turn_intent_response(json.dumps({
        'version': 1,
        'updates': [{
            'field': 'component_flows',
            'items': [{'entity': 'Ethanol', 'value': 50}, {'value': 60}],
        }],
        'queries': [], 'action': None,
    }))
    assert result['ok'] is True
    assert result['intent']['updates'][0]['items'][1]['entity'] is None


def test_parse_collection_update_empty_items_is_malformed():
    result = parse_turn_intent_response(json.dumps({
        'version': 1,
        'updates': [{'field': 'component_flows', 'items': []}],
        'queries': [], 'action': None,
    }))
    assert result['ok'] is False
    assert result['error'] == 'malformed_turn_intent'


def test_unknown_candidate_field_preserved_verbatim():
    """The parser must never guess or drop an unrecognized field -- semantic
    validation (unknown_problem_field) happens downstream, in
    turn_transaction/problem_snapshot, not here."""
    result = parse_turn_intent_response(json.dumps({
        'version': 1, 'updates': [], 'queries': [{'field': 'zB', 'raw_reference': 'zB'}], 'action': None,
    }))
    assert result['ok'] is True
    assert result['intent']['queries'][0]['field'] == 'zB'


def test_malformed_json_is_rejected():
    result = parse_turn_intent_response('not json at all')
    assert result['ok'] is False
    assert result['error'] == 'malformed_turn_intent'


def test_malformed_structure_is_rejected():
    # Valid JSON, but 'updates' isn't a list of the required shape.
    result = parse_turn_intent_response(json.dumps({
        'version': 1, 'updates': [{'value': 5}], 'queries': [], 'action': None,  # missing 'field'
    }))
    assert result['ok'] is False
    assert result['error'] == 'malformed_turn_intent'


def test_tool_looking_json_content_is_rejected_not_executed():
    """Failure 4 -- assistant content shaped like a tool call must never be
    treated as an executable operation. Since this parser is the ONLY
    consumer of `message.content` (no native tool-calling channel exists),
    a tool-call-shaped object simply fails TurnIntent structural validation
    -- there is no separate code path that could execute it."""
    result = parse_turn_intent_response(json.dumps({
        'name': 'get_binary_distillation_problem', 'arguments': {},
    }))
    assert result['ok'] is False
    assert result['error'] == 'malformed_turn_intent'


def test_empty_response_is_rejected():
    assert parse_turn_intent_response('')['ok'] is False
    assert parse_turn_intent_response(None)['ok'] is False


# ---------------------------------------------------------------------------
# propose_turn_intent -- fake client, no live Ollama.
# ---------------------------------------------------------------------------

class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeResponse:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _RecordingClient:
    """Never exposes any engineering operation -- proves the interpretation
    call cannot itself execute one (Part 7/14): it has no `update`/`reset`/
    `calculate` method for `ask()`-side code to accidentally invoke, only
    `.chat()`."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def chat(self, model, messages, tools=None, think=False, format=None, options=None):
        self.calls.append({'tools': tools, 'format': format})
        return self._responses.pop(0)


def test_propose_turn_intent_never_exposes_tools():
    client = _RecordingClient([_FakeResponse(json.dumps({'version': 1, 'updates': [], 'queries': [], 'action': None}))])
    propose_turn_intent(client, [{'role': 'user', 'content': 'hi'}], 'fake-model')
    assert client.calls[0]['tools'] is None
    assert client.calls[0]['format'] is not None  # schema-constrained


def test_propose_turn_intent_retries_once_on_malformed_response():
    client = _RecordingClient([
        _FakeResponse('not json'),
        _FakeResponse(json.dumps({'version': 1, 'updates': [], 'queries': [{'field': 'xD'}], 'action': None})),
    ])
    result = propose_turn_intent(client, [{'role': 'user', 'content': 'what is xD?'}], 'fake-model')
    assert len(client.calls) == 2
    assert result['ok'] is True


def test_propose_turn_intent_bounded_after_one_retry():
    client = _RecordingClient([_FakeResponse('not json'), _FakeResponse('still not json')])
    result = propose_turn_intent(client, [{'role': 'user', 'content': 'hi'}], 'fake-model')
    assert len(client.calls) == 2  # never a third attempt
    assert result['ok'] is False


def test_field_catalog_mentions_every_writable_field():
    from problem_field_registry import PROBLEM_FIELD_REGISTRY
    catalog = build_field_catalog_prompt()
    for name, entry in PROBLEM_FIELD_REGISTRY.items():
        assert name in catalog
