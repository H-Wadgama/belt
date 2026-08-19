# Separation-heuristics RAG PoC

Dual-storage RAG: every textbook chunk is stored raw, and any engineering
heuristics Qwen extracts from it are stored as separate, linked records in
the same Chroma collection. One query returns a mix of both; heuristic hits
get their parent chunk hydrated automatically.

## Setup

```bash
pip install -r requirements.txt
```

Make sure your local Qwen server is running and reachable at the URL in
`config.py` (defaults assume Ollama on `localhost:11434`). Adjust
`LLM_MODEL` to match the tag you've pulled/served.

## 1. Ingest a page range

Pick a section with a good density of design heuristics (purity
requirements, recovery vs. recycle, thermal sensitivity, etc.) — 10-20
pages is enough to validate the approach before running the whole book.

```bash
python ingest.py --pdf textbook.pdf --start-page 120 --end-page 140
```

Watch the printed extractions as it runs. If you see it inventing a
heuristic from every paragraph (including plain descriptive text), tighten
`EXTRACTION_PROMPT` in `ingest.py`. If it's missing heuristics you know are
there, check whether `CHUNK_TARGET_WORDS` is splitting them mid-thought —
paragraphs describing one rule of thumb sometimes span more than 250 words.

## 2. Query

```bash
python query.py --test
```

This runs the three PoC questions and prints, for each: what got
retrieved (heuristics + hydrated raw chunks) and Qwen's answer built from
that context. Read the retrieved heuristics list first — that's the part
worth judging for precision, independent of how well the final answer
reads.

Ask anything ad hoc:

```bash
python query.py "What should I consider for a heat-sensitive compound?"
```

## What to check before scaling to the full book

- **Precision on the structured side**: for each test question, is the
  *right* heuristic in the top-k, not just something plausible-sounding?
  This is the part that degrades quietly at scale if it's weak now.
- **Extraction false-positive rate**: spot-check a sample of chunks with
  zero heuristics extracted — confirm they really don't contain one,
  rather than the model just declining under ambiguity.
- **Chunk boundary cuts**: if a heuristic's condition and design
  implication land in different chunks, extraction quality drops. Bump
  `CHUNK_OVERLAP_WORDS` or switch to heading-aware chunking if this shows
  up often.

## Scaling past the PoC

Once this validates on your 10-20 pages: batch the `ingest.py` loop over
the whole book (this is the main thing that needs the "iteratively build
and review" treatment, not blind bulk-run), consider hybrid retrieval
(BM25 + embeddings) if the full book has many pages with near-duplicate
phrasing, and consider `LangChain`'s `ParentDocumentRetriever` /
`LlamaIndex`'s auto-merging retriever if you want the parent-child pattern
without maintaining it by hand.

This script only builds the "RAG retrieval" box in your diagram. Wiring
retrieved heuristics into an actual `design_implication -> BioSTEAM call`
step is a separate tool-use/function-calling layer on top of this.
