"""
tools/binary-distillation-issues-9-1-2026-fifth.md Parts 9-10 --
ProblemSnapshot construction and the generic `read_problem_value` reader,
plus the two scalability acceptance fixtures: multicomponent keyed access
and subject-aware (multi-unit) access. Neither fixture claims live support
for those engineering capabilities -- both build an artificial snapshot by
hand to prove the ACCESS LAYER is generic.

Run with:
    pytest tools/chopper/test_problem_snapshot.py -v
"""
from problem_field_registry import PROBLEM_FIELD_REGISTRY
from problem_snapshot import build_problem_snapshot, read_problem_value


def _assessment(feed_overrides=None, **top_level):
    feed = {
        'component_names': [], 'component_flows': {}, 'component_flows_provenance': {},
        'component_flow_units': None, 'total_flow': None, 'total_flow_provenance': None,
        'total_flow_units': None, 'composition': {}, 'composition_provenance': {},
        'composition_basis': None,
    }
    feed.update(feed_overrides or {})
    return {'feed': feed, **top_level}


def test_build_problem_snapshot_shape():
    snapshot = build_problem_snapshot({'pressure_Pa': 101325, 'feed': {}}, assessment=_assessment())
    assert snapshot['schema_id'] == 'binary_distillation_problem.v1'
    assert snapshot['inputs'] == {'pressure_Pa': 101325}  # 'feed' excluded from inputs
    assert snapshot['units'] == {}


def test_read_explicit_scalar_found():
    snapshot = build_problem_snapshot({'pressure_Pa': 101325}, assessment=_assessment())
    result = read_problem_value(snapshot, 'pressure_Pa')
    assert result == {'valid': True, 'found': True, 'field': 'pressure_Pa',
                       'value': 101325, 'units': 'Pa', 'provenance': 'user_explicit'}


def test_read_explicit_scalar_missing():
    snapshot = build_problem_snapshot({}, assessment=_assessment())
    result = read_problem_value(snapshot, 'xD')
    assert result == {'valid': True, 'found': False, 'field': 'xD', 'value': None, 'units': None, 'provenance': None}


def test_read_derived_total_flow():
    """Failure 2's fix: total_flow is read from assessment['feed'], and its
    'derived' provenance survives -- never relabeled 'user_explicit'."""
    assessment = _assessment(feed_overrides={
        'component_flows': {'Ethanol': 50, 'Water': 50},
        'component_flow_units': 'kmol/hr',
        'total_flow': 100, 'total_flow_provenance': 'derived',
    })
    snapshot = build_problem_snapshot({}, assessment=assessment)
    result = read_problem_value(snapshot, 'total_flow')
    assert result == {'valid': True, 'found': True, 'field': 'total_flow',
                       'value': 100, 'units': 'kmol/hr', 'provenance': 'derived'}


def test_read_keyed_component_flow():
    assessment = _assessment(feed_overrides={
        'component_names': ['Ethanol', 'Water'],
        'component_flows': {'Ethanol': 50}, 'component_flows_provenance': {'Ethanol': 'user_explicit'},
        'component_flow_units': 'kmol/hr',
    })
    snapshot = build_problem_snapshot({}, assessment=assessment)
    result = read_problem_value(snapshot, 'component_flows', entity='ethanol')  # case-insensitive
    assert result == {'valid': True, 'found': True, 'field': 'component_flows', 'entity': 'Ethanol',
                       'value': 50, 'units': 'kmol/hr', 'provenance': 'user_explicit'}


def test_read_keyed_component_flow_missing_is_not_an_error():
    assessment = _assessment(feed_overrides={'component_names': ['Ethanol', 'Water']})
    snapshot = build_problem_snapshot({}, assessment=assessment)
    result = read_problem_value(snapshot, 'component_flows', entity='Water')
    assert result['valid'] is True
    assert result['found'] is False


def test_read_keyed_field_without_entity_is_unknown_problem_entity():
    snapshot = build_problem_snapshot({}, assessment=_assessment())
    result = read_problem_value(snapshot, 'component_flows')
    assert result == {'valid': False, 'error': 'unknown_problem_entity', 'field': 'component_flows'}


