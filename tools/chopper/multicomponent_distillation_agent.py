"""
Natural-language front end for a future multicomponent-distillation toolkit,
backed by a local Ollama model (default: qwen3:8b) with tool calling.

This is a bare scaffold, mirroring the shape of separation_agent.py -- no
tools are wired in yet, so the model can only chat, it cannot design or
size anything. Tools will be added once the multicomponent engineering
layer exists.

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

TOOLS = []
TOOL_FUNCTIONS = {}

MODEL = 'qwen3:8b'

SYSTEM_PROMPT = """You are a process engineering assistant for multicomponent \
distillation problems. You do not have any tools available yet -- this is a \
placeholder front end. Say so plainly if asked to design or size a \
separation."""


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
