"""
Regression tests for the bounded per-turn tool-call controller in
`binary_distillation_workflow_agent.py::ask()` --
tools/binary-distillation-read-loop-fix-plan.md.

These use a fake/scripted Ollama client -- no running Ollama server is
required. The point is to prove termination and the one-engineering-op-
per-turn policy are enforced by `ask()` itself, not by the model choosing
to stop.

Run with:
    pytest tools/chopper/test_binary_distillation_workflow_agent.py -v
"""
import json

import pytest

import binary_distillation_workflow_agent as agent


# ---------------------------------------------------------------------------
# Fakes -- no ollama import required.
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


def with_calls(*tool_calls):
    return FakeResponse(FakeMessage(content=None, tool_calls=list(tool_calls)))


def write_call(**kwargs):
    return FakeToolCall('update_binary_distillation_problem', kwargs)


def read_call():
    return FakeToolCall('get_binary_distillation_problem')


def reset_call():
    return FakeToolCall('reset_workflow_session')


class ScriptedClient:
    """Returns responses from a fixed list, one per `.chat()` call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []  # one bool per call: whether `tools` was exposed

    def chat(self, model, messages, tools=None, think=False):
        self.calls.append(tools is not None)
        if not self._responses:
            raise AssertionError('ScriptedClient ran out of scripted responses -- ask() kept calling chat()')
        return self._responses.pop(0)


class StubbornClient:
    """A pathological client: always tries to make another tool call, with
    a fresh (non-duplicate) fingerprint each time, regardless of whether
    tools are exposed. Used to prove ask() terminates even when the model
    never voluntarily stops. Raises if called more than `max_calls` times,
    which would indicate an actual infinite loop rather than a bounded one.
    """

    def __init__(self, max_calls=6):
        self.max_calls = max_calls
        self.n_calls = 0

    def chat(self, model, messages, tools=None, think=False):
        self.n_calls += 1
        if self.n_calls > self.max_calls:
            raise AssertionError(f'ask() called chat() more than {self.max_calls} times -- looks unbounded')
        return with_calls(write_call(component_names=[f'Comp{self.n_calls}']))


def _tool_result_names(messages):
    return [m['tool_name'] for m in messages if isinstance(m, dict) and m.get('role') == 'tool']


@pytest.fixture(autouse=True)
def _reset_state():
    agent.reset_workflow_session()
    yield
    agent.reset_workflow_session()


def _base_messages():
    return [{'role': 'system', 'content': agent.SYSTEM_PROMPT}]


# ---------------------------------------------------------------------------
# Test 1 -- WRITE finalizes without READ
# ---------------------------------------------------------------------------

def test_write_finalizes_without_read():
    client = ScriptedClient([
        with_calls(write_call(component_names=['Methanol', 'Water'])),
        final('Got it -- Methanol and Water.'),
    ])
    messages = _base_messages() + [{'role': 'user', 'content': 'separate methanol and water'}]

    result = agent.ask(client, messages)

    assert _tool_result_names(messages) == ['update_binary_distillation_problem']
    assert client.calls == [True, False]  # 2nd (finalization) call has no tools
    assert result == 'Got it -- Methanol and Water.'


# ---------------------------------------------------------------------------
# Test 2 -- READ finalizes after one call
# ---------------------------------------------------------------------------

def test_read_finalizes_after_one_call():
    client = ScriptedClient([
        with_calls(read_call()),
        final('Here is what I have so far.'),
    ])
    messages = _base_messages() + [{'role': 'user', 'content': 'what do you have so far?'}]

    result = agent.ask(client, messages)

    assert _tool_result_names(messages) == ['get_binary_distillation_problem']
    assert client.calls == [True, False]
    assert result == 'Here is what I have so far.'


# ---------------------------------------------------------------------------
# Test 3 -- model attempts repeated READ
# ---------------------------------------------------------------------------

def test_repeated_read_is_forced_to_finalize():
    class AlwaysReadClient:
        def __init__(self):
            self.calls = []

        def chat(self, model, messages, tools=None, think=False):
            self.calls.append(tools is not None)
            if tools is not None:
                return with_calls(read_call())
            return final('stopping here')

    client = AlwaysReadClient()
    messages = _base_messages() + [{'role': 'user', 'content': 'state question'}]

    result = agent.ask(client, messages)

    assert _tool_result_names(messages) == ['get_binary_distillation_problem']
    assert client.calls == [True, False]
    assert result == 'stopping here'


# ---------------------------------------------------------------------------
# Test 4 -- mixed update/question turn uses only WRITE
# ---------------------------------------------------------------------------

def test_mixed_turn_uses_only_write():
    client = ScriptedClient([
        with_calls(write_call(component_flows={'Water': 90})),
        final('Composition updated.'),
    ])
    messages = _base_messages() + [
        {'role': 'user', 'content': 'Water is 90 kmol/hr. What is the composition now?'},
    ]

    agent.ask(client, messages)

    assert _tool_result_names(messages) == ['update_binary_distillation_problem']
    assert client.calls == [True, False]


# ---------------------------------------------------------------------------
# Test 5 -- RESET then WRITE, and nothing more
# ---------------------------------------------------------------------------

def test_reset_then_write_then_stop():
    client = ScriptedClient([
        with_calls(reset_call()),
        with_calls(write_call(component_names=['Ethanol', 'Water'])),
        final('Starting a new problem: Ethanol and Water.'),
    ])
    messages = _base_messages() + [{'role': 'user', 'content': "let's start over with ethanol and water"}]

    agent.ask(client, messages)

    assert _tool_result_names(messages) == ['reset_workflow_session', 'update_binary_distillation_problem']
    assert client.calls == [True, True, False]


# ---------------------------------------------------------------------------
# Test 6 -- UPDATE plus READ in one response: UPDATE wins, READ suppressed
# ---------------------------------------------------------------------------

def test_update_plus_read_in_one_response_suppresses_read():
    client = ScriptedClient([
        with_calls(write_call(component_names=['Methanol', 'Water']), read_call()),
        final('Noted.'),
    ])
    messages = _base_messages() + [{'role': 'user', 'content': 'methanol and water'}]

    agent.ask(client, messages)

    assert _tool_result_names(messages) == ['update_binary_distillation_problem']


# ---------------------------------------------------------------------------
# Test 7 -- duplicate fingerprint is executed only once
# ---------------------------------------------------------------------------

def test_duplicate_fingerprint_detection():
    fp_seen = set()
    call = reset_call()
    assert agent._select_allowed_calls([call], reset_used=False, engineering_tool_used=False, fingerprints=fp_seen) == [call]

    fp_seen.add(agent._fingerprint(call))
    assert agent._select_allowed_calls([call], reset_used=False, engineering_tool_used=False, fingerprints=fp_seen) == []


def test_duplicate_reset_across_rounds_executes_once():
    client = ScriptedClient([
        with_calls(reset_call()),
        with_calls(reset_call()),  # model stubbornly resets again
        final('done'),
    ])
    messages = _base_messages() + [{'role': 'user', 'content': 'reset twice, oddly'}]

    agent.ask(client, messages)

    assert _tool_result_names(messages) == ['reset_workflow_session']
    assert len(client.calls) <= agent.MAX_TOOL_CALLS_PER_TURN + 1


# ---------------------------------------------------------------------------
# Test 8 -- hard call budget under pathological tool choices
# ---------------------------------------------------------------------------

def test_hard_call_budget_enforced():
    client = StubbornClient(max_calls=6)
    messages = _base_messages() + [{'role': 'user', 'content': 'keep going forever'}]

    agent.ask(client, messages)  # must return, not raise, and not exceed StubbornClient's budget

    executed = _tool_result_names(messages)
    assert len(executed) <= agent.MAX_TOOL_CALLS_PER_TURN


# ---------------------------------------------------------------------------
# tools/chopper/binary-distillation-incorrect-symbol-reading-issue.md --
# engineering-output grounding: the raw tool-result text actually handed to
# the model must carry QR/Qc's authoritative meaning, and the prompt must
# never itself encode the wrong definition.
# ---------------------------------------------------------------------------

def test_system_prompt_contains_engineering_output_grounding_rule():
    assert 'ENGINEERING OUTPUT GROUNDING RULE' in agent.SYSTEM_PROMPT
    assert 'would_calculate_details' in agent.SYSTEM_PROMPT
    # "reflux flow rate" appears only as the explicit wrong-answer example in
    # the grounding rule itself, never as an actual definition of QR/Qc.
    assert 'never as "reflux flow rate"' in agent.SYSTEM_PROMPT
    assert 'label="reboiler duty"' in agent.SYSTEM_PROMPT


def test_system_prompt_instructs_no_bare_symbol_enrichment():
    assert 'do not invent a definition' in agent.SYSTEM_PROMPT.lower()


def test_ready_for_calculation_tool_result_grounds_QR_as_reboiler_duty():
    """Step 19 regression: complete Case A (xD=0.9, xB=0.1, L0/D=2,
    optimum feed plate) via one WRITE call, then check the JSON actually
    appended to `messages` for the model -- not a hypothetical -- carries
    QR's authoritative meaning and never the wrong "reflux flow rate"."""
    client = ScriptedClient([
        with_calls(write_call(
            component_names=['Methanol', 'Water'],
            component_flows={'Methanol': 40, 'Water': 60},
            component_flow_units='kmol/hr',
            pressure_Pa=101325,
            feed_temperature_K=350.0,
            reflux_condition='saturated_liquid',
            xD=0.9, xB=0.1,
            external_reflux_ratio_LD=2.0,
            use_optimum_feed_plate=True,
        )),
        final('Your Case A design is fully specified.'),
    ])
    messages = _base_messages() + [{'role': 'user', 'content': 'design a methanol/water column'}]

    agent.ask(client, messages)

    tool_messages = [m for m in messages if isinstance(m, dict) and m.get('role') == 'tool']
    assert tool_messages, 'expected a tool result message in the conversation'
    content = tool_messages[-1]['content']
    assert '"status": "ready_for_calculation"' in content
    assert '"symbol": "QR"' in content
    assert '"label": "reboiler duty"' in content
    assert '"symbol": "Qc"' in content
    assert '"label": "condenser duty"' in content
    assert 'reflux flow rate' not in content


