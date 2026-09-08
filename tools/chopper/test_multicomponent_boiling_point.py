"""
Tests for `multicomponent_boiling_point.py` and its integration into
`multicomponent_feed_tool.advance_feed_state`. See
tools/multicomponent-distillation-boiling-point-order-plan.md "Required
tests".

Run with:
    pytest tools/chopper/test_multicomponent_boiling_point.py -v
"""
import math

import pytest

import multicomponent_boiling_point as bp
import multicomponent_feed_tool as tool
from multicomponent_feed_state import empty_feed_state


class _FakeChemical:
    def __init__(self, Tb):
        self.Tb = Tb


class _FakeSettings:
    """Stands in for `bst.settings` -- `.set_thermo(names)` selects a
    subset of a fixed name->Chemical mapping, `.chemicals` exposes it by
    name, matching the two attributes `multicomponent_boiling_point.py`
    actually uses."""

    def __init__(self, chemicals_by_name):
        self._chemicals_by_name = chemicals_by_name
        self.chemicals = {}

    def set_thermo(self, names, cache=True):
        self.chemicals = {n: self._chemicals_by_name[n] for n in names}


# --- Real BioSTEAM chemicals: order, membership, spelling -------------------

def test_three_real_components_sorted_lowest_to_highest():
    result = bp.calculate_multicomponent_boiling_point_order(['Water', 'Ethanol', 'Methanol'])
    assert result['valid'] is True
    assert result['status'] == 'complete'
    # Known normal boiling points: Methanol ~337.8 K < Ethanol ~351.5 K < Water ~373.15 K.
    assert result['order_low_to_high'] == ['Methanol', 'Ethanol', 'Water']


def test_every_nonzero_flow_component_appears_exactly_once():
    names = ['Water', 'Ethanol', 'Methanol', 'Glycerol', 'Acetone']
    result = bp.calculate_multicomponent_boiling_point_order(names)
    assert result['valid'] is True
    assert sorted(result['order_low_to_high']) == sorted(names)
    assert len(result['order_low_to_high']) == len(names)


def test_established_component_spelling_is_preserved():
    names = ['methanol', 'Ethanol', 'WATER']
    result = bp.calculate_multicomponent_boiling_point_order(names)
    assert result['valid'] is True
    assert set(result['order_low_to_high']) == set(names)
    for entry in result['components']:
        assert entry['component'] in names


def test_result_is_deterministic_across_repeated_calls():
    names = ['Water', 'Ethanol', 'Methanol']
    first = bp.calculate_multicomponent_boiling_point_order(names)
    second = bp.calculate_multicomponent_boiling_point_order(names)
    assert first == second


# --- Fewer than three components -> structured failure ---------------------

def test_fewer_than_three_components_is_a_structured_failure():
    result = bp.calculate_multicomponent_boiling_point_order(['Water', 'Ethanol'])
    assert result['valid'] is False
    assert result['status'] == 'failed'
    assert result['error'] == 'unsupported_component_count'
    assert result['order_low_to_high'] == []


# --- Ties: exactly equal normal boiling points --------------------------

def test_equal_boiling_points_are_flagged_as_a_tie_and_keep_committed_order(monkeypatch):
    fake_settings = _FakeSettings({
        'A': _FakeChemical(300.0),
        'B': _FakeChemical(250.0),
        'C': _FakeChemical(300.0),
    })
    monkeypatch.setattr(bp.bst, 'settings', fake_settings)

    result = bp.calculate_multicomponent_boiling_point_order(['A', 'B', 'C'])

    assert result['valid'] is True
    # B (250K) first, then A and C (tied at 300K) preserving committed order.
    assert result['order_low_to_high'] == ['B', 'A', 'C']
    assert result['ties'] == [{'normal_boiling_point_K': 300.0, 'components': ['A', 'C']}]


def test_no_ties_reported_when_all_boiling_points_differ(monkeypatch):
    fake_settings = _FakeSettings({
        'A': _FakeChemical(300.0),
        'B': _FakeChemical(250.0),
        'C': _FakeChemical(400.0),
    })
    monkeypatch.setattr(bp.bst, 'settings', fake_settings)

    result = bp.calculate_multicomponent_boiling_point_order(['A', 'B', 'C'])
    assert result['ties'] == []


# --- Missing / nonfinite / invalid property -> structured failure ----------

@pytest.mark.parametrize('bad_Tb', [None, float('nan'), float('inf'), -300.0, 0.0, 'not-a-number'])
def test_missing_or_invalid_boiling_point_is_a_structured_failure(monkeypatch, bad_Tb):
    fake_settings = _FakeSettings({
        'A': _FakeChemical(300.0),
        'B': _FakeChemical(bad_Tb),
        'C': _FakeChemical(400.0),
    })
    monkeypatch.setattr(bp.bst, 'settings', fake_settings)

    result = bp.calculate_multicomponent_boiling_point_order(['A', 'B', 'C'])

    assert result['valid'] is False
    assert result['status'] == 'failed'
    assert result['error'] == 'missing_boiling_point'
    assert result['order_low_to_high'] == []
    assert result['ties'] == []
    failed_names = {f['component'] for f in result['failures']}
    assert failed_names == {'B'}
    # Successfully-resolved components are still reported for diagnostics.
    resolved_names = {c['component'] for c in result['components']}
    assert resolved_names == {'A', 'C'}


def test_thermo_build_failure_is_a_structured_failure(monkeypatch):
    class _BrokenSettings:
        def set_thermo(self, names, cache=True):
            raise ValueError('unrecognized chemical')

    monkeypatch.setattr(bp.bst, 'settings', _BrokenSettings())

    result = bp.calculate_multicomponent_boiling_point_order(['Unobtainium', 'Ethanol', 'Water'])
    assert result['valid'] is False
    assert result['error'] == 'thermo_build_failed'


# --- Integration: failure does not corrupt committed feed state ------------

def test_boiling_point_failure_does_not_corrupt_already_committed_feed_state(monkeypatch):
    def _always_fails(component_names):
        return {
            'check': 'multicomponent_boiling_point_order', 'valid': False, 'status': 'failed',
            'reference_pressure_Pa': bp.REFERENCE_PRESSURE_PA, 'components': [], 'failures': [],
            'order_low_to_high': [], 'ties': [], 'error': 'missing_boiling_point',
            'message': 'forced failure for test',
        }

    monkeypatch.setattr(tool, 'calculate_multicomponent_boiling_point_order', _always_fails)

    state = empty_feed_state()
    r = tool.advance_feed_state(state, {'component_names': ['Water', 'Ethanol', 'Methanol']})
    state = r['feed_state']
    r = tool.advance_feed_state(state, {
        'component_flows': {'Water': 30, 'Ethanol': 40, 'Methanol': 30},
        'component_flow_units': 'kmol/hr',
    })
    state = r['feed_state']
    r = tool.advance_feed_state(state, {'pressure': 1.0, 'pressure_units': 'atm'})
    state = r['feed_state']
    r = tool.advance_feed_state(state, {'feed_temperature': 350, 'feed_temperature_units': 'K'})

    assert r['complete'] is False
    assert r['valid'] is False
    assert r['error'] == 'missing_boiling_point'
    # The already-committed facts from this and earlier turns are untouched.
    committed = r['feed_state']
    assert committed['component_names'] == ['Water', 'Ethanol', 'Methanol']
    assert set(committed['component_flows']) == {'Water', 'Ethanol', 'Methanol'}
    from multicomponent_feed_state import record_value
    assert record_value(committed['feed_temperature']) == 350
