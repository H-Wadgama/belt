"""
Acceptance tests for tools/binary-distillation-flow-rate-issue.md section 17,
exercising `feed_state.py` directly (the deterministic merge/normalize layer)
plus the agent-level `component_names` (replace) vs `add_component_names`
(append) semantics from section 12.

Run with:
    pytest tools/chopper/test_feed_state.py -v
"""
from feed_state import apply_user_update, assess_feed_state, empty_feed_state, normalize_feed_state


def _assess(*updates):
    state = empty_feed_state()
    for update in updates:
        state = apply_user_update(state, update)
    return assess_feed_state(state)


# --- Test 1 -- component names only ---------------------------------------

def test_1_component_names_only():
    result = _assess({'component_names': ['Methanol', 'Water']})
    assert result['state']['component_names'] == ['Methanol', 'Water']
    assert result['state']['component_flows'] == {}
    assert result['state']['total_flow'] is None
    assert result['state']['composition'] == {}
    assert result['feed_flow_complete'] is False
    assert result['feed_composition_complete'] is False


# --- Test 2 -- one component flow ------------------------------------------

def test_2_one_component_flow():
    result = _assess(
        {'component_names': ['Methanol', 'Water']},
        {'component_flows': {'Methanol': 50}},
    )
    assert result['state']['component_flows'] == {'Methanol': 50}
    assert result['state']['total_flow'] is None
    assert result['state']['composition'] == {}
    assert result['feed_flow_complete'] is False


# --- Test 3 -- both component flows -----------------------------------------

def test_3_both_component_flows_derive_total_and_composition():
    result = _assess({
        'component_names': ['Methanol', 'Water'],
        'component_flows': {'Methanol': 50, 'Water': 30},
    })
    assert result['state']['total_flow'] == 80
    assert result['state']['composition'] == {'Methanol': 0.625, 'Water': 0.375}
    assert result['feed_flow_complete'] is True
    assert result['feed_composition_complete'] is True


# --- Test 4 -- total flow plus one component flow ---------------------------

def test_4_total_flow_plus_one_component_flow():
    result = _assess({
        'component_names': ['Methanol', 'Water'],
        'total_flow': 100, 'component_flows': {'Methanol': 40},
    })
    assert result['state']['component_flows']['Water'] == 60
    assert result['state']['composition'] == {'Methanol': 0.40, 'Water': 0.60}


# --- Test 5 -- one binary mole fraction -------------------------------------

def test_5_one_mole_fraction():
    result = _assess({
        'component_names': ['Methanol', 'Water'],
        'composition': {'Methanol': 0.40},
    })
    assert result['state']['composition']['Methanol'] == 0.40
    assert result['state']['composition']['Water'] == 0.60
    assert result['feed_composition_complete'] is True
    assert result['state']['total_flow'] is None
    assert result['feed_flow_complete'] is False


# --- Test 6 -- component flow without an established binary -----------------

def test_6_component_flow_without_established_binary():
    result = _assess({'component_flows': {'Methanol': 50}})
    assert result['state']['component_names'] == ['Methanol']
    assert result['state']['total_flow'] is None
    assert result['state']['composition'] == {}


# --- Test 7 -- component names never create flows ---------------------------

def test_7_component_names_never_create_flows():
    result = _assess({'component_names': ['Methanol', 'Water']})
    assert result['state']['component_flows'] == {}


# --- Test 8 -- component flow never automatically becomes total flow --------

def test_8_component_flow_never_becomes_total_flow():
    result = _assess({
        'component_names': ['Methanol', 'Water'],
        'component_flows': {'Methanol': 50},
    })
    assert result['state']['total_flow'] is None


# --- Test 9 -- provenance ----------------------------------------------------

