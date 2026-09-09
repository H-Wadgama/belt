"""
Natural-language front end for the multicomponent (>=3 component)
feed-phase intake agent, backed by a local Ollama model (default:
qwen3:8b).

See tools/multicomponent-distillation-context.md for the domain vocabulary
and scope, and tools/multicomponent-distillation-dialogue-robustness-plan.md
for the session/binding/grounding architecture this module implements:

  - The model NEVER gets a `tools=` engineering tool-calling channel. It
    performs ONE JOB per user turn: classify the turn's `intent` and
    propose, as one schema-constrained JSON object, which fields (if any)
    the CURRENT user message states.
  - That proposal is never trusted directly. `multicomponent_dialogue.
    bind_reply_to_pending` first narrows it to only the field(s) eligible
    this turn (the active pending question's field, or an explicitly named
    different field) -- this is what stops a value answering one question
    from also grounding an unrelated hallucinated field. Only THEN does
    `multicomponent_grounding.ground_proposed_update` check literal-text
    evidence for what's left.
  - Only the grounded fields are applied, in one call to
    `multicomponent_feed_tool.advance_feed_state`, directly in Python --
    never by sending a result back to the model as a second turn. The
    model is NOT called again after the extraction call: the next pending
    question, a conflict/validation message, a read-only query answer, or
    the terminal thermodynamic result is produced by deterministic Python here
    and in `multicomponent_dialogue.py`.
  - This module (plus `multicomponent_dialogue.py` and
    `multicomponent_grounding.py`) is the ONLY place that ever reads a raw
    user message or a model proposal -- `multicomponent_feed_tool.py`/
    `multicomponent_feed_state.py` only ever receive already-checked,
    plain field values.

This agent deliberately does NOT reproduce the binary chopper toolkit's
case-routing, design-assessment, RAG, or calculation-progress machinery.

Requires a running local Ollama server with the model pulled:
    ollama pull qwen3:8b

Run interactively:
    python multicomponent_distillation_agent.py

Or run a single one-shot prompt:
    python multicomponent_distillation_agent.py "hello"

Optional turn-by-turn diagnostics, off by default:

    python multicomponent_distillation_agent.py --debug
    python multicomponent_distillation_agent.py --debug-json

Diagnostic output goes to stderr; the ordinary `Assistant:` reply stays on
stdout. The trace includes the user's full message and the model's raw
output, which may contain sensitive process information.
"""
import argparse
import json
import sys

import ollama

import multicomponent_diagnostics as diag
import multicomponent_dialogue as dlg
import multicomponent_boiling_point as boiling_point
import multicomponent_critical_temperature as critical_temperature
import multicomponent_feed_phase as feed_phase
import multicomponent_feed_tool as tool
import multicomponent_grounding as ground
import multicomponent_relative_volatility as relative_volatility
from multicomponent_feed_state import assess_feed_state, record_unit, record_value
from multicomponent_units import temperature_to_K

MODEL = 'qwen3:8b'

_INTENT_VALUES = (
    'provide_information', 'answer_pending_request', 'query_current_state',
    'correct_information', 'confirm', 'deny', 'reset', 'unclear',
)
_IDENTITY_ACTIONS = ('none', 'initialize', 'add', 'remove', 'replace')

_FACT_FIELD_SCHEMAS = {
    'component_names': {'anyOf': [{'type': 'null'}, {'type': 'array', 'items': {'type': 'string'}}]},
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
    'product_purities': {'anyOf': [{'type': 'null'}, {'type': 'object', 'additionalProperties': {'type': 'number'}}]},
}
_FACT_FIELDS = tuple(_FACT_FIELD_SCHEMAS)
_META_FIELDS = ('intent', 'target_field', 'component_identity_action', 'evidence')

