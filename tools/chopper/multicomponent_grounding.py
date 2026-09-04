"""
Deterministic field-level grounding validator for the multicomponent
feed-phase intake agent.

See tools/multicomponent-distillation-dialogue-robustness-plan.md. A
tool-calling model cannot be trusted to only ever state facts actually
present in the user's message -- a prompt alone cannot prevent invented
pressure, flow, or unit values. This module is the deterministic boundary
between a model's PROPOSED feed update and the persistent
`multicomponent_feed_state`.

The actual fix for the numeric-collision failure ("1" answering a pressure
question getting attached to an unrelated hallucinated `water` value) does
NOT live here -- it lives in `multicomponent_dialogue.bind_reply_to_pending`,
which narrows the set of fields even OFFERED to this module down to the one
field a pending question named (or an explicitly-named different field)
*before* grounding ever runs. This module still only ever checks the
CURRENT user message's literal text (never conversation history) against
whatever candidate fields it is given -- that has always been true here;
the bug was that every proposed field used to be offered to it at once.

`ground_query_target_field` applies the same discipline to READ-ONLY
questions: a query is only answered once its target field's own wording is
confirmed present in the message, never trusted from the model's
`target_field` guess alone.

No BioSTEAM calls and no LLM calls -- pure text/data logic.
"""
import re

from multicomponent_units import (
    FLOW_UNIT_ALIASES,
    PRESSURE_UNIT_ALIASES,
    TEMPERATURE_UNIT_ALIASES,
    normalize_flow_unit,
    normalize_pressure_unit,
    normalize_temperature_unit,
)

_NUMBER_RE = re.compile(r'-?\d+(?:\.\d+)?\s*%?')
_PERCENT_WITH_BASIS_WORD_RE = re.compile(
    r'-?\d+(?:\.\d+)?(?=\s*(?:wt|weight|mol|mole|molar|mass)?\s*%)'
)

_MASS_BASIS_PHRASES = (
    'wt%', 'wt %', 'weight percent', 'weight %', 'mass fraction',
    'mass%', 'mass %', 'by mass', 'by weight', 'mass basis', 'weight basis',
)
_MOLE_BASIS_PHRASES = (
    'mol%', 'mol %', 'mole percent', 'mole%', 'mole %', 'mole fraction',
    'by mole', 'mole basis', 'molar basis',
)

_UNIT_FIELD_ALIAS_TABLES = {
    'component_flow_units': FLOW_UNIT_ALIASES,
    'total_flow_units': FLOW_UNIT_ALIASES,
    'pressure_units': PRESSURE_UNIT_ALIASES,
    'feed_temperature_units': TEMPERATURE_UNIT_ALIASES,
}

_UNIT_FIELD_NORMALIZERS = {
    'component_flow_units': normalize_flow_unit,
    'total_flow_units': normalize_flow_unit,
    'pressure_units': normalize_pressure_unit,
    'feed_temperature_units': normalize_temperature_unit,
}

# Question-wording aliases used ONLY to verify that a read-only query's
# claimed target field is actually named in the message -- "confirm that
# the question is about pressure before reading and reporting it from
# stored information." Deliberately short and literal; never guessed or
# expanded from synonyms not listed here.
QUERY_ALIASES = {
    'component_names': ('component', 'components', 'ingredient', 'species'),
    'component_flows': ('flow', 'flows', 'flow rate', 'flow rates'),
    'composition': ('composition', 'fraction', 'fractions', 'percent', '%'),
    'total_flow': ('total flow', 'total feed', 'feed rate', 'feed flow'),
    'pressure': ('pressure',),
    'feed_temperature': ('temperature', 'temp', 'feed temp'),
}


def _alias_present(alias, text_lower):
    pattern = r'(?<![a-z0-9])' + re.escape(alias.lower()) + r'(?![a-z0-9])'
    return re.search(pattern, text_lower) is not None


def detect_mixed_flow_units(message):
    """Set of distinct canonical flow units whose alias text literally
    appears in `message`."""
    text_lower = (message or '').lower()
    found = set()
    for alias, canonical in FLOW_UNIT_ALIASES.items():
        if _alias_present(alias, text_lower):
            found.add(canonical)
    return found


def detect_mixed_composition_basis(message):
    """Set of composition bases ('mass' and/or 'mole') explicitly worded in
    `message`."""
    text_lower = (message or '').lower()
    found = set()
    if any(p in text_lower for p in _MASS_BASIS_PHRASES):
        found.add('mass')
    if any(p in text_lower for p in _MOLE_BASIS_PHRASES):
        found.add('mole')
    return found


