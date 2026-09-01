"""
Round 1 regression tests -- tools/binary-distillation-issues-9-1-2026-first.md.

Covers `tool_argument_normalizer.py` directly (unit tests) plus
`update_binary_distillation_problem` (integration tests) to confirm a
malformed WRITE-tool payload never raises a raw Python exception and, where
safely recoverable, is normalized to the canonical shape before reaching
`feed_state.apply_user_update()`.

Run with:
    pytest tools/chopper/test_tool_argument_normalizer.py -v
"""
import pytest

from tool_argument_normalizer import (
    normalize_component_flow_units,
    normalize_component_flows,
    normalize_write_arguments,
)


# --- normalize_component_flows ---------------------------------------------

def test_valid_canonical_dict_passes_through_unchanged():
    normalized, err = normalize_component_flows(
        ['Water', 'Ethanol'], {'Water': 50, 'Ethanol': 50},
    )
    assert err is None
    assert normalized is None  # None == "leave the caller's value as-is"


def test_not_given_is_a_noop():
    normalized, err = normalize_component_flows(['Water', 'Ethanol'], None)
    assert normalized is None
    assert err is None


def test_recoverable_parallel_array_form_normalizes():
    normalized, err = normalize_component_flows(['Water', 'Ethanol'], [50, 50])
    assert err is None
    assert normalized == {'Water': 50, 'Ethanol': 50}


def test_parallel_array_with_no_component_names_is_structured_error():
    normalized, err = normalize_component_flows(None, [50, 50])
    assert normalized is None
    assert err['valid'] is False
    assert err['error'] == 'invalid_tool_arguments'
    assert err['field'] == 'component_flows'
    assert err['received_type'] == 'list'


def test_length_mismatch_is_structured_error():
    normalized, err = normalize_component_flows(['Water', 'Ethanol'], [50])
    assert normalized is None
    assert err['error'] == 'invalid_tool_arguments'
    assert err['field'] == 'component_flows'
    assert '1 entries' in err['message'] or '1' in err['message']


def test_nonnumeric_flow_is_structured_error():
    normalized, err = normalize_component_flows(['Water', 'Ethanol'], [50, 'fifty'])
    assert normalized is None
    assert err['error'] == 'invalid_tool_arguments'
    assert err['field'] == 'component_flows'


def test_nonnumeric_value_in_dict_form_is_structured_error():
    normalized, err = normalize_component_flows(
        ['Water', 'Ethanol'], {'Water': 50, 'Ethanol': 'fifty'},
    )
    assert normalized is None
    assert err['error'] == 'invalid_tool_arguments'
    assert err['field'] == 'component_flows'


def test_wrong_type_entirely_is_structured_error():
    normalized, err = normalize_component_flows(['Water', 'Ethanol'], 'fifty and fifty')
    assert normalized is None
    assert err['error'] == 'invalid_tool_arguments'
    assert err['received_type'] == 'str'


# --- normalize_component_flow_units -----------------------------------------

def test_valid_string_units_passes_through_unchanged():
    normalized, err = normalize_component_flow_units('kmol/hr')
    assert err is None
    assert normalized is None  # None == "leave the caller's value as-is"


def test_not_given_units_is_a_noop():
    normalized, err = normalize_component_flow_units(None)
    assert normalized is None
    assert err is None


def test_repeated_identical_units_normalize_to_single_string():
    normalized, err = normalize_component_flow_units(['kmol/hr', 'kmol/hr'])
    assert err is None
    assert normalized == 'kmol/hr'


def test_repeated_units_differing_only_by_alias_normalize():
    normalized, err = normalize_component_flow_units(['KMOL/HR', 'kmol per hour'])
    assert err is None
    assert normalized == 'KMOL/HR'


def test_conflicting_units_are_structured_error():
    normalized, err = normalize_component_flow_units(['kmol/hr', 'kg/hr'])
    assert normalized is None
    assert err['error'] == 'invalid_tool_arguments'
    assert err['field'] == 'component_flow_units'


def test_empty_units_list_is_structured_error():
    normalized, err = normalize_component_flow_units([])
    assert normalized is None
    assert err['error'] == 'invalid_tool_arguments'


# --- normalize_write_arguments (combined) -----------------------------------

