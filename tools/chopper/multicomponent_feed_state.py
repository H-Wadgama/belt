"""
Deterministic feed-state layer for multicomponent distillation intake.

See tools/multicomponent-distillation-dialogue-robustness-plan.md. Every
stored fact -- identity aside -- is exactly ONE measurement record:
`{'value', 'unit', 'status', 'provenance', 'source_turn', 'evidence'}`
(composition/basis entries carry `unit=None`, since a fraction/basis has no
unit of its own). This is deliberate: an earlier draft proposed a second,
parallel "measurements" dict alongside the plain value dict for keyed
fields (component_flows/composition) to carry unit/provenance -- rejected,
because two structures for one fact can silently disagree. There is
exactly one place each fact lives.

This module never reads a raw user message, a model proposal, or an
`intent`/`target_field` -- it only ever accepts already-checked, plain
field values (see `apply_user_update`'s `update` parameter) from the
conversation layer (`multicomponent_dialogue.py` / `multicomponent_grounding.py`
/ `multicomponent_distillation_agent.py`). Conversely, no function here
formats a user-facing question or reads message text; that is the
conversation layer's job.

This module stores only RAW explicit facts plus what is derivable by plain
arithmetic (unit-free fraction complements, same-unit flow sums, and
same-basis total*fraction products). Cross-basis conversion (e.g. a mass
composition against a molar total flow) requires molecular weights and is
deliberately NOT done here -- see multicomponent_biosteam_feed.py's
canonical component_molar_flows_kmol_per_hr conversion, which is the only
place that math happens.

No BioSTEAM calls and no LLM calls -- pure data-structure logic.
"""
import copy
import math

from multicomponent_units import (
    SUPPORTED_FLOW_UNITS,
    SUPPORTED_PRESSURE_UNITS,
    SUPPORTED_TEMPERATURE_UNITS,
    flow_unit_basis,
    temperature_to_K,
)

MIN_COMPONENTS = 3

# Every checked-fact key `apply_user_update` recognizes, tagged with the
# ONE logical group (tools/multicomponent-distillation-dialogue-robustness
# -plan.md Section 8) it belongs to. `multicomponent_dialogue.FIELD_REGISTRY`
# reuses this same mapping (via `field_group`) rather than declaring its
# own copy, so the group a field belongs to is never stated twice.
FIELD_GROUPS = {
    'component_names': 'identity',
    'component_identity_op': 'identity',
    'component_flows': 'quantity',
    'component_flow_units': 'quantity',
    'total_flow': 'quantity',
    'total_flow_units': 'quantity',
    'composition': 'quantity',
    'composition_basis': 'quantity',
    'pressure': 'pressure',
    'pressure_units': 'pressure',
    'feed_temperature': 'temperature',
    'feed_temperature_units': 'temperature',
}
GROUP_ORDER = ('identity', 'quantity', 'pressure', 'temperature')


def empty_feed_state():
    """A feed state with no identity, quantity, pressure, or thermal
    information at all. Every non-identity fact is `None` until given, then
    becomes exactly one measurement record -- never two structures for the
    same fact."""
    return {
        'component_names': [],
        'component_flows': {},
        'total_flow': None,
        'composition': {},
        'composition_basis': None,
        'pressure': None,
        'feed_temperature': None,
    }


def _record(value, unit=None, status=None, provenance='user_explicit', source_turn=None, evidence=None):
    if status is None:
        status = 'complete' if (unit is not None or value is None) else 'awaiting_unit'
    return {
        'value': value, 'unit': unit, 'status': status,
        'provenance': provenance, 'source_turn': source_turn, 'evidence': evidence,
    }


def record_value(record):
    """Public accessor -- the plain numeric/string value of a measurement
    record, or None if `record` is None or has no value yet. Every other
    module that reads a scalar/keyed fact from this state uses this
    accessor rather than indexing `['value']` directly, so the record
    shape can only ever change in one place."""
    return record['value'] if record else None


