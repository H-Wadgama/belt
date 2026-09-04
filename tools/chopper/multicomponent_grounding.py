"""
Deterministic field-level grounding validator for the multicomponent
feed-phase intake agent.

See tools/multicomponent-distillation-feed-phase-plan.md "Hard Grounding
Boundary" and "Composition-Basis Rules". A tool-calling model cannot be
trusted to only ever state facts actually present in the user's message --
a prompt alone cannot prevent invented pressure, flow, or unit values. This
module is the deterministic boundary between a model's PROPOSED feed
update and the persistent `multicomponent_feed_state`: the controller (the
agent module), never the model, supplies the exact current user message
text here; nothing the model proposes may reach state unless it is
grounded against that literal text.

Grounding rules enforced here, per field:
  - component_names / add_component_names : every name in the list must
    appear (case-insensitive) in the message; the WHOLE list is rejected if
    any entry doesn't, since a partial identity list changes what the feed
    even is.
  - component_flows / composition : each entry is checked independently
    (a per-key mapping) -- one ungrounded component does not discard the
    others. A numeric value is grounded if it appears literally in the
    message, or is the explicit `N% -> N/100` transform of a percentage
    token in the message.
  - total_flow / pressure / feed_temperature : the literal (or percentage-
    transformed) number must appear in the message.
  - component_flow_units / total_flow_units / pressure_units /
    feed_temperature_units : a supported alias mapping to the proposed
    canonical unit must appear literally in the message.
  - composition_basis : grounded only when the corresponding explicit
    basis wording ("wt%", "mol%", "mass fraction", "mole fraction", ...)
    appears in the message -- never guessed from context. Deferred,
    inferred-from-flow-units bases are never proposed by the model at all;
    that inference happens only in `multicomponent_feed_state.py`.

`detect_mixed_flow_units` / `detect_mixed_composition_basis` scan the raw
message directly (independent of anything the model proposed) for more
than one distinct unit/basis actually worded in the text -- the situation
where Mode A component flows or Mode B composition fractions were stated
with no single common unit/basis, which the plan requires be rejected with
a request to restate using one common unit/basis rather than silently
guessing or converting.

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
# A number is still a "percentage token" (grounds its /100 form too) when a
# basis word sits between it and the '%' -- e.g. "20 wt%" -- not just a bare
# "20%". Matched separately via lookahead so the plain-number pass above
# still finds the number itself either way.
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


def _alias_present(alias, text_lower):
    pattern = r'(?<![a-z0-9])' + re.escape(alias.lower()) + r'(?![a-z0-9])'
    return re.search(pattern, text_lower) is not None


def detect_mixed_flow_units(message):
    """Set of distinct canonical flow units (SUPPORTED_FLOW_UNITS values)
    whose alias text literally appears in `message` -- more than one entry
    means the message states more than one flow unit."""
    text_lower = (message or '').lower()
    found = set()
    for alias, canonical in FLOW_UNIT_ALIASES.items():
        if _alias_present(alias, text_lower):
            found.add(canonical)
    return found


def detect_mixed_composition_basis(message):
    """Set of composition bases ('mass' and/or 'mole') explicitly worded in
    `message` -- more than one entry means the message states composition
    on more than one basis."""
    text_lower = (message or '').lower()
    found = set()
    if any(p in text_lower for p in _MASS_BASIS_PHRASES):
        found.add('mass')
    if any(p in text_lower for p in _MOLE_BASIS_PHRASES):
        found.add('mole')
    return found


def _numeric_tokens(message):
    """All numbers literally present in `message`, plus each percentage
    token's /100 form -- both a bare "20%" and a basis-worded "20 wt%" /
    "20 mol%" ground 0.20."""
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


def _number_grounded(value, message, rel_tol=1e-6, abs_tol=1e-9):
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    tokens = _numeric_tokens(message)
    return any(
        abs(value - t) <= max(rel_tol * max(abs(value), abs(t)), abs_tol)
        for t in tokens
    )


def _name_grounded(name, message, known_component_names=()):
    """A component name is grounded if it appears literally in the CURRENT
    message, OR it is already an established component identity from an
    earlier turn -- an ordinary follow-up answer like "30, 40, 30 kmol/hr"
    legitimately doesn't re-state names the user already gave, and that is
    not the fabrication this boundary guards against (a genuinely NEW name
    the user never stated, in ANY turn, still fails this check)."""
    if not isinstance(name, str) or not name.strip():
        return False
    if name.strip().lower() in (message or '').lower():
        return True
    return name in known_component_names


def _unit_grounded(canonical_unit, message, alias_table):
    text_lower = (message or '').lower()
    for alias, canon in alias_table.items():
        if canon == canonical_unit and _alias_present(alias, text_lower):
            return True
    return False


def ground_proposed_update(message, proposed, known_component_names=()):
    """
    Validate every field in `proposed` (a dict shaped like
    `update_multicomponent_feed`'s keyword arguments) against the literal
    text of `message` -- the CURRENT user message, supplied by the
    controller, never derived from or passed through the model. Returns
    `(grounded, rejected)`:

        grounded : dict  -- only the fields/entries that passed grounding,
                    safe to merge into feed state via
                    `update_multicomponent_feed(**grounded)`.
        rejected : dict[str, str] -- field name (or "field[entity]" for a
                    dict-shaped field's individual entry) -> human-readable
                    reason, for everything dropped. Diagnostics only; never
                    raised, and never blocks the independently-grounded
                    fields from the same call.

    `known_component_names` -- the feed's already-established component
    identities (from earlier turns) -- lets a per-entry component name in
    `component_flows`/`composition` ground WITHOUT being re-stated in this
    exact message (see `_name_grounded`), so an ordinary follow-up answer
    like "30, 40, 30 kmol/hr" isn't rejected just for not repeating names
    already on record.
    """
    message = message or ''
    proposed = proposed or {}
    grounded = {}
    rejected = {}

    mixed_units = detect_mixed_flow_units(message)
    mixed_basis = detect_mixed_composition_basis(message)

    def reject(field, reason):
        rejected[field] = reason

    # --- component identity (list-shaped, all-or-nothing) ------------------
    for field in ('component_names', 'add_component_names'):
        names = proposed.get(field)
        if names is None:
            continue
        if not isinstance(names, list) or not names:
            reject(field, 'not a nonempty list of component names')
            continue
        if all(_name_grounded(n, message, known_component_names) for n in names):
            grounded[field] = names
        else:
            reject(field, f'one or more component names in {names!r} are not stated in the message')

    # --- component_flows (dict-shaped, per-entry) ---------------------------
    flows = proposed.get('component_flows')
    if flows is not None:
        if not isinstance(flows, dict):
            reject('component_flows', 'not a mapping of component name to numeric flow')
        else:
            kept = {}
            for name, value in flows.items():
                key = f'component_flows[{name}]'
                if not _name_grounded(name, message, known_component_names):
                    reject(key, 'component name not stated in the message')
                elif not _number_grounded(value, message):
                    reject(key, f'flow value {value!r} not stated in the message')
                else:
                    kept[name] = value
            if kept:
                grounded['component_flows'] = kept

    # --- composition (dict-shaped, per-entry) -------------------------------
    composition = proposed.get('composition')
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
            for name, value in composition.items():
                key = f'composition[{name}]'
                if not _name_grounded(name, message, known_component_names):
                    reject(key, 'component name not stated in the message')
                elif not _number_grounded(value, message):
                    reject(key, f'fraction value {value!r} not stated in the message')
                else:
                    kept[name] = value
            if kept:
                grounded['composition'] = kept

    # --- composition_basis ---------------------------------------------------
    basis = proposed.get('composition_basis')
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
        value = proposed.get(field)
        if value is None:
            continue
        if _number_grounded(value, message):
            grounded[field] = value
        else:
            reject(field, f'{field} value {value!r} not stated in the message')

    # --- unit fields -----------------------------------------------------------
    for field, alias_table in _UNIT_FIELD_ALIAS_TABLES.items():
        raw_unit = proposed.get(field)
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

    return grounded, rejected
