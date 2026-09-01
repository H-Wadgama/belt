"""
TurnIntent schema, field-catalog prompt, and the Ollama structured-output
adapter -- tools/binary-distillation-issues-9-1-2026-fifth.md Parts 4-5/14.

## Adapter decision (Part 5/14)

Live-probed against the actual local Ollama server (`ollama==0.6.2`,
`qwen3:8b`) before choosing this adapter:

  - Native tool-calling (`client.chat(..., tools=[...])`) was UNRELIABLE on
    an ambiguous/corrective turn ("Sorry, I meant xB" with no live pending
    question, only READ/WRITE tools exposed): the model called no tool at
    all and answered in free prose instead of checking whether xB was
    already known -- engineering meaning silently lost. This is the same
    failure class as Failure 4's literal JSON-in-content report: an 8B
    model's native tool-call adherence is unreliable on anything but a
    clean single-fact turn.
  - Structured output (`client.chat(..., format=<json schema>)`, NO
    `tools=` exposed at all) was RELIABLE across 8 scripted probes covering
    every required scenario (mixed WRITE+READ, unknown-field preservation,
    multi-turn correction, correctly-typed multi-field WRITE, two-entity
    keyed writes, explicit action requests, and vague/no-op input), once
    the schema constrained `value` to `anyOf[string, number, boolean,
    null]` (never a nested object) and the prompt included a compact
    per-field catalog with one worked keyed-field example and an explicit
    action-name whitelist.

Decision: `format`-constrained structured output is the SOLE interpretation
adapter. No `tools=` list is ever exposed to the model for this call --
satisfying Part 5's "expose only an intent-proposal operation... not
engineering WRITE/READ tools" literally: there is no tool-calling channel
open at all during interpretation, so assistant content can never look like
an executed tool call (Part 14's invariant: "Assistant content never
directly invokes a tool").

Python still independently validates and coerces every proposed value
(`turn_transaction.py`) -- the live probes occasionally produced a numeric
field as a JSON string before the prompt was tightened, confirming Part 7's
requirement that Python, not the prompt, is the source of type safety.
"""
import json

from problem_field_registry import ACTION_REGISTRY, PROBLEM_FIELD_REGISTRY

TURN_INTENT_VERSION = 1

_SUBJECT_SCHEMA = {
    'anyOf': [
        {'type': 'null'},
        {
            'type': 'object',
            'properties': {'kind': {'type': 'string'}, 'id': {'type': 'string'}},
            'required': ['kind', 'id'],
        },
    ],
}

_VALUE_SCHEMA = {
    'anyOf': [
        {'type': 'string'}, {'type': 'number'}, {'type': 'boolean'}, {'type': 'null'},
        {'type': 'array', 'items': {'type': 'string'}},
    ],
}

# tools/binary-distillation-issues-9-1-2026-sixth.md Part 2 -- a single
# update entry now has TWO mutually exclusive shapes: the existing scalar
# form (one field/entity/value), or a collection form for a KEYED field with
# several entity/value pairs stated in the same turn (`items=[...]`). Kept
# as two separate `anyOf` branches -- rather than loosening the scalar
# shape's own `required` list to accept either `value` or `items` -- so each
# branch's `required` stays a precise, minimal declaration of exactly what
# that shape needs; a model emitting a scalar update still sees the exact
# same required-field shape it always did.
_UPDATE_ITEM_ENTRY_SCHEMA = {
    'type': 'object',
    'properties': {
        'entity': {'type': 'string'},
        'value': _VALUE_SCHEMA,
        'units': {'type': ['string', 'null']},
        'basis': {'type': ['string', 'null']},
    },
    'required': ['entity', 'value'],
}

_SCALAR_UPDATE_SCHEMA = {
    'type': 'object',
    'properties': {
        'field': {'type': 'string'},
        'entity': {'type': ['string', 'null']},
        'subject': _SUBJECT_SCHEMA,
        'value': _VALUE_SCHEMA,
        'units': {'type': ['string', 'null']},
        'basis': {'type': ['string', 'null']},
    },
    'required': ['field', 'value'],
}

_COLLECTION_UPDATE_SCHEMA = {
    'type': 'object',
    'properties': {
        'field': {'type': 'string'},
        'subject': _SUBJECT_SCHEMA,
        'items': {
            'type': 'array',
            'items': _UPDATE_ITEM_ENTRY_SCHEMA,
            'minItems': 1,
        },
    },
    'required': ['field', 'items'],
}

