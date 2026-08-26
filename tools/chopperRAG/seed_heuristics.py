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
    # NOTE: originally one bundled entry ("thermally unstable, corrosive, or
    # chemically reactive"). Split into three single-condition entries
    # (2026-08-25) because the disjunctive condition string let a question
    # that only established one disjunct (e.g. "corrosive") cause the LLM to
    # treat the others (e.g. "thermally unstable") as also established,
    # wrongly pulling in the bottoms-temperature-decomposition feasibility
    # heuristic. This entry keeps its original list position/ID
    # (heur_seed_seider_ch9_3) so re-seeding overwrites rather than orphans
    # it; the other two splits are appended at the end of this list below.
    ("seider_ch9", Heuristic(
        category="separation_sequence_selection",
        condition="a feed contains a corrosive component",
        principle=(
            "corrosive components should be removed early in the "
            "separation sequence"
        ),
        design_implication=(
            "prioritize separation steps that remove the corrosive "
            "component before downstream operations"
        ),
    )),
    # --- Seader ch. 9, sec. 9.4: sequencing/feasibility of ordinary
    # distillation for nearly ideal multicomponent mixtures ---
    (DEFAULT_SOURCE_TAG, Heuristic(
        category="separation_sequence_selection",
        condition=(
            "a multicomponent feed is nearly ideal, such as a hydrocarbon "
            "mixture or a mixture from a homologous series such as alcohols"
        ),
        principle=(
            "an economical separation sequence will often consist only of "
            "ordinary distillation columns when the required feasibility "
            "conditions for each column are satisfied"
        ),
        design_implication=(
            "consider a sequence of two-product ordinary distillation columns, "
            "but verify relative volatility, reboiler duty, critical-temperature "
            "limitations, overhead condensation, thermal stability, azeotropes, "
            "and pressure drop before accepting the sequence"
        ),
    )),
    (DEFAULT_SOURCE_TAG, Heuristic(
        category="distillation_feasibility",
        condition=(
            "ordinary distillation is being considered for a split between "
            "two selected key components"
        ),
        principle=(
            "the relative volatility between the selected key components "
            "should be greater than 1.05"
        ),
        design_implication=(
            "check that the relative volatility of the selected light and "
            "heavy keys is greater than 1.05 before treating ordinary "
            "distillation as suitable for that split"
        ),
    )),
    (DEFAULT_SOURCE_TAG, Heuristic(
        category="distillation_feasibility",
        condition=(
            "ordinary distillation is being considered and the required "
            "reboiler duty may be large"
        ),
        principle=(
            "the reboiler duty should not be excessive; excessive duty can "
            "occur when the relative volatility between the key components is "
            "low and the light key has a high heat of vaporization, such as water"
        ),
        design_implication=(
            "estimate the reboiler energy requirement and reject or reconsider "
            "the ordinary-distillation split if the required duty is excessive"
        ),
    )),
    (DEFAULT_SOURCE_TAG, Heuristic(
        category="distillation_feasibility",
        condition=(
            "a distillation column is being considered at a specified tower pressure"
        ),
        principle=(
            "the tower pressure should not cause the mixture to approach its "
            "critical temperature"
        ),
        design_implication=(
            "check the relationship between operating pressure, mixture "
            "temperature, and critical-temperature limits before accepting "
            "the proposed column pressure"
        ),
    )),
    (DEFAULT_SOURCE_TAG, Heuristic(
        category="distillation_feasibility",
        condition=(
            "ordinary distillation requires overhead vapor condensation to "
            "provide reflux"
        ),
        principle=(
            "the overhead vapor should be at least partially condensable at "
            "the column pressure without excessive refrigeration requirements"
        ),
        design_implication=(
            "verify that the overhead can be condensed sufficiently to provide "
            "reflux at the proposed column pressure without requiring excessive "
            "refrigeration"
        ),
    )),
    (DEFAULT_SOURCE_TAG, Heuristic(
        category="distillation_feasibility",
        condition=(
            "ordinary distillation produces a high bottoms temperature at the "
            "selected tower pressure"
        ),
        principle=(
            "the bottoms temperature should not be so high that chemical "
            "decomposition occurs"
        ),
        design_implication=(
            "compare the expected bottoms temperature with the thermal stability "
            "of the mixture and reject or modify the operating conditions if "
            "decomposition would occur"
        ),
    )),
    (DEFAULT_SOURCE_TAG, Heuristic(
        category="distillation_feasibility",
        condition=(
            "ordinary distillation is being considered for a desired separation "
            "that may be affected by azeotropic behavior"
        ),
        principle=(
            "azeotropes should not prevent the desired separation"
        ),
        design_implication=(
            "check for azeotropic limitations before relying on ordinary "
            "distillation to achieve the required product split"
        ),
    )),
    (DEFAULT_SOURCE_TAG, Heuristic(
        category="distillation_feasibility",
        condition=(
            "a distillation column may experience significant pressure drop, "
            "particularly during vacuum operation"
        ),
        principle=(
            "column pressure drop should be tolerable, especially when the "
            "column operates under vacuum"
        ),
        design_implication=(
            "evaluate whether the expected pressure drop is acceptable for the "
            "proposed operation and pay particular attention to pressure-drop "
            "limitations in vacuum columns"
        ),
    )),
    # --- remaining two splits of the original bundled corrosive/thermally
    # unstable/reactive entry above (see note there) ---
    ("seider_ch9", Heuristic(
        category="separation_sequence_selection",
        condition="a feed contains a thermally unstable or heat-sensitive component",
        principle=(
            "thermally unstable/heat-sensitive components should be removed "
            "early in the separation sequence"
        ),
        design_implication=(
            "prioritize separation steps that remove the thermally unstable "
            "component before downstream operations"
        ),
    )),
    ("seider_ch9", Heuristic(
        category="separation_sequence_selection",
        condition="a feed contains a chemically reactive component",
        principle=(
            "chemically reactive components should be removed early in the "
            "separation sequence"
        ),
        design_implication=(
            "prioritize separation steps that remove the reactive component "
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