# tools/multicomponent-distillation-dialogue-robustness-plan.md Section 2 --
# the structured conversational-intent contract. `evidence` is captured
# for diagnostics/plan fidelity, but nothing downstream TRUSTS it: grounding
# independently re-derives its own literal-text evidence from the message,
# so a model that mis-reports its own evidence still can't corrupt state.
_TURN_INTENT_SCHEMA = {
    'type': 'object',
    'properties': {
        'intent': {'type': 'string', 'enum': list(_INTENT_VALUES)},
        'target_field': {'anyOf': [{'type': 'null'}, {'type': 'string'}]},
        'component_identity_action': {'type': 'string', 'enum': list(_IDENTITY_ACTIONS)},
        'evidence': {
            'anyOf': [
                {'type': 'null'},
                {
                    'type': 'object',
                    'additionalProperties': {
                        'anyOf': [
                            {'type': 'string'},
                            {'type': 'object', 'additionalProperties': {'type': 'string'}},
                        ],
                    },
                },
            ],
        },
        **_FACT_FIELD_SCHEMAS,
    },
    'required': list(_META_FIELDS) + list(_FACT_FIELDS),
}

SYSTEM_PROMPT = """You interpret ONE user turn for a multicomponent (three \
or more component) distillation feed-phase calculator. You do not \
calculate anything yourself and you have no callable tools -- your only \
job is to read the CURRENT user message (given separately as the final \
message) together with the ESTABLISHED STATE SUMMARY and ACTIVE REQUEST \
below, and return one JSON object matching the required schema.

intent -- classify the CURRENT user message as exactly one of:
  provide_information     -- states a new feed fact, unprompted.
  answer_pending_request  -- answers the ACTIVE REQUEST's question.
  query_current_state     -- asks what was already given (a question about \
stored information, not new information).
  correct_information     -- explicitly corrects a previously given fact.
  confirm / deny          -- a bare yes/no reply.
  reset                   -- explicitly switching to a different, unrelated \
feed, or asking to start over.
  unclear                 -- none of the above fit, or the message states \
no engineering fact and asks no clear question.

target_field -- if the message clearly names ONE specific field (one of: \
component_names, component_flows, composition, total_flow, pressure, \
feed_temperature, product_purities), name it; otherwise null. When intent is \
query_current_state, target_field MUST be set to the field being asked \
about -- this also includes phase, vapor_fraction, liquid_fraction, \
boiling_point_order, or relative_volatility \
when the user explicitly asks for the feed's equilibrium phase, vapor \
fraction, or liquid fraction (e.g. "what is the phase of the feed?", \
"what's the vapor fraction?", "what is the order of separations?"). These are read-only computed \
results, never fact fields you should populate.

component_identity_action -- 'none' unless the message explicitly adds, \
removes, or replaces feed components (e.g. "also include propanol" -> \
add; "actually, drop water" -> remove; "let's separate a completely \
different mixture instead" -> replace); otherwise 'none'.

Fact fields -- component_names, component_flows/composition (objects \
mapping a component name to a number), component_flow_units, \
total_flow_units, pressure_units, feed_temperature_units (strings), \
total_flow, pressure, feed_temperature (numbers), composition_basis \
("mole" or "mass", ONLY if the message explicitly says so), and \
product_purities (a component-to-minimum-mole-fraction mapping). Convert an \
explicit product mol% to a fraction; if the user explicitly gives one target \
for all/every product, repeat that grounded target for every established \
component.

evidence -- for each non-null fact field above, the literal substring of \
the CURRENT message that states it (a string for a scalar field, or an \
object keyed by component name for component_flows/composition); null or \
omitted for anything not stated.

Rules:
- Every fact field you did not find explicit evidence for in the CURRENT \
user message MUST be null -- never invent, guess, default, or carry \
forward a value merely because the ESTABLISHED STATE SUMMARY already \
records it.
- Never assume the feed temperature, and never default it to a bubble \
point.
- Never guess whether a stated composition is mole-basis or mass-basis.
- Never guess a unit for a flow, pressure, or temperature value.
- Never invent a component that was not named.
- component_flows values are literal per-component flow numbers actually \
stated -- never computed from a total and a fraction.
- composition values are fractions; "20%" means 0.20.
- If the message asks what was already given, set intent to \
query_current_state and target_field to the field being asked about -- do \
not populate any fact field for a query."""


def _empty_intent_result():
    result = {field: None for field in _FACT_FIELDS}
    result.update({
        'intent': 'unclear', 'target_field': None,
        'component_identity_action': 'none', 'evidence': None,
    })
    return result


