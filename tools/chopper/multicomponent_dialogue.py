"""
Session state, declarative field registry, pending-field binding, and
deterministic reply formatting for the multicomponent feed-phase agent.

See tools/multicomponent-distillation-dialogue-robustness-plan.md. This
module is part of the CONVERSATION layer (alongside
`multicomponent_distillation_agent.py` and `multicomponent_grounding.py`):
it is the only place that decides WHICH of a model's proposed fields are
even eligible for grounding this turn, based on the session's active
pending question. It never mutates feed state and never calls BioSTEAM or
Ollama -- `bind_reply_to_pending` only narrows candidate field data; the
conversation layer still runs everything it returns through
`multicomponent_grounding.ground_proposed_update` before it ever reaches
`multicomponent_feed_tool.advance_feed_state`.

This is the direct fix for the numeric-collision failure: a bare "1"
answering "what is the feed pressure?" is scoped to ONLY the pressure
field here, before grounding or feed-state ever see whatever else the
model may have hallucinated in the same response.
"""
import re

from multicomponent_feed_state import (
    MIN_COMPONENTS,
    empty_feed_state,
    record_unit,
    record_value,
)
from multicomponent_grounding import QUERY_ALIASES, detect_mixed_composition_basis
from multicomponent_units import (
    SUPPORTED_FLOW_UNITS,
    SUPPORTED_PRESSURE_UNITS,
    SUPPORTED_TEMPERATURE_UNITS,
    normalize_flow_unit,
    normalize_pressure_unit,
    normalize_temperature_unit,
)


def create_session():
    """One dialogue session -- owned by the caller (the REPL loop / one-shot
    `__main__` path), never reconstructed from model history, never shared
    between two independent conversations."""
    return {
        'feed_state': empty_feed_state(),
        'pending_request': None,
        'provisional_value': None,
        'confirmation': None,
        'turn_number': 0,
        # The immediately preceding (assistant question, user reply) pair
        # only -- narrow reference-resolution context (Section 3), never a
        # source of new facts and never the full transcript.
        'recent_turn': None,
    }


def _format_scalar(record, label):
    value = record_value(record)
    if value is None:
        return f'The {label} has not been provided yet.'
    unit = record_unit(record)
    if unit is None:
        return f'The {label} value is {value:g}, but its units have not been specified.'
    return f'The {label} is {value:g} {unit}.'


def _format_component_names(state):
    names = state['component_names']
    if not names:
        return 'No components have been given yet.'
    return 'The feed components are: ' + ', '.join(names) + '.'


def _format_component_flows(state):
    flows = state['component_flows']
    if not flows:
        return 'No component flows have been given yet.'
    parts = []
    for name, record in flows.items():
        value = record_value(record)
        unit = record_unit(record) or '(unit not yet given)'
        parts.append(f'{name}: {value:g} {unit}')
    return 'Component flows so far: ' + '; '.join(parts) + '.'


def _format_composition(state):
    comp = state['composition']
    if not comp:
        return 'No composition has been given yet.'
    basis = record_value(state['composition_basis']) or '(basis not yet given)'
    parts = [f'{name}: {record_value(record):g}' for name, record in comp.items()]
    return f'Composition so far ({basis} basis): ' + '; '.join(parts) + '.'


def _format_total_flow(state):
    return _format_scalar(state['total_flow'], 'total feed flow')


def _format_pressure(state):
    return _format_scalar(state['pressure'], 'feed pressure')


def _format_feed_temperature(state):
    return _format_scalar(state['feed_temperature'], 'feed temperature')


# The single declarative registry driving pending-question wording,
# short-answer type compatibility, query-field verification, and
# query-answer formatting (Section 10). `group` is imported from
# `multicomponent_feed_state.FIELD_GROUPS` rather than re-declared, so a
# field's logical group is never stated in two places.
FIELD_REGISTRY = {
    'component_names': {
        'value_type': 'name_list',
        'value_question': f'Which components are in the feed? At least {MIN_COMPONENTS} are required.',
        'query_aliases': QUERY_ALIASES['component_names'],
        'formatter': _format_component_names,
    },
    'component_flows': {
        'value_type': 'number_map',
        'unit_field': 'component_flow_units',
        'supported_units': list(SUPPORTED_FLOW_UNITS),
        'value_question': (
            'What is the feed quantity and composition? Give either a flow '
            'rate for every component, or the total feed flow rate plus '
            'fractions for all but one component.'
        ),
        'unit_question': 'What are the units of the feed flow rate?',
        'query_aliases': QUERY_ALIASES['component_flows'],
        'formatter': _format_component_flows,
    },
    'composition': {
        'value_type': 'fraction_map',
        'basis_question': 'Is the given composition on a mole or mass basis?',
        'query_aliases': QUERY_ALIASES['composition'],
        'formatter': _format_composition,
    },
    'total_flow': {
        'value_type': 'number',
        'unit_field': 'total_flow_units',
        'supported_units': list(SUPPORTED_FLOW_UNITS),
        'query_aliases': QUERY_ALIASES['total_flow'],
        'formatter': _format_total_flow,
    },
    'pressure': {
        'value_type': 'number',
        'unit_field': 'pressure_units',
        'supported_units': list(SUPPORTED_PRESSURE_UNITS),
        'value_question': 'What is the feed pressure?',
        'unit_question': 'What are the units of the feed pressure?',
        'query_aliases': QUERY_ALIASES['pressure'],
        'formatter': _format_pressure,
    },
    'feed_temperature': {
        'value_type': 'number',
        'unit_field': 'feed_temperature_units',
        'supported_units': list(SUPPORTED_TEMPERATURE_UNITS),
        # Section 10: user-facing wording drops "never assumed to be the
        # bubble point" -- the no-bubble-point rule is enforced internally
        # (this agent never has a bubble-point/enthalpy/quality input path
        # at all) and is asserted in tests, not repeated to the user here.
        'value_question': 'What is the feed temperature?',
        'unit_question': 'What are the units of the feed temperature?',
        'query_aliases': QUERY_ALIASES['feed_temperature'],
        'formatter': _format_feed_temperature,
    },
}