def _numeric_tokens(message):
    text = message or ''
    values = set()
    for match in _NUMBER_RE.finditer(text):
        token = match.group().strip()
        if not token:
            continue
        is_pct = token.endswith('%')
        raw = token[:-1].strip() if is_pct else token
        try:
            v = float(raw)
        except ValueError:
            continue
        values.add(v)
        if is_pct:
            values.add(v / 100.0)
    for match in _PERCENT_WITH_BASIS_WORD_RE.finditer(text):
        try:
            v = float(match.group())
        except ValueError:
            continue
        values.add(v / 100.0)
    return values


def _matches(value, token_value, rel_tol=1e-6, abs_tol=1e-9):
    return abs(value - token_value) <= max(rel_tol * max(abs(value), abs(token_value)), abs_tol)


def number_evidence(value, message):
    """The literal substring of `message` that grounds `value` (a plain
    number, or the /100 form of a percentage token), or None if `value`
    isn't stated anywhere in `message`. This IS the evidence text stamped
    onto the resulting measurement record -- grounding and evidence
    capture are the same pass, not two."""
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    text = message or ''
    for match in _NUMBER_RE.finditer(text):
        token = match.group().strip()
        if not token:
            continue
        is_pct = token.endswith('%')
        raw = token[:-1].strip() if is_pct else token
        try:
            v = float(raw)
        except ValueError:
            continue
        candidates = [v] + ([v / 100.0] if is_pct else [])
        if any(_matches(value, c) for c in candidates):
            return token
    for match in _PERCENT_WITH_BASIS_WORD_RE.finditer(text):
        try:
            v = float(match.group()) / 100.0
        except ValueError:
            continue
        if _matches(value, v):
            return match.group() + '%'
    return None


def _number_grounded(value, message):
    return number_evidence(value, message) is not None


def _name_grounded(name, message, known_component_names=()):
    """A component name is grounded if it appears literally in the CURRENT
    message, OR it is already an established component identity from an
    earlier turn."""
    if not isinstance(name, str) or not name.strip():
        return False
    if name.strip().lower() in (message or '').lower():
        return True
    return name in known_component_names


def unit_evidence(canonical_unit, message, alias_table):
    """The literal alias text in `message` that grounds `canonical_unit`,
    or None."""
    text_lower = (message or '').lower()
    for alias, canon in alias_table.items():
        if canon == canonical_unit and _alias_present(alias, text_lower):
            return alias
    return None


def _unit_grounded(canonical_unit, message, alias_table):
    return unit_evidence(canonical_unit, message, alias_table) is not None


def ground_query_target_field(message, target_field):
    """Confirm that `message` actually names `target_field` before a
    read-only query is ever answered from stored state -- "verify
    questions too." A `target_field` with no registered alias list (an
    unrecognized field) is never confirmed."""
    aliases = QUERY_ALIASES.get(target_field)
    if not aliases:
        return False
    text_lower = (message or '').lower()
    return any(_alias_present(alias, text_lower) for alias in aliases)