def _parse_intent_result(raw_content):
    """Best-effort parse of one structured-output response. Returns None
    (never raises) if malformed."""
    if not raw_content or not isinstance(raw_content, str):
        return None
    try:
        parsed = json.loads(raw_content)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    if not (set(_META_FIELDS) | set(_FACT_FIELDS)) <= parsed.keys():
        return None
    if parsed.get('intent') not in _INTENT_VALUES:
        return None
    if parsed.get('component_identity_action') not in _IDENTITY_ACTIONS:
        return None
    return {field: parsed.get(field) for field in list(_META_FIELDS) + list(_FACT_FIELDS)}


def propose_feed_update(client, session, user_message):
    """
    Issue ONE structured-output interpretation call (plus at most one
    bounded retry on a malformed response) and return `(intent_result, ok,
    diagnostics)`. Sends exactly two messages -- a system message built
    from `SYSTEM_PROMPT` plus the labelled ESTABLISHED STATE SUMMARY /
    ACTIVE REQUEST / RECENT CONTEXT sections
    (`multicomponent_dialogue.format_extraction_context`), and the current
    user message -- never an undifferentiated raw conversation history.
    """
    context = dlg.format_extraction_context(session)
    messages = [
        {'role': 'system', 'content': SYSTEM_PROMPT + '\n\n' + context},
        {'role': 'user', 'content': user_message},
    ]

    raw_responses = []
    response = client.chat(
        model=MODEL, messages=messages, format=_TURN_INTENT_SCHEMA,
        think=False, options={'temperature': 0},
    )
    raw_responses.append(response.message.content)
    parsed = _parse_intent_result(response.message.content)
    if parsed is not None:
        return parsed, True, {
            'call_count': 1, 'raw_responses': raw_responses,
            'parsed_proposal': parsed, 'retry_used': False, 'parse_succeeded': True,
        }

    retry_messages = messages + [{
        'role': 'system',
        'content': (
            'Your previous response was not valid JSON matching the required '
            'schema. Return ONLY a valid JSON object matching that schema -- '
            'no other text.'
        ),
    }]
    response = client.chat(
        model=MODEL, messages=retry_messages, format=_TURN_INTENT_SCHEMA,
        think=False, options={'temperature': 0},
    )
    raw_responses.append(response.message.content)
    parsed = _parse_intent_result(response.message.content)
    if parsed is not None:
        return parsed, True, {
            'call_count': 2, 'raw_responses': raw_responses,
            'parsed_proposal': parsed, 'retry_used': True, 'parse_succeeded': True,
        }

    return _empty_intent_result(), False, {
        'call_count': 2, 'raw_responses': raw_responses,
        'parsed_proposal': None, 'retry_used': True, 'parse_succeeded': False,
    }


def _format_result_reply(result):
    """Report product count, Psat values, and adjacent ideal-liquid alphas.

    The boiling-point order remains in the structured result for selecting
    adjacent pairs and diagnostics, but is not printed as a user-facing list.
    """
    critical = result['critical_temperature_check']
    if not critical['ordinary_distillation_feasible']:
        details = ' '.join(
            f"The feed temperature, {item['feed_temperature_K']:g} K, is above "
            f"the critical temperature, {item['critical_temperature_K']:g} K, "
            f"of {item['component']}."
            for item in critical['violations']
        )
        return (
            'Ordinary distillation is not feasible at this temperature condition. '
            + details
            + ' Distillation relies on the existence of vapor-liquid equilibrium, '
            'which does not exist for these components at these temperature conditions.'
        )

    close_pairs = result.get('close_relative_volatility_pairs') or []
    if close_pairs:
        details = '; '.join(
            f"{item['more_volatile_component']}/{item['less_volatile_component']}: "
            f"alpha = {item['relative_volatility']:.6g}"
            for item in close_pairs
        )
        return (
            'Ordinary distillation is not preferred because these adjacent '
            f'relative volatilities are below 1.05: {details}.'
        )

    train = result.get('shortcut_train')
    if train:
        column_text = ' '.join(
            f"Column {column['column_number']} ({column['light_key']}/"
            f"{column['heavy_key']}): y_top={column['y_top']:.6g}, "
            f"x_bot={column['x_bot']:.6g}."
            for column in train['columns']
        )
        product_text = '; '.join(
            f"{product['component']}: {100 * product['achieved_mole_purity']:.4g} mol% "
            f"(minimum {100 * product['target_minimum_mole_purity']:.4g} mol%)"
            for product in train['products']
        )
        return (
            'Direct ShortcutColumn sequence completed at 101325 Pa with zero '
            'pressure drop, k=2, and partial_condenser=False. '
            + column_text
            + ' Product purities: ' + product_text + '. '
            'The specifications minimize composition-specification severity '
            'subject to the requested minimum purities.'
        )

    return 'Ordinary-distillation screening passed.'


