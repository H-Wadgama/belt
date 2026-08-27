"""
Acceptance tests for tools/binary-distillation-workflow.md section 19,
updated for the feed-state refactor in
tools/binary-distillation-flow-rate-issue.md (feed identity/quantity are now
separated fields -- `component_names`/`component_flows`/`total_flow`/
`composition` -- instead of a single `components: dict[str, float]`).

Exercises `binary_distillation_workflow.assess_binary_distillation_problem`
directly (the deterministic, LLM-free checker) -- these are the same tests
`binary_distillation_workflow_agent.py`'s tool call ultimately reduces to
after cross-turn accumulation, which is exercised separately in
`test_feed_state.py` (agent-level merge semantics) and Test 11 below
(Form 1 -> Form 2 normalization via `assess_binary_distillation_problem`
itself).

Run with:
    pytest tools/chopper/test_binary_distillation_workflow.py -v
"""
from binary_distillation_workflow import assess_binary_distillation_problem

PRESSURE = 101325
TEMP = 350.0
REFLUX = 'saturated_liquid'

ESSENTIALS = {
    'component_names': ['Methanol', 'Water'],
    'component_flows': {'Methanol': 40, 'Water': 60},
    'pressure_Pa': PRESSURE,
    'feed_temperature_K': TEMP,
    'reflux_condition': REFLUX,
}


def test_1_one_component():
    """Test 1 -- one component: status=need_components, asks for the second."""
    result = assess_binary_distillation_problem({'component_names': ['Methanol']})
    assert result['status'] == 'need_components'
    assert result['calculation_performed'] is False
    assert 'second component' in result['message'].lower()


def test_2_three_components():
    """Test 2 -- three components: status=unsupported_multicomponent, no calculation."""
    result = assess_binary_distillation_problem({
        'component_names': ['Methanol', 'Water', 'Glycerol'],
    })
    assert result['status'] == 'unsupported_multicomponent'
    assert result['calculation_performed'] is False


def test_2b_component_names_alone_never_invents_flows():
    """Naming components with no quantities must never produce a flow, total, or composition -- issue doc section 3/7 Situation 1."""
    result = assess_binary_distillation_problem({'component_names': ['Methanol', 'Water']})
    assert result['valid_binary_scope'] is True
    assert result['feed_flow_complete'] is False
    assert result['feed_composition_complete'] is False
    assert result['feed']['component_flows'] == {}
    assert result['feed']['total_flow'] is None
    assert result['feed']['composition'] == {}


def test_2c_one_component_flow_never_becomes_total():
    """A single component's flow must never be interpreted as the total feed flow -- issue doc section 1 example / Situation 2."""
    result = assess_binary_distillation_problem({
        'component_names': ['Methanol', 'Water'],
        'component_flows': {'Methanol': 50},
    })
    assert result['valid_binary_scope'] is True
    assert result['feed_flow_complete'] is False
    assert result['feed_composition_complete'] is False
    assert result['feed']['total_flow'] is None
    assert result['feed']['composition'] == {}
    assert result['status'] == 'need_essential_inputs'
    assert 'not yet fully defined' in result['message']


def test_3_two_components_no_operating_data():
    """Test 3 -- two components with full flows, nothing else: reports the three remaining essentials as missing, no assumed bubble point/1 atm."""
    result = assess_binary_distillation_problem({
        'component_names': ['Methanol', 'Water'],
        'component_flows': {'Methanol': 40, 'Water': 60},
    })
    assert result['status'] == 'need_essential_inputs'
    assert result['valid_binary_scope'] is True
    assert result['feed_flow_complete'] is True
    assert result['feed_composition_complete'] is True
    missing_joined = ' '.join(result['missing_essential_inputs'])
    assert 'pressure_Pa' in missing_joined
    assert 'feed thermal condition' in missing_joined
    assert 'reflux_condition' in missing_joined


def test_4_optimum_feed_plate_only():
    """Test 4 -- essentials complete, only 'use optimum feed plate' stated: does NOT identify a case; all four remain candidates."""
    result = assess_binary_distillation_problem(dict(ESSENTIALS))
    assert result['essential_complete'] is True
    assert result['case'] is None
    assert set(result['case_candidates']) == {'A', 'B', 'C', 'D'}
    assert result['status'] == 'need_case_definition'