def ground_proposed_update(message, candidate_fields, known_component_names=(), active_request=None):
    """
    Validate every field in `candidate_fields` against the literal text of
    `message` -- the CURRENT user message. `candidate_fields` has already
    been narrowed by `multicomponent_dialogue.bind_reply_to_pending` to
    only the fields eligible for this turn (this is what prevents a value
    answering one pending question from grounding an unrelated field); this
    function's own job is unchanged from before: confirm literal textual
    evidence for whatever it's handed, never fabricate it.

    `active_request` (the session's current pending request dict, or None)
    is accepted for diagnostics/parity with the plan's function signature;
    grounding itself never needs to relax its current-message-only rule
    because of it -- the binder already did the field-scoping work.

    Returns `(grounded, evidence, rejected)`:

        grounded : dict  -- only the fields/entries that passed grounding;
                    ready to pass straight through as
                    `multicomponent_feed_tool.advance_feed_state`'s
                    `checked_facts` argument.
        evidence : dict  -- the literal text span that grounded each
                    accepted field (per-component for `component_flows`/
                    `composition`), shaped for `advance_feed_state`'s
                    `evidence` argument.
        rejected : dict[str, str] -- field name (or "field[entity]") ->
                    human-readable reason, for everything dropped.

    `known_component_names` lets a per-entry component name in
    `component_flows`/`composition` ground WITHOUT being re-stated in this
    exact message.
    """
    message = message or ''
    candidate_fields = candidate_fields or {}
    grounded = {}
    evidence = {}
    rejected = {}

    mixed_units = detect_mixed_flow_units(message)
    mixed_basis = detect_mixed_composition_basis(message)

    def reject(field, reason):
        rejected[field] = reason

    # --- component identity (list-shaped, all-or-nothing) ------------------
    for field in ('component_names',):
        names = candidate_fields.get(field)
        if names is None:
            continue
        if not isinstance(names, list) or not names:
            reject(field, 'not a nonempty list of component names')
            continue
        if all(_name_grounded(n, message, known_component_names) for n in names):
            grounded[field] = names
            if 'component_identity_op' in candidate_fields:
                grounded['component_identity_op'] = candidate_fields['component_identity_op']
        else:
            reject(field, f'one or more component names in {names!r} are not stated in the message')

    # --- component_flows (dict-shaped, per-entry) ---------------------------
    flows = candidate_fields.get('component_flows')
    if flows is not None:
        if not isinstance(flows, dict):
            reject('component_flows', 'not a mapping of component name to numeric flow')
        else:
            kept = {}
            kept_evidence = {}
            for name, value in flows.items():
                key = f'component_flows[{name}]'
                if not _name_grounded(name, message, known_component_names):
                    reject(key, 'component name not stated in the message')
                    continue
                ev = number_evidence(value, message)
                if ev is None:
                    reject(key, f'flow value {value!r} not stated in the message')
                else:
                    kept[name] = value
                    kept_evidence[name] = ev
            if kept:
                grounded['component_flows'] = kept
                evidence['component_flows'] = kept_evidence

    # --- composition (dict-shaped, per-entry) -------------------------------
    composition = candidate_fields.get('composition')
    if composition is not None:
        if not isinstance(composition, dict):
            reject('composition', 'not a mapping of component name to numeric fraction')
        elif len(mixed_basis) > 1:
            reject(
                'composition',
                'message states composition on more than one basis (mass and '
                'mole) -- ask the user for one common basis',
            )
        else:
            kept = {}
            kept_evidence = {}
            for name, value in composition.items():
                key = f'composition[{name}]'
                if not _name_grounded(name, message, known_component_names):
                    reject(key, 'component name not stated in the message')
                    continue
                ev = number_evidence(value, message)
                if ev is None:
                    reject(key, f'fraction value {value!r} not stated in the message')
                else:
                    kept[name] = value
                    kept_evidence[name] = ev
            if kept:
                grounded['composition'] = kept
                evidence['composition'] = kept_evidence

    # --- composition_basis ---------------------------------------------------
    basis = candidate_fields.get('composition_basis')
    if basis is not None:
        if len(mixed_basis) > 1:
            reject(
                'composition_basis',
                'message states more than one composition basis -- ask the '
                'user for one common basis',
            )
        elif basis in mixed_basis:
            grounded['composition_basis'] = basis
        else:
            reject('composition_basis', f'basis {basis!r} is not explicitly worded in the message')

    # --- scalar numeric fields -----------------------------------------------
    for field in ('total_flow', 'pressure', 'feed_temperature'):
        value = candidate_fields.get(field)
        if value is None:
            continue
        ev = number_evidence(value, message)
        if ev is not None:
            grounded[field] = value
            evidence[field] = ev
        else:
            reject(field, f'{field} value {value!r} not stated in the message')

    # --- unit fields -----------------------------------------------------------
    for field, alias_table in _UNIT_FIELD_ALIAS_TABLES.items():
        raw_unit = candidate_fields.get(field)
        if raw_unit is None:
            continue
        canonical_unit = _UNIT_FIELD_NORMALIZERS[field](raw_unit)
        if canonical_unit is None:
            reject(field, f'unrecognized unit {raw_unit!r}')
            continue
        if field in ('component_flow_units', 'total_flow_units') and len(mixed_units) > 1:
            reject(field, 'message states more than one flow unit -- ask for one common unit')
            continue
        if _unit_grounded(canonical_unit, message, alias_table):
            grounded[field] = raw_unit
        else:
            reject(field, f'unit {raw_unit!r} is not stated in the message')

    return grounded, evidence, rejected
