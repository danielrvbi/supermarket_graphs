"""
LLM classification of a single receipt item into the frozen taxonomy.

The label is a single 'Category > Subcategory' enum field, so the model can only
return valid pairs.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from v2.common.mistral_client import get_mistral_llm
from v2.common.settings import settings
from v2.common.token_tracker import TokenTracker
from v2.stage3_classification.matcher import Neighbour
from v2.stage3_classification.prompts import (
    CLASSIFY_SYSTEM_PROMPT,
    CLASSIFY_USER_PROMPT_TEMPLATE,
    format_neighbours,
    format_taxonomy,
    format_search_results,
)
from v2.stage3_classification.taxonomy import TAXONOMY, all_labels, split_label


LABELS = tuple(all_labels())
CONFIDENCE_SCORES = {"high": 0.9, "medium": 0.7, "low": 0.4}
SYSTEM_PROMPT = CLASSIFY_SYSTEM_PROMPT.format(taxonomy=format_taxonomy(TAXONOMY))


class ItemClassification(BaseModel):
    """Structured LLM output."""
    reasoning: str = Field(description="One short sentence: what the abbreviation most likely means")
    producto_es: str = Field(description="Short Spanish product name, brand/store label last")
    label: Literal[LABELS] = Field(description="Exactly one 'Category > Subcategory' from the allowed list")
    confidence: Literal["high", "medium", "low"]


@dataclass
class ClassificationResult:
    """Final label for one item, ready for item_labels."""
    item_name: str
    store: str
    producto_es: str
    category: str
    subcategory: str
    source: str
    confidence: float
    needs_review: bool
    evidence: Dict = field(default_factory=dict)


class Classifier:
    """Wraps the structured Mistral call and the review/confidence rules."""

    def __init__(self, stage: str = "classify"):
        self.llm = get_mistral_llm(temperature=0.0).with_structured_output(ItemClassification)
        self.tracker = TokenTracker(settings.TOKEN_USAGE_DB)
        self.stage = stage
        self.calls = 0

    def classify(
        self,
        item_name: str,
        store: str,
        neighbours: List[Neighbour],
        gate_passed: bool,
        search: Optional[Dict] = None,
    ) -> ClassificationResult:
        prompt = CLASSIFY_USER_PROMPT_TEMPLATE.format(
            item_name=item_name,
            store=store,
            neighbours=format_neighbours(neighbours),
            search_results=format_search_results(search),
        )
        callback = self.tracker.create_callback(stage=self.stage, file_path=f"{store}:{item_name}")
        output: ItemClassification = self.llm.invoke(
            [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)],
            config={"callbacks": [callback]},
        )
        self.calls += 1

        category, subcategory = split_label(output.label)
        searched = bool(search and search["success"])
        disagrees = gate_passed and neighbours and category != neighbours[0].category

        return ClassificationResult(
            item_name=item_name,
            store=store,
            producto_es=output.producto_es.strip(),
            category=category,
            subcategory=subcategory,
            source="search_llm" if searched else "embed_llm",
            confidence=CONFIDENCE_SCORES[output.confidence],
            needs_review=(
                output.confidence == "low"
                or bool(disagrees)
                or (not gate_passed and (not searched or output.confidence != "high"))
            ),
            evidence={
                "reasoning": output.reasoning,
                "llm_confidence": output.confidence,
                "gate_passed": gate_passed,
                "neighbours": [n.to_dict() for n in neighbours],
                "search_query": search["query"] if search else None,
                "search_ok": searched,
                "search_urls": [r["url"] for r in search["results"]] if search else [],
            },
        )
