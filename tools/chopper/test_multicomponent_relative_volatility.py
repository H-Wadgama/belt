import math

import multicomponent_relative_volatility as rv


class _FakeChemical:
    def __init__(self, psat):
        self._psat = psat

    def Psat(self, temperature):
        return self._psat[temperature] if isinstance(self._psat, dict) else self._psat


class _FakeSettings:
    def __init__(self, chemicals_by_name):
        self._chemicals_by_name = chemicals_by_name
        self.chemicals = {}

    def set_thermo(self, names, cache=True):
        self.chemicals = {name: self._chemicals_by_name[name] for name in names}


def test_psat_and_adjacent_relative_volatility_use_feed_temperature(monkeypatch):
    monkeypatch.setattr(rv.bst, 'settings', _FakeSettings({
        'Water': _FakeChemical({355.0: 50_000.0}),
        'Methanol': _FakeChemical({355.0: 200_000.0}),
        'Ethanol': _FakeChemical({355.0: 100_000.0}),
        'Glycerol': _FakeChemical({355.0: 100.0}),
    }))

    result = rv.calculate_adjacent_relative_volatilities(
        ['Water', 'Methanol', 'Ethanol', 'Glycerol'],
        ['Methanol', 'Ethanol', 'Water', 'Glycerol'],
        355.0,
    )

    assert result['valid'] is True
    assert [x['component'] for x in result['saturation_pressures']] == [
        'Water', 'Methanol', 'Ethanol', 'Glycerol',
    ]
    assert [x['relative_volatility'] for x in result['adjacent_pairs']] == [2.0, 2.0, 500.0]


def test_invalid_psat_returns_structured_failure(monkeypatch):
    monkeypatch.setattr(rv.bst, 'settings', _FakeSettings({
        'A': _FakeChemical(10.0), 'B': _FakeChemical(math.nan), 'C': _FakeChemical(1.0),
    }))
    result = rv.calculate_adjacent_relative_volatilities(['A', 'B', 'C'], ['A', 'B', 'C'], 300.0)
    assert result['valid'] is False
    assert result['error'] == 'missing_saturation_pressure'
    assert result['adjacent_pairs'] == []


def test_mismatched_internal_order_returns_structured_failure():
    result = rv.calculate_adjacent_relative_volatilities(['A', 'B', 'C'], ['A', 'B'], 300.0)
    assert result['valid'] is False
    assert result['error'] == 'invalid_component_order'
