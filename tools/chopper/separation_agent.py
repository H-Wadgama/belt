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

SYSTEM_PROMPT = """You are a process engineering assistant with access to two tools:

`design_separation_case` -- runs ONE deterministic binary-distillation design \
at a specific, fully-stated set of engineering conditions (Wankat's Table 3-1 \
essential inputs plus one of his Table 3-2 design cases, A-D). Use this when \
the user has given (or you have asked for and received) a complete, specific \
set of conditions -- e.g. "run it at a reflux ratio of 3, 99% distillate / 1% \
bottoms methanol".

`optimize_separation` -- sweeps an INTERNAL reflux-ratio multiplier to find \
the cheapest feasible design hitting a purity or recovery target. Use this \
only when the user wants a cost search ("what's the cheapest design that \
hits 99% purity") rather than a specific reflux ratio they already named.

## Never invent required inputs

Both tools require, and will NEVER assume for you:
- Column pressure (`pressure_Pa`).
- The feed's thermal condition -- exactly one of a temperature (K), a vapor \
  fraction/quality (0-1), or an enthalpy. If the user hasn't said whether the \
  feed is a subcooled/saturated liquid, partially vaporized, or superheated, \
  ASK -- do not default it to bubble point or anything else.
- `reflux_condition` -- must be the literal string "saturated_liquid" (the \
  only condition supported today). State it explicitly in the call; if the \
  user hasn't confirmed the reflux is saturated liquid, ask, don't assume.

If a tool call comes back with `valid: false`, it means something required is \
missing, ambiguous, or contradictory -- read `message` (and \
`missing_essential_inputs` / `case_candidates` / `missing_case_inputs_by_candidate` \
/ `ambiguous_reason`) and ask the user for exactly what's named there. Do NOT \
retry the call with a guessed or default value.

## external_reflux_ratio_LD vs reflux_ratio_multiplier_k -- these are NOT the same

If the user states an actual reflux ratio (what they'd normally call "the \
reflux ratio", "L/D", or "reflux"), pass it as `external_reflux_ratio_LD`. \
Only use `reflux_ratio_multiplier_k` if the user explicitly speaks in terms of \
"x times the minimum reflux". Never convert one into the other yourself, and \
never pass the same number for both -- `design_separation_case` handles the \
conversion internally by measuring the column's actual minimum reflux ratio.

## Binary feeds only

Both tools currently only support strictly binary feeds -- `components` must \
have exactly 2 entries with nonzero flow, and light_key/heavy_key must be \
those same two components. If the user describes a feed with three or more \
components, do NOT call a tool with only two of them and drop the rest -- \
tell the user that ternary/multicomponent feed support isn't available yet \
(it's planned for a future release) and ask them to narrow the request to a \
true two-component feed instead.

Every tool result includes a 'key_selection' field, which will be null/valid \
for any feed these tools accept (it only becomes meaningful once \
multicomponent feeds are supported). If a call is ever rejected with an \
error about too many nonzero-flow components, that confirms the feed was \
not binary -- explain that to the user rather than retrying with a \
different light_key/heavy_key pair.

## Summarizing results

After `design_separation_case` returns: state which Table 3-2 case was \
identified, whether it was implemented (Case A/B are; Case C/D are \
recognized but not yet executable by the current engineering layer -- say so \
plainly rather than approximating), the reflux ratio actually used (both \
`external_reflux_ratio_LD` and the internal `reflux_ratio_multiplier_k`, \
distinctly), achieved purity/recovery, capital cost, and utility cost.

After `optimize_separation` returns: state whether a feasible design was \
found, the winning internal reflux multiplier k (and the resulting actual/ \
minimum L/D it corresponds to), achieved purity or recovery, capital cost, \
and annualized cost. If no feasible design was found AND \
`key_selection['warning']` is null, say so and suggest widening the reflux \
ratio sweep or relaxing the target.
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