_FIELD_KEYS = {
    'component_names': ('component_names', 'component_identity_op'),
    'component_flows': ('component_flows', 'component_flow_units'),
    'composition': ('composition', 'composition_basis'),
    'total_flow': ('total_flow', 'total_flow_units'),
    'pressure': ('pressure', 'pressure_units'),
    'feed_temperature': ('feed_temperature', 'feed_temperature_units'),
}
_ALL_UPDATE_KEYS = {k for keys in _FIELD_KEYS.values() for k in keys}
_KEY_TO_FIELD = {k: fname for fname, keys in _FIELD_KEYS.items() for k in keys}

_UNIT_NORMALIZERS = {
    'component_flow_units': normalize_flow_unit,
    'total_flow_units': normalize_flow_unit,
    'pressure_units': normalize_pressure_unit,
    'feed_temperature_units': normalize_temperature_unit,
}

_BARE_NUMBER_RE = re.compile(r'^\s*-?\d+(?:\.\d+)?\s*%?\s*$')


def pending_request_for(missing_field, turn_number=None):
    """Map one `multicomponent_feed_state.missing_inputs()` identifier to a
    full pending-request dict, registry-driven. Replaces the old ad hoc
    `_PENDING_REQUESTS` table in `multicomponent_feed_tool.py`."""
    def _req(field, kind, question, allowed_units=None):
        return {
            'field': field, 'kind': kind, 'question': question,
            'allowed_units': allowed_units, 'related_value': None,
            'asked_on_turn': turn_number,
        }

    if missing_field == 'component_names':
        return _req('component_names', 'value', FIELD_REGISTRY['component_names']['value_question'])
    if missing_field == 'feed_quantity':
        return _req('component_flows', 'value', FIELD_REGISTRY['component_flows']['value_question'])
    if missing_field == 'flow_units':
        entry = FIELD_REGISTRY['component_flows']
        return _req('component_flows', 'unit', entry['unit_question'], entry['supported_units'])
    if missing_field == 'composition_basis':
        return _req('composition', 'basis', FIELD_REGISTRY['composition']['basis_question'], ['mole', 'mass'])
    if missing_field == 'pressure_value':
        return _req('pressure', 'value', FIELD_REGISTRY['pressure']['value_question'])
    if missing_field == 'pressure_units':
        entry = FIELD_REGISTRY['pressure']
        return _req('pressure', 'unit', entry['unit_question'], entry['supported_units'])
    if missing_field == 'feed_temperature_value':
        return _req('feed_temperature', 'value', FIELD_REGISTRY['feed_temperature']['value_question'])
    if missing_field == 'feed_temperature_units':
        entry = FIELD_REGISTRY['feed_temperature']
        return _req('feed_temperature', 'unit', entry['unit_question'], entry['supported_units'])
    return _req(missing_field, 'value', f'Please provide {missing_field}.')


def format_pending_question(pending):
    if pending is None:
        return 'More information is needed.'
    text = pending['question']
    if pending.get('allowed_units'):
        text += ' (' + ', '.join(pending['allowed_units']) + ')'
    return text


def format_query_answer(field, state):
    entry = FIELD_REGISTRY.get(field)
    if entry is None:
        return "I don't have that information."
    return entry['formatter'](state)


def format_extraction_context(session):
    """The three labelled sections (Section 3) sent to the model as a
    single system message, replacing an undifferentiated raw-history
    passthrough."""
    state = session['feed_state']
    lines = ['ESTABLISHED STATE SUMMARY']
    any_known = False
    for field, entry in FIELD_REGISTRY.items():
        text = entry['formatter'](state)
        if 'has not been provided yet' not in text and text.startswith('No ') is False:
            lines.append('- ' + text)
            any_known = True
    if not any_known:
        lines.append('(nothing established yet)')

    lines.append('')
    lines.append('ACTIVE REQUEST')
    pending = session.get('pending_request')
    lines.append(format_pending_question(pending) if pending else 'none')

    recent = session.get('recent_turn')
    if recent:
        lines.append('')
        lines.append('RECENT CONTEXT (for resolving references only -- never a source of new facts)')
        lines.append(f"Assistant: {recent.get('assistant', '')}")
        lines.append(f"User: {recent.get('user', '')}")

    return '\n'.join(lines)


