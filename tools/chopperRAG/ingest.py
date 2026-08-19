"""
Ingestion pipeline:
  PDF pages -> paragraph-aware chunks -> Qwen extraction -> dual storage in Chroma

Every chunk is stored as a raw_chunk record regardless of extraction outcome.
Zero or more heuristic records are stored per chunk, each linked back to its
parent chunk via parent_chunk_id.

Usage:
    python ingest.py --pdf textbook.pdf --start-page 120 --end-page 140
"""
import argparse
import re
from pathlib import Path

import chromadb
import fitz  # PyMuPDF
from openai import OpenAI
from sentence_transformers import SentenceTransformer

import config
from schema import ExtractionResult

EXTRACTION_PROMPT = """You are reading a chemical engineering separations textbook.
Extract every design heuristic or rule of thumb from the passage below - the kind of
judgment an engineer would use to decide HOW to configure or select a separation process,
not just factual/descriptive content.

For each heuristic found, fill in:
- category: a short tag (e.g. separation_objective, purity_target, thermal_sensitivity, cost_tradeoff, feed_composition)
- condition: the scenario/context the heuristic applies under
- principle: the rule of thumb itself
- design_implication: the concrete consequence for process selection or design

If the passage contains no such heuristic (e.g. it's pure background, definitions, or math
derivation with no judgment call), return an empty list. Do not invent heuristics that
aren't clearly supported by the text.

Passage:
\"\"\"
{chunk}
\"\"\"

Respond with ONLY a JSON object matching this shape:
{{"heuristics": [{{"category": "...", "condition": "...", "principle": "...", "design_implication": "..."}}]}}
"""


def extract_page_chunks(pdf_path: str, start_page: int, end_page: int):
    """Yield (page_number, chunk_text) using paragraph-aware packing with overlap."""
    doc = fitz.open(pdf_path)
    for page_num in range(start_page - 1, end_page):  # fitz is 0-indexed
        page = doc[page_num]
        text = page.get_text("text")
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

        buf, buf_words = [], 0
        for para in paragraphs:
            words = para.split()
            if buf_words + len(words) > config.CHUNK_TARGET_WORDS and buf:
                yield page_num + 1, " ".join(buf)
                overlap = " ".join(buf).split()[-config.CHUNK_OVERLAP_WORDS:]
                buf, buf_words = list(overlap), len(overlap)
            buf.extend(words)
            buf_words += len(words)
        if buf:
            yield page_num + 1, " ".join(buf)
    doc.close()


def call_qwen_extraction(client: OpenAI, chunk_text: str) -> ExtractionResult:
    """Ask Qwen to extract heuristics, with pydantic validation + one retry on failure."""
    prompt = EXTRACTION_PROMPT.format(chunk=chunk_text)
    for attempt in range(2):
        try:
            resp = client.chat.completions.create(
                model=config.LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},  # widest compatibility across backends
                temperature=0,
            )
            raw = resp.choices[0].message.content
            return ExtractionResult.model_validate_json(raw)
        except Exception as e:
            if attempt == 0:
                continue  # one silent retry
            print(f"  [extraction failed after retry: {e}] -> treating as no heuristics")
            return ExtractionResult(heuristics=[])


def render_heuristic_for_embedding(h) -> str:
    """Turn structured JSON into a natural-language sentence for embedding.
    Embedding models are trained on prose, not JSON syntax, so this matters."""
    return f"When {h.condition}: {h.principle}. Design implication: {h.design_implication}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--start-page", type=int, required=True)
    ap.add_argument("--end-page", type=int, required=True)
    args = ap.parse_args()

    llm = OpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY)
    embedder = SentenceTransformer(config.EMBED_MODEL)
    chroma = chromadb.PersistentClient(path=config.CHROMA_DIR)
    collection = chroma.get_or_create_collection(config.COLLECTION_NAME)

    source_file = Path(args.pdf).stem.replace(" ", "_")
    n_chunks, n_heuristics = 0, 0

    for page_num, chunk_text in extract_page_chunks(args.pdf, args.start_page, args.end_page):
        chunk_id = f"chunk_{source_file}_{page_num}_{n_chunks}"
        n_chunks += 1

        # 1. Always store the raw chunk, regardless of whether extraction finds anything.
        #    upsert (not add) so re-running ingestion while you tune the prompt is safe.
        collection.upsert(
            ids=[chunk_id],
            documents=[chunk_text],
            embeddings=[embedder.encode(chunk_text).tolist()],
            metadatas=[{
                "type": "raw_chunk",
                "page": page_num,
                "source_file": source_file,
            }],
        )

        # 2. Extract structured heuristics from this chunk via Qwen.
        result = call_qwen_extraction(llm, chunk_text)
        for h in result.heuristics:
            heur_id = f"heur_{source_file}_{page_num}_{n_heuristics}"
            n_heuristics += 1
            embed_text = render_heuristic_for_embedding(h)
            collection.upsert(
                ids=[heur_id],
                documents=[embed_text],
                embeddings=[embedder.encode(embed_text).tolist()],
                metadatas=[{
                    "type": "heuristic",
                    "parent_chunk_id": chunk_id,
                    "page": page_num,
                    "source_file": source_file,
                    "category": h.category,
                    "condition": h.condition,
                    "principle": h.principle,
                    "design_implication": h.design_implication,
                }],
            )
            print(f"  page {page_num}: extracted heuristic [{h.category}] {h.principle[:70]}")

    print(f"\nDone. {n_chunks} raw chunks, {n_heuristics} heuristics stored in "
          f"'{config.COLLECTION_NAME}' at {config.CHROMA_DIR}")


if __name__ == "__main__":
    main()
