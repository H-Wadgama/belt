"""
Schema for the structured heuristic extracted from each chunk.
"""
from typing import List

from pydantic import BaseModel, Field


class Heuristic(BaseModel):
    category: str = Field(
        ..., description="e.g. separation_objective, purity_target, thermal_sensitivity, cost_tradeoff"
    )
    condition: str = Field(..., description="the scenario this heuristic applies under")
    principle: str = Field(..., description="the rule of thumb itself, as the book states or implies it")
    design_implication: str = Field(
        ..., description="what this means for choosing/configuring a separation process"
    )


class ExtractionResult(BaseModel):
    heuristics: List[Heuristic] = Field(default_factory=list)


# Useful if your serving backend supports constrained/guided JSON decoding
# (Ollama >=0.5 via `format`, vLLM via `guided_json`, etc.)
EXTRACTION_JSON_SCHEMA = ExtractionResult.model_json_schema()