def test_legacy_bare_would_calculate_symbol_has_no_details_entry_mismatch():
    """Bare-symbol fallback (Step 16): whenever `would_calculate` carries a
    symbol, `would_calculate_details` must carry its grounded counterpart --
    so the model is never left needing to guess at a symbol that legitimately
    has a definition available."""
    client = ScriptedClient([
        with_calls(write_call(
            component_names=['Methanol', 'Water'],
            component_flows={'Methanol': 40, 'Water': 60},
            component_flow_units='kmol/hr',
            pressure_Pa=101325,
            feed_temperature_K=350.0,
            reflux_condition='saturated_liquid',
            xD=0.9, xB=0.1,
            external_reflux_ratio_LD=2.0,
            use_optimum_feed_plate=True,
        )),
        final('Your Case A design is fully specified.'),
    ])
    messages = _base_messages() + [{'role': 'user', 'content': 'design a methanol/water column'}]

    agent.ask(client, messages)

    tool_messages = [m for m in messages if isinstance(m, dict) and m.get('role') == 'tool']
    result = json.loads(tool_messages[-1]['content'])
    symbols_in_would_calculate = {s for s in result['would_calculate'] if s in ('D', 'B', 'QR', 'Qc', 'N')}
    symbols_with_details = {e['symbol'] for e in result['would_calculate_details']}
    assert symbols_in_would_calculate <= symbols_with_details