def _format_phase_query_reply(result):
    """Deterministic formatter for a completed on-demand feed-phase
    evaluation -- the same sentence shape the terminal reply used before
    tools/multicomponent-distillation-boiling-point-order-plan.md replaced
    it as the default output. Only ever called on-demand now, when the
    user explicitly asks for the phase."""
    return (
        f"Phase: {result['phase']}. "
        f"Vapor fraction: {result['vapor_fraction']:.4f}. "
        f"Liquid fraction: {result['liquid_fraction']:.4f}."
    )


def _handle_boiling_point_order_query(session, record):
    """Calculate and report the normal-boiling-point order read-only."""
    names = list(session['feed_state'].get('component_names') or [])
    if len(names) < 3:
        return 'The boiling-point order cannot be evaluated yet -- which components are in the feed?'
    result = boiling_point.calculate_multicomponent_boiling_point_order(names)
    if record is not None:
        record['boiling_point_order'] = diag.to_jsonable(result)
    if not result.get('valid'):
        return f"Could not determine the boiling-point order: {result.get('message') or result.get('error')}"
    return (
        'Component order by normal boiling point (lowest to highest): '
        + ', '.join(result['order_low_to_high']) + '.'
    )


def _handle_relative_volatility_query(session, record):
    """Calculate and report adjacent ideal-liquid relative volatilities read-only."""
    assessment = assess_feed_state(session['feed_state'])
    if not assessment['ready']:
        missing_field = assessment['missing_inputs'][0] if assessment['missing_inputs'] else None
        pending = dlg.pending_request_for(missing_field) if missing_field else None
        return (
            'Relative volatilities cannot be evaluated yet -- '
            + (dlg.format_pending_question(pending) if pending else 'more feed information is needed.')
        )
    state = assessment['state']
    boiling = boiling_point.calculate_multicomponent_boiling_point_order(state['component_names'])
    if not boiling.get('valid'):
        return f"Could not determine relative volatilities: {boiling.get('message')}"
    temperature_K = temperature_to_K(
        record_value(state['feed_temperature']),
        record_unit(state['feed_temperature']),
    )
    critical = critical_temperature.evaluate_critical_temperatures(
        state['component_names'], temperature_K,
    )
    if not critical.get('valid'):
        return f"Could not determine relative volatilities: {critical.get('message')}"
    if not critical['ordinary_distillation_feasible']:
        return _format_result_reply({'critical_temperature_check': critical})
    volatility = relative_volatility.calculate_adjacent_relative_volatilities(
        state['component_names'], boiling['order_low_to_high'], temperature_K,
    )
    if record is not None:
        record['boiling_point_order'] = diag.to_jsonable(boiling)
        record['critical_temperature_check'] = diag.to_jsonable(critical)
        record['relative_volatility'] = diag.to_jsonable(volatility)
    if not volatility.get('valid'):
        return f"Could not determine relative volatilities: {volatility.get('message')}"
    return 'Adjacent-pair relative volatilities: ' + '; '.join(
        f"{item['more_volatile_component']}/{item['less_volatile_component']}: "
        f"{item['relative_volatility']:.6g}"
        for item in volatility['adjacent_pairs']
    ) + '.'


