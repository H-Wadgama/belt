"""
Merged natural-language front end for BOTH separation toolkits in this
`tools/` folder, backed by a local Ollama model (default: qwen3:8b) with
tool calling.

This supersedes neither `chopper/separation_agent.py` nor `chopperRAG/query.py`
-- both remain independently runnable for standalone testing. This script
just registers both of their capabilities as tools on one agent:

    optimize_separation            (tools/chopper/separation_tool.py)
        builds a BioSTEAM feed stream, sweeps reflux ratio via
        optimizer.optimize_reflux_ratio, and returns the cheapest
        feasible column design.

    retrieve_separation_heuristics (new, wraps tools/chopperRAG/query.py)
        retrieves engineering rules of thumb and textbook passages about
        separation process selection/feasibility from the chopperRAG
        Chroma vector store.

The model decides which tool(s) to call each turn -- including, per the
SYSTEM_PROMPT below, checking heuristics before or alongside a sizing call
when the situation looks unusual (e.g. a vapor feed), so a heuristic
caveat and a costed design can show up together in one summary instead of
living in two disconnected tools.

Requires:
    - A running local Ollama server with qwen3:8b pulled (`ollama pull qwen3:8b`).
    - The chopperRAG Chroma collection seeded at least once:
        python tools/chopperRAG/seed_heuristics.py

Run interactively:
    python separation_rag_agent.py

Or run a single one-shot prompt:
    python separation_rag_agent.py "I have a vapor feed of 80 kmol/hr methanol and 100 kmol/hr water at 1 atm. Should I use ordinary distillation, and if so what would a 99% pure methanol column cost?"
"""
import json
import sys
from pathlib import Path

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE / 'chopper'))
sys.path.insert(0, str(_HERE / 'chopperRAG'))

import chromadb
import ollama
from sentence_transformers import SentenceTransformer

import config as rag_config
import query as rag_query
from separation_tool import TOOLS as SEPARATION_TOOLS, TOOL_FUNCTIONS as SEPARATION_TOOL_FUNCTIONS

MODEL = rag_config.LLM_MODEL

_embedder = None
_collection = None


def _init_rag():
    """Lazily load the embedder and open the Chroma collection once, before the first tool call needs them."""
    global _embedder, _collection
    if _embedder is None:
        _embedder = SentenceTransformer(rag_config.EMBED_MODEL)
        chroma = chromadb.PersistentClient(path=rag_config.CHROMA_DIR)
        _collection = chroma.get_or_create_collection(rag_config.COLLECTION_NAME)


def retrieve_separation_heuristics(question: str, top_k: int = 8) -> dict:
    """Retrieve engineering rules of thumb and textbook passages about separation process selection and design, relevant to a natural-language question.

    Searches a curated knowledge base of separation-process heuristics (e.g.
    which separation technique fits a given feed phase, how to sequence a
    multi-column train, when ordinary distillation is or isn't feasible) and
    returns the most relevant structured rules plus supporting textbook text.
    This tool does not perform any calculation or sizing itself -- use it to
    sanity-check an approach (e.g. before or after calling
    optimize_separation), not as a substitute for it.

    Args:
        question: A natural-language question about separation process
            selection, sequencing, or feasibility, e.g. "What separation
            technique should I use for a vapor feed?". Phrase it as a
            question about the engineering situation, not specific chemical
            names or flow rates.
        top_k: Maximum number of heuristics to retrieve. Default 8.

    Returns:
        A dict with 'heuristics' (list of matched rules, each with
        'category', 'condition', 'principle', 'design_implication', and for
        equation-type entries an 'equation' string that is NOT evaluated --
        read it, don't expect a numeric result), 'raw_chunks' (list of
        {'page', 'text'} supporting passages), and 'n_heuristics'/
        'n_raw_chunks' counts. Ranked nearest-first; an empty 'heuristics'
        list means no structured rule matched closely -- fall back to
        'raw_chunks' or say nothing relevant was found.
    """
    heuristics, raw_chunks = rag_query.retrieve(_collection, _embedder, question, top_k=top_k)
    return {
        'heuristics': [
            {**{k: v for k, v in h.items() if k != '_distance'}, 'distance': round(h['_distance'], 4)}
            for h in heuristics
        ],
        'raw_chunks': [{'page': page, 'text': text} for page, text in raw_chunks],
        'n_heuristics': len(heuristics),
        'n_raw_chunks': len(raw_chunks),
    }


TOOLS = SEPARATION_TOOLS + [retrieve_separation_heuristics]
TOOL_FUNCTIONS = {**SEPARATION_TOOL_FUNCTIONS, 'retrieve_separation_heuristics': retrieve_separation_heuristics}

