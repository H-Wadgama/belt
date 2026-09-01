"""
Shared fake-Ollama-client helpers for testing the TurnIntent-based `ask()`
pipeline WITHOUT a running Ollama server --
tools/binary-distillation-issues-9-1-2026-fifth.md ("Do not rely on a live
LLM for transaction correctness").

`ask()` calls `client.chat(model=..., messages=..., format=<schema>,
think=False, options={...})` for interpretation (no `tools=`) and
`client.chat(model=..., messages=..., think=False)` for narration/
finalization (no `format=`, no `tools=`). `ScriptedClient` here accepts both
call shapes and returns canned responses off a fixed list, in order --
raising if `ask()` calls `.chat()` more times than scripted, the same
discipline the pre-Round-2 fakes used to prove a deterministically-routed
turn never reaches the model for a decision it shouldn't make.
"""
import json


class FakeMessage:
    def __init__(self, content=None):
        self.content = content
        self.role = 'assistant'
        self.tool_calls = None  # no native tool-calling channel is used any more


class FakeResponse:
    def __init__(self, message):
        self.message = message


def final(content='ok'):
    """A plain narration/finalization response (no `format=` on that call)."""
    return FakeResponse(FakeMessage(content=content))


def intent(updates=None, queries=None, action=None, version=1):
    """Build a TurnIntent dict -- the shape a real structured-output call
    would return as JSON `message.content`."""
    return {
        'version': version,
        'updates': updates or [],
        'queries': queries or [],
        'action': action,
    }


def intent_response(*args, **kwargs):
    """A structured-output interpretation response: `message.content` is the
    JSON-serialized TurnIntent. Pass either a ready-made intent dict or the
    same kwargs `intent()` accepts."""
    if args and isinstance(args[0], dict):
        payload = args[0]
    else:
        payload = intent(*args, **kwargs)
    return FakeResponse(FakeMessage(content=json.dumps(payload)))


def update(field, value, entity=None, units=None, subject=None, basis=None):
    return {'field': field, 'entity': entity, 'subject': subject, 'value': value, 'units': units, 'basis': basis}


def query(field, entity=None, subject=None, raw_reference=None):
    return {'field': field, 'entity': entity, 'subject': subject, 'raw_reference': raw_reference}


class ScriptedClient:
    """Returns responses from a fixed list, one per `.chat()` call --
    regardless of whether the call was an interpretation call (`format=`
    given) or a narration call (no `format=`). Raises if `ask()` calls
    `.chat()` more times than scripted."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []  # one dict per call: {'format': bool, 'tools': bool}

    def chat(self, model, messages, tools=None, think=False, format=None, options=None):
        self.calls.append({'format': format is not None, 'tools': tools is not None})
        if not self._responses:
            raise AssertionError('ScriptedClient ran out of scripted responses -- ask() called chat() more than expected')
        return self._responses.pop(0)


class StubbornInterpretationClient:
    """A pathological client that always proposes the SAME action on every
    interpretation call, regardless of context. Used to prove `ask()` still
    terminates in a bounded number of `.chat()` calls even when the model
    never varies its answer. Raises past `max_calls`, which would indicate
    an actual unbounded loop."""

    def __init__(self, action_name, max_calls=6):
        self.action_name = action_name
        self.max_calls = max_calls
        self.n_calls = 0

    def chat(self, model, messages, tools=None, think=False, format=None, options=None):
        self.n_calls += 1
        if self.n_calls > self.max_calls:
            raise AssertionError(f'ask() called chat() more than {self.max_calls} times -- looks unbounded')
        return intent_response(action={'name': self.action_name})
