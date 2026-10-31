"""
LLM extraction node for AH receipts using Mistral.
"""

import json
from typing import List
from pydantic import BaseModel, Field
from typing import Literal, Optional

from langchain_core.messages import SystemMessage, HumanMessage
from v2.common.mistral_client import get_mistral_llm
from v2.common.token_tracker import TokenTracker
from v2.common.settings import settings
from v2.stage1_extraction.ah.state import AHPipelineState
from v2.stage1_extraction.ah.prompts import EXTRACTION_SYSTEM_PROMPT, EXTRACTION_USER_PROMPT_TEMPLATE


class LLMItem(BaseModel):
    """Item schema for LLM structured output."""
    item_name: str
    measurement_type: Literal["discrete_units", "weight_in_grams"]
    measurement_quantity: float
    price_per_measurement_unit: Optional[float] = None
    line_total_paid_amount: float


class LLMReceipt(BaseModel):
    """Receipt schema for LLM structured output."""
    date_of_purchase: str = Field(description="Date in YYYY/MM/DD format")
    items: List[LLMItem]


def llm_extract_node(state: AHPipelineState) -> AHPipelineState:
    """
    LangGraph node: Extract structured data from AH receipt using Mistral LLM.

    Uses structured output with Pydantic schema for reliable JSON extraction.
    """
    raw_text = state.get("raw_text", "")

    if not raw_text:
        return {
            **state,
            "errors": state.get("errors", []) + ["No raw text available for LLM extraction"],
            "llm_items": [],
        }

    try:
        # Get LLM with structured output
        llm = get_mistral_llm(temperature=0.0)
        structured_llm = llm.with_structured_output(LLMReceipt)

        # Build prompt
        user_prompt = EXTRACTION_USER_PROMPT_TEMPLATE.format(receipt_text=raw_text)

        # Create token tracking callback
        tracker = TokenTracker(settings.TOKEN_USAGE_DB)
        callback = tracker.create_callback(
            stage="extract",
            file_path=state["receipt_path"],
            thread_id=state.get("thread_id"),
        )

        # Invoke LLM with token tracking
        result: LLMReceipt = structured_llm.invoke(
            [
                SystemMessage(content=EXTRACTION_SYSTEM_PROMPT),
                HumanMessage(content=user_prompt),
            ],
            config={"callbacks": [callback]},
        )

        # Convert to dict format matching v1 schema
        items = []
        for item in result.items:
            item_dict = {
                "item_name": item.item_name,
                "measurement_type": item.measurement_type,
                "measurement_quantity": item.measurement_quantity,
                "price_per_measurement_unit": item.price_per_measurement_unit,
                "line_total_paid_amount": item.line_total_paid_amount,
                "_source": "llm",
            }
            items.append(item_dict)

        return {
            **state,
            "llm_items": items,
            "date_of_purchase": state.get("date_of_purchase") or result.date_of_purchase,
            "processing_steps": state.get("processing_steps", []) + ["llm_extract"],
        }

    except Exception as e:
        return {
            **state,
            "errors": state.get("errors", []) + [f"LLM extraction failed: {str(e)}"],
            "llm_items": [],
            "processing_steps": state.get("processing_steps", []) + ["llm_extract_failed"],
        }