def _handle_phase_query(session, record):
    """
    Read-only on-demand feed-phase evaluation (see
    tools/multicomponent-distillation-boiling-point-order-plan.md
    "On-demand feed-phase evaluation"). Runs the deterministic
    `multicomponent_feed_phase` calculation directly against a snapshot of
    the committed feed state -- never caches a result into `feed_state`,
    never touches `pending_request`, and never re-derives or replaces the
    normal-boiling-point order. The `101325 Pa` boiling-point reference
    pressure is never involved here; the feed's own committed pressure is
    used, exactly as `multicomponent_feed_phase.calculate_multicomponent_
    feed_phase` requires.
    """
    assessment = assess_feed_state(session['feed_state'])

    if not assessment['ready']:
        missing = assessment['missing_inputs']
        missing_field = missing[0] if missing else None
        pending = dlg.pending_request_for(missing_field) if missing_field else None
        if record is not None:
            record['feed_phase_evaluation'] = {
                'temperature_K': None, 'pressure_Pa': None,
                'component_molar_flows_kmol_per_hr': None,
                'calculation_type': 'temperature_pressure',
                'phase': None, 'vapor_fraction': None, 'liquid_fraction': None,
                'valid': False, 'status': 'missing_inputs',
                'error': 'missing_inputs', 'message': f'missing: {missing_field}',
            }
        if pending is None:
            return 'More feed information is needed before the phase can be evaluated.'
        return (
            "The feed phase can't be evaluated yet -- "
            + dlg.format_pending_question(pending)
        )

    result, inputs = feed_phase.calculate_multicomponent_feed_phase_with_inputs(assessment['state'])
    if record is not None:
        record['feed_phase_evaluation'] = {
            'temperature_K': inputs['feed_temperature_K'],
            'pressure_Pa': inputs['pressure_Pa'],
            'component_molar_flows_kmol_per_hr': diag.to_jsonable(inputs['component_molar_flows_kmol_per_hr']),
            'calculation_type': 'temperature_pressure',
            'phase': result.get('phase'),
            'vapor_fraction': result.get('vapor_fraction'),
            'liquid_fraction': result.get('liquid_fraction'),
            'valid': result.get('valid'),
            'status': 'complete' if result.get('valid') else 'failed',
            'error': result.get('error'),
            'message': result.get('message'),
        }

    if not result.get('valid'):
        return f"Could not evaluate the feed phase: {result.get('message') or result.get('error')}"
    return _format_phase_query_reply(result)


def _emit_debug_record(record, debug_mode):
    text = diag.render_json(record) if debug_mode == 'json' else diag.render_human_readable(record)
    print(text, file=sys.stderr)