def _synthesize_short_answer(pending, raw_message):
    """Parse `raw_message` itself as a compatible short answer for
    `pending`, entirely independent of what the model proposed -- the
    fallback that guards against the model proposing nothing usable (or
    something wrong-role) for the field it was just asked about."""
    text = (raw_message or '').strip()
    field, kind = pending['field'], pending['kind']

    if kind == 'unit':
        unit_field = FIELD_REGISTRY.get(field, {}).get('unit_field')
        normalizer = _UNIT_NORMALIZERS.get(unit_field)
        if unit_field and normalizer and normalizer(text) is not None:
            return {unit_field: text}
        return None

    if kind == 'basis':
        bases = detect_mixed_composition_basis(text)
        if len(bases) == 1:
            return {'composition_basis': next(iter(bases))}
        if text.lower() in ('mole', 'mass'):
            return {'composition_basis': text.lower()}
        return None

    if kind == 'value' and field in ('pressure', 'feed_temperature', 'total_flow'):
        if not _BARE_NUMBER_RE.match(text):
            return None
        try:
            is_pct = text.rstrip().endswith('%')
            value = float(text.rstrip().rstrip('%').strip())
        except ValueError:
            return None
        if is_pct:
            value = value / 100.0
        return {field: value}

    return None


def _identity_clarification(session, candidate):
    """Section 6: an identity change with no explicit
    `component_identity_op` and an established, differing identity gets ONE
    clarification question instead of a silent state mutation (the state
    layer's own idempotent/subset-safe handling is a defense-in-depth
    backstop, not the primary UX for this case)."""
    names = candidate.get('component_names')
    if not names or candidate.get('component_identity_op'):
        return None
    current = session['feed_state']['component_names']
    if not current or set(names) == set(current):
        return None
    return (
        'The feed already has these components: ' + ', '.join(current) + '. '
        'Are you adding ' + ', '.join(names) + ' to that list, replacing the '
        'list entirely, or removing some of them?'
    )


def _finalize(session, candidate):
    clarification = _identity_clarification(session, candidate)
    if clarification:
        return {'action': 'clarify', 'message': clarification}
    return {'action': 'candidate', 'candidate_fields': candidate}


def bind_reply_to_pending(session, intent_result, raw_message):
    """
    Scope a model's proposed fields (`intent_result`, a flat dict shaped
    like the extraction schema's fact fields plus `target_field` and
    `component_identity_action`) down to what this turn is actually
    allowed to touch. Returns either:

        {'action': 'candidate', 'candidate_fields': {...}}
        {'action': 'clarify', 'message': str}

    Never touches feed state -- `candidate_fields` still has to pass
    `multicomponent_grounding.ground_proposed_update` before it can reach
    `multicomponent_feed_tool.advance_feed_state`.
    """
    intent_result = intent_result or {}
    pending = session.get('pending_request')
    model_fields = {
        k: v for k, v in intent_result.items()
        if k in _ALL_UPDATE_KEYS and v is not None
    }

    def scoped(field_name):
        return {k: model_fields[k] for k in _FIELD_KEYS.get(field_name, ()) if k in model_fields}

    def with_identity_op(field_name, candidate):
        action = intent_result.get('component_identity_action')
        if field_name == 'component_names' and action not in (None, 'none') and candidate.get('component_names'):
            candidate['component_identity_op'] = action
        return candidate

    raw_target = intent_result.get('target_field')
    target_field = raw_target if raw_target in _FIELD_KEYS else _KEY_TO_FIELD.get(raw_target)

    if target_field:
        candidate = scoped(target_field)
        if not candidate and pending and pending['field'] == target_field:
            candidate = _synthesize_short_answer(pending, raw_message) or {}
        candidate = with_identity_op(target_field, candidate)
        return _finalize(session, candidate)

    if pending is not None:
        field = pending['field']
        candidate = scoped(field)
        if not candidate:
            candidate = _synthesize_short_answer(pending, raw_message) or {}
        if candidate:
            candidate = with_identity_op(field, candidate)
            return _finalize(session, candidate)

        other = {}
        for name in _FIELD_KEYS:
            if name == field:
                continue
            other.update(scoped(name))
        if other:
            other = with_identity_op('component_names', other)
            return _finalize(session, other)

        return {'action': 'clarify', 'message': format_pending_question(pending)}

    candidate = dict(model_fields)
    candidate = with_identity_op('component_names', candidate)
    return _finalize(session, candidate)
