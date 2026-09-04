"""
Natural-language front end for the multicomponent (>=3 component)
feed-phase intake agent, backed by a local Ollama model (default:
qwen3:8b) with tool calling.

See ../multicomponent-distillation-context.md for the domain vocabulary
and scope, and
../multicomponent-distillation-feed-phase-plan.md for the implementation
plan this agent follows. This agent exposes exactly one intake-and-
calculate tool (`update_multicomponent_feed`, in
`multicomponent_feed_tool.py`) plus a session reset -- it deliberately
does NOT reproduce the binary chopper toolkit's case-routing, design-
assessment, RAG, transaction-diagnostics, or calculation-progress
machinery. The model's only jobs are: record explicit facts from the
user's message as tool arguments; relay the tool's one pending question
verbatim; and, once the tool reports `complete: True`, report only the
phase and molar vapor/liquid fractions it returned.

Requires a running local Ollama server with the model pulled:
    ollama pull qwen3:8b

Run interactively:
    python multicomponent_distillation_agent.py

Or run a single one-shot prompt (useful for scripting/testing):
    python multicomponent_distillation_agent.py "hello"
"""
import json
import sys

import ollama

from multicomponent_feed_tool import TOOL_FUNCTIONS, TOOLS

MODEL = 'qwen3:8b'

SYSTEM_PROMPT = """You are a feed-phase intake assistant for multicomponent \
(three or more component) distillation feeds. You have exactly one \
engineering tool, `update_multicomponent_feed`, plus \
`reset_multicomponent_feed_session`.

Every feed you handle has AT LEAST THREE nonzero-flow components -- if the \
user describes a feed with fewer than three components, say this agent is \
for multicomponent feeds only and does not handle two-component feeds.

## Recording facts

On every turn, record every explicit fact the CURRENT user message states \
by calling `update_multicomponent_feed` with only those fields. The tool \
REMEMBERS everything given in earlier calls -- never repeat an already- \
known value just to resend it, and never invent, guess, or default a \
value the user has not stated. In particular:
- Never assume the feed's thermal condition (temperature, enthalpy, or \
quality) -- never default it to the bubble point.
- Never guess whether a stated composition is on a mole or mass basis.
- Never guess a unit for a flow, pressure, temperature, or enthalpy value.
- Never invent a component that was not named.

## Asking for missing information

Every call to `update_multicomponent_feed` returns either a `pending_request` \
(when something is still missing or invalid) or a final result (when the \
feed is complete). When `pending_request` is present, ask the user \
EXACTLY that question (`pending_request['question']`), listing \
`pending_request['choices']` if present -- do not invent a different \
question, do not ask about something not named there, and do not ask \
about more than one missing item at a time.

If the tool returns `conflicts` or `validation_errors`, relay the message \
to the user and ask them to resolve it -- do not pick a value yourself.

## Calling the tool again

When the user answers a question you asked, your next action must be a \
real call to `update_multicomponent_feed` with just the new field(s) they \
gave -- never just repeat their answer back as text.

## Never determine phase yourself

Never state, guess, or imply the feed's equilibrium phase, vapor \
fraction, or liquid fraction from general chemistry knowledge or from the \
numbers you can see -- that is decided entirely by the tool's deterministic \
calculation. Only report a phase/fraction result the tool actually \
returned.

## Reporting the final result

Once `update_multicomponent_feed` returns `complete: True`, report ONLY \
the phase (`liquid`, `vapor`, or `vapor_liquid`) and the molar vapor and \
liquid fractions it returned. Do not route the feed, select a separation, \
recommend a design, or perform any distillation calculation beyond this -- \
this agent's output boundary stops at the equilibrium phase.

## Starting over

Call `reset_multicomponent_feed_session` ONLY when the user explicitly \
switches to a different, unrelated feed -- never between ordinary \
follow-up turns that are still refining the same feed."""


def _run_tool_call(call):
    fn = TOOL_FUNCTIONS.get(call.function.name)
    if fn is None:
        return {'error': f'Unknown tool: {call.function.name}'}
    try:
        return fn(**call.function.arguments)
    except Exception as e:
        return {'error': f'{type(e).__name__}: {e}'}


def ask(client, messages):
    """Send `messages` to the model, resolving any tool calls, and return the final assistant message text."""
    response = client.chat(model=MODEL, messages=messages, tools=TOOLS, think=False)
    messages.append(response.message)

    while response.message.tool_calls:
        for call in response.message.tool_calls:
            print(f"  [calling {call.function.name}({call.function.arguments})]")
            result = _run_tool_call(call)
            messages.append({
                'role': 'tool',
                'tool_name': call.function.name,
                'content': json.dumps(result),
            })
        response = client.chat(model=MODEL, messages=messages, tools=TOOLS, think=False)
        messages.append(response.message)

    return response.message.content


def run_repl():
    client = ollama.Client()
    messages = [{'role': 'system', 'content': SYSTEM_PROMPT}]

    print(f"Multicomponent distillation agent ready (model: {MODEL}). Type 'exit' to quit.")
    while True:
        try:
            user_input = input('\nYou: ').strip()
        except (EOFError, KeyboardInterrupt):
            break
        if user_input.lower() in ('exit', 'quit'):
            break
        if not user_input:
            continue

        messages.append({'role': 'user', 'content': user_input})
        reply = ask(client, messages)
        print(f"\nAssistant: {reply}")


if __name__ == '__main__':
    if len(sys.argv) > 1:
        # One-shot mode: single prompt from argv, print the reply, exit.
        client = ollama.Client()
        messages = [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': ' '.join(sys.argv[1:])},
        ]
        print(ask(client, messages))
    else:
        run_repl()
