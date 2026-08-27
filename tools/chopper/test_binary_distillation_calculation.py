"""
Integration tests for `binary_distillation_calculation.py` -- see
`tools/binary-distillation-feed-phase-evaluation.md` Step 12.
"""
from binary_distillation_calculation import calculate_binary_distillation_problem

INCOMPLETE_SPEC = {'component_names': ['Butane', 'Acetaldehyde']}

COMPLETE_SPEC = {
    'component_names': ['Butane', 'Acetaldehyde'],
    'component_flows': {'Butane': 50, 'Acetaldehyde': 50},
    'component_flow_units': 'kmol/hr',
    'pressure_Pa': 101325,
    'feed_temperature_K': 405,
    'reflux_condition': 'saturated_liquid',
    'Lr': 0.99, 'Hr': 0.99,
    'external_reflux_ratio_LD': 5.0,
    'use_optimum_feed_plate': True,
}


def test_incomplete_workflow_does_not_calculate():
    result = calculate_binary_distillation_problem(INCOMPLETE_SPEC)
    assert result['calculation_performed'] is False
    assert result['checks'] == {}
    assert result['workflow']['status'] != 'ready_for_calculation'


def test_complete_workflow_runs_feed_phase_calculation():
    result = calculate_binary_distillation_problem(COMPLETE_SPEC)
    assert result['calculation_performed'] is True
    assert result['workflow']['status'] == 'ready_for_calculation'
    assert 'feed_phase' in result['checks']
    assert result['checks']['feed_phase']['valid'] is True
    assert result['checks']['feed_phase']['phase'] in {'liquid', 'vapor', 'vapor_liquid'}


def test_ternary_spec_rejected_before_calculation():
    """The binary-scope gate in assess_binary_distillation_problem runs
    before any BioSTEAM code, so a 3-component spec never reaches the
    calculation layer."""
    spec = dict(COMPLETE_SPEC, component_names=['Butane', 'Acetaldehyde', 'Water'],
                component_flows={'Butane': 40, 'Acetaldehyde': 40, 'Water': 20})
    result = calculate_binary_distillation_problem(spec)
    assert result['calculation_performed'] is False
    assert result['workflow']['status'] == 'unsupported_multicomponent'
    assert result['checks'] == {}
