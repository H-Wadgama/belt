"""
Natural-language front end for the multicomponent (>=3 component)
feed-phase intake agent, backed by a local Ollama model (default:
qwen3:8b).

See ../multicomponent-distillation-context.md for the domain vocabulary
and scope, and ../multicomponent-distillation-feed-phase-plan.md for the
architecture this agent follows:

  - The model NEVER gets a `tools=` engineering tool-calling channel. It
    only ever performs ONE JOB per user turn: propose, as one
    schema-constrained JSON object (`format=`, not `tools=` -- the same
    adapter decision `turn_intent.py` made for the binary agent, and for
    the same live-probed reason: native tool-calling was unreliable on
    anything but a clean single-fact turn), which of the tool's fields the
    CURRENT user message states.
  - That proposal is never trusted directly. The controller (this module)
    grounds it against the exact current user message text with
    `multicomponent_grounding.ground_proposed_update` -- a value the model
    invents, or that describes the wrong physical field, is discarded
    before it can reach state.
  - Only the grounded fields are applied, in one call to
    `multicomponent_feed_tool.update_multicomponent_feed`, directly in
    Python -- never by sending the tool's result back to the model as a
    second turn. The model is NOT called again after the extraction call:
    the next pending question, a conflict/validation message, or the final
    phase result are all produced by deterministic formatters below.

This agent deliberately does NOT reproduce the binary chopper toolkit's
case-routing, design-assessment, RAG, transaction-diagnostics, or
calculation-progress machinery -- see "Module-Level Changes" in the plan.

Requires a running local Ollama server with the model pulled:
    ollama pull qwen3:8b

Run interactively:
    python multicomponent_distillation_agent.py

Or run a single one-shot prompt (useful for scripting/testing):
    python multicomponent_distillation_agent.py "hello"
"""
import json
import sys

import ollama

from multicomponent_feed_tool import (
    get_known_component_names,
    reset_multicomponent_feed_session,
    update_multicomponent_feed,
)
from multicomponent_grounding import (
    detect_mixed_composition_basis,
    detect_mixed_flow_units,
    ground_proposed_update,
)

MODEL = 'qwen3:8b'

# tools/multicomponent-distillation-feed-phase-plan.md "One State Update
# Per User Turn" -- the extraction schema mirrors
# `update_multicomponent_feed`'s keyword arguments exactly (no enthalpy/
# quality fields at all), plus a `reset` flag standing in for
# `reset_multicomponent_feed_session`. Every property is nullable/required
# so a single well-formed JSON object is the only legal shape -- matching
# `turn_intent.py`'s live-probed finding that a compact, fully-required
# schema is what makes qwen3:8b's structured output reliable.
_PROPOSAL_JSON_SCHEMA = {
    'type': 'object',
    'properties': {
        'component_names': {'anyOf': [{'type': 'null'}, {'type': 'array', 'items': {'type': 'string'}}]},
        'add_component_names': {'anyOf': [{'type': 'null'}, {'type': 'array', 'items': {'type': 'string'}}]},
        'component_flows': {'anyOf': [{'type': 'null'}, {'type': 'object', 'additionalProperties': {'type': 'number'}}]},
        'component_flow_units': {'anyOf': [{'type': 'null'}, {'type': 'string'}]},
        'total_flow': {'anyOf': [{'type': 'null'}, {'type': 'number'}]},
        'total_flow_units': {'anyOf': [{'type': 'null'}, {'type': 'string'}]},
        'composition': {'anyOf': [{'type': 'null'}, {'type': 'object', 'additionalProperties': {'type': 'number'}}]},
        'composition_basis': {'anyOf': [{'type': 'null'}, {'type': 'string'}]},
        'pressure': {'anyOf': [{'type': 'null'}, {'type': 'number'}]},
        'pressure_units': {'anyOf': [{'type': 'null'}, {'type': 'string'}]},
        'feed_temperature': {'anyOf': [{'type': 'null'}, {'type': 'number'}]},
        'feed_temperature_units': {'anyOf': [{'type': 'null'}, {'type': 'string'}]},
        'reset': {'type': 'boolean'},
    },
    'required': [
        'component_names', 'add_component_names', 'component_flows',
        'component_flow_units', 'total_flow', 'total_flow_units',
        'composition', 'composition_basis', 'pressure', 'pressure_units',
        'feed_temperature', 'feed_temperature_units', 'reset',
    ],
}