TURN_INTENT_JSON_SCHEMA = {
    'type': 'object',
    'properties': {
        'version': {'type': 'integer'},
        'updates': {
            'type': 'array',
            'items': {'anyOf': [_SCALAR_UPDATE_SCHEMA, _COLLECTION_UPDATE_SCHEMA]},
        },
        'queries': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'field': {'type': 'string'},
                    'entity': {'type': ['string', 'null']},
                    'subject': _SUBJECT_SCHEMA,
                    'raw_reference': {'type': ['string', 'null']},
                },
                'required': ['field'],
            },
        },
        'action': {
            'anyOf': [
                {'type': 'null'},
                {
                    'type': 'object',
                    'properties': {
                        'name': {'type': 'string'},
                        'arguments': {'type': 'object'},
                    },
                    'required': ['name'],
                },
            ],
        },
    },
    'required': ['version', 'updates', 'queries', 'action'],
}


def _describe_field(name, entry):
    parts = []
    parts.append('read' if entry.get('readable') else 'no-read')
    parts.append('write' if entry.get('writable') else 'READ-ONLY')
    kind = f", value_type={entry['value_type']}"
    if entry.get('canonical_units'):
        kind += f", units={entry['canonical_units']}"
    if entry.get('allowed_values'):
        kind += f", allowed_values={entry['allowed_values']}"
    if entry.get('constraints'):
        kind += f", constraints={entry['constraints']}"
    keyed = ', KEYED by component name -- put the component name in "entity"' if entry.get('keyed') else ''
    return f"- {name}: {'/'.join(parts)}{kind}{keyed} -- {entry['description']}"


def build_field_catalog_prompt(registry=PROBLEM_FIELD_REGISTRY, actions=ACTION_REGISTRY):
    """Generate the compact per-field/action catalog text from the registry
    at call time -- the registry is the single source of truth (Part 2); no
    hand-maintained duplicate phrase list. Includes one worked example for
    the first keyed field found, and the action-name whitelist."""
    lines = ['Known fields (name: read/write, type, description):']
    keyed_example_field = None
    for name, entry in registry.items():
        lines.append(_describe_field(name, entry))
        if entry.get('keyed') and keyed_example_field is None:
            keyed_example_field = name

    if keyed_example_field is not None:
        lines.append('')
        lines.append(
            f'Examples of a KEYED write for "{keyed_example_field}" (ALWAYS include an explicit '
            f'component-name "entity" for every value -- never omit it, and never leave it null):\n'
            f'  ONE component value this turn -> use "entity" + "value" directly on the update:\n'
            f'    "the ethanol flow is 50 kmol/hr" -> '
            f'{{"field": "{keyed_example_field}", "entity": "Ethanol", "value": 50, "units": "kmol/hr"}}\n'
            f'  SEVERAL component values in the SAME message -> use ONE update with "items", '
            f'where EVERY item states its own component "entity" and "value" '
            f'(do NOT emit multiple "{keyed_example_field}" updates with "entity": null -- that '
            f'loses which value belongs to which component):\n'
            f'    "50 kmol/hr ethanol and 50 kmol/hr water" -> ONE update: '
            f'{{"field": "{keyed_example_field}", "items": ['
            f'{{"entity": "Ethanol", "value": 50, "units": "kmol/hr"}}, '
            f'{{"entity": "Water", "value": 50, "units": "kmol/hr"}}]}}'
        )

    if 'component_names' in registry:
        lines.append('')
        lines.append(
            'Example of a component_names write (use ONLY when no quantity is given yet): '
            '"separate methanol and water" -> '
            '{"field": "component_names", "value": ["Methanol", "Water"]}.'
        )

    action_names = ', '.join(sorted(actions.keys()))
    lines.append('')
    lines.append(
        'Rules:\n'
        '- Only fields marked "write" above may appear in "updates". A field marked '
        '"READ-ONLY" must appear only in "queries", never in "updates".\n'
        '- If the user references a symbol NOT in this catalog (e.g. an unrecognized '
        'variable name), still record it verbatim as a query field -- do not guess '
        'which known field they meant, and do not silently drop it.\n'
        '- "value" must be a plain JSON string, number, boolean, or null -- a numeric '
        "field's value must be a JSON number, never a quoted string, and never a "
        'nested object.\n'
        '- For a KEYED field, put the key (e.g. the component name) in "entity", '
        'never inside "value" or "field".\n'
        '- For a KEYED field with MULTIPLE component values in the SAME message, use ONE '
        'update with "items": [{"entity": ..., "value": ..., "units": ...}, ...], one item per '
        'component -- never split them into several separate updates for the same field with '
        '"entity": null. Every entity, whether given directly on an update or inside "items", '
        'must be an explicit component name the user actually stated.\n'
        f'- Only propose "action" when the user is explicitly asking to run/continue a '
        f'calculation or reset the problem; otherwise "action" must be null. Valid '
        f'action names: {action_names}.\n'
        '- Propose ONLY what the CURRENT user message actually states or asks -- '
        'never restate or re-propose a value already known from earlier in the '
        'conversation merely because it is still true.\n'
        '- A message phrased as a QUESTION about whether/what was already given -- '
        'containing "didn\'t I", "did I", "have I", "haven\'t I", "already", or a '
        'question mark -- is ALWAYS a query, NEVER an update, no matter how it is '
        'phrased or which field name it names. "updates" MUST be empty for such a '
        'message. Find the ONE field name the question is actually about (from the '
        'catalog above) and put exactly that field in "queries" -- do not substitute '
        'a different field. Example: "I just told you the boilup ratio, didn\'t I?" '
        '-> {"updates": [], "queries": [{"field": "boilup_ratio_VB", '
        '"raw_reference": "boilup ratio, didn\'t I"}], "action": null}. Example: '
        '"did I already give you the pressure?" -> {"updates": [], '
        '"queries": [{"field": "pressure_Pa", "raw_reference": "pressure"}], '
        '"action": null}.'
    )
    return '\n'.join(lines)


