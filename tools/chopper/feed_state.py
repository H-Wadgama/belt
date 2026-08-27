"""
Deterministic feed-state layer for binary distillation.

Implements `tools/binary-distillation-flow-rate-issue.md` in full: a
state representation that keeps component IDENTITY (`component_names`)
strictly separate from component QUANTITY (`component_flows`,
`total_flow`, `composition`), a non-destructive merge function
(`apply_user_update`), and a deterministic normalization function
(`normalize_feed_state`) that derives a quantity only when it is
mathematically forced by what has already been explicitly supplied --
never by assumption.

No BioSTEAM calls and no LLM calls -- pure data-structure logic, same
spirit as `problem_spec.py`. `binary_distillation_workflow.py` is the
only caller today; it inserts this layer BEFORE the existing binary-scope
gate and Wankat Case A-D workflow (see that module and
tools/binary-distillation-flow-rate-issue.md section 18 for the full
pipeline).

Every quantity this module derives is tagged with its provenance --
`'user_explicit'` (came directly from the user) or `'derived'`
(mathematically forced by user-explicit values) -- so callers can tell
the two apart (issue doc section 10). There is deliberately no
`'assumed_by_llm'` state: a value is either known (explicit or derived)
or left `None`/absent.
"""
import copy

# Quantity fields tracked on a feed state, together with the provenance
# key that records where each entry came from.
_SCALAR_QUANTITY_FIELDS = ('total_flow',)
_DICT_QUANTITY_FIELDS = ('component_flows', 'composition')


def empty_feed_state():
    """A feed state with no identity and no quantity information at all."""
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
    }


def _add_names(state, names):
    for name in names:
        if name not in state['component_names']:
            state['component_names'].append(name)