def test_5_boilup_ratio_routes_to_case_d():
    """Test 5 -- V/B given: case narrows to D directly, asking for xD/xB (and optimum-feed-plate), never a case letter."""
    spec = dict(ESSENTIALS, boilup_ratio_VB=2.0)
    result = assess_binary_distillation_problem(spec)
    assert result['case_candidates'] == ['D']
    assert set(result['missing_case_inputs']['D']) == {'xD', 'xB'}
    assert 'which case' not in result['message'].lower()


def test_6_complete_case_d():
    """Test 6 -- complete Case D spec: ready_for_calculation, correct would_calculate list, no calculation performed."""
    spec = dict(ESSENTIALS, xD=0.99, xB=0.01, boilup_ratio_VB=2.0, use_optimum_feed_plate=True)
    result = assess_binary_distillation_problem(spec)
    assert result['status'] == 'ready_for_calculation'
    assert result['case'] == 'D'
    assert set(result['would_calculate']) == {
        'D', 'B', 'QR', 'Qc', 'N', 'Nfeed (optimum feed stage)', 'column diameter',
    }
    assert result['calculation_performed'] is False


def test_7_xD_xB_only_ambiguous_between_A_and_D():
    """Test 7 -- xD+xB only (no reflux ratio, no boilup ratio): candidates are exactly A and D, not a guess."""
    spec = dict(ESSENTIALS, xD=0.99, xB=0.01)
    result = assess_binary_distillation_problem(spec)
    assert result['case'] is None
    assert set(result['case_candidates']) == {'A', 'D'}
    assert 'external_reflux_ratio_LD' in ' '.join(result['missing_case_inputs']['A'])
    assert 'boilup_ratio_VB' in ' '.join(result['missing_case_inputs']['D'])


def test_8_complete_case_a():
    """Test 8 -- complete Case A spec: ready_for_calculation, correct would_calculate list."""
    spec = dict(ESSENTIALS, xD=0.99, xB=0.01, external_reflux_ratio_LD=3.0, use_optimum_feed_plate=True)
    result = assess_binary_distillation_problem(spec)
    assert result['status'] == 'ready_for_calculation'
    assert result['case'] == 'A'
    assert set(result['would_calculate']) == {
        'D', 'B', 'QR', 'Qc', 'N', 'Nfeed (optimum feed stage)', 'column diameter',
    }
    assert result['calculation_performed'] is False


def test_9_recoveries_route_to_case_b():
    """Test 9 -- fractional recoveries given: routes to Case B, reports missing Case B fields."""
    spec = dict(ESSENTIALS, Lr=0.99)
    result = assess_binary_distillation_problem(spec)
    assert result['case_candidates'] == ['B']
    assert set(result['missing_case_inputs']['B']) >= {'Hr'}


def test_10_product_flow_plus_composition_routes_to_case_c():
    """Test 10 -- a product flow + a composition given: routes to Case C, correctly treating D/xD as given inputs (only the reflux ratio is still missing)."""
    spec = dict(ESSENTIALS, distillate_flow=40.0, xD=0.99)
    result = assess_binary_distillation_problem(spec)
    assert result['case_candidates'] == ['C']
    assert result['missing_case_inputs']['C'] == ['external_reflux_ratio_LD (or reflux_ratio_multiplier_k)']

    # Complete it and confirm Case C reports the CALCULATED (not given) flow/composition.
    complete_spec = dict(spec, external_reflux_ratio_LD=3.0, use_optimum_feed_plate=True)
    complete_result = assess_binary_distillation_problem(complete_spec)
    assert complete_result['status'] == 'ready_for_calculation'
    assert complete_result['case'] == 'C'
    assert 'B (bottoms flow)' in complete_result['would_calculate']
    assert 'xB' in complete_result['would_calculate']
    assert 'D (distillate flow)' not in complete_result['would_calculate']
    assert 'xD' not in complete_result['would_calculate']


def test_11_component_flows_imply_total_and_composition():
    """Test 11 -- per-component flow rates fully determine total flow + composition, DERIVED (not user_explicit) -- issue doc Situation 3 / Test 3 / Test 9."""
    result = assess_binary_distillation_problem(dict(ESSENTIALS))
    assert result['valid_binary_scope'] is True
    assert result['feed_flow_complete'] is True
    assert result['feed_composition_complete'] is True
    feed = result['feed']
    assert feed['total_flow'] == 100
    assert feed['total_flow_provenance'] == 'derived'
    assert feed['composition'] == {'Methanol': 0.4, 'Water': 0.6}
    assert feed['composition_provenance'] == {'Methanol': 'derived', 'Water': 'derived'}