def record_unit(record):
    """Public accessor -- the unit of a measurement record, or None."""
    return record.get('unit') if record else None


def _component_key(name):
    """Case-insensitive identity key used only for matching components.

    Keep the spelling from the first established component list for display
    and for BioSTEAM, but never let a later capitalization difference create
    a second logical component (for example, ``ethanol`` and ``Ethanol``).
    """
    return name.strip().casefold() if isinstance(name, str) else name


def _canonical_component_name(state, name):
    """Return the already-established spelling for ``name`` when present."""
    key = _component_key(name)
    for established in state['component_names']:
        if _component_key(established) == key:
            return established
    return name.strip() if isinstance(name, str) else name


def _canonicalize_name_list(state, names):
    """Resolve names against established identities and deduplicate by key."""
    result = []
    seen = set()
    for name in names:
        canonical = _canonical_component_name(state, name)
        key = _component_key(canonical)
        if key not in seen:
            result.append(canonical)
            seen.add(key)
    return result


def _add_names(state, names):
    existing_keys = {_component_key(n) for n in state['component_names']}
    for name in names:
        canonical = _canonical_component_name(state, name)
        key = _component_key(canonical)
        if key not in existing_keys:
            state['component_names'].append(canonical)
            existing_keys.add(key)


def shared_component_flow_unit(state):
    """The ONE common flow unit across every component_flows measurement
    (plus total_flow's unit, if set) -- None if no unit is known yet, or if
    more than one distinct unit is present. This is a derived read, never a
    separately stored field, so it can never drift from the measurements it
    summarizes (Section 7: "derive a shared unit only when the stored
    component measurements agree")."""
    units = {r['unit'] for r in state['component_flows'].values() if r.get('unit')}
    total_unit = record_unit(state['total_flow'])
    if total_unit:
        units = units | {total_unit}
    return next(iter(units)) if len(units) == 1 else None


