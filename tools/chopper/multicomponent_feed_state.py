"""
Deterministic feed-state layer for multicomponent distillation intake.

See tools/multicomponent-distillation-feed-phase-plan.md "State and
Validation Changes". Generalizes the binary `feed_state.py` merge/
normalize/completeness pattern to any number of components (the agent
itself only ever uses this for >=3 -- see MIN_COMPONENTS -- but nothing in
this module hard-codes a component count), keyed by component name so the
logic is independent of how many components are involved. Also carries
pressure and the feed's single thermal specification -- temperature is the
ONLY accepted thermal input for this agent (see "Scope Boundaries" in the
plan); enthalpy and quality are not fields of this state at all.

Every quantity here is tagged with its provenance -- 'user_explicit' or
'derived' -- same convention as `feed_state.py`, so a later user correction
never leaves a stale derived value behind. Composition basis additionally
carries its own provenance -- 'user_explicit' or
'inferred_from_total_flow_units' -- since a bare percentage's basis is
deferred until the total-flow unit is known (Composition-Basis Rules) and
must be re-inferred, not left stale, if the flow units later change.

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
    normalize_flow_unit,
    normalize_pressure_unit,
    normalize_temperature_unit,
    temperature_to_K,
)

MIN_COMPONENTS = 3


def empty_feed_state():
    """A feed state with no identity, quantity, pressure, or thermal information at all."""
    return {
        'component_names': [],
        'component_flows': {},
        'component_flows_provenance': {},
        'component_flow_units': None,
        'total_flow': None,
        'total_flow_provenance': None,
        'total_flow_units': None,
        'composition': {},
        'composition_provenance': {},
        'composition_basis': None,
        'composition_basis_provenance': None,
        'pressure': None,
        'pressure_provenance': None,
        'pressure_units': None,
        'feed_temperature': None,
        'feed_temperature_provenance': None,
        'feed_temperature_units': None,
    }


def _add_names(state, names):
    for name in names:
        if name not in state['component_names']:
            state['component_names'].append(name)


def apply_user_update(state, update):
    """
    Non-destructive merge of a partial update into `state`. Never mutates
    the input; returns a new state dict.

    Recognized keys in `update` (all optional; anything else is ignored, so
    a full accumulated spec dict can be passed straight through):

        component_names        : list[str] -- REPLACES the feed's identity
                                  entirely. Because a changed identity
                                  invalidates any previously known/derived
                                  quantity, this also clears
                                  component_flows, total_flow, and
                                  composition (and their provenance).
        add_component_names    : list[str] -- APPENDS to the existing
                                  identity without touching any known
                                  quantity.
        component_flows        : dict[str, float] -- merged into the
                                  existing component_flows (per-key
                                  overwrite), each marked 'user_explicit'.
                                  Any name not yet in component_names is
                                  added to it.
        component_flow_units   : str -- overwrites if given; normalized
                                  through the unit registry (stored as-is,
                                  unnormalized, if the alias is not
                                  recognized, so validation can report it).
        total_flow              : float -- overwrites if given, marked
                                  'user_explicit'.
        total_flow_units        : str -- overwrites if given (normalized).
        composition              : dict[str, float] -- merged like
                                  component_flows, each marked
                                  'user_explicit'.
        composition_basis        : str -- 'mole' or 'mass', overwrites if
                                  given; always marked 'user_explicit'
                                  (deferred, inferred bases are only ever
                                  set by normalize_feed_state, never here).
        pressure / pressure_units             : float / str.
        feed_temperature / feed_temperature_units : float / str.

    A component name never implies a component flow, and a single
    component's flow is never treated as the total feed flow -- this
    function only ever records what was explicitly given.
    """
    state = copy.deepcopy(state) if state else empty_feed_state()
    update = update or {}

    if update.get('component_names') is not None:
        new_names = list(dict.fromkeys(update['component_names']))
        # A tool-calling model cannot be relied on to omit already-known
        # facts on every turn (see multicomponent_grounding.py's
        # known-component-names grounding fallback) -- a REDUNDANT
        # restatement of the exact same identity set must never wipe out
        # quantities already established for it. Only an actual identity
        # CHANGE (a different set of names) clears them.
        if set(new_names) != set(state['component_names']):
            state['component_names'] = new_names
            state['component_flows'] = {}
            state['component_flows_provenance'] = {}
            state['component_flow_units'] = None
            state['total_flow'] = None
            state['total_flow_provenance'] = None
            state['total_flow_units'] = None
            state['composition'] = {}
            state['composition_provenance'] = {}
            state['composition_basis'] = None
            state['composition_basis_provenance'] = None

    if update.get('add_component_names'):
        _add_names(state, update['add_component_names'])

    if update.get('component_flows'):
        for name, value in update['component_flows'].items():
            state['component_flows'][name] = value
            state['component_flows_provenance'][name] = 'user_explicit'
        _add_names(state, update['component_flows'].keys())

    if update.get('component_flow_units') is not None:
        raw = update['component_flow_units']
        state['component_flow_units'] = normalize_flow_unit(raw) or raw

    if update.get('total_flow') is not None:
        state['total_flow'] = update['total_flow']
        state['total_flow_provenance'] = 'user_explicit'

    if update.get('total_flow_units') is not None:
        raw = update['total_flow_units']
        state['total_flow_units'] = normalize_flow_unit(raw) or raw

    if update.get('composition'):
        for name, value in update['composition'].items():
            state['composition'][name] = value
            state['composition_provenance'][name] = 'user_explicit'
        _add_names(state, update['composition'].keys())

    if update.get('composition_basis') is not None:
        state['composition_basis'] = update['composition_basis']
        state['composition_basis_provenance'] = 'user_explicit'

    if update.get('pressure') is not None:
        state['pressure'] = update['pressure']
        state['pressure_provenance'] = 'user_explicit'

    if update.get('pressure_units') is not None:
        raw = update['pressure_units']
        state['pressure_units'] = normalize_pressure_unit(raw) or raw

    if update.get('feed_temperature') is not None:
        state['feed_temperature'] = update['feed_temperature']
        state['feed_temperature_provenance'] = 'user_explicit'

    if update.get('feed_temperature_units') is not None:
        raw = update['feed_temperature_units']
        state['feed_temperature_units'] = normalize_temperature_unit(raw) or raw

    return state


def _close(a, b, rel_tol=1e-3, abs_tol=1e-6):
    if a is None or b is None:
        return True
    return abs(a - b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)


def normalize_feed_state(state):
    """
    Deterministically derive total_flow / component_flows / composition /
    composition_basis entries that are mathematically FORCED by what's
    already user_explicit, using only unit-free arithmetic (fraction
    complements, same-unit sums, same-basis total*fraction products).
    Never invents a value beyond what that arithmetic requires, and never
    performs a cross-basis (mass<->mole) conversion -- that needs molecular
    weights and is deferred to multicomponent_biosteam_feed.py.

    Also cross-checks redundant explicit information for contradictions
    (e.g. component flows that don't sum to an explicitly-given total flow
    when their units agree, or N composition fractions that don't sum to
    1), and infers a still-unset composition basis from the known flow
    units (Composition-Basis Rules 3-4) -- re-inferring it fresh every call
    so a later change to the flow units never leaves a stale inferred basis
    behind.

    Returns
    -------
    (new_state, conflicts) : (dict, list[str])
        `new_state` is `state` with every derivable field filled in
        (never mutates the input). `conflicts` is a list of human-readable
        contradiction descriptions; when non-empty, the caller should
        treat the feed as inconsistent rather than proceeding.
    """
    state = copy.deepcopy(state)
    names = state['component_names']

    # Drop every previously-DERIVED value before recomputing -- only what's
    # still 'user_explicit' survives untouched. Every derived value below is
    # either recomputed fresh from the current explicit values, or correctly
    # disappears if it's no longer mathematically forced -- so a correction
    # on a later turn can never leave a stale derived value behind.
    flows = {
        n: v for n, v in state['component_flows'].items()
        if state['component_flows_provenance'].get(n) == 'user_explicit'
    }
    flows_prov = {n: 'user_explicit' for n in flows}
    comp = {
        n: v for n, v in state['composition'].items()
        if state['composition_provenance'].get(n) == 'user_explicit'
    }
    comp_prov = {n: 'user_explicit' for n in comp}
    if state['total_flow_provenance'] != 'user_explicit':
        state['total_flow'] = None
        state['total_flow_provenance'] = None
    if state['composition_basis_provenance'] != 'user_explicit':
        state['composition_basis'] = None
        state['composition_basis_provenance'] = None
    conflicts = []

    def known_flow_names():
        return [n for n in names if n in flows]

    def all_flows_known():
        # len(names) >= 2 guards against a degenerate single-named-component
        # state: one component's flow must never read as "all flows known".
        return len(names) >= 2 and len(known_flow_names()) == len(names)

    # --- Composition-Basis Rules 3-4: infer a still-unset basis from
    # whichever flow-unit is already known. Explicit bases (still present
    # above) are never overridden. ---
    if state['composition_basis'] is None:
        flow_units_for_basis = state['total_flow_units'] or state['component_flow_units']
        inferred = flow_unit_basis(normalize_flow_unit(flow_units_for_basis) or flow_units_for_basis) \
            if flow_units_for_basis else None
        if inferred is not None:
            state['composition_basis'] = inferred
            state['composition_basis_provenance'] = 'inferred_from_total_flow_units'

    basis_matches_total_flow = (
        state['total_flow_units'] is not None and state['composition_basis'] is not None
        and flow_unit_basis(normalize_flow_unit(state['total_flow_units']) or state['total_flow_units'])
        == state['composition_basis']
    )
    basis_matches_component_flow = (
        state['component_flow_units'] is not None and state['composition_basis'] is not None
        and flow_unit_basis(normalize_flow_unit(state['component_flow_units']) or state['component_flow_units'])
        == state['composition_basis']
    )

    # --- total_flow vs. component_flows (only comparable when their units
    # agree, or at least one side's units are still unknown -- a genuine
    # cross-unit comparison needs molecular weights and is deferred). ---
    units_comparable = (
        state['component_flow_units'] is None or state['total_flow_units'] is None
        or state['component_flow_units'] == state['total_flow_units']
    )
    if state['total_flow_provenance'] == 'user_explicit':
        if all_flows_known() and units_comparable:
            implied_total = sum(flows[n] for n in names)
            if not _close(implied_total, state['total_flow']):
                conflicts.append(
                    f"Component flows sum to {implied_total:g}, but total "
                    f"flow was specified as {state['total_flow']:g}."
                )
    elif all_flows_known() and known_flow_names() and units_comparable:
        state['total_flow'] = sum(flows[n] for n in names)
        state['total_flow_provenance'] = 'derived'
        if state['total_flow_units'] is None:
            state['total_flow_units'] = state['component_flow_units']

    # --- total_flow known + all-but-one component flow known (same units)
    # -> derive it. ---
    if state['total_flow'] is not None and names and units_comparable:
        missing = [n for n in names if n not in flows]
        if len(missing) == 1 and len(known_flow_names()) == len(names) - 1:
            derived = state['total_flow'] - sum(flows[n] for n in known_flow_names())
            flows[missing[0]] = derived
            flows_prov[missing[0]] = 'derived'

    # --- N-1 of N composition fractions known -> derive the last one.
    # Pure arithmetic (fractions on one common basis sum to 1 regardless of
    # what that basis is), so this needs no molecular weights. ---
    known_comp_names = [n for n in names if n in comp]
    if len(names) >= 2 and len(known_comp_names) == len(names) - 1:
        missing_name = [n for n in names if n not in comp][0]
        complement = 1.0 - sum(comp[n] for n in known_comp_names)
        comp[missing_name] = complement
        comp_prov[missing_name] = 'derived'
    elif len(names) >= 2 and known_comp_names and len(known_comp_names) == len(names):
        total_frac = sum(comp[n] for n in names)
        if not _close(total_frac, 1.0, rel_tol=0.0, abs_tol=1e-3):
            conflicts.append(f'Composition fractions sum to {total_frac:g}, not 1.')

    # --- total_flow known + full composition known, ON THE SAME BASIS as
    # total_flow_units implies -> derive component_flows directly (no MW
    # needed since basis already agrees). A basis that disagrees with
    # total_flow_units (e.g. a mass composition against a molar total) is
    # left to multicomponent_biosteam_feed.py's MW-aware conversion. ---
    known_comp_names = [n for n in names if n in comp]
    if (state['total_flow'] is not None and names and len(known_comp_names) == len(names)
            and basis_matches_total_flow):
        for n in names:
            derived = state['total_flow'] * comp[n]
            if n in flows:
                if not _close(flows[n], derived):
                    conflicts.append(
                        f"{n} flow was specified as {flows[n]:g}, but total "
                        f"flow times composition implies {derived:g}."
                    )
            else:
                flows[n] = derived
                flows_prov[n] = 'derived'
        if state['component_flow_units'] is None:
            state['component_flow_units'] = state['total_flow_units']

    # --- Reverse: total_flow + all component_flows known (same basis as
    # component_flow_units) -> derive composition (flag disagreement with
    # any explicit fraction). ---
    total = state['total_flow']
    known_comp_names = [n for n in names if n in comp]
    if (total and all_flows_known() and len(known_comp_names) < len(names)
            and units_comparable and (basis_matches_component_flow or state['composition_basis'] is None)):
        for n in names:
            implied_frac = flows[n] / total
            if n in comp:
                if not _close(comp[n], implied_frac):
                    conflicts.append(
                        f"{n} fraction was specified as {comp[n]:g}, but "
                        f"component flows imply {implied_frac:g}."
                    )
            else:
                comp[n] = implied_frac
                comp_prov[n] = 'derived'

    state['component_flows'] = flows
    state['component_flows_provenance'] = flows_prov
    state['composition'] = comp
    state['composition_provenance'] = comp_prov
    return state, conflicts


def feed_quantity_complete(state):
    """
    True once the feed QUANTITY VALUES are fully pinned down -- either
    every named component has a known flow (Mode A, possibly derived), or
    the total flow value and every component's fraction are known (Mode
    B). Deliberately does NOT require flow units or a resolved composition
    basis here -- those are reported as their own, later missing-input
    items (`flow_units`, `composition_basis`) so that "total flow value +
    fractions given, units not yet stated" surfaces as a units question,
    not a generic re-ask for the quantity (plan: "the next question is for
    total-flow units... infer the basis and continue without a redundant
    basis question").
    """
    names = state['component_names']
    if not names:
        return False
    if all(n in state['component_flows'] for n in names):
        return True
    return state['total_flow'] is not None and all(n in state['composition'] for n in names)


def validate_feed_state(state):
    """
    Validation errors against an already-`normalize_feed_state`-d state --
    genuinely invalid combinations of what IS present, as opposed to
    `missing_inputs` (below), which reports what is not yet present at all.

    Returns list[str] of human-readable error messages (empty if none).
    """
    errors = []
    names = state['component_names']

    def _finite(v):
        return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)

    if names and len(set(names)) != len(names):
        errors.append('Duplicate component names given.')

    for n, v in state['component_flows'].items():
        if not _finite(v):
            errors.append(f'{n} flow must be a finite number; got {v!r}.')
        elif v <= 0:
            errors.append(f'{n} flow must be positive; got {v:g}.')

    if state['total_flow'] is not None:
        if not _finite(state['total_flow']):
            errors.append(f"total_flow must be a finite number; got {state['total_flow']!r}.")
        elif state['total_flow'] <= 0:
            errors.append(f"total_flow must be positive; got {state['total_flow']:g}.")

    for n, v in state['composition'].items():
        if not _finite(v):
            errors.append(f'{n} composition fraction must be a finite number; got {v!r}.')
        elif not (0.0 <= v <= 1.0):
            errors.append(f'{n} composition fraction must be between 0 and 1; got {v:g}.')

    if state['composition'] and state['composition_basis'] is not None \
            and state['composition_basis'] not in ('mole', 'mass'):
        errors.append(
            f"Composition basis must be \"mole\" or \"mass\"; got "
            f"{state['composition_basis']!r}."
        )

    if state['pressure'] is not None:
        if not _finite(state['pressure']):
            errors.append(f"pressure must be a finite number; got {state['pressure']!r}.")
        elif state['pressure'] <= 0:
            errors.append(f"pressure must be positive; got {state['pressure']:g}.")

    if state['feed_temperature'] is not None:
        if not _finite(state['feed_temperature']):
            errors.append(f"feed_temperature must be a finite number; got {state['feed_temperature']!r}.")
        elif state['feed_temperature_units'] in SUPPORTED_TEMPERATURE_UNITS:
            T_K = temperature_to_K(state['feed_temperature'], state['feed_temperature_units'])
            if T_K <= 0:
                errors.append(f'feed_temperature must be above absolute zero; got {T_K:g} K.')

    def _check_unit(value, supported, label):
        if value is not None and value not in supported:
            errors.append(
                f"Unsupported {label} {value!r}; supported units: "
                f"{', '.join(supported)}."
            )

    _check_unit(state['component_flow_units'], SUPPORTED_FLOW_UNITS, 'flow unit')
    _check_unit(state['total_flow_units'], SUPPORTED_FLOW_UNITS, 'flow unit')
    _check_unit(state['pressure_units'], SUPPORTED_PRESSURE_UNITS, 'pressure unit')
    _check_unit(state['feed_temperature_units'], SUPPORTED_TEMPERATURE_UNITS, 'temperature unit')

    return errors


def missing_inputs(state):
    """
    Ordered list of genuinely missing input identifiers, following:
    1. component identities, 2. feed quantity/composition, 3. shared flow
    or total-flow units, 4. composition-basis conflict (only when
    composition was given but no basis could be resolved, explicit or
    inferred), 5. pressure value, 6. pressure units, 7. feed temperature
    value, 8. feed temperature units.

    Only the FIRST entry should ever be surfaced to the user in one turn.
    """
    missing = []
    names = state['component_names']

    if len(set(names)) < MIN_COMPONENTS:
        missing.append('component_names')
        return missing

    if not feed_quantity_complete(state):
        missing.append('feed_quantity')

    flow_units = state['component_flow_units'] or state['total_flow_units']
    if flow_units is None:
        missing.append('flow_units')

    composition_started = any(
        state['composition_provenance'].get(n) == 'user_explicit' for n in names
    )
    if composition_started and state['composition_basis'] is None:
        missing.append('composition_basis')

    if state['pressure'] is None:
        missing.append('pressure_value')
    elif state['pressure_units'] is None:
        missing.append('pressure_units')

    if state['feed_temperature'] is None:
        missing.append('feed_temperature_value')
    elif state['feed_temperature_units'] is None:
        missing.append('feed_temperature_units')

    return missing


def assess_feed_state(state):
    """
    Normalize + validate consistency + report missing inputs in one call.

    Returns
    -------
    dict with keys:
        'state'              : the normalized feed state.
        'conflicts'          : list[str] -- contradictions between
                                redundant explicit values.
        'validation_errors'  : list[str] -- invalid values present in the
                                state (not missing-ness).
        'missing_inputs'     : ordered list[str] -- see missing_inputs().
        'ready'               : bool -- True only when there are no
                                conflicts, no validation errors, no missing
                                inputs, and at least MIN_COMPONENTS
                                components are named.
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
