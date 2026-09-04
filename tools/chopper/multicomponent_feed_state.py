"""
Deterministic feed-state layer for multicomponent distillation intake.

See tools/multicomponent-distillation-feed-phase-plan.md "1. Stateful feed
specification". Generalizes the binary `feed_state.py` merge/normalize/
completeness pattern to any number of components (the agent itself only
ever uses this for >=3 -- see MIN_COMPONENTS -- but nothing in this module
hard-codes a component count), keyed by component name so the logic is
independent of how many components are involved. Also carries pressure and
the feed's single thermal specification (temperature, enthalpy, or
quality), each tagged with its own unit field, normalized through
`multicomponent_units.py` -- never guessed or defaulted.

Every quantity here is tagged with its provenance -- 'user_explicit' or
'derived' -- same convention as `feed_state.py`, so a later user correction
never leaves a stale derived value behind.

No BioSTEAM calls and no LLM calls -- pure data-structure logic.
"""
import copy

from multicomponent_units import (
    SUPPORTED_ENTHALPY_UNITS,
    SUPPORTED_FLOW_UNITS,
    SUPPORTED_PRESSURE_UNITS,
    SUPPORTED_TEMPERATURE_UNITS,
    normalize_enthalpy_unit,
    normalize_flow_unit,
    normalize_pressure_unit,
    normalize_temperature_unit,
)

MIN_COMPONENTS = 3

