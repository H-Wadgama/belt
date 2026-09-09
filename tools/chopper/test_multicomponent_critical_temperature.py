import math

import multicomponent_critical_temperature as critical


class _FakeChemical:
    def __init__(self, Tc):
        self.Tc = Tc


class _FakeSettings:
    def __init__(self, chemicals_by_name):
        self._chemicals_by_name = chemicals_by_name
        self.chemicals = {}

    def set_thermo(self, names, cache=True):
        self.chemicals = {name: self._chemicals_by_name[name] for name in names}


def test_every_component_tc_is_checked_and_all_violations_are_returned(monkeypatch):
    monkeypatch.setattr(critical.bst, 'settings', _FakeSettings({
        'Hydrogen': _FakeChemical(33.145),
        'Methane': _FakeChemical(190.564),
        'Methanol': _FakeChemical(513.38),
    }))

    result = critical.evaluate_critical_temperatures(
        ['Hydrogen', 'Methane', 'Methanol'], 355.0,
    )

    assert result['valid'] is True
    assert result['ordinary_distillation_feasible'] is False
    assert [item['component'] for item in result['components']] == [
        'Hydrogen', 'Methane', 'Methanol',
    ]
    assert [item['component'] for item in result['violations']] == ['Hydrogen', 'Methane']
    assert all(item['feed_temperature_K'] == 355.0 for item in result['violations'])


def test_equal_to_critical_temperature_does_not_trigger_strict_greater_than_rule(monkeypatch):
    monkeypatch.setattr(critical.bst, 'settings', _FakeSettings({
        'A': _FakeChemical(355.0), 'B': _FakeChemical(400.0),
    }))
    result = critical.evaluate_critical_temperatures(['A', 'B'], 355.0)
    assert result['ordinary_distillation_feasible'] is True
    assert result['violations'] == []


def test_missing_critical_temperature_is_a_structured_failure(monkeypatch):
    monkeypatch.setattr(critical.bst, 'settings', _FakeSettings({
        'A': _FakeChemical(400.0), 'B': _FakeChemical(math.nan),
    }))
    result = critical.evaluate_critical_temperatures(['A', 'B'], 300.0)
    assert result['valid'] is False
    assert result['error'] == 'missing_critical_temperature'
    assert result['ordinary_distillation_feasible'] is None
