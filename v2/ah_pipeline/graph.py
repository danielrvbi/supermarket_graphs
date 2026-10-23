"""
AH Pipeline LangGraph assembly.

Builds the complete pipeline graph with persistent SQLite checkpoints.

SIMPLIFIED VALIDATION:
- Only schema checks (item_name + price present) are required
- Arithmetic and reconciliation are warnings only, never fail
- Deposits (STATIEGELD), discounts (BONUS), taxes (BTW) are ignored
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Literal

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver

from v2.config.settings import settings
from v2.shared.validators import (
    check_arithmetic,
    detect_duplicates,
    sanity_check_items,
)
from v2.shared.output_writer import OutputWriter
from v2.shared.audit_log import AuditLogger
from v2.ah_pipeline.state import AHPipelineState
from v2.ah_pipeline.preprocess import preprocess_node
from v2.ah_pipeline.deterministic import deterministic_parse_node
from v2.ah_pipeline.llm_extract import llm_extract_node
from v2.ah_pipeline.verifier import verify_node


MAX_CORRECTION_ITERATIONS = 2  # Prevent infinite loops


# ============================================================
# Merge node
# ============================================================

def merge_node(state: AHPipelineState) -> AHPipelineState:
    """
    Merge deterministic and LLM extraction results.

    Strategy:
    - Prefer deterministic (regex is reliable for structured PDF tables)
    - Add LLM-only items (might catch items regex missed)
    - Flag conflicts for verification
    """
    det_items = state.get("deterministic_items", [])
    llm_items = state.get("llm_items", [])

    merged = []

    # Create lookup for LLM items by normalized name
    def normalize_name(name: str) -> str:
        return name.upper().strip().replace(" ", "")

    llm_by_name = {normalize_name(item.get("item_name", "")): item for item in llm_items}

    # Start with deterministic items (more reliable for AH tables)
    for det_item in det_items:
        name_norm = normalize_name(det_item.get("item_name", ""))
        llm_item = llm_by_name.get(name_norm)

        merged_item = det_item.copy()
        if llm_item:
            merged_item["_confidence"] = 0.95  # Both agree
        else:
            merged_item["_confidence"] = 0.80  # Only deterministic

        # Clean up internal fields
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
            llm_item_copy["_confidence"] = 0.60  # Only LLM found it
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
# Validate node (SIMPLIFIED - no reconciliation, no arithmetic failure)
# ============================================================

def validate_node(state: AHPipelineState) -> AHPipelineState:
    """
    Run validation checks on merged items.

    SIMPLIFIED: Only schema validation is required.
    Arithmetic, duplicates, sanity are warnings only.
    """
    items = state.get("merged_items", [])

    errors = []
    warnings = []

    # 1. Schema validation (REQUIRED - must pass)
    for i, item in enumerate(items):
        if not item.get("item_name"):
            errors.append(f"Item {i}: missing item_name")
        if item.get("line_total_paid_amount") is None:
            errors.append(f"Item {i} ('{item.get('item_name', '?')}'): missing price")
        if item.get("measurement_quantity") is None:
            # Default to 1 if missing
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

    # Validation passes if no schema errors
    validation_passed = len(errors) == 0

    # Calculate total for metadata only
    calculated_total = sum(i.get("line_total_paid_amount", 0) for i in items)

    return {
        **state,
        "validation_passed": validation_passed,
        "validation_errors": errors,
        "validation_warnings": warnings,
        "arithmetic_ok": len(arithmetic_warnings) == 0,  # Informational only
        "reconciliation_ok": True,  # Always True - reconciliation disabled
        "reconciliation_error": None,
        "duplicates_found": duplicates,
        "calculated_total": calculated_total,
        "processing_steps": state.get("processing_steps", []) + ["validate"],
    }


# ============================================================
# Correct node
# ============================================================

def correct_node(state: AHPipelineState) -> AHPipelineState:
    """
    Apply corrections based on verification discrepancies.

    Increments correction_iterations to prevent infinite loops.
    """
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

def finalize_node(state: AHPipelineState) -> AHPipelineState:
    """
    Make final decision: approve, review, or reject.
    """
    items = state.get("merged_items", [])
    date_of_purchase = state.get("date_of_purchase", "")

    # Calculate overall confidence (SIMPLIFIED)
    confidence_factors = []

    # Schema validation passed (required)
    if state.get("validation_passed"):
        confidence_factors.append(1.0)
    else:
        confidence_factors.append(0.3)

    # Verification confidence (most important)
    verification_conf = state.get("verification_confidence", 0.0)
    processing_steps = state.get("processing_steps", [])

    # If verification was skipped (both sources agreed), use agreement-based confidence
    if "verify" not in processing_steps:
        # Verification skipped because deterministic and LLM agree
        det_count = len(state.get("deterministic_items", []))
        llm_count = len(state.get("llm_items", []))
        if det_count > 0 and det_count == llm_count:
            verification_conf = 0.95  # High confidence when both sources agree
        else:
            verification_conf = 0.85  # Default when skipped

    confidence_factors.append(verification_conf)

    # Extraction agreement (deterministic vs LLM)
    det_count = len(state.get("deterministic_items", []))
    llm_count = len(state.get("llm_items", []))
    merged_count = len(items)

    if det_count > 0 and llm_count > 0:
        # Agreement ratio
        agreement = min(det_count, llm_count) / max(det_count, llm_count) if max(det_count, llm_count) > 0 else 0
        confidence_factors.append(0.5 + 0.5 * agreement)
    else:
        confidence_factors.append(0.7)  # Only one source

    # Item count reasonableness
    if merged_count > 0:
        confidence_factors.append(1.0)
    else:
        confidence_factors.append(0.0)

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

    # Build final receipt in v1-compatible format
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
        "discrepancies": state.get("verification_discrepancies", []),
        "warnings": state.get("validation_warnings", []),
        "items_count": len(items),
        "processing_steps": state.get("processing_steps", []),
    }

    status_map = {"approved": "clean", "review": "review", "rejected": "rejected"}
    output_writer.write_receipt(
        store="ah",
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

def should_verify(state: AHPipelineState) -> Literal["verify", "finalize"]:
    """Decide if AI verification is needed."""
    # Always verify if there are errors
    if state.get("errors"):
        return "verify"

    # Always verify if validation failed
    if not state.get("validation_passed"):
        return "verify"

    # Skip verification only if high confidence from both sources agreeing
    det_count = len(state.get("deterministic_items", []))
    llm_count = len(state.get("llm_items", []))

    if det_count > 0 and det_count == llm_count and det_count >= 3:
        # Both sources agree on item count, skip expensive verification
        return "finalize"

    return "verify"


def should_correct(state: AHPipelineState) -> Literal["correct", "finalize"]:
    """Decide if correction is needed after verification."""
    # Prevent infinite loops
    iterations = state.get("correction_iterations", 0)
    if iterations >= MAX_CORRECTION_ITERATIONS:
        return "finalize"

    discrepancies = state.get("verification_discrepancies", [])
    confidence = state.get("verification_confidence", 0.0)

    # Only correct if there are real discrepancies (not just warnings)
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

def build_ah_pipeline(
    checkpoint_path: str = None,
) -> "CompiledGraph":
    """Build the complete AH pipeline graph with persistent checkpoints."""
    if checkpoint_path is None:
        checkpoint_path = str(Path(settings.CHECKPOINTS_DIR) / "ah_pipeline.db")

    Path(checkpoint_path).parent.mkdir(parents=True, exist_ok=True)

    graph = StateGraph(AHPipelineState)

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

    # Conditional: validate → verify or finalize
    graph.add_conditional_edges(
        "validate",
        should_verify,
        {"verify": "verify", "finalize": "finalize"}
    )

    # Conditional: verify → correct or finalize
    graph.add_conditional_edges(
        "verify",
        should_correct,
        {"correct": "correct", "finalize": "finalize"}
    )

    # Loop back: correct → validate (with iteration limit)
    graph.add_edge("correct", "validate")

    # Final: finalize → END
    graph.add_edge("finalize", END)

    # Compile with SQLite checkpointer
    import sqlite3
    conn = sqlite3.connect(checkpoint_path, check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    checkpointer.setup()
    return graph.compile(checkpointer=checkpointer)


def run_ah_receipt(
    pipeline: "CompiledGraph",
    receipt_path: str,
    thread_id: str = None,
) -> AHPipelineState:
    """Run a single AH receipt through the pipeline."""
    if thread_id is None:
        thread_id = f"ah_{Path(receipt_path).stem}"

    # Initialize audit log
    audit = AuditLogger()
    audit.start_receipt(thread_id, receipt_path, "ah")

    initial_state: AHPipelineState = {
        "receipt_path": receipt_path,
        "thread_id": thread_id,
        "raw_text": "",
        "deterministic_items": [],
        "llm_items": [],
        "merged_items": [],
        "date_of_purchase": None,
        "date_from_filename": None,
        "subtotal": None,
        "total": None,
        "uw_voordeel": None,
        "statiegeld_total": 0.0,
        "bonus_discounts": [],
        "btw_9_base": None,
        "btw_9_amount": None,
        "btw_21_base": None,
        "btw_21_amount": None,
        "statiegeld_items": [],
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

    # Run pipeline
    result = pipeline.invoke(initial_state, config=config)

    return result