_PROPOSAL_FIELDS = tuple(_PROPOSAL_JSON_SCHEMA['required'])

SYSTEM_PROMPT = """You extract feed facts for a multicomponent (three or \
more component) distillation feed-phase calculator. You do not calculate \
anything yourself and you do not have any callable tools -- your only job \
is to read the CURRENT user message (the final message below) and return \
one JSON object naming exactly the facts THAT MESSAGE states, matching \
the required schema.

Fields: component_names, add_component_names (arrays of component name \
strings), component_flows, composition (objects mapping a component name \
to a number), component_flow_units, total_flow_units, pressure_units, \
feed_temperature_units (strings), total_flow, pressure, feed_temperature \
(numbers), composition_basis ("mole" or "mass", ONLY if the message \
explicitly says so, e.g. "wt%" or "mol%"), and reset (boolean).

Rules:
- Every field you did not find explicit evidence for in the CURRENT user \
message MUST be null (or false for reset) -- never invent, guess, \
default, or carry forward a value from earlier in the conversation just \
because it is still true. Earlier turns are shown only for context (e.g. \
resolving "the third one is X").
- Never assume the feed temperature -- never default it to a bubble \
point, and never invent one from general chemistry knowledge.
- Never guess whether a stated composition is mole-basis or mass-basis; \
leave composition_basis null unless the message uses explicit wording.
- Never guess a unit for a flow, pressure, or temperature value -- leave \
the corresponding *_units field null if the message does not state one.
- Never invent a component that was not named, and never populate \
component_flows or composition for a component not actually given a \
number in this message.
- component_flows values are literal per-component flow numbers the \
message states -- never compute or guess one from a total and a fraction.
- composition values are fractions; a "20%" phrasing means 0.20.
- Set reset=true ONLY when the user is explicitly switching to a \
different, unrelated feed or asking to start over -- otherwise reset must \
be false.
- If the message asks a question about what was already given, or states \
no new engineering fact at all, return every field null/false."""


def _parse_proposal(raw_content):
    """Best-effort parse of one structured-output response into a proposal
    dict. Returns None (never raises) if the content is not valid JSON
    matching the required schema's top-level shape."""
    if not raw_content or not isinstance(raw_content, str):
        return None
    try:
        parsed = json.loads(raw_content)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    if not set(_PROPOSAL_FIELDS) <= parsed.keys():
        return None
    return {field: parsed.get(field) for field in _PROPOSAL_FIELDS}


def propose_feed_update(client, messages):
    """
    Issue ONE structured-output extraction call (plus at most one bounded
    retry on a malformed response -- the retry does not mutate state, it
    only asks the model to reformat) and return a raw proposal dict shaped
    like `update_multicomponent_feed`'s keyword arguments (plus `reset`).
    No `tools=` are ever exposed here -- this call can never itself
    execute an engineering operation (see module docstring).

    Returns
    -------
    (proposal, ok) : (dict, bool)
        `ok` is False only if both the original call and the retry failed
        to produce a well-formed JSON object; `proposal` is then an
        all-null/false dict, safe to treat as "nothing proposed".
    """
    history = [m for m in messages if not (isinstance(m, dict) and m.get('role') == 'system')]
    interpretation_messages = [{'role': 'system', 'content': SYSTEM_PROMPT}] + history

    response = client.chat(
        model=MODEL, messages=interpretation_messages,
        format=_PROPOSAL_JSON_SCHEMA, think=False, options={'temperature': 0},
    )
    proposal = _parse_proposal(response.message.content)
    if proposal is not None:
        return proposal, True

    retry_messages = interpretation_messages + [{
        'role': 'system',
        'content': (
            'Your previous response was not valid JSON matching the required '
            'schema. Return ONLY a valid JSON object matching that schema -- '
            'no other text.'
        ),
    }]
    response = client.chat(
        model=MODEL, messages=retry_messages,
        format=_PROPOSAL_JSON_SCHEMA, think=False, options={'temperature': 0},
    )
    proposal = _parse_proposal(response.message.content)
    if proposal is not None:
        return proposal, True

    return {field: (False if field == 'reset' else None) for field in _PROPOSAL_FIELDS}, False