def apply_user_update(state, update, *, turn_number=None, evidence=None):
    """
    Non-destructive merge of already-checked facts into `state`. Never
    mutates the input; returns a new state dict. `update` and `evidence`
    are plain dicts supplied by the conversation layer -- this function
    never sees a raw message or a model proposal.

    Recognized `update` keys (all optional):

        component_names / component_identity_op :
            `component_identity_op` is one of 'initialize', 'add',
            'remove', 'replace', or omitted/None. Its meaning changes what
            `component_names` holds:
              - None / 'initialize' : the FULL identity list (only applied
                if the feed has no identity yet, or the set is identical to
                what's already established -- any other shape is silently
                ignored here; the conversation layer is responsible for
                classifying a genuine change and supplying the correct op
                instead of ever reaching this branch with one unclassified).
              - 'add'     : names to ADD to the existing identity.
              - 'remove'  : names to REMOVE (also drops their component_flows/
                composition entries).
              - 'replace' : the FULL new identity list; clears
                component_flows/total_flow/composition/composition_basis
                (they described the old feed).
        component_flows / component_flow_units :
            component_flows is {name: number}, merged per-key (overwrite);
            component_flow_units, if given, fills in the unit of any
            component_flows entry that doesn't have one yet (a shared-unit
            answer) -- it never overwrites an entry that already recorded a
            *different* unit, so a genuine cross-turn unit conflict is
            preserved for normalize_feed_state to report, not silently lost.
        total_flow / total_flow_units, pressure / pressure_units,
        feed_temperature / feed_temperature_units :
            each pair merges into ONE measurement record; a units-only
            answer fills in the pending record's unit.
        composition / composition_basis :
            composition is {name: fraction}, merged per-key.

    `evidence` mirrors `update`'s shape: a plain string for a scalar field
    (`evidence['pressure']`), or a per-component dict for a keyed field
    (`evidence['component_flows']['Water']`).
    """
    state = copy.deepcopy(state) if state else empty_feed_state()
    update = update or {}
    evidence = evidence or {}

    # --- component identity --------------------------------------------------
    op = update.get('component_identity_op')
    names_arg = update.get('component_names')
    if names_arg is not None:
        names_arg = _canonicalize_name_list(state, names_arg)
        current = state['component_names']
        if op == 'add':
            _add_names(state, names_arg)
        elif op == 'remove':
            remove_keys = {_component_key(n) for n in names_arg}
            removed_names = [n for n in current if _component_key(n) in remove_keys]
            state['component_names'] = [n for n in current if _component_key(n) not in remove_keys]
            for name in removed_names:
                state['component_flows'].pop(name, None)
                state['composition'].pop(name, None)
        elif op == 'replace':
            state['component_names'] = names_arg
            state['component_flows'] = {}
            state['total_flow'] = None
            state['composition'] = {}
            state['composition_basis'] = None
        else:
            # None or 'initialize': only ever an idempotent restatement of
            # the identical set, or the first-ever identity. A differing
            # set with no explicit op is ignored -- never a silent replace.
            if not current or {_component_key(n) for n in names_arg} == {_component_key(n) for n in current}:
                state['component_names'] = names_arg or current

    # --- component flows -------------------------------------------------------
    flows_arg = update.get('component_flows')
    shared_unit = update.get('component_flow_units')
    flow_evidence = evidence.get('component_flows') or {}
    if flows_arg:
        for name, value in flows_arg.items():
            canonical_name = _canonical_component_name(state, name)
            unit = shared_unit
            state['component_flows'][canonical_name] = _record(
                value, unit=unit, provenance='user_explicit',
                source_turn=turn_number, evidence=flow_evidence.get(name),
            )
        _add_names(state, flows_arg.keys())
    if shared_unit is not None:
        for rec in state['component_flows'].values():
            if rec.get('unit') is None:
                rec['unit'] = shared_unit
                rec['status'] = 'complete'

    # --- total_flow ---------------------------------------------------------------
    if update.get('total_flow') is not None:
        existing_unit = record_unit(state['total_flow'])
        state['total_flow'] = _record(
            update['total_flow'], unit=existing_unit, provenance='user_explicit',
            source_turn=turn_number, evidence=evidence.get('total_flow'),
        )
    if update.get('total_flow_units') is not None:
        if state['total_flow'] is None:
            state['total_flow'] = _record(None, unit=update['total_flow_units'], provenance=None)
        else:
            state['total_flow']['unit'] = update['total_flow_units']
            if state['total_flow']['value'] is not None:
                state['total_flow']['status'] = 'complete'

    # --- composition ---------------------------------------------------------------
    comp_arg = update.get('composition')
    comp_evidence = evidence.get('composition') or {}
    if comp_arg:
        for name, value in comp_arg.items():
            canonical_name = _canonical_component_name(state, name)
            state['composition'][canonical_name] = _record(
                value, provenance='user_explicit',
                source_turn=turn_number, evidence=comp_evidence.get(name),
            )
        _add_names(state, comp_arg.keys())

    if update.get('composition_basis') is not None:
        state['composition_basis'] = _record(
            update['composition_basis'], provenance='user_explicit',
            source_turn=turn_number, evidence=evidence.get('composition_basis'),
        )

    # --- pressure -----------------------------------------------------------------
    if update.get('pressure') is not None:
        existing_unit = record_unit(state['pressure'])
        state['pressure'] = _record(
            update['pressure'], unit=existing_unit, provenance='user_explicit',
            source_turn=turn_number, evidence=evidence.get('pressure'),
        )
    if update.get('pressure_units') is not None:
        if state['pressure'] is None:
            state['pressure'] = _record(None, unit=update['pressure_units'], provenance=None)
        else:
            state['pressure']['unit'] = update['pressure_units']
            if state['pressure']['value'] is not None:
                state['pressure']['status'] = 'complete'

    # --- feed_temperature -----------------------------------------------------------
    if update.get('feed_temperature') is not None:
        existing_unit = record_unit(state['feed_temperature'])
        state['feed_temperature'] = _record(
            update['feed_temperature'], unit=existing_unit, provenance='user_explicit',
            source_turn=turn_number, evidence=evidence.get('feed_temperature'),
        )
    if update.get('feed_temperature_units') is not None:
        if state['feed_temperature'] is None:
            state['feed_temperature'] = _record(None, unit=update['feed_temperature_units'], provenance=None)
        else:
            state['feed_temperature']['unit'] = update['feed_temperature_units']
            if state['feed_temperature']['value'] is not None:
                state['feed_temperature']['status'] = 'complete'

    return state