def _is_valid_update_shape(item):
    """Structurally accept EITHER update shape (Part 2): a scalar update
    (`field` + `value`) or a collection update (`field` + `items` as a
    list). Deliberately lenient on the CONTENTS of `items` here (e.g. an
    item missing its own `entity`) -- that is a semantic problem for
    `turn_transaction.normalize_turn_intent_updates`/`validate_turn_intent`
    to reject as one specific, atomic-batch-rejecting invalid update, not a
    reason to throw away the ENTIRE TurnIntent (including otherwise-valid
    queries/action) as malformed. This mirrors the existing scalar path,
    which already defers value-type/range checking to semantic validation."""
    if not (isinstance(item, dict) and 'field' in item and isinstance(item['field'], str)):
        return False
    if 'items' in item:
        return isinstance(item['items'], list) and len(item['items']) >= 1
    return 'value' in item


def _is_valid_query_shape(item):
    return isinstance(item, dict) and 'field' in item and isinstance(item['field'], str)


def _is_valid_action_shape(action):
    if action is None:
        return True
    return isinstance(action, dict) and isinstance(action.get('name'), str)


def _normalize_parsed_update(u):
    """Preserve whichever of the two update shapes (Part 2) the model
    actually proposed -- a collection update's `items` must survive parsing
    verbatim (never collapsed into scalar `entity`/`value` here), so that
    both the model-proposed collection form and its later normalized
    expansion (`turn_transaction.normalize_turn_intent_updates`) are
    available for diagnostics (Part 8) and for semantic validation."""
    if 'items' in u:
        return {
            'field': u['field'],
            'subject': u.get('subject'),
            'items': [
                {
                    'entity': entry.get('entity') if isinstance(entry, dict) else None,
                    'value': entry.get('value') if isinstance(entry, dict) else None,
                    'units': entry.get('units') if isinstance(entry, dict) else None,
                    'basis': entry.get('basis') if isinstance(entry, dict) else None,
                }
                for entry in u['items']
            ],
        }
    return {
        'field': u['field'],
        'entity': u.get('entity'),
        'subject': u.get('subject'),
        'value': u['value'],
        'units': u.get('units'),
        'basis': u.get('basis'),
    }


def parse_turn_intent_response(raw_content):
    """
    Normalize a raw Ollama structured-output response into a
    TurnIntentParseResult. Never raises -- malformed model output becomes a
    structured parse error (Part 5/7), never a Python exception.

    Returns:
        {'ok': True, 'intent': TurnIntent} or
        {'ok': False, 'error': 'malformed_turn_intent', 'detail': str, 'raw': raw_content}
    """
    if not raw_content or not isinstance(raw_content, str):
        return {'ok': False, 'error': 'malformed_turn_intent', 'detail': 'empty response', 'raw': raw_content}
    try:
        parsed = json.loads(raw_content)
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        return {'ok': False, 'error': 'malformed_turn_intent', 'detail': str(e), 'raw': raw_content}

    if not isinstance(parsed, dict):
        return {'ok': False, 'error': 'malformed_turn_intent', 'detail': 'top-level value is not an object', 'raw': raw_content}

    # Require the declared TurnIntent shape explicitly (matching
    # TURN_INTENT_JSON_SCHEMA's own 'required' list) rather than defaulting
    # missing keys to empty -- an arbitrary/tool-call-shaped JSON object
    # (e.g. {"name": "get_binary_distillation_problem", "arguments": {}})
    # must be rejected as malformed, never silently treated as an empty,
    # harmless intent (Part 5: "reject malformed types and invalid
    # top-level structure").
    missing = {'version', 'updates', 'queries', 'action'} - parsed.keys()
    if missing:
        return {'ok': False, 'error': 'malformed_turn_intent', 'detail': f'missing keys: {sorted(missing)}', 'raw': raw_content}

    updates = parsed['updates']
    queries = parsed['queries']
    action = parsed['action']

    if not isinstance(updates, list) or not all(_is_valid_update_shape(u) for u in updates):
        return {'ok': False, 'error': 'malformed_turn_intent', 'detail': 'invalid updates shape', 'raw': raw_content}
    if not isinstance(queries, list) or not all(_is_valid_query_shape(q) for q in queries):
        return {'ok': False, 'error': 'malformed_turn_intent', 'detail': 'invalid queries shape', 'raw': raw_content}
    if not _is_valid_action_shape(action):
        return {'ok': False, 'error': 'malformed_turn_intent', 'detail': 'invalid action shape', 'raw': raw_content}

    intent = {
        'version': parsed.get('version', TURN_INTENT_VERSION),
        'updates': [_normalize_parsed_update(u) for u in updates],
        'queries': [
            {
                'field': q['field'],
                'entity': q.get('entity'),
                'subject': q.get('subject'),
                'raw_reference': q.get('raw_reference'),
            }
            for q in queries
        ],
        'action': action,
    }
    return {'ok': True, 'intent': intent}


