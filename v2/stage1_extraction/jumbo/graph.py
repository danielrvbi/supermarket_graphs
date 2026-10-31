"""
Jumbo Pipeline LangGraph assembly.

Builds the complete pipeline graph with persistent SQLite checkpoints.

SIMPLIFIED VALIDATION:
- Only schema checks (item_name + price present) are required
- Arithmetic and reconciliation are warnings only, never fail
- Discounts (ACTIE), totals are ignored
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Literal

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver

from v2.common.settings import settings
from v2.stage1_extraction.validators import (
    check_arithmetic,
    detect_duplicates,
    sanity_check_items,
)
from v2.stage1_extraction.output_writer import OutputWriter
from v2.stage1_extraction.audit_log import AuditLogger
from v2.stage1_extraction.jumbo.state import JumboPipelineState
from v2.stage1_extraction.jumbo.preprocess import preprocess_node
from v2.stage1_extraction.jumbo.deterministic import deterministic_parse_node
from v2.stage1_extraction.jumbo.llm_extract import llm_extract_node
from v2.stage1_extraction.jumbo.verifier import verify_node


MAX_CORRECTION_ITERATIONS = 2  # Prevent infinite loops


# ============================================================
# Merge node
# ============================================================

def merge_node(state: JumboPipelineState) -> JumboPipelineState:
    """
    Merge deterministic and LLM extraction results for Jumbo.
    """
    import re
    
    det_items = state.get("deterministic_items", [])
    llm_items = state.get("llm_items", [])

    merged = []

    def normalize_name(name: str) -> str:
        """Normalize name for matching: uppercase, remove spaces and trailing P."""
        if not name:
            return ""
        # Remove trailing 'P' (price-marked indicator)
        name = re.sub(r"\s+P\s*$", "", name.strip(), flags=re.IGNORECASE)
        return name.upper().strip().replace(" ", "")

    def clean_item_name(name: str) -> str:
        """Clean item name: remove trailing 'P' indicator, extra spaces."""
        if not name:
            return name
        # Remove trailing ' P' or ' P ' (price-marked indicator)
        name = re.sub(r"\s+P\s*$", "", name.strip(), flags=re.IGNORECASE)
        # Remove ' P' in middle followed by price-like patterns
        name = re.sub(r"\s+P\s+\d", " ", name, flags=re.IGNORECASE)
        # Collapse multiple spaces
        name = re.sub(r"\s+", " ", name).strip()
        return name

    llm_by_name = {normalize_name(item.get("item_name", "")): item for item in llm_items}

    # Start with deterministic items
    for det_item in det_items:
        name_norm = normalize_name(det_item.get("item_name", ""))
        llm_item = llm_by_name.get(name_norm)

        merged_item = det_item.copy()
        # Clean the item name
        merged_item["item_name"] = clean_item_name(merged_item.get("item_name", ""))
        
        if llm_item:
            merged_item["_confidence"] = 0.95
        else:
            merged_item["_confidence"] = 0.80

        for key in list(merged_item.keys()):
            if key.startswith("_"):
                del merged_item[key]
        merged.append(merged_item)

    # Add LLM-only items
    det_names = {normalize_name(item.get("item_name", "")) for item in det_items}
    for llm_item in llm_items:
        name_norm = normalize_name(llm_item.get("item_name", ""))
        if name_norm not in det_names:
            llm_item_copy = llm_item.copy()
            # Clean the item name
            llm_item_copy["item_name"] = clean_item_name(llm_item_copy.get("item_name", ""))
            llm_item_copy["_confidence"] = 0.60
            for key in list(llm_item_copy.keys()):
                if key.startswith("_"):
                    del llm_item_copy[key]
            merged.append(llm_item_copy)

    return {
        **state,
        "merged_items": merged,
        "processing_steps": state.get("processing_steps", []) + ["merge"],
    }


# ============================================================
# Validate node (SIMPLIFIED)
# ============================================================

def validate_node(state: JumboPipelineState) -> JumboPipelineState:
    """
    Run validation checks on merged items.

    SIMPLIFIED: Only schema validation is required.
    """
    items = state.get("merged_items", [])

    errors = []
    warnings = []

    # 1. Schema validation (REQUIRED)
    for i, item in enumerate(items):
        if not item.get("item_name"):
            errors.append(f"Item {i}: missing item_name")
        if item.get("line_total_paid_amount") is None:
            errors.append(f"Item {i} ('{item.get('item_name', '?')}'): missing price")
        if item.get("measurement_quantity") is None:
            item["measurement_quantity"] = 1.0

    # 2. Arithmetic check (WARNING only)
    _, arithmetic_warnings = check_arithmetic(items)
    warnings.extend(arithmetic_warnings)

    # 3. Duplicate detection (WARNING only)
    has_duplicates, duplicates = detect_duplicates(items)
    if has_duplicates:
        warnings.append(f"Potential duplicates: {len(duplicates)} pairs")

    # 4. Sanity checks (WARNING only)
    _, sanity_warnings = sanity_check_items(items)
    warnings.extend(sanity_warnings)

    # 5. OCR quality warning
    ocr_quality = state.get("ocr_quality_score", 1.0)
    if ocr_quality < 0.7:
        warnings.append(f"Low OCR quality: {ocr_quality:.2f}")

    validation_passed = len(errors) == 0
    calculated_total = sum(i.get("line_total_paid_amount", 0) for i in items)

    return {
        **state,
        "validation_passed": validation_passed,
        "validation_errors": errors,
        "validation_warnings": warnings,
        "arithmetic_ok": len(arithmetic_warnings) == 0,
        "reconciliation_ok": True,  # Always True - disabled
        "reconciliation_error": None,
        "duplicates_found": duplicates,
        "calculated_total": calculated_total,
        "processing_steps": state.get("processing_steps", []) + ["validate"],
    }


# ============================================================
# Correct node
# ============================================================

def correct_node(state: JumboPipelineState) -> JumboPipelineState:
    """Apply corrections based on verification discrepancies."""
    discrepancies = state.get("verification_discrepancies", [])
    iterations = state.get("correction_iterations", 0) + 1

    corrections = []

    if discrepancies:
        corrections.append({
            "type": "verification_discrepancies",
            "iteration": iterations,
            "count": len(discrepancies),
            "discrepancies": discrepancies[:5],
            "action": "flagged_for_review",
        })

    return {
        **state,
        "corrections_applied": state.get("corrections_applied", []) + corrections,
        "correction_iterations": iterations,
        "processing_steps": state.get("processing_steps", []) + ["correct"],
    }


# ============================================================
# Finalize node
# ============================================================

def finalize_node(state: JumboPipelineState) -> JumboPipelineState:
    """Make final decision: approve, review, or reject."""
    items = state.get("merged_items", [])
    date_of_purchase = state.get("date_of_purchase", "")

    # Calculate overall confidence (SIMPLIFIED)
    confidence_factors = []

    # Schema validation passed
    if state.get("validation_passed"):
        confidence_factors.append(1.0)
    else:
        confidence_factors.append(0.3)

    # Verification confidence (most important)
    verification_conf = state.get("verification_confidence", 0.0)
    processing_steps = state.get("processing_steps", [])

    # If verification was skipped (both sources agreed), use agreement-based confidence
    if "verify" not in processing_steps:
        det_count = len(state.get("deterministic_items", []))
        llm_count = len(state.get("llm_items", []))
        if det_count > 0 and det_count == llm_count:
            verification_conf = 0.90  # High confidence when both sources agree (lower for OCR)
        else:
            verification_conf = 0.75  # Default when skipped

    confidence_factors.append(verification_conf)

    # Extraction agreement
    det_count = len(state.get("deterministic_items", []))
    llm_count = len(state.get("llm_items", []))
    merged_count = len(items)

    if det_count > 0 and llm_count > 0:
        agreement = min(det_count, llm_count) / max(det_count, llm_count) if max(det_count, llm_count) > 0 else 0
        confidence_factors.append(0.5 + 0.5 * agreement)
    else:
        confidence_factors.append(0.7)

    # Item count reasonableness
    if merged_count > 0:
        confidence_factors.append(1.0)
    else:
        confidence_factors.append(0.0)

    # OCR quality factor
    ocr_quality = state.get("ocr_quality_score", 0.5)
    confidence_factors.append(0.5 + 0.5 * ocr_quality)

    # No errors
    if not state.get("errors"):
        confidence_factors.append(1.0)
    else:
        confidence_factors.append(0.5)

    overall_confidence = sum(confidence_factors) / len(confidence_factors)

    # Determine final status
    errors = state.get("errors", [])
    validation_errors = state.get("validation_errors", [])

    if errors:
        final_status = "rejected"
    elif not validation_errors and overall_confidence >= settings.CONFIDENCE_THRESHOLD_APPROVE:
        final_status = "approved"
    elif overall_confidence >= settings.CONFIDENCE_THRESHOLD_REVIEW:
        final_status = "review"
    else:
        final_status = "rejected"

    # Build final receipt
    final_items = [
        {
            "item_name": item.get("item_name"),
            "measurement_type": item.get("measurement_type"),
            "measurement_quantity": item.get("measurement_quantity"),
            "price_per_measurement_unit": item.get("price_per_measurement_unit"),
            "line_total_paid_amount": item.get("line_total_paid_amount"),
        }
        for item in items
    ]

    final_receipt = {
        "date_of_purchase": date_of_purchase,
        "items": final_items,
    }

    # Write output
    output_writer = OutputWriter()
    metadata = {
        "confidence": overall_confidence,
        "validation_passed": state.get("validation_passed"),
        "verification_confidence": verification_conf,
        "ocr_quality": ocr_quality,
        "discrepancies": state.get("verification_discrepancies", []),
        "warnings": state.get("validation_warnings", []),
        "items_count": len(items),
        "processing_steps": state.get("processing_steps", []),
    }

    status_map = {"approved": "clean", "review": "review", "rejected": "rejected"}
    output_writer.write_receipt(
        store="jumbo",
        receipt_path=state["receipt_path"],
        receipt_data=final_receipt,
        status=status_map[final_status],
        metadata=metadata,
    )

    # Log to audit
    audit = AuditLogger()
    thread_id = state.get("thread_id", Path(state["receipt_path"]).stem)
    audit.complete_receipt(thread_id, overall_confidence, final_status)

    return {
        **state,
        "overall_confidence": overall_confidence,
        "final_status": final_status,
        "final_receipt": final_receipt,
        "completed_at": datetime.now().isoformat(),
        "processing_steps": state.get("processing_steps", []) + ["finalize"],
    }


# ============================================================
# Conditional edges
# ============================================================

def should_verify(state: JumboPipelineState) -> Literal["verify", "finalize"]:
    """Decide if AI verification is needed."""
    if state.get("errors"):
        return "verify"

    if not state.get("validation_passed"):
        return "verify"

    # For Jumbo, always verify if OCR quality is low
    ocr_quality = state.get("ocr_quality_score", 1.0)
    if ocr_quality < 0.8:
        return "verify"

    # Skip verification if both sources agree
    det_count = len(state.get("deterministic_items", []))
    llm_count = len(state.get("llm_items", []))

    if det_count > 0 and det_count == llm_count and det_count >= 3:
        return "finalize"

    return "verify"


def should_correct(state: JumboPipelineState) -> Literal["correct", "finalize"]:
    """Decide if correction is needed after verification."""
    iterations = state.get("correction_iterations", 0)
    if iterations >= MAX_CORRECTION_ITERATIONS:
        return "finalize"

    discrepancies = state.get("verification_discrepancies", [])
    confidence = state.get("verification_confidence", 0.0)

    real_discrepancies = [
        d for d in discrepancies
        if "missing" in d.lower() or "extra" in d.lower() or "wrong" in d.lower()
    ]

    if real_discrepancies and confidence < 0.90:
        return "correct"

    return "finalize"


# ============================================================
# Graph assembly
# ============================================================

def build_jumbo_pipeline(
    checkpoint_path: str = None,
) -> "CompiledGraph":
    """Build the complete Jumbo pipeline graph with persistent checkpoints."""
    if checkpoint_path is None:
        checkpoint_path = str(Path(settings.CHECKPOINTS_DIR) / "jumbo_pipeline.db")

    Path(checkpoint_path).parent.mkdir(parents=True, exist_ok=True)

    graph = StateGraph(JumboPipelineState)

    # Add nodes
    graph.add_node("preprocess", preprocess_node)
    graph.add_node("deterministic", deterministic_parse_node)
    graph.add_node("llm_extract", llm_extract_node)
    graph.add_node("merge", merge_node)
    graph.add_node("validate", validate_node)
    graph.add_node("verify", verify_node)
    graph.add_node("correct", correct_node)
    graph.add_node("finalize", finalize_node)

    # Entry point
    graph.set_entry_point("preprocess")

    # Sequential edges
    graph.add_edge("preprocess", "deterministic")
    graph.add_edge("deterministic", "llm_extract")
    graph.add_edge("llm_extract", "merge")
    graph.add_edge("merge", "validate")

    # Conditional edges
    graph.add_conditional_edges(
        "validate",
        should_verify,
        {"verify": "verify", "finalize": "finalize"}
    )

    graph.add_conditional_edges(
        "verify",
        should_correct,
        {"correct": "correct", "finalize": "finalize"}
    )

    graph.add_edge("correct", "validate")
    graph.add_edge("finalize", END)

    # Compile with SQLite checkpointer
    import sqlite3
    conn = sqlite3.connect(checkpoint_path, check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    checkpointer.setup()
    return graph.compile(checkpointer=checkpointer)


def run_jumbo_receipt(
    pipeline: "CompiledGraph",
    receipt_path: str,
    thread_id: str = None,
) -> JumboPipelineState:
    """Run a single Jumbo receipt through the pipeline."""
    if thread_id is None:
        thread_id = f"jumbo_{Path(receipt_path).stem}"

    # Initialize audit log
    audit = AuditLogger()
    audit.start_receipt(thread_id, receipt_path, "jumbo")

    initial_state: JumboPipelineState = {
        "receipt_path": receipt_path,
        "thread_id": thread_id,
        "raw_text": "",
        "deterministic_items": [],
        "llm_items": [],
        "merged_items": [],
        "date_of_purchase": None,
        "store_location": None,
        "total_incl_btw": None,
        "total_korting": None,
        "actie_discounts": [],
        "validation_passed": False,
        "validation_errors": [],
        "validation_warnings": [],
        "arithmetic_ok": True,
        "reconciliation_ok": True,
        "reconciliation_error": None,
        "duplicates_found": [],
        "calculated_total": 0.0,
        "verification_confidence": 0.0,
        "verification_discrepancies": [],
        "verification_notes": "",
        "verification_passed": False,
        "ocr_quality_score": 0.0,
        "corrections_applied": [],
        "correction_iterations": 0,
        "overall_confidence": 0.0,
        "final_status": "pending",
        "final_receipt": None,
        "started_at": datetime.now().isoformat(),
        "completed_at": None,
        "processing_steps": [],
        "errors": [],
    }

    config = {"configurable": {"thread_id": thread_id}}

    result = pipeline.invoke(initial_state, config=config)

    return result