def test_combined_valid_case():
    normalized, err = normalize_write_arguments(
        ['Water', 'Ethanol'], {'Water': 50, 'Ethanol': 50}, 'kmol/hr',
    )
    assert err is None
    assert normalized == {
        'component_flows': {'Water': 50, 'Ethanol': 50},
        'component_flow_units': 'kmol/hr',
    }


def test_combined_recoverable_case():
    normalized, err = normalize_write_arguments(
        ['Water', 'Ethanol'], [50, 50], ['kmol/hr', 'kmol/hr'],
    )
    assert err is None
    assert normalized == {
        'component_flows': {'Water': 50, 'Ethanol': 50},
        'component_flow_units': 'kmol/hr',
    }


def test_combined_nothing_given():
    normalized, err = normalize_write_arguments(['Water', 'Ethanol'], None, None)
    assert err is None
    assert normalized == {'component_flows': None, 'component_flow_units': None}


# --- Integration: update_binary_distillation_problem never raises ----------

@pytest.fixture(autouse=True)
def _reset_agent_state():
    import binary_distillation_workflow_agent as agent
    agent.reset_workflow_session()
    yield
    agent.reset_workflow_session()


def test_agent_write_with_valid_canonical_form_works_unchanged():
    from binary_distillation_workflow_agent import update_binary_distillation_problem

    result = update_binary_distillation_problem(
        component_names=['Water', 'Ethanol'],
        component_flows={'Water': 50, 'Ethanol': 50},
        component_flow_units='kmol/hr',
    )
    assert result.get('error') is None
    assert result['feed_flow_complete'] is True


def test_agent_write_normalizes_parallel_array_form_instead_of_crashing():
    from binary_distillation_workflow_agent import update_binary_distillation_problem

    result = update_binary_distillation_problem(
        component_names=['Water', 'Ethanol'],
        component_flows=[50, 50],
    )
    assert result.get('error') is None
    assert result.get('valid') is not False
    assert result['feed_flow_complete'] is True
    assert result['feed']['component_flows'] == {'Water': 50, 'Ethanol': 50}


def test_agent_write_normalizes_repeated_units_instead_of_crashing():
    from binary_distillation_workflow_agent import update_binary_distillation_problem

    result = update_binary_distillation_problem(
        component_names=['Water', 'Ethanol'],
        component_flows={'Water': 50, 'Ethanol': 50},
        component_flow_units=['kmol/hr', 'kmol/hr'],
    )
    assert result.get('error') is None
    assert result['feed']['component_flow_units'] == 'kmol/hr'


def test_agent_write_with_conflicting_units_returns_structured_error_not_exception():
    from binary_distillation_workflow_agent import update_binary_distillation_problem

    result = update_binary_distillation_problem(
        component_names=['Water', 'Ethanol'],
        component_flows={'Water': 50, 'Ethanol': 50},
        component_flow_units=['kmol/hr', 'kg/hr'],
    )
    assert result['valid'] is False
    assert result['error'] == 'invalid_tool_arguments'
    assert result['field'] == 'component_flow_units'


def test_agent_write_with_length_mismatch_returns_structured_error_not_exception():
    from binary_distillation_workflow_agent import update_binary_distillation_problem

    result = update_binary_distillation_problem(
        component_names=['Water', 'Ethanol'],
        component_flows=[50],
    )
    assert result['valid'] is False
    assert result['error'] == 'invalid_tool_arguments'
    assert result['field'] == 'component_flows'


def test_agent_write_original_bug_report_reproduction():
    """The exact malformed payload from the issue doc's Bug report."""
    from binary_distillation_workflow_agent import update_binary_distillation_problem

    result = update_binary_distillation_problem(
        component_names=['Water', 'Ethanol'],
        component_flows=[50, 50],
        component_flow_units=['kmol/hr', 'kmol/hr'],
        pressure_Pa=101325,
        feed_temperature_K=355,
        reflux_condition='saturated_liquid',
    )
    assert result.get('error') is None
    assert result['feed']['component_flows'] == {'Water': 50, 'Ethanol': 50}
    assert result['feed']['component_flow_units'] == 'kmol/hr'
    assert result['feed_screening']['ready'] is True
