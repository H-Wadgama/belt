"""
Tests for `multicomponent_dialogue.py` -- session state, the declarative
field registry, pending-field binding, and read-only query formatting. See
tools/multicomponent-distillation-dialogue-robustness-plan.md.

Run with:
    pytest tools/chopper/test_multicomponent_dialogue.py -v
"""
import multicomponent_dialogue as dlg
from multicomponent_feed_state import apply_user_update, empty_feed_state


def _empty_proposal(**fields):
    base = {
        'target_field': None, 'component_identity_action': 'none',
        'component_names': None, 'component_flows': None, 'component_flow_units': None,
        'total_flow': None, 'total_flow_units': None, 'composition': None,
        'composition_basis': None, 'pressure': None, 'pressure_units': None,
        'feed_temperature': None, 'feed_temperature_units': None,
    }
    base.update(fields)
    return base


def _session_with_pending(missing_field, feed_state=None):
    session = dlg.create_session()
    if feed_state is not None:
        session['feed_state'] = feed_state
    session['pending_request'] = dlg.pending_request_for(missing_field, turn_number=1)
    return session


# --- Pending-field binding: the numeric-collision fix -------------------------

def test_bare_reply_binds_only_to_the_pending_field():
    session = _session_with_pending('pressure_value')
    proposal = _empty_proposal(pressure=1, component_flows={'Water': 1.0})
    binding = dlg.bind_reply_to_pending(session, proposal, '1')
    assert binding['action'] == 'candidate'
    assert binding['candidate_fields'] == {'pressure': 1}
    assert 'component_flows' not in binding['candidate_fields']


def test_unit_only_reply_attaches_to_the_pending_unit_field():
    session = _session_with_pending('pressure_units')
    proposal = _empty_proposal(pressure_units='atm')
    binding = dlg.bind_reply_to_pending(session, proposal, 'atm')
    assert binding == {'action': 'candidate', 'candidate_fields': {'pressure_units': 'atm'}}


def test_bare_value_synthesized_from_raw_text_when_model_proposes_nothing():
    """The model proposing NOTHING for the pending field must not strand
    the turn -- the binder falls back to parsing the raw short answer
    itself."""
    session = _session_with_pending('pressure_value')
    proposal = _empty_proposal()  # model proposed nothing at all
    binding = dlg.bind_reply_to_pending(session, proposal, '1')
    assert binding == {'action': 'candidate', 'candidate_fields': {'pressure': 1}}


def test_incompatible_short_answer_with_no_model_help_asks_for_clarification():
    session = _session_with_pending('pressure_value')
    proposal = _empty_proposal()
    binding = dlg.bind_reply_to_pending(session, proposal, 'blah blah not a number')
    assert binding['action'] == 'clarify'


def test_explicit_different_field_is_accepted_while_pending_stays_conceptually_open():
    """If the message clearly supplies a different field than what was
    asked, that field's data is still accepted this turn."""
    session = _session_with_pending('pressure_value')
    proposal = _empty_proposal(target_field='feed_temperature', feed_temperature=350)
    binding = dlg.bind_reply_to_pending(session, proposal, 'the temperature is 350 K')
    assert binding == {'action': 'candidate', 'candidate_fields': {'feed_temperature': 350}}


def test_no_pending_and_no_target_field_passes_everything_proposed():
    session = dlg.create_session()
    proposal = _empty_proposal(pressure=1, pressure_units='atm')
    binding = dlg.bind_reply_to_pending(session, proposal, 'pressure is 1 atm')
    assert binding['action'] == 'candidate'
    assert binding['candidate_fields'] == {'pressure': 1, 'pressure_units': 'atm'}


def test_target_field_scopes_even_without_pending_request():
    session = dlg.create_session()
    proposal = _empty_proposal(
        target_field='pressure', pressure=1, component_flows={'Water': 5},
    )
    binding = dlg.bind_reply_to_pending(session, proposal, 'pressure is 1')
    assert binding['candidate_fields'] == {'pressure': 1}


