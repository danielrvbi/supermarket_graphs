"""
State schema for the AH pipeline (LangGraph TypedDict).
"""

from typing import TypedDict, List, Optional, Literal, Any
from datetime import datetime


class AHPipelineState(TypedDict, total=False):
    """
    State that flows through the AH LangGraph pipeline.

    All fields are optional (total=False) because nodes populate them incrementally.
    """

    # === Input ===
    receipt_path: str
    raw_text: str  # pdfplumber extracted text with layout

    # === Extraction results ===
    deterministic_items: List[dict]
    llm_items: List[dict]
    merged_items: List[dict]

    # === AH-specific metadata from receipt ===
    date_of_purchase: Optional[str]  # From footer: "08-03-2024" or "22/10/2026"
    date_from_filename: Optional[str]  # From filename: "2024-03-08"
    subtotal: Optional[float]  # SUBTOTAAL row
    total: Optional[float]  # TOTAAL row
    uw_voordeel: Optional[float]  # Savings amount
    statiegeld_total: float  # Sum of deposit amounts
    bonus_discounts: List[dict]  # BONUS discount rows
    btw_9_base: Optional[float]  # 9% VAT base
    btw_9_amount: Optional[float]  # 9% VAT amount
    btw_21_base: Optional[float]  # 21% VAT base
    btw_21_amount: Optional[float]  # 21% VAT amount
    statiegeld_items: List[dict]  # Deposit items (excluded from groceries)

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

    # === Corrections ===
    corrections_applied: List[dict]
    correction_iterations: int  # Track to prevent infinite loops

    # === Final ===
    overall_confidence: float
    final_status: Literal["pending", "approved", "review", "rejected"]
    final_receipt: Optional[dict]  # RawReceipt-compatible dict

    # === Metadata ===
    thread_id: str
    started_at: str
    completed_at: Optional[str]
    processing_steps: List[str]
    errors: List[str]