def process_turn(client, session, user_message, debug_mode=None):
    """
    Process exactly ONE user turn end-to-end and return the reply text.
    Mutates `session` in place (`feed_state`, `pending_request`,
    `turn_number`, `recent_turn`).

    Per turn: at most one model call (plus its bounded malformed-JSON
    retry) is made; binding, grounding, state application, and reply
    formatting are all deterministic Python from there on.
    """
    session['turn_number'] = session.get('turn_number', 0) + 1
    turn_number = session['turn_number']

    record = diag.new_turn_record(turn_number, user_message) if debug_mode else None
    if record is not None:
        record['pending_before'] = session.get('pending_request')
        record['active_request_before'] = session.get('pending_request')
        record['state_before'] = diag.to_jsonable(session['feed_state'])

    reply = None
    exit_path = None
    try:
        proposal, ok, model_diagnostics = propose_feed_update(client, session, user_message)
        if record is not None:
            record['model'] = model_diagnostics
            record['intent'] = proposal.get('intent')
            record['target_field'] = proposal.get('target_field')
            record['evidence'] = proposal.get('evidence')

        if not ok:
            reply = "Sorry, I couldn't parse that -- could you restate the feed information?"
            exit_path = 'model_parse_failure'
            return reply

        intent = proposal.get('intent')

        # First honor an unambiguous literal answer to the active question.
        # This path is independent of Qwen's intent/target/value proposal, so
        # a bare numeric or unit answer cannot be lost merely because the
        # model called it unclear, assigned the wrong value, or chose the
        # wrong intent.
        direct_binding = dlg.bind_direct_reply_to_pending(
            session, user_message,
        )

        if direct_binding is None and intent == 'reset':
            session['feed_state'] = tool.reset_multicomponent_feed_session()
            session['pending_request'] = None
            if record is not None:
                record['function_calls'].append({
                    'name': 'reset_multicomponent_feed_session', 'arguments': {},
                    'result': diag.to_jsonable(session['feed_state']),
                })
            reply = 'Starting a new feed. Which components are in the feed?'
            exit_path = 'reset'
            return reply

        if direct_binding is None and intent == 'query_current_state':
            target_field = proposal.get('target_field')
            verified = bool(target_field) and ground.ground_query_target_field(user_message, target_field)
            if verified and target_field in ground.PHASE_QUERY_FIELDS:
                reply = _handle_phase_query(session, record)
                exit_path = 'phase_query'
                return reply
            if verified and target_field in ground.BOILING_ORDER_QUERY_FIELDS:
                reply = _handle_boiling_point_order_query(session, record)
                exit_path = 'boiling_point_order_query'
                return reply
            if verified and target_field in ground.RELATIVE_VOLATILITY_QUERY_FIELDS:
                reply = _handle_relative_volatility_query(session, record)
                exit_path = 'relative_volatility_query'
                return reply
            if verified:
                snapshot = tool.query_feed_state(session['feed_state'], target_field)
                answer = dlg.format_query_answer(target_field, snapshot)
                if session.get('pending_request'):
                    answer += ' ' + dlg.format_pending_question(session['pending_request'])
                reply = answer
                if record is not None:
                    record['query_result'] = answer
                exit_path = 'query_answered'
            else:
                reply = (
                    "I'm not sure which value you're asking about -- could "
                    "you say which one (e.g. pressure, temperature, "
                    "composition)?"
                )
                exit_path = 'query_unclear'
            return reply

        if direct_binding is None and intent == 'unclear':
            pending = session.get('pending_request')
            reply = dlg.format_pending_question(pending) if pending else (
                "Could you tell me more about the feed you'd like to evaluate?"
            )
            exit_path = 'unclear'
            return reply

        # provide_information / answer_pending_request / correct_information
        # / confirm / deny all flow through the same bind -> ground -> commit
        # pipeline; the binder decides field scope from the active pending
        # request regardless of which of these the message was classified as.
        binding = direct_binding or dlg.bind_reply_to_pending(
            session, proposal, user_message,
        )
        if record is not None:
            record['binding_decision'] = binding

        if binding['action'] == 'clarify':
            reply = binding['message']
            exit_path = 'clarification'
            return reply

        candidate_fields = dict(binding['candidate_fields'])

        mixed_units = ground.detect_mixed_flow_units(user_message)
        mixed_basis = ground.detect_mixed_composition_basis(user_message)
        if record is not None:
            record['prechecks'] = {
                'detected_flow_units': sorted(mixed_units),
                'detected_composition_bases': sorted(mixed_basis),
                'mixed_flow_units': len(mixed_units) > 1,
                'mixed_composition_basis': len(mixed_basis) > 1,
            }

        if len(mixed_units) > 1 and (
                candidate_fields.get('component_flows') or candidate_fields.get('component_flow_units')
                or candidate_fields.get('total_flow_units')):
            reply = (
                'The message gives more than one flow unit -- please restate all '
                'component flows using one common unit (kmol/hr, mol/hr, or kg/hr).'
            )
            exit_path = 'mixed_flow_units'
            return reply

        if len(mixed_basis) > 1 and (
                candidate_fields.get('composition') or candidate_fields.get('composition_basis')):
            reply = (
                'The message gives composition on more than one basis -- please '
                'restate all fractions using one common basis (mole or mass).'
            )
            exit_path = 'mixed_composition_basis'
            return reply

        grounded, evidence, rejected = ground.ground_proposed_update(
            user_message, candidate_fields,
            known_component_names=tool.get_known_component_names(session['feed_state']),
            active_request=session.get('pending_request'),
        )
        if record is not None:
            record['grounding'] = {'accepted': diag.to_jsonable(grounded), 'rejected': diag.to_jsonable(rejected)}
            record['evidence'] = diag.to_jsonable(evidence)

        if not grounded:
            pending = session.get('pending_request')
            reply = dlg.format_pending_question(pending) if pending else (
                "I couldn't find that information stated in your message -- could you restate it?"
            )
            exit_path = 'nothing_grounded'
            return reply

        result = tool.advance_feed_state(
            session['feed_state'], grounded, turn_number=turn_number, evidence=evidence,
        )
        session['feed_state'] = result['feed_state']
        if record is not None:
            record['function_calls'].append({
                'name': 'advance_feed_state', 'arguments': diag.to_jsonable(grounded),
                'result': diag.to_jsonable(result),
            })
            record['accepted_groups'] = result['accepted_groups']
            record['rejected_groups'] = diag.to_jsonable(result['rejected_groups'])
            record['committed_state'] = diag.to_jsonable(result['feed_state'])
            record['rollback'] = not result['accepted_groups']
            if result.get('boiling_point_order') is not None:
                record['boiling_point_order'] = diag.to_jsonable(result['boiling_point_order'])
            if result.get('critical_temperature_check') is not None:
                record['critical_temperature_check'] = diag.to_jsonable(
                    result['critical_temperature_check']
                )
            if result.get('relative_volatility') is not None:
                record['relative_volatility'] = diag.to_jsonable(result['relative_volatility'])
            if result.get('product_specification') is not None:
                record['product_specification'] = diag.to_jsonable(result['product_specification'])
            if result.get('shortcut_train') is not None:
                record['shortcut_train'] = diag.to_jsonable(result['shortcut_train'])

        if result['conflicts']:
            reply = 'Conflicting feed information was given: ' + ' '.join(c['message'] for c in result['conflicts'])
            exit_path = 'conflict'
            return reply

        if result['validation_errors']:
            reply = 'The feed information given is invalid: ' + ' '.join(e['message'] for e in result['validation_errors'])
            exit_path = 'validation_error'
            return reply

        if result.get('error'):
            reply = result.get('error_message') or f"Could not process the feed: {result['error']}"
            exit_path = 'calculation_error'
            return reply

        if result['complete']:
            session['pending_request'] = None
            reply = _format_result_reply(result)
            exit_path = 'complete_result'
            return reply

        pending = dlg.pending_request_for(result['missing_field'], turn_number=turn_number) if result['missing_field'] else None
        session['pending_request'] = pending
        reply = dlg.format_pending_question(pending) if pending else 'More information is needed.'
        exit_path = 'pending_request'
        return reply
    finally:
        session['recent_turn'] = {'assistant': reply, 'user': user_message}
        if record is not None:
            record['active_request_after'] = session.get('pending_request')
            record['reply'] = reply
            record['exit_path'] = exit_path
            record['state_after'] = diag.to_jsonable(session['feed_state'])
            record['state_diff'] = diag.compute_state_diff(record['state_before'], record['state_after'])
            _emit_debug_record(record, debug_mode)