def test_read_unknown_field_reports_near_match():
    snapshot = build_problem_snapshot({}, assessment=_assessment())
    result = read_problem_value(snapshot, 'zB')
    assert result['valid'] is False
    assert result['error'] == 'unknown_problem_field'
    assert result['field'] == 'zB'
    assert 'xB' in result['near_matches']


def test_read_unknown_subject_kind_is_rejected():
    snapshot = build_problem_snapshot({}, assessment=_assessment())
    result = read_problem_value(snapshot, 'reflux_condition', subject={'kind': 'planet', 'id': 'mars'})
    assert result == {'valid': False, 'error': 'unknown_problem_subject', 'field': 'reflux_condition',
                       'subject': {'kind': 'planet', 'id': 'mars'}}


def test_read_never_mutates_snapshot():
    assessment = _assessment(feed_overrides={'component_names': ['Ethanol', 'Water']})
    snapshot = build_problem_snapshot({'pressure_Pa': 101325}, assessment=assessment)
    before = repr(snapshot)
    read_problem_value(snapshot, 'pressure_Pa')
    read_problem_value(snapshot, 'component_flows', entity='Ethanol')
    read_problem_value(snapshot, 'zB')
    assert repr(snapshot) == before


# ---------------------------------------------------------------------------
# Scalability acceptance test 1 -- multicomponent keyed access. The real
# binary workflow still rejects a 3+ component feed for CALCULATION, but the
# generic reader itself must not assume exactly two components.
# ---------------------------------------------------------------------------

def test_multicomponent_keyed_access_no_component_specific_resolver():
    component_flows = {'Water': 50, 'Ethanol': 50, 'Methanol': 20, 'Acetone': 10}
    assessment = _assessment(feed_overrides={
        'component_names': list(component_flows),
        'component_flows': component_flows,
        'component_flows_provenance': {k: 'user_explicit' for k in component_flows},
        'component_flow_units': 'kmol/hr',
    })
    snapshot = build_problem_snapshot({}, assessment=assessment)

    result = read_problem_value(snapshot, 'component_flows', entity='Methanol')
    assert result['found'] is True
    assert result['value'] == 20

    result = read_problem_value(snapshot, 'component_flows', entity='Acetone')
    assert result['value'] == 10


# ---------------------------------------------------------------------------
# Scalability acceptance test 2 -- subject-aware access against an
# artificial two-unit fixture (D1/D2). This does NOT claim live
# multicolumn support (the real workflow's `snapshot['units']` is always
# empty) -- it proves the reader dispatches on `subject` generically when
# such state exists, per pressure_Pa's own `unit_accessor`.
# ---------------------------------------------------------------------------

def test_subject_aware_access_selects_the_right_unit_operation():
    snapshot = build_problem_snapshot(
        {}, assessment=_assessment(),
        units={'D1': {'pressure_Pa': 101325}, 'D2': {'pressure_Pa': 150000}},
    )

    result_d1 = read_problem_value(snapshot, 'pressure_Pa', subject={'kind': 'unit_operation', 'id': 'D1'})
    result_d2 = read_problem_value(snapshot, 'pressure_Pa', subject={'kind': 'unit_operation', 'id': 'D2'})

    assert result_d1['value'] == 101325
    assert result_d2['value'] == 150000


def test_subject_aware_access_unknown_unit_id_is_bounded():
    snapshot = build_problem_snapshot({}, assessment=_assessment(), units={'D1': {'pressure_Pa': 101325}})
    result = read_problem_value(snapshot, 'pressure_Pa', subject={'kind': 'unit_operation', 'id': 'D9'})
    assert result['valid'] is False
    assert result['error'] == 'unknown_problem_subject'


def test_real_workflow_never_populates_units_map():
    """The real single-column workflow's snapshots never carry a 'units'
    entry -- this is what keeps the subject-aware test above from claiming
    live multicolumn support."""
    import binary_distillation_workflow_agent as agent
    agent.reset_workflow_session()
    snapshot = build_problem_snapshot(agent._workflow_state, assessment=agent.get_binary_distillation_problem())
    assert snapshot['units'] == {}
    agent.reset_workflow_session()
