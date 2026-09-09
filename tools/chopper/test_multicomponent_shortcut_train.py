import pytest

import multicomponent_shortcut_train as train
from multicomponent_feed_state import apply_user_update, empty_feed_state, normalize_feed_state


def _ternary_state():
    state = apply_user_update(empty_feed_state(), {
        'component_names': ['Water', 'Ethanol', 'Glycerol'],
        'component_flows': {'Water': 50, 'Ethanol': 50, 'Glycerol': 50},
        'component_flow_units': 'kmol/hr',
        'pressure': 101325, 'pressure_units': 'Pa',
        'feed_temperature': 355, 'feed_temperature_units': 'K',
        'product_purities': {'Water': 0.9, 'Ethanol': 0.9, 'Glycerol': 0.9},
    })
    return normalize_feed_state(state)[0]


def test_seven_component_direct_sequence_has_six_adjacent_columns():
    order = ['A', 'B', 'C', 'D', 'E', 'F', 'G']
    assert train.direct_sequence_pairs(order) == [
        ('A', 'B'), ('B', 'C'), ('C', 'D'),
        ('D', 'E'), ('E', 'F'), ('F', 'G'),
    ]


def test_ternary_direct_train_meets_total_stream_purities_and_exposes_specs():
    result = train.design_direct_shortcut_train(
        _ternary_state(), ['Ethanol', 'Water', 'Glycerol'],
    )
    assert result['valid'] is True
    assert result['sequence'] == 'direct_light_first'
    assert result['column_pressure_Pa'] == 101325.0
    assert result['pressure_drop_Pa_per_column'] == 0.0
    assert result['k'] == 2.0
    assert result['partial_condenser'] is False
    assert [(c['light_key'], c['heavy_key']) for c in result['columns']] == [
        ('Ethanol', 'Water'), ('Water', 'Glycerol'),
    ]
    for column in result['columns']:
        assert 0 < column['x_bot'] < 1
        assert 0 < column['y_top'] < 1
    for product in result['products']:
        assert product['achieved_mole_purity'] + 1e-6 >= product['target_minimum_mole_purity']


def test_train_requires_every_product_purity():
    state = _ternary_state()
    state['product_purities'].pop('Water')
    result = train.design_direct_shortcut_train(state, ['Ethanol', 'Water', 'Glycerol'])
    assert result['valid'] is False
    assert result['error'] == 'missing_product_purities'