SYSTEM_PROMPT = """You are a process engineering assistant with access to two tools:

`optimize_separation` -- sizes and costs a binary distillation column by \
sweeping reflux ratio and returns the cheapest feasible design.

`retrieve_separation_heuristics` -- looks up engineering rules of thumb and \
textbook guidance about separation process selection, sequencing, and \
feasibility. It does not size or cost anything.

## Using optimize_separation

When the user asks you to design, size, cost, or optimize a separation between \
two components, call the tool rather than guessing numbers yourself. Feed \
component flows must use real chemical names (e.g. Water, Methanol, Ethanol, \
Glycerol) and a molar (kmol/hr) or mass (kg/hr) basis -- ask the user for \
missing flow rates or a target purity/recovery if they weren't given.

This tool currently only supports strictly binary feeds -- the feed must \
have exactly 2 components with nonzero flow, and light_key/heavy_key must \
be those same two components. If the user describes a feed with three or \
more components, do NOT call the tool with only two of them and drop the \
rest -- tell the user that ternary/multicomponent feed support isn't \
available yet (it's planned for a future release) and ask them to narrow \
the request to a true two-component feed instead.

Every tool result includes a 'key_selection' field, which will be null/valid \
for any feed this tool accepts (it only becomes meaningful once \
multicomponent feeds are supported). If a call is ever rejected with an \
error about too many nonzero-flow components, that confirms the feed was \
not binary -- explain that to the user rather than retrying with a \
different light_key/heavy_key pair.

## Using retrieve_separation_heuristics

Call this tool -- before, alongside, or after a sizing call -- whenever the \
situation looks like it might not be a plain, ordinary-distillation-appropriate \
split. In particular, consider it when:
- the user mentions a vapor feed, a heat-sensitive/thermally unstable, \
corrosive, or reactive component, or an azeotrope;
- the user asks a "what should I use" / "is this a good approach" style \
question rather than requesting a specific numeric design;
- a sizing call comes back infeasible for a reason `key_selection['warning']` \
doesn't explain, and you want to sanity-check the overall approach rather \
than just the reflux ratio.

It is NOT required for a plain, ordinary-distillation-appropriate sizing \
request (e.g. "separate 80 kmol/hr methanol and 100 kmol/hr water, 99% pure \
methanol overhead") -- don't call it reflexively on every turn.

When you get results back, first filter for relevance before writing \
anything: do not mention a retrieved heuristic merely because it came back in \
the results. Ignore any heuristic or raw_chunk that doesn't actually help \
answer the question, even if it's ranked highly. If both 'n_heuristics' and \
'n_raw_chunks' are 0, or nothing that came back is relevant, say plainly that \
nothing relevant was found rather than guessing.

### Relevance tiers

For every heuristic you keep, classify it by whether its 'condition' is \
actually established by what the user told you:

- **Directly triggered**: the condition is explicitly stated or clearly \
implied by the given facts (e.g. a numeric relative volatility below 1.05, a \
named heat-sensitive/thermally unstable/corrosive/reactive component, an \
explicitly vapor feed). State its principle and design_implication as an \
active finding.
- **Conditionally relevant**: the heuristic bears on the situation, but its \
own condition has NOT been established yet (e.g. "ordinary distillation \
produces a high bottoms temperature" when no bottoms temperature has been \
given or computed). Don't state its implication as an established fact -- \
phrase it as a check that still needs to be performed if the design \
proceeds, not as a conclusion already reached.

A single question can, and often should, trigger multiple heuristics at once, \
operating at different levels: technique/key selection, sequencing, and \
feasibility checks. Do NOT collapse this into one "winning" heuristic -- \
synthesize across levels into one coherent answer. A useful order is: \
directly-triggered selection/feasibility findings first, then sequencing \
implications, then remaining conditionally relevant checks.

**Worked example** -- question: "Relative volatility is 1.03 and the \
compound is heat sensitive." Retrieved heuristics might include the \
relative-volatility threshold heuristic (directly triggered: 1.03 < 1.05), \
the early-removal/heat-sensitive sequencing heuristic (directly triggered: a \
heat-sensitive component is explicitly named), the bottoms-temperature \
decomposition heuristic (conditionally relevant: heat sensitivity means this \
SHOULD be checked, but no bottoms temperature has been established, so its \
condition isn't met yet), and possibly an unrelated equation heuristic about \
ideal vapor/liquid solutions (not relevant -- drop it). A good synthesized \
answer: "A relative volatility of 1.03 is below the heuristic threshold of \
1.05 for ordinary distillation, so the proposed split may be difficult. \
Because the component is heat-sensitive, it should also be prioritized for \
removal early in the separation sequence. If ordinary distillation is still \
considered, the expected bottoms temperature should be checked against the \
component's thermal stability to ensure decomposition does not occur."

Never introduce an engineering recommendation that isn't supported by the \
retrieved context. If a retrieved heuristic has an 'equation' field, treat it \
as reference text only -- never claim you evaluated it numerically, that is \
not something either tool does.

## Summarizing for the user

After tool calls return, summarize in plain language: state whether a \
feasible design was found, the winning reflux ratio (k), achieved purity or \
recovery, capital cost, and annualized cost. If no feasible design was found \
AND key_selection['warning'] is null, say so and suggest widening the reflux \
ratio sweep or relaxing the target. If you also consulted \
retrieve_separation_heuristics, weave the directly triggered findings and any \
conditionally relevant checks into the SAME summary (per the relevance-tier \
guidance above) rather than presenting them separately or listing every \
heuristic that was retrieved -- e.g. note that the feed is a vapor and \
heuristics suggest ordinary distillation may not be the default choice, even \
while reporting the costed design the user asked for.
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
    _init_rag()
    client = ollama.Client()
    messages = [{'role': 'system', 'content': SYSTEM_PROMPT}]

    print(f"Separation + RAG agent ready (model: {MODEL}). Type 'exit' to quit.")
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
        _init_rag()
        client = ollama.Client()
        messages = [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': ' '.join(sys.argv[1:])},
        ]
        print(ask(client, messages))
    else:
        run_repl()
