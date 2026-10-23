"""
State schema for the Jumbo pipeline (LangGraph TypedDict).
"""

from typing import TypedDict, List, Optional, Literal
from datetime import datetime


class JumboPipelineState(TypedDict, total=False):
    """
    State that flows through the Jumbo LangGraph pipeline.
    """

    # === Input ===
    receipt_path: str
    raw_text: str  # OCR extracted text

    # === Extraction results ===
    deterministic_items: List[dict]
    llm_items: List[dict]
    merged_items: List[dict]

    # === Jumbo-specific metadata ===
    date_of_purchase: Optional[str]  # Dutch format: "Dinsdag 12 mei 2026"
    store_location: Optional[str]  # e.g., "Jumbo Haarlem Engelenburg"
    total_incl_btw: Optional[float]  # "Totaal (incl. BTW)" or "Totaal*"
    total_korting: Optional[float]  # "Totaal korting"
    actie_discounts: List[float]  # List of ACTIE discount amounts

    # === Validation results ===
    validation_passed: bool
    validation_errors: List[str]
    validation_warnings: List[str]
    arithmetic_ok: bool
    reconciliation_ok: bool
    reconciliation_error: Optional[str]
    duplicates_found: List[tuple]
    calculated_total: float

    # === AI Verification ===
    verification_confidence: float
    verification_discrepancies: List[str]
    verification_notes: str
    verification_passed: bool
    ocr_quality_score: float  # Estimated OCR quality

    # === Corrections ===
    corrections_applied: List[dict]
    correction_iterations: int  # Track to prevent infinite loops

    # === Final ===
    overall_confidence: float
    final_status: Literal["pending", "approved", "review", "rejected"]
    final_receipt: Optional[dict]

    # === Metadata ===
    thread_id: str
    started_at: str
    completed_at: Optional[str]
    processing_steps: List[str]
    errors: List[str]