def _close(a, b, rel_tol=1e-3, abs_tol=1e-6):
    if a is None or b is None:
        return True
    return abs(a - b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)


def _issue(message, group, fields):
    return {'message': message, 'group': group, 'fields': list(fields)}


def normalize_feed_state(state):
    """
    Deterministically derive total_flow / component_flows / composition /
    composition_basis entries that are mathematically FORCED by what's
    already user_explicit, using only unit-free arithmetic. Never performs
    a cross-basis (mass<->mole) conversion -- deferred to
    multicomponent_biosteam_feed.py.

    Returns
    -------
    (new_state, conflicts) : (dict, list[dict])
        `new_state` is `state` with every derivable field filled in (never
        mutates the input). `conflicts` is a list of
        `{'message', 'group', 'fields'}` dicts -- group-tagged so a
        candidate/commit transaction can attribute a conflict to exactly
        one logical group (Section 8).
    """
    state = copy.deepcopy(state)
    names = state['component_names']

    flows = {n: r for n, r in state['component_flows'].items() if r.get('provenance') == 'user_explicit'}
    comp = {n: r for n, r in state['composition'].items() if r.get('provenance') == 'user_explicit'}
    if state['total_flow'] and state['total_flow'].get('provenance') != 'user_explicit':
        state['total_flow'] = None
    if state['composition_basis'] and state['composition_basis'].get('provenance') != 'user_explicit':
        state['composition_basis'] = None
    conflicts = []

    def known_flow_names():
        return [n for n in names if n in flows]

    def all_flows_known():
        return len(names) >= 2 and len(known_flow_names()) == len(names)

    def flow_units_present():
        return {r['unit'] for r in flows.values() if r.get('unit')}

    total_unit = record_unit(state['total_flow'])

    if state['composition_basis'] is None:
        candidate_units = flow_units_present()
        if total_unit:
            candidate_units = candidate_units | {total_unit}
        if len(candidate_units) == 1:
            inferred = flow_unit_basis(next(iter(candidate_units)))
            if inferred is not None:
                state['composition_basis'] = _record(inferred, provenance='inferred_from_total_flow_units')

    basis_value = record_value(state['composition_basis'])
    basis_matches_total_flow = (
        total_unit is not None and basis_value is not None
        and flow_unit_basis(total_unit) == basis_value
    )
    single_comp_flow_unit = next(iter(flow_units_present())) if len(flow_units_present()) == 1 else None
    basis_matches_component_flow = (
        single_comp_flow_unit is not None and basis_value is not None
        and flow_unit_basis(single_comp_flow_unit) == basis_value
    )

    all_flow_units = flow_units_present() | ({total_unit} if total_unit else set())
    units_comparable = len(all_flow_units) <= 1

    total_value = record_value(state['total_flow'])
    if state['total_flow'] is not None and state['total_flow'].get('provenance') == 'user_explicit':
        if all_flows_known() and units_comparable:
            implied_total = sum(record_value(flows[n]) for n in names)
            if not _close(implied_total, total_value):
                conflicts.append(_issue(
                    f"Component flows sum to {implied_total:g}, but total "
                    f"flow was specified as {total_value:g}.",
                    'quantity', ('component_flows', 'total_flow'),
                ))
    elif all_flows_known() and known_flow_names() and units_comparable:
        derived_unit = single_comp_flow_unit
        state['total_flow'] = _record(
            sum(record_value(flows[n]) for n in names), unit=derived_unit, provenance='derived',
        )

    total_value = record_value(state['total_flow'])
    total_unit = record_unit(state['total_flow'])
    if total_value is not None and names and units_comparable:
        missing = [n for n in names if n not in flows]
        if len(missing) == 1 and len(known_flow_names()) == len(names) - 1:
            derived_val = total_value - sum(record_value(flows[n]) for n in known_flow_names())
            flows[missing[0]] = _record(derived_val, unit=total_unit, provenance='derived')

    known_comp_names = [n for n in names if n in comp]
    if len(names) >= 2 and len(known_comp_names) == len(names) - 1:
        missing_name = [n for n in names if n not in comp][0]
        complement = 1.0 - sum(record_value(comp[n]) for n in known_comp_names)
        comp[missing_name] = _record(complement, provenance='derived')
    elif len(names) >= 2 and known_comp_names and len(known_comp_names) == len(names):
        total_frac = sum(record_value(comp[n]) for n in names)
        if not _close(total_frac, 1.0, rel_tol=0.0, abs_tol=1e-3):
            conflicts.append(_issue(f'Composition fractions sum to {total_frac:g}, not 1.', 'quantity', ('composition',)))

    known_comp_names = [n for n in names if n in comp]
    if (total_value is not None and names and len(known_comp_names) == len(names) and basis_matches_total_flow):
        for n in names:
            derived_val = total_value * record_value(comp[n])
            if n in flows:
                if not _close(record_value(flows[n]), derived_val):
                    conflicts.append(_issue(
                        f"{n} flow was specified as {record_value(flows[n]):g}, but total "
                        f"flow times composition implies {derived_val:g}.",
                        'quantity', ('component_flows', 'total_flow', 'composition'),
                    ))
            else:
                flows[n] = _record(derived_val, unit=total_unit, provenance='derived')

    total = total_value
    known_comp_names = [n for n in names if n in comp]
    if (total and all_flows_known() and len(known_comp_names) < len(names)
            and units_comparable and (basis_matches_component_flow or basis_value is None)):
        for n in names:
            implied_frac = record_value(flows[n]) / total
            if n in comp:
                if not _close(record_value(comp[n]), implied_frac):
                    conflicts.append(_issue(
                        f"{n} fraction was specified as {record_value(comp[n]):g}, but "
                        f"component flows imply {implied_frac:g}.",
                        'quantity', ('composition', 'component_flows'),
                    ))
            else:
                comp[n] = _record(implied_frac, provenance='derived')

    if len(flow_units_present()) > 1:
        conflicts.append(_issue(
            "Component flows were given in more than one unit "
            f"({', '.join(sorted(flow_units_present()))}) -- please restate "
            "all component flows using one common unit.",
            'quantity', ('component_flows',),
        ))

    state['component_flows'] = flows
    state['composition'] = comp
    return state, conflicts


