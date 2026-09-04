"""
Unit tests for `multicomponent_diagnostics.py` -- pure data-model tests,
no Ollama, no BioSTEAM, no agent module.

See tools/multicomponent-distillation-debugging-plan.md "Required Tests".
"""
import inspect
import json

import multicomponent_diagnostics as diag


# --- new_turn_record ---------------------------------------------------

def test_new_turn_record_has_the_documented_top_level_shape():
    record = diag.new_turn_record(3, 'hello')
    assert record['turn'] == 3
    assert record['user_message'] == 'hello'
    for key in (
        'pending_before', 'state_before', 'model', 'prechecks', 'grounding',
        'function_calls', 'state_after', 'state_diff', 'reply', 'exit_path',
    ):
        assert key in record
    assert record['grounding'] == {'accepted': {}, 'rejected': {}}
    assert record['function_calls'] == []


# --- to_jsonable ---------------------------------------------------------

def test_to_jsonable_passes_through_plain_json_values():
    value = {'a': 1, 'b': [1, 2.5, 'x', None, True], 'c': {'d': 'e'}}
    assert diag.to_jsonable(value) == value


def test_to_jsonable_handles_circular_references_without_raising():
    circular = {}
    circular['self'] = circular
    result = diag.to_jsonable(circular)
    assert result['self'] == '<circular>'
    json.dumps(result)  # must not raise


def test_to_jsonable_replaces_callables_and_exceptions_with_markers():
    def some_func():
        pass

    result = diag.to_jsonable({'fn': some_func, 'err': ValueError('boom')})
    assert result['fn'] == '<callable:some_func>'
    assert result['err'] == '<exception:ValueError:boom>'
    json.dumps(result)  # must not raise


def test_to_jsonable_replaces_non_serializable_objects_with_type_marker():
    class Opaque:
        pass

    result = diag.to_jsonable(Opaque())
    assert result == '<non_serializable:Opaque>'


# --- compute_state_diff ---------------------------------------------------

def test_compute_state_diff_reports_added_changed_removed():
    before = {
        'component_names': ['Methanol', 'Ethanol', 'Water'],
        'component_flows': {'Ethanol': 20},
        'component_flow_units': 'kg/hr',
    }
    after = {
        'component_names': ['Methanol'],
        'component_flows': {},
        'component_flow_units': 'kmol/hr',
        'pressure': 101325,
    }
    diff = diag.compute_state_diff(before, after)

    assert diff['changed']['component_names'] == {
        'before': ['Methanol', 'Ethanol', 'Water'], 'after': ['Methanol'],
    }
    assert diff['changed']['component_flow_units'] == {'before': 'kg/hr', 'after': 'kmol/hr'}
    assert diff['removed']['component_flows.Ethanol'] == 20
    assert diff['added']['pressure'] == 101325


def test_compute_state_diff_excludes_unchanged_fields():
    state = {'component_names': ['A', 'B', 'C'], 'pressure': 101325}
    diff = diag.compute_state_diff(state, state)
    assert diff == {'added': {}, 'changed': {}, 'removed': {}}


def test_compute_state_diff_compares_component_mappings_by_key_not_list_index():
    before = {'component_flows': {'Water': 30, 'Ethanol': 40}}
    after = {'component_flows': {'Water': 30, 'Ethanol': 50, 'Methanol': 10}}
    diff = diag.compute_state_diff(before, after)
    assert 'component_flows.Water' not in diff['changed']
    assert diff['changed']['component_flows.Ethanol'] == {'before': 40, 'after': 50}
    assert diff['added']['component_flows.Methanol'] == 10


# --- render_human_readable -------------------------------------------------

def test_render_human_readable_omits_empty_sections():
    record = diag.new_turn_record(1, 'hi')
    record['reply'] = 'What is the feed pressure?'
    record['exit_path'] = 'pending_request'
    text = diag.render_human_readable(record)

    assert '[debug turn 1]' in text
    assert '[reply] What is the feed pressure?' in text
    assert '[exit path] pending_request' in text
    # Nothing was proposed/grounded/called this turn -- those sections
    # carry no information and must not appear.
    assert '[model proposal]' not in text
    assert '[grounding accepted]' not in text
    assert '[grounding rejected]' not in text
    assert '[calling' not in text
    assert '[state diff] (no change)' in text


def test_render_human_readable_includes_populated_sections():
    record = diag.new_turn_record(2, 'methanol = 30 kg/hr')
    record['model'] = {
        'call_count': 1, 'raw_responses': ['{"foo": 1}'],
        'parsed_proposal': {'component_flows': {'Methanol': 30}}, 'retry_used': False,
        'parse_succeeded': True,
    }
    record['grounding'] = {'accepted': {'component_flows': {'Methanol': 30}}, 'rejected': {}}
    record['function_calls'] = [{
        'name': 'update_multicomponent_feed', 'arguments': {'component_flows': {'Methanol': 30}},
        'result': {'complete': False, 'pending_request': None},
    }]
    record['state_diff'] = {
        'added': {}, 'changed': {'component_flows.Methanol': {'before': None, 'after': 30}}, 'removed': {},
    }
    record['reply'] = 'What is the feed pressure?'
    record['exit_path'] = 'pending_request'

    text = diag.render_human_readable(record)
    assert '[model proposal] call_count=1 retry_used=False parse_succeeded=True' in text
    assert 'raw[1]: {"foo": 1}' in text
    assert '[grounding accepted]' in text
    assert '[calling update_multicomponent_feed]' in text
    assert '[function result]' in text
    assert 'changed.component_flows.Methanol' in text


# --- render_json -----------------------------------------------------------

def test_render_json_produces_valid_json_with_required_top_level_fields():
    record = diag.new_turn_record(1, 'hi')
    record['reply'] = 'ok'
    record['exit_path'] = 'pending_request'
    parsed = json.loads(diag.render_json(record))
    for key in (
        'turn', 'user_message', 'pending_before', 'state_before', 'model',
        'prechecks', 'grounding', 'function_calls', 'state_after',
        'state_diff', 'reply', 'exit_path',
    ):
        assert key in parsed


def test_render_json_never_raises_on_non_serializable_content():
    record = diag.new_turn_record(1, 'hi')
    record['state_before'] = {'weird': object()}
    diag.render_json(record)  # must not raise


# --- Module independence: no Ollama/BioSTEAM/state-changing calls ----------

def test_module_never_imports_ollama_or_biosteam_or_state_changing_functions():
    for forbidden in (
        'import ollama', 'import biosteam', 'import bst',
        'import multicomponent_feed_tool', 'from multicomponent_feed_tool',
    ):
        assert forbidden not in inspect.getsource(diag)
