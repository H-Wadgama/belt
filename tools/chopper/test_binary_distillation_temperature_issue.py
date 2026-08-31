"""
Regression tests for tools/chopper/binary-distillation-temperature-issue.md
-- an explicitly stated feed temperature must always survive into the WRITE
(both on first mention and on a later corrective restatement), and a
corrective restatement must never be misrouted to a READ.

Three layers are exercised, same split as
`test_binary_distillation_pending_truth.py`:
  - `binary_distillation_workflow.assess_binary_distillation_problem`'s
    deterministic `pending_request` generation for the feed thermal
    condition (no LLM, no agent).
  - `binary_distillation_workflow_agent`'s deterministic extraction/resolver
    helpers (`extract_explicit_feed_temperature_K`, `resolve_pending_reply`
    with `request_type='temperature_K'`).
  - `binary_distillation_workflow_agent.ask()`'s wiring of both into the
    pre-model deterministic short-circuit, using the same fake/scripted
    Ollama client style as `test_binary_distillation_workflow_agent.py` --
    no running Ollama server is required.

Run with:
    pytest tools/chopper/test_binary_distillation_temperature_issue.py -v
"""
import pytest

import binary_distillation_workflow_agent as agent
from binary_distillation_workflow import assess_binary_distillation_problem

PRESSURE = 101325
REFLUX = 'saturated_liquid'

# Essentials with everything EXCEPT the feed thermal condition -- the
# reproducible-failure setup from the issue doc (temperature is the sole
# missing essential, so a pending_request for it should exist).
ESSENTIALS_MINUS_TEMPERATURE = {
    'component_names': ['Ethanol', 'Water'],
    'component_flows': {'Ethanol': 50, 'Water': 50},
    'component_flow_units': 'kmol/hr',
    'pressure_Pa': PRESSURE,
    'reflux_condition': REFLUX,
}


# ---------------------------------------------------------------------------
# `assess_binary_distillation_problem` pending_request generation for the
# feed thermal condition (Step 5).
# ---------------------------------------------------------------------------

def test_pending_request_feed_temperature_when_sole_missing_essential():
    result = assess_binary_distillation_problem(dict(ESSENTIALS_MINUS_TEMPERATURE))
    assert result['status'] == 'need_essential_inputs'
    assert result['pending_request'] is not None
    assert result['pending_request']['field'] == 'feed_temperature_K'
    assert result['pending_request']['request_type'] == 'temperature_K'


def test_pending_request_none_for_temperature_when_other_essentials_also_missing():
    """Feed thermal condition is missing ALONGSIDE another essential (pressure) --
    still no single-field guess, same discipline as the pre-existing essentials."""
    spec = {k: v for k, v in ESSENTIALS_MINUS_TEMPERATURE.items() if k != 'pressure_Pa'}
    result = assess_binary_distillation_problem(spec)
    assert result['status'] == 'need_essential_inputs'
    assert result['pending_request'] is None


def test_essential_complete_true_after_temperature_write():
    """Step 18 -- once feed_temperature_K is supplied, essential_complete flips True
    (assuming everything else is already known) and the report moves on."""
    spec = dict(ESSENTIALS_MINUS_TEMPERATURE, feed_temperature_K=355)
    result = assess_binary_distillation_problem(spec)
    assert result['essential_complete'] is True
    assert 'need_essential_inputs' != result['status']


# ---------------------------------------------------------------------------
# Step 15/16 -- exactly-one-thermal-spec behavior is untouched.
# ---------------------------------------------------------------------------

def test_feed_quality_still_recognized_as_its_own_thermal_spec():
    spec = dict(ESSENTIALS_MINUS_TEMPERATURE, feed_quality=0.5)
    result = assess_binary_distillation_problem(spec)
    assert result['essential_complete'] is True


def test_conflicting_thermal_specs_still_reported_ambiguous():
    spec = dict(ESSENTIALS_MINUS_TEMPERATURE, feed_temperature_K=355, feed_quality=0.4)
    result = assess_binary_distillation_problem(spec)
    assert result['status'] == 'need_essential_inputs'
    assert 'mutually exclusive' in result['message']


# ---------------------------------------------------------------------------
# Agent-level: resolve_pending_reply(request_type='temperature_K')
# ---------------------------------------------------------------------------

TEMPERATURE_PENDING = {
    'field': 'feed_temperature_K', 'request_type': 'temperature_K',
    'prompt': 'What is the feed thermal condition?',
}


@pytest.mark.parametrize('raw', [
    'I think I specified the feed temperature as 355 K',
    'Feed temperature is 355 K',
    'It was 355 K',
    'It is 355 K',
    '355 K',
    'I already said 355 K',
    '355K',
])
def test_resolve_temperature_pending_reply(raw):
    assert agent.resolve_pending_reply(TEMPERATURE_PENDING, raw) == {'feed_temperature_K': 355.0}