# --- Component identity protection --------------------------------------------

def test_differing_identity_with_no_explicit_op_triggers_clarification():
    feed_state = apply_user_update(empty_feed_state(), {
        'component_names': ['Ethanol', 'Methanol', 'Water'],
    })
    session = dlg.create_session()
    session['feed_state'] = feed_state
    proposal = _empty_proposal(component_names=['Methanol'])
    binding = dlg.bind_reply_to_pending(session, proposal, 'methanol = 30 kg/hr')
    assert binding['action'] == 'clarify'
    assert 'Methanol' in binding['message']


def test_explicit_add_action_is_not_treated_as_ambiguous():
    feed_state = apply_user_update(empty_feed_state(), {
        'component_names': ['Ethanol', 'Methanol'],
    })
    session = dlg.create_session()
    session['feed_state'] = feed_state
    proposal = _empty_proposal(component_names=['Water'], component_identity_action='add')
    binding = dlg.bind_reply_to_pending(session, proposal, 'also add water')
    assert binding['action'] == 'candidate'
    assert binding['candidate_fields']['component_names'] == ['Water']
    assert binding['candidate_fields']['component_identity_op'] == 'add'


def test_identical_set_restatement_is_not_a_clarification():
    feed_state = apply_user_update(empty_feed_state(), {
        'component_names': ['Ethanol', 'Methanol', 'Water'],
    })
    session = dlg.create_session()
    session['feed_state'] = feed_state
    proposal = _empty_proposal(component_names=['Water', 'Ethanol', 'Methanol'])
    binding = dlg.bind_reply_to_pending(session, proposal, 'water, ethanol, methanol')
    assert binding['action'] == 'candidate'


# --- pending_request_for / format_pending_question ----------------------------

def test_pending_request_for_pressure_value():
    pending = dlg.pending_request_for('pressure_value', turn_number=3)
    assert pending['field'] == 'pressure'
    assert pending['kind'] == 'value'
    assert pending['asked_on_turn'] == 3


def test_pending_request_for_temperature_drops_bubble_point_wording():
    pending = dlg.pending_request_for('feed_temperature_value')
    assert 'bubble point' not in pending['question'].lower()


def test_format_pending_question_includes_choices():
    pending = dlg.pending_request_for('pressure_units')
    text = dlg.format_pending_question(pending)
    assert 'atm' in text


# --- Read-only query formatting -----------------------------------------------

def test_format_query_answer_pressure_known():
    state = apply_user_update(empty_feed_state(), {'pressure': 2, 'pressure_units': 'bar'})
    assert dlg.format_query_answer('pressure', state) == 'The feed pressure is 2 bar.'


def test_format_query_answer_pressure_missing():
    state = empty_feed_state()
    text = dlg.format_query_answer('pressure', state)
    assert 'has not been provided yet' in text


def test_format_query_answer_pressure_value_only_no_unit():
    state = apply_user_update(empty_feed_state(), {'pressure': 1})
    text = dlg.format_query_answer('pressure', state)
    assert '1' in text and 'units have not been specified' in text


def test_format_query_answer_unregistered_field():
    state = empty_feed_state()
    assert dlg.format_query_answer('not_a_field', state) == "I don't have that information."


# --- Extraction context -------------------------------------------------------

def test_format_extraction_context_includes_established_state_and_active_request():
    state = apply_user_update(empty_feed_state(), {'pressure': 1, 'pressure_units': 'atm'})
    session = dlg.create_session()
    session['feed_state'] = state
    session['pending_request'] = dlg.pending_request_for('feed_temperature_value')
    context = dlg.format_extraction_context(session)
    assert 'ESTABLISHED STATE SUMMARY' in context
    assert '1 atm' in context
    assert 'ACTIVE REQUEST' in context
    assert 'What is the feed temperature?' in context


def test_format_extraction_context_no_active_request_says_none():
    session = dlg.create_session()
    context = dlg.format_extraction_context(session)
    assert 'ACTIVE REQUEST\nnone' in context