def _attempt_record(raw, parse_result):
    """One interpretation attempt -- the exact raw model content plus its
    parse outcome. `parse_result`'s own 'raw' key (present on a failed
    parse) is stripped here since it would otherwise duplicate this same
    attempt's 'raw' field -- tools/binary-distillation-turn-diagnostics-plan.md
    Step 3: "Avoid recursive structures.\""""
    return {
        'raw': raw,
        'parse_result': {k: v for k, v in parse_result.items() if k != 'raw'},
    }


def propose_turn_intent(client, messages, model, catalog_prompt=None):
    """
    Issue ONE structured-output interpretation call (plus at most one
    strict-schema retry on a malformed response -- Part 5) and return a
    TurnIntentParseResult. No `tools=` are ever exposed here -- this call
    can never execute an engineering operation itself (Part 7/14 invariant).

    The large, narration-oriented `SYSTEM_PROMPT` (calculation-narration
    rules, Design Option explanation guidance, etc.) is deliberately NOT
    included here -- live-probed to matter: combined with that prompt, the
    interpretation call produced a fixed, hallucinated TurnIntent (fabricated
    xD/xB/temperature/etc. values, byte-identical across unrelated turns)
    regardless of the actual user message. Conversation history (the actual
    user/assistant turns) is kept for corrective-turn context (e.g. "Sorry, I
    meant xB"); only the system message is replaced with a minimal,
    interpretation-focused one built from the field catalog.

    Every raw model response is preserved -- tools/chopper/turn-diagnostics
    -plan.md Step 3 -- so a caller can determine, after the fact, exactly
    what Qwen actually said this turn, on both a successful and an
    unsuccessful parse:

        {
            'ok': True, 'intent': {...},
            'attempts': [{'raw': '<exact response.message.content>', 'parse_result': {...}}, ...],
            'retry_used': False,
        }

    `ok`/`intent` (on success) are kept for existing callers; `attempts`/
    `retry_used` are additive.
    """
    catalog_prompt = catalog_prompt or build_field_catalog_prompt()
    history = [m for m in messages if not (isinstance(m, dict) and m.get('role') == 'system')]
    interpretation_messages = [{
        'role': 'system',
        'content': (
            'Interpret the CURRENT user turn (the final user message below) into a '
            'TurnIntent JSON object matching the required schema. ' + catalog_prompt
        ),
    }] + history

    # temperature=0 -- live-probed to matter: with default sampling, entity
    # extraction on some phrasings (e.g. "50 kmol/hr ethanol and 50 kmol/hr
    # water" with no other context) was inconsistent run-to-run; pinned to
    # greedy decoding it was 100% reproducible across repeated runs.
    response = client.chat(model=model, messages=interpretation_messages,
                            format=TURN_INTENT_JSON_SCHEMA, think=False,
                            options={'temperature': 0})
    raw = response.message.content
    result = parse_turn_intent_response(raw)
    attempts = [_attempt_record(raw, result)]
    if result['ok']:
        return {'ok': True, 'intent': result['intent'], 'attempts': attempts, 'retry_used': False}

    retry_messages = interpretation_messages + [{
        'role': 'system',
        'content': 'Your previous response was not valid JSON matching the required TurnIntent schema. Return ONLY a valid JSON object matching that schema -- no other text.',
    }]
    response = client.chat(model=model, messages=retry_messages,
                            format=TURN_INTENT_JSON_SCHEMA, think=False,
                            options={'temperature': 0})
    raw = response.message.content
    result = parse_turn_intent_response(raw)
    attempts.append(_attempt_record(raw, result))
    if result['ok']:
        return {'ok': True, 'intent': result['intent'], 'attempts': attempts, 'retry_used': True}
    return {
        'ok': False, 'error': result.get('error'), 'detail': result.get('detail'),
        'attempts': attempts, 'retry_used': True,
    }
