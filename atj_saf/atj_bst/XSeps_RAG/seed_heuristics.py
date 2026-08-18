"""
Hand-seed a small number of manually-verified heuristics directly into the
Chroma store, bypassing the Qwen extraction step in ingest.py.

Useful for testing retrieval quality against ground-truth heuristics before
trusting the LLM extraction pipeline on the rest of the book.

Usage:
    python seed_heuristics.py
"""
import chromadb
from sentence_transformers import SentenceTransformer

import config
from schema import Heuristic

SEED_HEURISTICS = [
    Heuristic(
        category="separation_technique_selection",
        condition="feed is a vapor, or is readily converted to a vapor",
        principle=(
            "ordinary distillation is not the default choice for a vapor feed; "
            "a specific set of vapor-phase separation techniques applies instead"
        ),
        design_implication=(
            "consider partial condensation, distillation under cryogenic conditions, "
            "gas absorption, gas adsorption, gas permeation with a membrane, "
            "or desublimation - not an ambient-condition BinaryDistillation column"
        ),
    ),
    Heuristic(
        category="separation_technique_selection",
        condition="feed is a liquid, or is readily converted to a liquid",
        principle=(
            "a broad set of liquid-phase separation techniques becomes applicable, "
            "including standard distillation and its variants"
        ),
        design_implication=(
            "consider flash/partial vaporization, ordinary distillation, stripping, "
            "extractive distillation, azeotropic distillation, liquid-liquid extraction, "
            "crystallization, liquid adsorption, dialysis/reverse osmosis/ultrafiltration/"
            "pervaporation with a membrane, or supercritical extraction"
        ),
    ),
]

# Tag these by source so you can tell hand-seeded ground truth apart from
# whatever ingest.py later extracts automatically from the same book.
SOURCE_TAG = "seader_separation_process_principles_ch9"


def render_heuristic_for_embedding(h: Heuristic) -> str:
    return f"When {h.condition}: {h.principle}. Design implication: {h.design_implication}"


def main():
    embedder = SentenceTransformer(config.EMBED_MODEL)
    chroma = chromadb.PersistentClient(path=config.CHROMA_DIR)
    collection = chroma.get_or_create_collection(config.COLLECTION_NAME)

    for i, h in enumerate(SEED_HEURISTICS):
        heur_id = f"heur_seed_{SOURCE_TAG}_{i}"
        embed_text = render_heuristic_for_embedding(h)
        collection.upsert(
            ids=[heur_id],
            documents=[embed_text],
            embeddings=[embedder.encode(embed_text).tolist()],
            metadatas=[{
                "type": "heuristic",
                "parent_chunk_id": "",  # hand-seeded, no source chunk on file
                "source_file": SOURCE_TAG,
                "category": h.category,
                "condition": h.condition,
                "principle": h.principle,
                "design_implication": h.design_implication,
            }],
        )
        print(f"seeded: [{h.category}] {h.principle[:70]}")

    print(f"\nDone. {len(SEED_HEURISTICS)} hand-seeded heuristics added to "
          f"'{config.COLLECTION_NAME}' at {config.CHROMA_DIR}")


if __name__ == "__main__":
    main()