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
Use the retrieved material below to answer the question. Prefer the structured
engineering rules when they directly apply; use the raw textbook passages for
context or when no rule covers the question. If nothing retrieved is relevant,
say so rather than guessing.

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
    for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
        if meta["type"] == "heuristic":
            heuristics.append(meta)
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