def validate_feed_state(state):
    """
    Validation errors against an already-`normalize_feed_state`-d state.
    Returns list[dict] shaped like `normalize_feed_state`'s conflicts.
    """
    errors = []
    names = state['component_names']

    def _finite(v):
        return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)

    if names and len({_component_key(n) for n in names}) != len(names):
        errors.append(_issue('Duplicate component names given.', 'identity', ('component_names',)))

    for n, r in state['component_flows'].items():
        v = record_value(r)
        if not _finite(v):
            errors.append(_issue(f'{n} flow must be a finite number; got {v!r}.', 'quantity', ('component_flows',)))
        elif v <= 0:
            errors.append(_issue(f'{n} flow must be positive; got {v:g}.', 'quantity', ('component_flows',)))

    total_value = record_value(state['total_flow'])
    if total_value is not None:
        if not _finite(total_value):
            errors.append(_issue(f'total_flow must be a finite number; got {total_value!r}.', 'quantity', ('total_flow',)))
        elif total_value <= 0:
            errors.append(_issue(f'total_flow must be positive; got {total_value:g}.', 'quantity', ('total_flow',)))

    for n, r in state['composition'].items():
        v = record_value(r)
        if not _finite(v):
            errors.append(_issue(f'{n} composition fraction must be a finite number; got {v!r}.', 'quantity', ('composition',)))
        elif not (0.0 <= v <= 1.0):
            errors.append(_issue(f'{n} composition fraction must be between 0 and 1; got {v:g}.', 'quantity', ('composition',)))

    basis_value = record_value(state['composition_basis'])
    if state['composition'] and basis_value is not None and basis_value not in ('mole', 'mass'):
        errors.append(_issue(f'Composition basis must be "mole" or "mass"; got {basis_value!r}.', 'quantity', ('composition_basis',)))

    pressure_value = record_value(state['pressure'])
    if pressure_value is not None:
        if not _finite(pressure_value):
            errors.append(_issue(f'pressure must be a finite number; got {pressure_value!r}.', 'pressure', ('pressure',)))
        elif pressure_value <= 0:
            errors.append(_issue(f'pressure must be positive; got {pressure_value:g}.', 'pressure', ('pressure',)))

    temp_value = record_value(state['feed_temperature'])
    temp_unit = record_unit(state['feed_temperature'])
    if temp_value is not None:
        if not _finite(temp_value):
            errors.append(_issue(f'feed_temperature must be a finite number; got {temp_value!r}.', 'temperature', ('feed_temperature',)))
        elif temp_unit in SUPPORTED_TEMPERATURE_UNITS:
            T_K = temperature_to_K(temp_value, temp_unit)
            if T_K <= 0:
                errors.append(_issue(f'feed_temperature must be above absolute zero; got {T_K:g} K.', 'temperature', ('feed_temperature',)))

    def _check_unit(value, supported, label, group, field):
        if value is not None and value not in supported:
            errors.append(_issue(
                f"Unsupported {label} {value!r}; supported units: {', '.join(supported)}.",
                group, (field,),
            ))

    for r in state['component_flows'].values():
        _check_unit(r.get('unit'), SUPPORTED_FLOW_UNITS, 'flow unit', 'quantity', 'component_flows')
    _check_unit(record_unit(state['total_flow']), SUPPORTED_FLOW_UNITS, 'flow unit', 'quantity', 'total_flow')
    _check_unit(record_unit(state['pressure']), SUPPORTED_PRESSURE_UNITS, 'pressure unit', 'pressure', 'pressure_units')
    _check_unit(record_unit(state['feed_temperature']), SUPPORTED_TEMPERATURE_UNITS, 'temperature unit', 'temperature', 'feed_temperature_units')

    return errors