def test_resolve_temperature_pending_reply_not_hijacked_by_condenser_context():
    """Step 6 negative example -- naming a different apparatus must not resolve
    the feed-temperature pending request, even though a live pending_request exists."""
    assert agent.resolve_pending_reply(TEMPERATURE_PENDING, 'the condenser operates at 355 K') is None


def test_resolve_temperature_pending_reply_none_without_kelvin_suffix():
    """A bare unitless number must not resolve to a temperature -- it could be
    feed_quality instead (Step 15); this task only fixes explicit temperature."""
    assert agent.resolve_pending_reply(TEMPERATURE_PENDING, '355') is None


def test_resolve_temperature_pending_reply_none_for_read_question():
    """Step 11 -- a genuine question about stored state must not resolve as a WRITE."""
    assert agent.resolve_pending_reply(TEMPERATURE_PENDING, 'What feed temperature do you currently have stored?') is None


# ---------------------------------------------------------------------------
# Agent-level: extract_explicit_feed_temperature_K (Step 6, case 2 -- no
# pending_request required, but requires unambiguous feed-temperature wording)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('raw,expected', [
    ('feed temperature is 355 K', 355.0),
    ('Feed temperature is 355 K!', 355.0),
    ('feed temp is 355 K', 355.0),
    ('the feed enters at 400 K', 400.0),
    ('The feed is at 355 K.', 355.0),
    ('The feed temperature is 355 K.', 355.0),
])
def test_extract_explicit_feed_temperature_positive(raw, expected):
    assert agent.extract_explicit_feed_temperature_K(raw) == expected


@pytest.mark.parametrize('raw', [
    'What feed temperature do you currently have stored?',
    'What is the current pressure?',
    'the condenser operates at 355 K',
    'the bottoms temperature is 355 K',
    'The pressure is 101325 Pa and the reflux ratio is 2.',
    'xD = 0.95',
    '355 K',  # bare number, no explicit feed-temperature wording
])
def test_extract_explicit_feed_temperature_negative(raw):
    assert agent.extract_explicit_feed_temperature_K(raw) is None


def test_extract_explicit_feed_temperature_does_not_hijack_rich_composite_message():
    """Step 8/9 -- the initial multi-fact problem statement must not be shortcut
    down to temperature alone; it must still be extracted in full by the model."""
    text = (
        'Separate water and ethanol at 355 K and 101325 Pa pressure. '
        'The feed composition is 50 kmol/hr ethanol and 50 kmol/hr water, '
        'and the reflux is saturated liquid.'
    )
    assert agent.extract_explicit_feed_temperature_K(text) is None


# ---------------------------------------------------------------------------
# Agent-level: ask() wiring -- fakes, no live Ollama server required.
# ---------------------------------------------------------------------------

class FakeFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class FakeToolCall:
    def __init__(self, name, arguments=None):
        self.function = FakeFunction(name, arguments or {})


class FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []
        self.role = 'assistant'


class FakeResponse:
    def __init__(self, message):
        self.message = message


def final(content='ok'):
    return FakeResponse(FakeMessage(content=content, tool_calls=[]))


class ScriptedClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def chat(self, model, messages, tools=None, think=False):
        self.calls.append(tools is not None)
        if not self._responses:
            raise AssertionError('ScriptedClient ran out of scripted responses')
        return self._responses.pop(0)


def _tool_result_names(messages):
    return [m['tool_name'] for m in messages if isinstance(m, dict) and m.get('role') == 'tool']


def _tool_result_args(messages, tool_name):
    """Find the arguments a tool was called with, whether the assistant
    message is a synthetic dict (deterministic pending-resolver injection)
    or a FakeMessage object (normal model-driven tool_calls response)."""
    for m in messages:
        if isinstance(m, dict):
            tool_calls = m.get('tool_calls')
        else:
            tool_calls = getattr(m, 'tool_calls', None)
        for call in (tool_calls or []):
            if isinstance(call, dict):
                name, args = call['function']['name'], call['function']['arguments']
            else:
                name, args = call.function.name, call.function.arguments
            if name == tool_name:
                return args
    return None


def _base_messages():
    return [{'role': 'system', 'content': agent.SYSTEM_PROMPT}]


@pytest.fixture(autouse=True)
def _reset_state():
    agent.reset_workflow_session()
    yield
    agent.reset_workflow_session()


def test_ask_corrective_temperature_reply_performs_write_not_read():
    """The exact reproducible-failure sequence from the issue doc: temperature
    is the sole missing essential (pending), and the user's corrective
    restatement must perform a real WRITE, never a READ."""
    agent.update_binary_distillation_problem(**ESSENTIALS_MINUS_TEMPERATURE)
    pre_state = agent.get_binary_distillation_problem()
    assert pre_state['pending_request']['field'] == 'feed_temperature_K'

    client = ScriptedClient([final('Feed temperature recorded as 355 K.')])
    messages = _base_messages() + [
        {'role': 'user', 'content': 'I think I specified the feed temperature as 355 K'},
    ]

    agent.ask(client, messages)

    assert _tool_result_names(messages) == ['update_binary_distillation_problem']
    assert _tool_result_args(messages, 'update_binary_distillation_problem') == {'feed_temperature_K': 355.0}
    # Finalization call has no tools exposed -- the model never got a chance
    # to call get_binary_distillation_problem instead.
    assert client.calls == [False]

    post_state = agent.get_binary_distillation_problem()
    assert post_state['essential_complete'] is True