def test_12_reflux_ratio_terminology_not_reinterpreted():
    """Test 12 -- external_reflux_ratio_LD is never silently treated as reflux_ratio_multiplier_k, or vice versa; giving both is ambiguous, not auto-resolved."""
    spec = dict(ESSENTIALS, xD=0.99, xB=0.01, external_reflux_ratio_LD=2.5, reflux_ratio_multiplier_k=1.5)
    result = assess_binary_distillation_problem(spec)
    assert result['status'] == 'ambiguous'
    assert 'external_reflux_ratio_LD' in result['message']
    assert 'reflux_ratio_multiplier_k' in result['message']


def test_no_default_to_case_a():
    """Section 7 -- essentials-only spec (no case-distinguishing field at all) must NOT default to Case A."""
    result = assess_binary_distillation_problem(dict(ESSENTIALS))
    assert result['case'] != 'A'
    assert result['case'] is None
    assert 'A' in result['case_candidates']
    assert 'B' in result['case_candidates']
    assert 'C' in result['case_candidates']
    assert 'D' in result['case_candidates']


def test_no_calculation_ever_performed():
    """calculation_performed must be False for every status, including ready_for_calculation."""
    for spec in (
        {},
        {'component_names': ['Methanol']},
        dict(ESSENTIALS),
        dict(ESSENTIALS, xD=0.99, xB=0.01, external_reflux_ratio_LD=3.0, use_optimum_feed_plate=True),
    ):
        assert assess_binary_distillation_problem(spec)['calculation_performed'] is False


# --- tools/binary-distillation-flow-rate-issue.md acceptance tests -------


def test_inconsistent_total_flow():
    """Issue doc section 11 / Test 10 -- component flows sum to 100, but total_flow explicitly given as 120: status=inconsistent_input, not silently resolved."""
    spec = dict(ESSENTIALS, total_flow=120)
    result = assess_binary_distillation_problem(spec)
    assert result['status'] == 'inconsistent_input'
    assert '100' in result['message']
    assert '120' in result['message']


def test_inconsistent_composition():
    """Issue doc section 11 / Test 11 -- component flows imply a 0.4/0.6 split, but Methanol composition explicitly given as 0.7: status=inconsistent_input."""
    spec = dict(ESSENTIALS, composition={'Methanol': 0.7})
    result = assess_binary_distillation_problem(spec)
    assert result['status'] == 'inconsistent_input'
    assert '0.7' in result['message']


def test_problem_example_1_no_invented_flows_across_scope_replacement():
    """Issue doc section 15 -- three components rejected; naming just 'Water' replaces (not narrows) the identity list with none of the old flows surviving; the pair is established with no invented Water=80/Methanol=100 numbers."""
    three = assess_binary_distillation_problem({'component_names': ['Water', 'Methanol', 'Butanol']})
    assert three['status'] == 'unsupported_multicomponent'

    one = assess_binary_distillation_problem({'component_names': ['Water']})
    assert one['status'] == 'need_components'
    assert one['feed']['component_flows'] == {}

    two = assess_binary_distillation_problem({'component_names': ['Water', 'Methanol']})
    assert two['valid_binary_scope'] is True
    assert two['feed']['component_flows'] == {}
    assert two['feed']['total_flow'] is None
    assert two['feed']['composition'] == {}


def test_problem_example_2_single_component_flow_never_becomes_total():
    """Issue doc section 16 -- 'Methanol feed rate is 50 kmol/hr' must never be read as the total feed flow, and must not produce a composition."""
    spec = {
        'component_names': ['Methanol', 'Water'],
        'component_flows': {'Methanol': 50}, 'component_flow_units': 'kmol/hr',
    }
    result = assess_binary_distillation_problem(spec)
    assert result['feed']['total_flow'] is None
    assert result['feed']['composition'] == {}
    assert result['status'] == 'need_essential_inputs'
    assert '50' in result['message']
    assert 'not yet fully defined' in result['message']