def _build_arg_parser():
    parser = argparse.ArgumentParser(
        prog='multicomponent_distillation_agent.py',
        description=(
            'Natural-language front end for the multicomponent (>=3 '
            'component) feed-phase intake agent.'
        ),
    )
    debug_group = parser.add_mutually_exclusive_group()
    debug_group.add_argument(
        '--debug', action='store_true',
        help=(
            "Print a compact human-readable diagnostic trace of every turn "
            "to stderr; the ordinary Assistant reply still goes to stdout. "
            "WARNING: the trace includes the full raw user message and the "
            "model's raw output, which may contain sensitive process "
            "information."
        ),
    )
    debug_group.add_argument(
        '--debug-json', action='store_true',
        help=(
            "Print one complete JSON diagnostic object per turn to stderr; "
            "the ordinary Assistant reply still goes to stdout. WARNING: "
            "the trace includes the full raw user message and the model's "
            "raw output, which may contain sensitive process information."
        ),
    )
    parser.add_argument(
        'prompt', nargs='*',
        help='One-shot prompt text. If omitted, starts an interactive REPL.',
    )
    return parser


def run_repl(debug_mode=None):
    client = ollama.Client()
    session = dlg.create_session()

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

        reply = process_turn(client, session, user_input, debug_mode=debug_mode)
        print(f"\nAssistant: {reply}")


if __name__ == '__main__':
    args = _build_arg_parser().parse_args()
    debug_mode = 'json' if args.debug_json else ('human' if args.debug else None)

    if args.prompt:
        client = ollama.Client()
        session = dlg.create_session()
        print(process_turn(client, session, ' '.join(args.prompt), debug_mode=debug_mode))
    else:
        run_repl(debug_mode=debug_mode)