def apply_user_update(state, update):
    """
    Non-destructive merge of a partial update into `state` -- issue doc
    sections 2, 5, 12. Never mutates the input; returns a new state dict.

    Recognized keys in `update` (all optional; anything else is ignored,
    so a full accumulated spec dict containing unrelated fields -- e.g.
    `pressure_Pa`, `xD` -- can be passed straight through):

        component_names      : list[str] -- REPLACES the feed's identity
                                entirely (issue doc section 12: "replacing
                                the separation problem"). Because a
                                changed identity invalidates any
                                previously known/derived quantity, this
                                also clears component_flows, total_flow,
                                and composition (and their provenance).
        add_component_names   : list[str] -- APPENDS to the existing
                                identity without touching any known
                                quantity (issue doc section 12: "adding
                                information to the existing separation",
                                e.g. answering "please specify the second
                                component").
        component_flows       : dict[str, float] -- merged into the
                                existing component_flows (per-key
                                overwrite), each marked 'user_explicit'.
                                Any name not yet in component_names is
                                added to it -- stating a component's flow
                                implies that component is part of the feed.
        component_flow_units  : str -- overwrites if given.
        total_flow             : float -- overwrites if given, marked
                                'user_explicit'.
        total_flow_units       : str -- overwrites if given.
        composition             : dict[str, float] -- merged like
                                component_flows, each marked
                                'user_explicit'. Names are likewise added
                                to component_names.
        composition_basis       : str -- overwrites if given.

    A component name never implies a component flow, and a single
    component's flow is never treated as the total feed flow -- this
    function only ever records what was explicitly given.
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
        state['component_flow_units'] = update['component_flow_units']

    if update.get('total_flow') is not None:
        state['total_flow'] = update['total_flow']
        state['total_flow_provenance'] = 'user_explicit'

    if update.get('total_flow_units') is not None:
        state['total_flow_units'] = update['total_flow_units']

    if update.get('composition'):
        for name, value in update['composition'].items():
            state['composition'][name] = value
            state['composition_provenance'][name] = 'user_explicit'
        _add_names(state, update['composition'].keys())

    if update.get('composition_basis') is not None:
        state['composition_basis'] = update['composition_basis']

    return state


def _close(a, b, rel_tol=1e-3, abs_tol=1e-6):
    if a is None or b is None:
        return True
    return abs(a - b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)


def normalize_feed_state(state):
    """
    Deterministically derive total_flow / component_flows / composition
    entries that are mathematically FORCED by what's already
    user_explicit -- issue doc section 7, Situations 1-6. Never invents a
    value beyond what the math requires.

    Also cross-checks redundant explicit information for contradictions
    (issue doc section 11) -- e.g. component flows that don't sum to an
    explicitly-given total flow, or a composition that doesn't match what
    the component flows imply.

    Returns
    -------
    (new_state, conflicts) : (dict, list[str])
        `new_state` is `state` with every derivable field filled in
        (never mutates the input). `conflicts` is a list of human-readable
        contradiction descriptions; when non-empty, the caller should
        treat the feed as `inconsistent_input` rather than proceeding --
        derived fields that would depend on the conflicting values may be
        incomplete or reflect only one side of the contradiction.
    """
    state = copy.deepcopy(state)
    names = state['component_names']
    flows = state['component_flows']
    flows_prov = state['component_flows_provenance']
    comp = state['composition']
    comp_prov = state['composition_provenance']
    conflicts = []

    def known_flow_names():
        return [n for n in names if n in flows]

    def all_flows_known():
        # len(names) >= 2 guards against the degenerate single-named-component
        # case (issue doc Test 6): one component's flow must never be read as
        # "all flows known" -> total flow, before a second component even
        # exists.
        return len(names) >= 2 and len(known_flow_names()) == len(names)

    # --- total_flow vs. component_flows (Situations 3 and 11) ---
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

    # --- Situation 5: total_flow known + all-but-one component flow known
    # -> derive the missing one. ---
    if state['total_flow'] is not None and names:
        missing = [n for n in names if n not in flows]
        if len(missing) == 1 and len(known_flow_names()) == len(names) - 1:
            derived = state['total_flow'] - sum(flows[n] for n in known_flow_names())
            flows[missing[0]] = derived
            flows_prov[missing[0]] = 'derived'

    # --- Situation 4: total_flow known + full composition known -> derive
    # component_flows (and flag a conflict against any that were also
    # given explicitly and disagree). ---
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

    # --- Reverse of Situations 3/4: total_flow + all component_flows known
    # -> derive composition (and flag disagreement with any explicit
    # fraction already given). ---
    total = state['total_flow']
    known_comp_names = [n for n in names if n in comp]
    if total and all_flows_known() and len(known_comp_names) < len(names):
        for n in names:
            implied_frac = flows[n] / total
            if n in comp:
                if not _close(comp[n], implied_frac):
                    conflicts.append(
                        f"{n} mole fraction was specified as {comp[n]:g}, but "
                        f"component flows imply {implied_frac:g}."
                    )
            else:
                comp[n] = implied_frac
                comp_prov[n] = 'derived'

    # --- Situation 6: exactly 2 components, one composition fraction known,
    # no total flow -> derive the complementary fraction. ---
    total = state['total_flow']
    if len(names) == 2 and total is None:
        known_comp_names = [n for n in names if n in comp]
        if len(known_comp_names) == 1:
            known = known_comp_names[0]
            other = [n for n in names if n != known][0]
            complement = 1.0 - comp[known]
            if other in comp:
                if not _close(comp[other], complement):
                    conflicts.append(
                        f"{known} and {other} mole fractions were both "
                        f"specified but do not sum to 1 "
                        f"({comp[known]:g} + {comp[other]:g})."
                    )
            else:
                comp[other] = complement
                comp_prov[other] = 'derived'

    state['component_flows'] = flows
    state['component_flows_provenance'] = flows_prov
    state['composition'] = comp
    state['composition_provenance'] = comp_prov
    return state, conflicts


def feed_completeness(state):
    """
    (feed_flow_complete, feed_composition_complete) -- issue doc section 8.
    Call this on an already-`normalize_feed_state`-d state.
    """
    names = state['component_names']
    flow_complete = state['total_flow'] is not None
    composition_complete = bool(names) and all(n in state['composition'] for n in names)
    return flow_complete, composition_complete


def assess_feed_state(state):
    """
    Normalize + validate consistency + report completeness in one call.

    Returns
    -------
    dict with keys:
        'state'                      : the normalized feed state.
        'conflicts'                  : list[str] -- see normalize_feed_state.
        'feed_flow_complete'         : bool.
        'feed_composition_complete'  : bool.
        'components'                 : dict[str, float] -- component ->
                                        flow, populated ONLY when both
                                        completeness flags are True (empty
                                        dict otherwise) -- the canonical
                                        shape the Wankat Case A-D layer
                                        (`problem_spec.py`) expects.
    """
    normalized, conflicts = normalize_feed_state(state)
    flow_complete, composition_complete = feed_completeness(normalized)
    components = {}
    if flow_complete and composition_complete:
        components = {n: normalized['component_flows'][n] for n in normalized['component_names']}
    return {
        'state': normalized,
        'conflicts': conflicts,
        'feed_flow_complete': flow_complete,
        'feed_composition_complete': composition_complete,
        'components': components,
    }


if __name__ == '__main__':
    import json

    def demo(title, update):
        state = apply_user_update(empty_feed_state(), update)
        result = assess_feed_state(state)
        print(f'--- {title} ---')
        print(json.dumps(result, indent=2, default=str))
        print()

    demo('Component names only', {'component_names': ['Methanol', 'Water']})
    demo('One component flow', {
        'component_names': ['Methanol', 'Water'],
        'component_flows': {'Methanol': 50},
    })
    demo('Both component flows', {
        'component_names': ['Methanol', 'Water'],
        'component_flows': {'Methanol': 50, 'Water': 30},
    })
    demo('Total flow + full composition', {
        'component_names': ['Methanol', 'Water'],
        'total_flow': 100, 'composition': {'Methanol': 0.4, 'Water': 0.6},
    })
    demo('Total flow + one component flow', {
        'component_names': ['Methanol', 'Water'],
        'total_flow': 100, 'component_flows': {'Methanol': 40},
    })
    demo('One mole fraction only', {
        'component_names': ['Methanol', 'Water'],
        'composition': {'Methanol': 0.4},
    })
    demo('Inconsistent: flows disagree with explicit total', {
        'component_names': ['Methanol', 'Water'],
        'component_flows': {'Methanol': 50, 'Water': 50}, 'total_flow': 120,
    })