def test_9_provenance():
    result = _assess({
        'component_names': ['Methanol', 'Water'],
        'component_flows': {'Methanol': 50, 'Water': 30},
    })
    assert result['state']['component_flows_provenance']['Methanol'] == 'user_explicit'
    assert result['state']['component_flows_provenance']['Water'] == 'user_explicit'
    assert result['state']['total_flow_provenance'] == 'derived'
    assert result['state']['composition_provenance']['Methanol'] == 'derived'
    assert result['state']['composition_provenance']['Water'] == 'derived'


# --- Test 10 -- conflicting total flow ---------------------------------------

def test_10_conflicting_total_flow():
    result = _assess({
        'component_names': ['Methanol', 'Water'],
        'component_flows': {'Methanol': 50, 'Water': 50},
        'total_flow': 120,
    })
    assert result['conflicts']
    assert any('100' in c and '120' in c for c in result['conflicts'])


# --- Test 11 -- conflicting composition --------------------------------------

def test_11_conflicting_composition():
    result = _assess({
        'component_names': ['Methanol', 'Water'],
        'component_flows': {'Methanol': 50, 'Water': 50},
        'composition': {'Methanol': 0.70},
    })
    assert result['conflicts']
    assert any('0.7' in c for c in result['conflicts'])


# --- Test 12 -- replacement of an invalid multicomponent problem ------------

def test_12_replacement_clears_stale_flows():
    state = apply_user_update(empty_feed_state(), {
        'component_names': ['Water', 'Methanol', 'Butanol'],
    })
    state = apply_user_update(state, {'component_flows': {'Water': 80}})
    # Now restate the separation as just "Water" -- a REPLACEMENT, not a
    # narrowing -- so the stale Water=80 flow must not survive.
    state = apply_user_update(state, {'component_names': ['Water']})
    assert state['component_names'] == ['Water']
    assert state['component_flows'] == {}
    assert state['total_flow'] is None
    assert state['composition'] == {}


# --- Non-destructive merge (issue doc section 5) -----------------------------

def test_merge_does_not_erase_unrelated_fields():
    state = apply_user_update(empty_feed_state(), {
        'component_names': ['Methanol', 'Water'],
        'component_flows': {'Methanol': 40},
    })
    state = apply_user_update(state, {'component_flows': {'Water': 60}})
    assert state['component_flows'] == {'Methanol': 40, 'Water': 60}
    assert state['component_names'] == ['Methanol', 'Water']


# --- add_component_names appends without clearing (issue doc section 12) ----

def test_add_component_names_appends_without_clearing():
    state = apply_user_update(empty_feed_state(), {
        'component_names': ['Water'],
        'component_flows': {'Water': 80},
    })
    state = apply_user_update(state, {'add_component_names': ['Methanol']})
    assert state['component_names'] == ['Water', 'Methanol']
    assert state['component_flows'] == {'Water': 80}


def test_component_names_replace_clears_add_component_names_target_too():
    """A full `component_names` restatement always wins over any earlier partial state, matching issue doc section 12's water/methanol/butanol -> water -> methanol walk-through."""
    state = apply_user_update(empty_feed_state(), {
        'component_names': ['Water', 'Methanol', 'Butanol'],
    })
    state = apply_user_update(state, {'component_names': ['Water']})
    state = apply_user_update(state, {'add_component_names': ['Methanol']})
    assert state['component_names'] == ['Water', 'Methanol']
    assert state['component_flows'] == {}
    assert state['total_flow'] is None
    assert state['composition'] == {}


def test_normalize_feed_state_is_pure():
    """normalize_feed_state must not mutate its input -- callers may re-normalize the same accumulated state repeatedly (e.g. once per tool call)."""
    state = apply_user_update(empty_feed_state(), {
        'component_names': ['Methanol', 'Water'],
        'component_flows': {'Methanol': 50, 'Water': 30},
    })
    before = {'total_flow': state['total_flow'], 'composition': dict(state['composition'])}
    normalize_feed_state(state)
    assert state['total_flow'] == before['total_flow']
    assert state['composition'] == before['composition']