def feed_quantity_complete(state):
    """True once every named component has a known flow value (Mode A,
    possibly derived), or the total flow value and every component's
    fraction are known (Mode B)."""
    names = state['component_names']
    if not names:
        return False
    if all(n in state['component_flows'] and record_value(state['component_flows'][n]) is not None for n in names):
        return True
    return (
        record_value(state['total_flow']) is not None
        and all(n in state['composition'] and record_value(state['composition'][n]) is not None for n in names)
    )


def missing_inputs(state):
    """Ordered list of genuinely missing input identifiers. Only the FIRST
    entry should ever be surfaced to the user in one turn."""
    missing = []
    names = state['component_names']

    if len({_component_key(n) for n in names}) < MIN_COMPONENTS:
        missing.append('component_names')
        return missing

    if not feed_quantity_complete(state):
        missing.append('feed_quantity')

    any_flow_unit_given = bool(
        {r['unit'] for r in state['component_flows'].values() if r.get('unit')}
    ) or record_unit(state['total_flow']) is not None
    if not any_flow_unit_given:
        missing.append('flow_units')

    composition_started = any(
        r.get('provenance') == 'user_explicit' for r in state['composition'].values()
    )
    if composition_started and record_value(state['composition_basis']) is None:
        missing.append('composition_basis')

    if record_value(state['pressure']) is None:
        missing.append('pressure_value')
    elif record_unit(state['pressure']) is None:
        missing.append('pressure_units')

    if record_value(state['feed_temperature']) is None:
        missing.append('feed_temperature_value')
    elif record_unit(state['feed_temperature']) is None:
        missing.append('feed_temperature_units')

    return missing


