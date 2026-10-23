"""
AH-specific AI verifier node.

Cross-checks extracted data against the original PDF text using Mistral.
"""

import json
from typing import List
from pydantic import BaseModel, Field

from langchain_core.messages import SystemMessage, HumanMessage
from v2.common.mistral_client import get_mistral_llm
from v2.common.token_tracker import TokenTracker
from v2.common.settings import settings
from v2.stage1_extraction.ah.state import AHPipelineState
from v2.stage1_extraction.ah.prompts import VERIFICATION_SYSTEM_PROMPT, VERIFICATION_USER_PROMPT_TEMPLATE


class VerificationResult(BaseModel):
    """Verification result schema for LLM structured output."""
    confidence: float = Field(description="Confidence score 0.0-1.0", ge=0.0, le=1.0)
    discrepancies: List[str] = Field(default_factory=list, description="List of specific issues found")
    missing_items: List[str] = Field(default_factory=list, description="Items on receipt but not extracted")
    extra_items: List[str] = Field(default_factory=list, description="Items extracted but not on receipt")
    notes: str = Field(default="", description="Brief summary of verification")


def verify_node(state: AHPipelineState) -> AHPipelineState:
    """
    LangGraph node: Verify AH extraction using AI.

    Compares extracted items against original receipt text.
    """
    raw_text = state.get("raw_text", "")
    merged_items = state.get("merged_items", [])
    calculated_total = state.get("calculated_total", 0.0)
    receipt_total = state.get("total")

    if not merged_items:
        return {
            **state,
            "verification_confidence": 0.0,
            "verification_discrepancies": ["No items to verify"],
            "verification_passed": False,
            "processing_steps": state.get("processing_steps", []) + ["verify_failed"],
        }

    try:
        # Prepare extracted data for verification
        extracted_data = {
            "date_of_purchase": state.get("date_of_purchase"),
            "items": [
                {
                    "item_name": item.get("item_name"),
                    "measurement_type": item.get("measurement_type"),
                    "measurement_quantity": item.get("measurement_quantity"),
                    "price_per_measurement_unit": item.get("price_per_measurement_unit"),
                    "line_total_paid_amount": item.get("line_total_paid_amount"),
                }
                for item in merged_items
            ],
        }

        # Get LLM with structured output
        llm = get_mistral_llm(temperature=0.0)
        structured_llm = llm.with_structured_output(VerificationResult)

        # Build prompt
        user_prompt = VERIFICATION_USER_PROMPT_TEMPLATE.format(
            original_text=raw_text[:8000],  # Limit context size
            extracted_data=json.dumps(extracted_data, indent=2, ensure_ascii=False),
        )

        # Create token tracking callback
        tracker = TokenTracker(settings.TOKEN_USAGE_DB)
        callback = tracker.create_callback(
            stage="verify",
            file_path=state["receipt_path"],
            thread_id=state.get("thread_id"),
        )

        # Invoke LLM with token tracking
        result: VerificationResult = structured_llm.invoke(
            [
                SystemMessage(content=VERIFICATION_SYSTEM_PROMPT),
                HumanMessage(content=user_prompt),
            ],
            config={"callbacks": [callback]},
        )

        # Combine all discrepancies
        all_discrepancies = list(result.discrepancies)
        if result.missing_items:
            all_discrepancies.append(f"Missing items: {', '.join(result.missing_items)}")
        if result.extra_items:
            all_discrepancies.append(f"Extra items: {', '.join(result.extra_items)}")

        # Verification passes if confidence >= 0.85 and no critical discrepancies
        verification_passed = result.confidence >= 0.85 and len(all_discrepancies) == 0

        return {
            **state,
            "verification_confidence": result.confidence,
            "verification_discrepancies": all_discrepancies,
            "verification_notes": result.notes,
            "verification_passed": verification_passed,
            "processing_steps": state.get("processing_steps", []) + ["verify"],
        }

    except Exception as e:
        return {
            **state,
            "verification_confidence": 0.5,  # Neutral confidence on error
            "verification_discrepancies": [f"Verification failed: {str(e)}"],
            "verification_notes": "Verification error - manual review recommended",
            "verification_passed": False,
            "errors": state.get("errors", []) + [f"Verification error: {str(e)}"],
            "processing_steps": state.get("processing_steps", []) + ["verify_error"],
        }