_THERMAL_FIELDS = ('feed_temperature', 'feed_enthalpy', 'feed_quality')


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
        'pressure': None,
        'pressure_provenance': None,
        'pressure_units': None,
        'feed_temperature': None,
        'feed_temperature_provenance': None,
        'feed_temperature_units': None,
        'feed_enthalpy': None,
        'feed_enthalpy_provenance': None,
        'feed_enthalpy_units': None,
        'feed_quality': None,
        'feed_quality_provenance': None,
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
                                  given.
        pressure / pressure_units             : float / str.
        feed_temperature / feed_temperature_units : float / str.
        feed_enthalpy / feed_enthalpy_units       : float / str.
        feed_quality                              : float (0-1).

    A component name never implies a component flow, and a single
    component's flow is never treated as the total feed flow -- this
    function only ever records what was explicitly given.

    Supplying a new value for one of feed_temperature/feed_enthalpy/
    feed_quality clears the other two -- the feed has exactly one thermal
    specification at a time.
    """
    state = copy.deepcopy(state) if state else empty_feed_state()
    update = update or {}

    if update.get('component_names') is not None:
        state['component_names'] = list(dict.fromkeys(update['component_names']))
        state['component_flows'] = {}
        state['component_flows_provenance'] = {}
        state['component_flow_units'] = None
        state['total_flow'] = None
        state['total_flow_provenance'] = None
        state['total_flow_units'] = None
        state['composition'] = {}
        state['composition_provenance'] = {}
        state['composition_basis'] = None

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

    if update.get('pressure') is not None:
        state['pressure'] = update['pressure']
        state['pressure_provenance'] = 'user_explicit'

    if update.get('pressure_units') is not None:
        raw = update['pressure_units']
        state['pressure_units'] = normalize_pressure_unit(raw) or raw

    if update.get('feed_temperature') is not None:
        state['feed_temperature'] = update['feed_temperature']
        state['feed_temperature_provenance'] = 'user_explicit'
        state['feed_enthalpy'] = None
        state['feed_enthalpy_provenance'] = None
        state['feed_quality'] = None
        state['feed_quality_provenance'] = None

    if update.get('feed_temperature_units') is not None:
        raw = update['feed_temperature_units']
        state['feed_temperature_units'] = normalize_temperature_unit(raw) or raw

    if update.get('feed_enthalpy') is not None:
        state['feed_enthalpy'] = update['feed_enthalpy']
        state['feed_enthalpy_provenance'] = 'user_explicit'
        state['feed_temperature'] = None
        state['feed_temperature_provenance'] = None
        state['feed_quality'] = None
        state['feed_quality_provenance'] = None

    if update.get('feed_enthalpy_units') is not None:
        raw = update['feed_enthalpy_units']
        state['feed_enthalpy_units'] = normalize_enthalpy_unit(raw) or raw

    if update.get('feed_quality') is not None:
        state['feed_quality'] = update['feed_quality']
        state['feed_quality_provenance'] = 'user_explicit'
        state['feed_temperature'] = None
        state['feed_temperature_provenance'] = None
        state['feed_enthalpy'] = None
        state['feed_enthalpy_provenance'] = None

    return state


def _close(a, b, rel_tol=1e-3, abs_tol=1e-6):
    if a is None or b is None:
        return True
    return abs(a - b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)


def normalize_feed_state(state):
    """
    Deterministically derive total_flow / component_flows / composition
    entries that are mathematically FORCED by what's already
    user_explicit. Never invents a value beyond what the math requires.

    Also cross-checks redundant explicit information for contradictions
    (e.g. component flows that don't sum to an explicitly-given total
    flow, or a composition that doesn't match what the component flows
    imply, or N composition fractions that don't sum to 1).

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
    conflicts = []

    def known_flow_names():
        return [n for n in names if n in flows]

    def all_flows_known():
        # len(names) >= 2 guards against a degenerate single-named-component
        # state: one component's flow must never read as "all flows known".
        return len(names) >= 2 and len(known_flow_names()) == len(names)

    # --- total_flow vs. component_flows ---
    if state['total_flow_provenance'] == 'user_explicit':
        if all_flows_known():
            implied_total = sum(flows[n] for n in names)
            if not _close(implied_total, state['total_flow']):
                conflicts.append(
                    f"Component flows sum to {implied_total:g}, but total "
                    f"flow was specified as {state['total_flow']:g}."
                )
    elif all_flows_known() and known_flow_names():
        state['total_flow'] = sum(flows[n] for n in names)
        state['total_flow_provenance'] = 'derived'

    # --- total_flow known + all-but-one component flow known -> derive it ---
    if state['total_flow'] is not None and names:
        missing = [n for n in names if n not in flows]
        if len(missing) == 1 and len(known_flow_names()) == len(names) - 1:
            derived = state['total_flow'] - sum(flows[n] for n in known_flow_names())
            flows[missing[0]] = derived
            flows_prov[missing[0]] = 'derived'

    # --- N-1 of N composition fractions known -> derive the last one.
    # Generalizes the binary "one fraction implies the other" case to any
    # component count. ---
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

    # --- total_flow known + full composition known -> derive component_flows
    # (flag disagreement against any that were also given explicitly). ---
    known_comp_names = [n for n in names if n in comp]
    if state['total_flow'] is not None and names and len(known_comp_names) == len(names):
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

    # --- Reverse: total_flow + all component_flows known -> derive
    # composition (flag disagreement with any explicit fraction). ---
    total = state['total_flow']
    known_comp_names = [n for n in names if n in comp]
    if total and all_flows_known() and len(known_comp_names) < len(names):
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
    """True once every named component has a known flow (explicit or derived)."""
    names = state['component_names']
    if not names:
        return False
    return all(n in state['component_flows'] for n in names)


def _thermal_given_fields(state):
    return [f for f in _THERMAL_FIELDS if state.get(f) is not None]


def validate_feed_state(state):
    """
    Validation errors against an already-`normalize_feed_state`-d state --
    genuinely invalid combinations of what IS present, as opposed to
    `missing_inputs` (below), which reports what is not yet present at all.

    Returns list[str] of human-readable error messages (empty if none).
    """
    errors = []
    names = state['component_names']

    if names and len(set(names)) != len(names):
        errors.append('Duplicate component names given.')

    for n, v in state['component_flows'].items():
        if v is not None and v <= 0:
            errors.append(f'{n} flow must be positive; got {v:g}.')

    if state['total_flow'] is not None and state['total_flow'] <= 0:
        errors.append(f"total_flow must be positive; got {state['total_flow']:g}.")

    for n, v in state['composition'].items():
        if v is not None and not (0.0 <= v <= 1.0):
            errors.append(f'{n} composition fraction must be between 0 and 1; got {v:g}.')

    if state['composition'] and state['composition_basis'] is not None \
            and state['composition_basis'] not in ('mole', 'mass'):
        errors.append(
            f"Composition basis must be \"mole\" or \"mass\"; got "
            f"{state['composition_basis']!r}."
        )

    given_thermal = _thermal_given_fields(state)
    if len(given_thermal) > 1:
        errors.append(
            f'Exactly one feed thermal condition may be given; got '
            f'{len(given_thermal)}: {given_thermal}.'
        )

    if state['feed_quality'] is not None and not (0.0 <= state['feed_quality'] <= 1.0):
        errors.append(f"feed_quality must be between 0 and 1; got {state['feed_quality']:g}.")

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
    _check_unit(state['feed_enthalpy_units'], SUPPORTED_ENTHALPY_UNITS, 'enthalpy unit')

    return errors


def missing_inputs(state):
    """
    Ordered list of genuinely missing input identifiers, following:
    1. component identities, 2. feed quantities/composition,
    3. composition basis (when applicable), 4. flow units, 5. pressure
    (value then units), 6. thermal condition (value then units).

    Only the FIRST entry should ever be surfaced to the user in one turn.
    """
    missing = []
    names = state['component_names']

    if len(set(names)) < MIN_COMPONENTS:
        missing.append('component_names')
        return missing

    if not feed_quantity_complete(state):
        missing.append('feed_quantity')

    composition_started = any(
        state['composition_provenance'].get(n) == 'user_explicit' for n in names
    )
    if composition_started and state['composition_basis'] is None:
        missing.append('composition_basis')

    flow_units = state['component_flow_units'] or state['total_flow_units']
    if feed_quantity_complete(state) and flow_units is None:
        missing.append('flow_units')

    if state['pressure'] is None:
        missing.append('pressure_value')
    elif state['pressure_units'] is None:
        missing.append('pressure_units')

    given_thermal = _thermal_given_fields(state)
    if len(given_thermal) == 0:
        missing.append('feed_thermal_condition')
    elif len(given_thermal) == 1:
        field = given_thermal[0]
        if field == 'feed_temperature' and state['feed_temperature_units'] is None:
            missing.append('feed_temperature_units')
        elif field == 'feed_enthalpy' and state['feed_enthalpy_units'] is None:
            missing.append('feed_enthalpy_units')

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
