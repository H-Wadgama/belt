"""
Natural-language front end for the separation-optimizer toolkit, backed by
a local Ollama model (default: qwen3:8b) with tool calling.

The user describes a separation in plain language; the model decides when
to call `optimize_separation` (see separation_tool.py), which builds a
BioSTEAM feed stream, runs `optimizer.optimize_reflux_ratio`'s reflux-ratio
sweep, and returns the cheapest feasible column design. The model then
explains the result back to the user.

Requires a running local Ollama server with the model pulled:
    ollama pull qwen3:8b

Run interactively:
    python separation_agent.py

Or run a single one-shot prompt (useful for scripting/testing):
    python separation_agent.py "Separate 80 kmol/hr methanol and 100 kmol/hr water, 99% pure methanol overhead"
"""
import json
import sys

import ollama

from separation_tool import TOOLS, TOOL_FUNCTIONS

MODEL = 'qwen3:8b'

SYSTEM_PROMPT = """You are a process engineering assistant with access to one tool, \
`optimize_separation`, which sizes and costs a binary distillation column by \
sweeping reflux ratio and returns the cheapest feasible design.

When the user asks you to design, size, cost, or optimize a separation between \
two components, call the tool rather than guessing numbers yourself. Feed \
component flows must use real chemical names (e.g. Water, Methanol, Ethanol, \
Glycerol) and a molar (kmol/hr) or mass (kg/hr) basis -- ask the user for \
missing flow rates or a target purity/recovery if they weren't given.

After the tool returns, summarize the result in plain language: state whether \
a feasible design was found, the winning reflux ratio (k), achieved purity or \
recovery, capital cost, and annualized cost. If no feasible design was found, \
say so and suggest widening the reflux ratio sweep or relaxing the target.
"""


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
    response = client.chat(model=MODEL, messages=messages, tools=TOOLS)
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
        response = client.chat(model=MODEL, messages=messages, tools=TOOLS)
        messages.append(response.message)

    return response.message.content


def run_repl():
    client = ollama.Client()
    messages = [{'role': 'system', 'content': SYSTEM_PROMPT}]

    print(f"Separation agent ready (model: {MODEL}). Type 'exit' to quit.")
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