def _format_pending_reply(result):
    """Deterministic formatter for a non-complete tool result -- never
    another generation step (see "One State Update Per User Turn")."""
    if result.get('conflicts'):
        return 'Conflicting feed information was given: ' + ' '.join(result['conflicts'])
    if result.get('validation_errors'):
        return 'The feed information given is invalid: ' + ' '.join(result['validation_errors'])
    if not result.get('valid', True) and result.get('error'):
        return result.get('message') or f"Could not process the feed: {result['error']}"
    pending = result.get('pending_request')
    if pending is None:
        return result.get('message', 'More information is needed.')
    text = pending['question']
    if pending.get('choices'):
        text += ' (' + ', '.join(pending['choices']) + ')'
    return text


def _format_result_reply(result):
    """Deterministic formatter for a complete tool result -- reports ONLY
    the phase and the two molar fractions (the agent's output boundary)."""
    return (
        f"Phase: {result['phase']}. "
        f"Vapor fraction: {result['vapor_fraction']:.4f}. "
        f"Liquid fraction: {result['liquid_fraction']:.4f}."
    )


def process_turn(client, messages, user_message):
    """
    Process exactly ONE user turn end-to-end and return the reply text,
    appending both the user message and the reply to `messages`.

    Per turn: at most one model call (the extraction call, plus its
    bounded malformed-JSON retry) is made; grounding, state application,
    and reply formatting are all deterministic Python from there on -- the
    model is never called again after extraction on this same turn.
    """
    messages.append({'role': 'user', 'content': user_message})

    proposal, ok = propose_feed_update(client, messages)
    if not ok:
        reply = "Sorry, I couldn't parse that -- could you restate the feed information?"
        messages.append({'role': 'assistant', 'content': reply})
        return reply

    if proposal.get('reset'):
        reset_multicomponent_feed_session()
        reply = 'Starting a new feed. Which components are in the feed?'
        messages.append({'role': 'assistant', 'content': reply})
        return reply

    if len(detect_mixed_flow_units(user_message)) > 1 and (
            proposal.get('component_flows') or proposal.get('component_flow_units')
            or proposal.get('total_flow_units')):
        reply = (
            'The message gives more than one flow unit -- please restate all '
            'component flows using one common unit (kmol/hr, mol/hr, or kg/hr).'
        )
        messages.append({'role': 'assistant', 'content': reply})
        return reply

    if len(detect_mixed_composition_basis(user_message)) > 1 and (
            proposal.get('composition') or proposal.get('composition_basis')):
        reply = (
            'The message gives composition on more than one basis -- please '
            'restate all fractions using one common basis (mole or mass).'
        )
        messages.append({'role': 'assistant', 'content': reply})
        return reply

    grounded, _rejected = ground_proposed_update(
        user_message, {k: v for k, v in proposal.items() if k != 'reset'},
        known_component_names=get_known_component_names(),
    )

    result = update_multicomponent_feed(**grounded)

    reply = _format_result_reply(result) if result.get('complete') else _format_pending_reply(result)
    messages.append({'role': 'assistant', 'content': reply})
    return reply


def run_repl():
    client = ollama.Client()
    messages = [{'role': 'system', 'content': SYSTEM_PROMPT}]

    print(f"Multicomponent distillation agent ready (model: {MODEL}). Type 'exit' to quit.")
    while True:
        try:
            user_input = input('\nYou: ').strip()
        except (EOFError, KeyboardInterrupt):
            break
        if user_input.lower() in ('exit', 'quit'):
            break
        if not user_input:
            continue

        reply = process_turn(client, messages, user_input)
        print(f"\nAssistant: {reply}")


if __name__ == '__main__':
    if len(sys.argv) > 1:
        # One-shot mode: single prompt from argv, print the reply, exit.
        client = ollama.Client()
        messages = [{'role': 'system', 'content': SYSTEM_PROMPT}]
        print(process_turn(client, messages, ' '.join(sys.argv[1:])))
    else:
        run_repl()
