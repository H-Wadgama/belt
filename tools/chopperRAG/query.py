"""
Retrieval + qualitative test harness.

Usage:
    python query.py "What factors should affect whether I require 99.9% purity?"
    python query.py --test   # runs the three PoC test questions
"""
import argparse
import json

import chromadb
from openai import OpenAI
from sentence_transformers import SentenceTransformer

import config

TEST_QUESTIONS = [
    "What factors should affect whether I require 99.9% purity?",
    "How should recovery for recycle differ from final-product purification?",
    "What should I consider for a heat-sensitive compound?",
]

ANSWER_PROMPT = """You are helping select and configure a separation process.
Answer the question using only the retrieved context that is directly
relevant to it. Do not mention a retrieved rule merely because it was
provided -- ignore anything that doesn't help answer this specific question,
even if it's highly ranked. If nothing retrieved is relevant, say so plainly
rather than guessing.

For each rule you do use, judge whether its condition is actually established
by the question:
- Directly triggered: the condition is explicitly stated or clearly implied
  by the question (e.g. a stated relative volatility, a named heat-sensitive/
  corrosive/reactive component). State its principle as an active finding.
- Conditionally relevant: the rule bears on the situation but its own
  condition hasn't been established yet (e.g. a rule about high bottoms
  temperature when no bottoms temperature is known or given). Phrase it as a
  check still to be performed, not as a conclusion already reached.

A question can trigger multiple rules at once, operating at different levels
-- selection, sequencing, feasibility. Don't reduce this to one "winning"
rule; synthesize across levels into one coherent answer. For example, given
"Relative volatility is 1.03 and the compound is heat sensitive": "A relative
volatility of 1.03 is below the heuristic threshold of 1.05 for ordinary
distillation, so the proposed split may be difficult. Because the component
is heat-sensitive, it should also be prioritized for removal early in the
separation sequence. If ordinary distillation is still considered, the
expected bottoms temperature should be checked against the component's
thermal stability to ensure decomposition does not occur."

Do not introduce engineering recommendations that aren't supported by the
retrieved context.

Structured engineering rules:
{heuristics}

Raw textbook passages:
{raw_chunks}

Question: {question}
"""


def retrieve(collection, embedder, question: str, top_k: int = config.TOP_K):
    q_emb = embedder.encode(question).tolist()
    results = collection.query(query_embeddings=[q_emb], n_results=top_k)

    heuristics, raw_chunks = [], []
    for doc, meta, dist in zip(results["documents"][0], results["metadatas"][0], results["distances"][0]):
        if meta["type"] == "heuristic":
            heuristics.append({**meta, "_distance": dist})
        else:
            raw_chunks.append((meta.get("page"), doc))

    # Hydrate: pull in the parent raw chunk for each retrieved heuristic,
    # even if that chunk didn't make the top-k on its own merit.
    parent_ids = {h["parent_chunk_id"] for h in heuristics}
    if parent_ids:
        parents = collection.get(ids=list(parent_ids))
        for doc, meta in zip(parents["documents"], parents["metadatas"]):
            raw_chunks.append((meta.get("page"), doc))

    return heuristics, raw_chunks


def format_heuristics(heuristics) -> str:
    if not heuristics:
        return "(none retrieved)"
    out = []
    for h in heuristics:
        entry = {
            "distance": round(h["_distance"], 4),
            "category": h["category"],
            "condition": h["condition"],
            "principle": h["principle"],
            "design_implication": h["design_implication"],
        }
        if h.get("heuristic_type") == "equation":
            entry["equation"] = h.get("equation", "")
            required_variables = h.get("required_variables", "")
            entry["required_variables"] = required_variables.split(",") if required_variables else []
        out.append(json.dumps(entry, indent=2))
    return "\n".join(out)


def format_raw_chunks(raw_chunks) -> str:
    if not raw_chunks:
        return "(none retrieved)"
    seen, out = set(), []
    for page, text in raw_chunks:
        key = (page, text[:50])
        if key in seen:
            continue
        seen.add(key)
        out.append(f"[p.{page}] {text}")
    return "\n\n".join(out)


def answer(llm, question: str, heuristics, raw_chunks) -> str:
    prompt = ANSWER_PROMPT.format(
        heuristics=format_heuristics(heuristics),
        raw_chunks=format_raw_chunks(raw_chunks),
        question=question,
    )
    resp = llm.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    return resp.choices[0].message.content


def run_one(collection, embedder, llm, question: str):
    print(f"\n{'=' * 80}\nQ: {question}\n{'=' * 80}")
    heuristics, raw_chunks = retrieve(collection, embedder, question)
    print(f"\n-- retrieved {len(heuristics)} heuristic(s), {len(raw_chunks)} raw chunk(s) --")
    print(format_heuristics(heuristics))
    print(f"\nANSWER:\n{answer(llm, question, heuristics, raw_chunks)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="?", default=None)
    ap.add_argument("--test", action="store_true", help="run the three PoC test questions")
    args = ap.parse_args()

    llm = OpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY)
    embedder = SentenceTransformer(config.EMBED_MODEL)
    chroma = chromadb.PersistentClient(path=config.CHROMA_DIR)
    collection = chroma.get_or_create_collection(config.COLLECTION_NAME)

    if args.test:
        for q in TEST_QUESTIONS:
            run_one(collection, embedder, llm, q)
    elif args.question:
        run_one(collection, embedder, llm, args.question)
    else:
        print("Provide a question, or pass --test to run the PoC test set.")


if __name__ == "__main__":
    main()