@pytest.mark.parametrize('raw', ['Feed temperature is 355 K', 'It is 355 K', '355 K'])
def test_ask_corrective_temperature_reply_variants_write(raw):
    agent.update_binary_distillation_problem(**ESSENTIALS_MINUS_TEMPERATURE)

    client = ScriptedClient([final('Noted.')])
    messages = _base_messages() + [{'role': 'user', 'content': raw}]

    agent.ask(client, messages)

    assert _tool_result_names(messages) == ['update_binary_distillation_problem']
    assert _tool_result_args(messages, 'update_binary_distillation_problem') == {'feed_temperature_K': 355.0}


def test_ask_standalone_explicit_temperature_write_without_pending_request():
    """Step 6 case 2 -- feed thermal condition is missing, but nothing else is
    pending yet (multiple essentials still open, so no single-field
    pending_request exists). An unambiguous standalone statement still
    performs a real WRITE, not a READ or fall-through to the model."""
    agent.update_binary_distillation_problem(component_names=['Ethanol', 'Water'])
    pre_state = agent.get_binary_distillation_problem()
    assert pre_state['pending_request'] is None  # multiple essentials still missing

    client = ScriptedClient([final('Feed temperature recorded.')])
    messages = _base_messages() + [{'role': 'user', 'content': 'The feed temperature is 355 K.'}]

    agent.ask(client, messages)

    assert _tool_result_names(messages) == ['update_binary_distillation_problem']
    assert _tool_result_args(messages, 'update_binary_distillation_problem') == {'feed_temperature_K': 355.0}
    assert client.calls == [False]


def test_ask_read_question_about_temperature_falls_through_to_model():
    """Step 11 -- a genuine question about stored state is not intercepted by
    either deterministic layer; it falls through to normal model-driven
    routing (which would call get_binary_distillation_problem)."""
    agent.update_binary_distillation_problem(**ESSENTIALS_MINUS_TEMPERATURE)

    client = ScriptedClient([final('You have not specified a feed temperature yet.')])
    messages = _base_messages() + [
        {'role': 'user', 'content': 'What feed temperature do you currently have stored?'},
    ]

    result = agent.ask(client, messages)

    # Neither deterministic shortcut fired -- no synthetic WRITE was injected.
    assert _tool_result_names(messages) == []
    assert result == 'You have not specified a feed temperature yet.'


def test_ask_does_not_shortcut_the_rich_initial_problem_statement():
    """The long multi-fact initial statement must fall through to normal
    model-driven tool selection (where the improved prompt/docstring teaches
    the model to extract feed_temperature_K alongside everything else in one
    WRITE) rather than being deterministically shortcut to temperature alone."""
    text = (
        'Separate water and ethanol at 355 K and 101325 Pa pressure. '
        'The feed composition is 50 kmol/hr ethanol and 50 kmol/hr water, '
        'and the reflux is saturated liquid.'
    )
    # Build a scripted WRITE call carrying the full extraction a correctly-
    # prompted model would produce, to prove ask() lets it through untouched.
    full_write = FakeToolCall('update_binary_distillation_problem', {
        'component_names': ['Water', 'Ethanol'],
        'component_flows': {'Ethanol': 50, 'Water': 50},
        'component_flow_units': 'kmol/hr',
        'feed_temperature_K': 355,
        'pressure_Pa': 101325,
        'reflux_condition': 'saturated_liquid',
    })
    client = ScriptedClient([
        FakeResponse(FakeMessage(content=None, tool_calls=[full_write])),
        final('Got it.'),
    ])
    messages = _base_messages() + [{'role': 'user', 'content': text}]

    agent.ask(client, messages)

    assert _tool_result_names(messages) == ['update_binary_distillation_problem']
    assert _tool_result_args(messages, 'update_binary_distillation_problem')['feed_temperature_K'] == 355


# ---------------------------------------------------------------------------
# Prompt/docstring content guard -- Steps 3/4/7. Lightweight regression guard
# that the extraction reinforcement wasn't accidentally removed; does not
# (and cannot, without a live model) prove Qwen always extracts correctly.
# ---------------------------------------------------------------------------

def test_system_prompt_has_feed_temperature_extraction_rule():
    assert 'FEED TEMPERATURE EXTRACTION RULE' in agent.SYSTEM_PROMPT
    assert 'feed_temperature_K=355' in agent.SYSTEM_PROMPT
    assert 'pressure_Pa=101325' in agent.SYSTEM_PROMPT


def test_update_tool_docstring_has_temperature_examples():
    doc = agent.update_binary_distillation_problem.__doc__
    assert 'feed temperature is 355 K' in doc
    assert 'feed_temperature_K=355' in doc