def assess_feed_state(state):
    """
    Normalize + validate consistency + report missing inputs in one call.

    Returns dict with keys: 'state', 'conflicts' (list[dict]),
    'validation_errors' (list[dict]), 'missing_inputs' (list[str]), 'ready' (bool).
    """
    normalized, conflicts = normalize_feed_state(state)
    validation_errors = validate_feed_state(normalized)
    missing = missing_inputs(normalized)
    ready = (
        not conflicts and not validation_errors and not missing
        and len(normalized['component_names']) >= MIN_COMPONENTS
    )
    return {
        'state': normalized,
        'conflicts': conflicts,
        'validation_errors': validation_errors,
        'missing_inputs': missing,
        'ready': ready,
    }


def assess_candidate_transition(committed_state, checked_facts, *, turn_number=None, evidence=None):
    """
    Transactional candidate/commit (Section 8): partitions `checked_facts`
    by `FIELD_GROUPS` and applies groups in `GROUP_ORDER` (identity must
    precede quantity so an identity change's clear-quantity behavior fires
    before same-turn quantity values land). After each group's tentative
    apply, re-normalizes/validates and rejects that group alone if it
    introduces a NEW conflict/validation error tagged with its own group --
    everything else commits. `checked_facts`/`evidence` are plain data from
    the conversation layer; this function never reads a message or a model
    proposal.

    Returns
    -------
    dict with keys:
        'candidate_state' / 'committed_state' : the same final, normalized
            state (both keys kept for parity with the plan's required
            transition-result shape; there is no separate "attempted but
            not committed" state here since rejected groups are dropped
            before the final state is built).
        'accepted_groups' / 'rejected_groups' : list[str] / dict[str, dict].
        'conflicts' / 'validation_errors'      : list[dict], the union of
            every rejected group's own issues -- for user-facing reporting.
    """
    checked_facts = checked_facts or {}
    evidence = evidence or {}
    working_state = copy.deepcopy(committed_state)
    accepted_groups = []
    rejected_groups = {}

    for group in GROUP_ORDER:
        group_update = {k: v for k, v in checked_facts.items() if FIELD_GROUPS.get(k) == group}
        if not group_update:
            continue
        group_evidence = {k: v for k, v in evidence.items() if FIELD_GROUPS.get(k) == group}
        candidate = apply_user_update(working_state, group_update, turn_number=turn_number, evidence=group_evidence)
        normalized, conflicts = normalize_feed_state(candidate)
        errors = validate_feed_state(normalized)
        group_conflicts = [c for c in conflicts if c['group'] == group]
        group_errors = [e for e in errors if e['group'] == group]
        if group_conflicts or group_errors:
            rejected_groups[group] = {'conflicts': group_conflicts, 'validation_errors': group_errors}
            continue
        working_state = candidate
        accepted_groups.append(group)

    final_normalized, _residual_conflicts = normalize_feed_state(working_state)
    reported_conflicts = [c for g in rejected_groups.values() for c in g['conflicts']]
    reported_errors = [e for g in rejected_groups.values() for e in g['validation_errors']]

    return {
        'candidate_state': final_normalized,
        'committed_state': final_normalized,
        'accepted_groups': accepted_groups,
        'rejected_groups': rejected_groups,
        'conflicts': reported_conflicts,
        'validation_errors': reported_errors,
    }
