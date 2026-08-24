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

DEFAULT_SOURCE_TAG = "seader_ch9"  # Seader's Separation Process Principles, ch. 9

# Each entry pairs a Heuristic with the source it actually came from. Two
# different textbooks are both cited as "ch. 9" here (Seader's *Separation
# Process Principles* vs. Seider et al.'s *Product and Process Design
# Principles*) so the source tag is set explicitly per-heuristic rather than
# assumed from one module-level constant.
SEED_HEURISTICS = [
    (DEFAULT_SOURCE_TAG, Heuristic(
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
    )),
    (DEFAULT_SOURCE_TAG, Heuristic(
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
    )),
    (DEFAULT_SOURCE_TAG, Heuristic(
        category="separation_factor_estimation",
        condition=(
            "liquid and vapor solutions are nearly ideal "
            "and the vapor phase obeys the ideal gas law"
        ),
        principle=(
            "For vapor-liquid separation using an ESA, "
            "the separation factor equals the relative volatility."
        ),
        design_implication=(
            "Estimate separation difficulty from the ratio "
            "of the component vapor pressures."
        ),
        heuristic_type="equation",
        equation="SF = alpha_1,2 = Ps_1 / Ps_2",
        required_variables=["Ps_1", "Ps_2"],
    )),
    ("seider_ch9", Heuristic(
        category="separation_sequence_selection",
        condition=(
            "a feed contains thermally unstable, corrosive, "
            "or chemically reactive components"
        ),
        principle=(
            "thermally unstable, corrosive, or chemically reactive "
            "components should be removed early in the separation sequence"
        ),
        design_implication=(
            "prioritize separation steps that remove these components "
            "before downstream operations"
        ),
    )),
]


def render_heuristic_for_embedding(h: Heuristic) -> str:
    sentence = f"When {h.condition}: {h.principle}. Design implication: {h.design_implication}"
    if h.heuristic_type == "equation" and h.equation:
        sentence += f" Equation: {h.equation}."
    return sentence


def _serialize_required_variables(required_variables) -> str:
    """Chroma metadata values must be scalars, so a list is joined into a
    comma-separated string for storage; split back on ',' when reading."""
    return ",".join(required_variables) if required_variables else ""


def main():
    embedder = SentenceTransformer(config.EMBED_MODEL)
    chroma = chromadb.PersistentClient(path=config.CHROMA_DIR)
    collection = chroma.get_or_create_collection(config.COLLECTION_NAME)

    for i, (source_tag, h) in enumerate(SEED_HEURISTICS):
        heur_id = f"heur_seed_{source_tag}_{i}"
        embed_text = render_heuristic_for_embedding(h)
        collection.upsert(
            ids=[heur_id],
            documents=[embed_text],
            embeddings=[embedder.encode(embed_text).tolist()],
            metadatas=[{
                "type": "heuristic",
                "parent_chunk_id": "",  # hand-seeded, no source chunk on file
                "source_file": source_tag,
                "category": h.category,
                "condition": h.condition,
                "principle": h.principle,
                "design_implication": h.design_implication,
                "heuristic_type": h.heuristic_type,
                "equation": h.equation or "",
                "required_variables": _serialize_required_variables(h.required_variables),
            }],
        )
        print(f"seeded: [{h.category}] {h.principle[:70]}")

    print(f"\nDone. {len(SEED_HEURISTICS)} hand-seeded heuristics added to "
          f"'{config.COLLECTION_NAME}' at {config.CHROMA_DIR}")


if __name__ == "__main__":
    main()