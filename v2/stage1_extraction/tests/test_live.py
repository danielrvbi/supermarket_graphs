"""
Live test runner for V2 pipeline.

Tests 4 AH + 4 Jumbo receipts: earliest, latest, and middle files.
Receipt paths are read from v2/stage1_extraction/tests/test_files.local.json (gitignored);
copy v2/stage1_extraction/tests/test_files.example.json to create it.

Usage:
    python -m v2.stage1_extraction.tests.test_live ah       # Test 4 AH receipts
    python -m v2.stage1_extraction.tests.test_live jumbo    # Test 4 Jumbo receipts
    python -m v2.stage1_extraction.tests.test_live all      # Test all 8 receipts
    python -m v2.stage1_extraction.tests.test_live inspect  # Inspect checkpoints for test receipts
"""

import sys
import json
import tempfile
from pathlib import Path
from datetime import datetime

from v2.common.settings import settings
from v2.stage1_extraction.ah.graph import build_ah_pipeline, run_ah_receipt
from v2.stage1_extraction.jumbo.graph import build_jumbo_pipeline, run_jumbo_receipt
from v2.stage1_extraction.audit_log import AuditLogger
from v2.common.cost_report import CostReport
from v2.stage1_extraction.output_writer import OutputWriter
from v2.stage1_extraction.store import ProcessedDataStore
from v2.stage1_extraction.debug.inspect import inspect_receipt, list_checkpoints


# ============================================================
# Test file definitions
# ============================================================

# Receipt paths are personal, so they live in a gitignored local file.
# Copy test_files.example.json to test_files.local.json and fill in your own.
TEST_FILES_PATH = Path(__file__).parent / "test_files.local.json"


def load_test_files() -> dict:
    if not TEST_FILES_PATH.exists():
        return {"ah": [], "jumbo": []}
    with open(TEST_FILES_PATH) as f:
        return json.load(f)


_test_files = load_test_files()
AH_TEST_FILES = _test_files.get("ah", [])
JUMBO_TEST_FILES = _test_files.get("jumbo", [])


# ============================================================
# Test runners
# ============================================================

def test_ah_receipt(pipeline, test_file: dict) -> dict:
    """Run a single AH test receipt through the pipeline."""
    isolate_live_tests()
    print(f"\n{'='*70}")
    print(f"Testing: {test_file['id']} ({test_file['period']})")
    print(f"File: {test_file['path']}")
    print(f"Date: {test_file['date']}")
    print(f"{'='*70}")

    thread_id = f"test_ah_{test_file['id']}"

    try:
        result = run_ah_receipt(pipeline, test_file["path"], thread_id=thread_id)

        # Print results
        print(f"\n--- Results ---")
        print(f"Status: {result.get('final_status', 'unknown')}")
        print(f"Confidence: {result.get('overall_confidence', 0):.2f}")
        print(f"Items extracted: {len(result.get('merged_items', []))}")
        print(f"Deterministic items: {len(result.get('deterministic_items', []))}")
        print(f"LLM items: {len(result.get('llm_items', []))}")
        print(f"Validation passed: {result.get('validation_passed', False)}")
        print(f"Arithmetic OK: {result.get('arithmetic_ok', False)}")
        print(f"Reconciliation OK: {result.get('reconciliation_ok', False)}")
        print(f"Verification confidence: {result.get('verification_confidence', 0):.2f}")
        print(f"Processing steps: {' → '.join(result.get('processing_steps', []))}")

        if result.get("errors"):
            print(f"\nErrors:")
            for err in result["errors"]:
                print(f"  - {err}")

        if result.get("validation_errors"):
            print(f"\nValidation errors:")
            for err in result["validation_errors"]:
                print(f"  - {err}")

        if result.get("verification_discrepancies"):
            print(f"\nVerification discrepancies:")
            for disc in result["verification_discrepancies"][:5]:
                print(f"  - {disc}")

        # Print items
        print(f"\n--- Extracted Items ---")
        for item in result.get("merged_items", []):
            print(f"  • {item.get('item_name')}: "
                  f"{item.get('measurement_quantity')} {item.get('measurement_type')}, "
                  f"€{item.get('line_total_paid_amount')} "
                  f"(unit: €{item.get('price_per_measurement_unit')})")

        # Print receipt metadata
        print(f"\n--- Receipt Metadata ---")
        print(f"Date: {result.get('date_of_purchase')}")
        print(f"Subtotal: €{result.get('subtotal')}")
        print(f"Total: €{result.get('total')}")
        print(f"Calculated total: €{result.get('calculated_total', 0):.2f}")

        return {
            "test_id": test_file["id"],
            "path": test_file["path"],
            "status": result.get("final_status"),
            "confidence": result.get("overall_confidence", 0),
            "items_count": len(result.get("merged_items", [])),
            "validation_passed": result.get("validation_passed", False),
            "verification_confidence": result.get("verification_confidence", 0),
            "errors": result.get("errors", []),
        }

    except Exception as e:
        print(f"\n❌ FAILED: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            "test_id": test_file["id"],
            "path": test_file["path"],
            "status": "failed",
            "error": str(e),
        }


def test_jumbo_receipt(pipeline, test_file: dict) -> dict:
    """Run a single Jumbo test receipt through the pipeline."""
    isolate_live_tests()
    print(f"\n{'='*70}")
    print(f"Testing: {test_file['id']} ({test_file['period']})")
    print(f"File: {test_file['path']}")
    print(f"Date: {test_file['date']}")
    print(f"Format: {test_file.get('format', 'unknown')}")
    print(f"{'='*70}")

    thread_id = f"test_jumbo_{test_file['id']}"

    try:
        result = run_jumbo_receipt(pipeline, test_file["path"], thread_id=thread_id)

        # Print results
        print(f"\n--- Results ---")
        print(f"Status: {result.get('final_status', 'unknown')}")
        print(f"Confidence: {result.get('overall_confidence', 0):.2f}")
        print(f"Items extracted: {len(result.get('merged_items', []))}")
        print(f"Deterministic items: {len(result.get('deterministic_items', []))}")
        print(f"LLM items: {len(result.get('llm_items', []))}")
        print(f"OCR quality: {result.get('ocr_quality_score', 0):.2f}")
        print(f"Validation passed: {result.get('validation_passed', False)}")
        print(f"Arithmetic OK: {result.get('arithmetic_ok', False)}")
        print(f"Reconciliation OK: {result.get('reconciliation_ok', False)}")
        print(f"Verification confidence: {result.get('verification_confidence', 0):.2f}")
        print(f"Processing steps: {' → '.join(result.get('processing_steps', []))}")

        if result.get("errors"):
            print(f"\nErrors:")
            for err in result["errors"]:
                print(f"  - {err}")

        if result.get("validation_errors"):
            print(f"\nValidation errors:")
            for err in result["validation_errors"]:
                print(f"  - {err}")

        if result.get("verification_discrepancies"):
            print(f"\nVerification discrepancies:")
            for disc in result["verification_discrepancies"][:5]:
                print(f"  - {disc}")

        # Print items
        print(f"\n--- Extracted Items ---")
        for item in result.get("merged_items", []):
            print(f"  • {item.get('item_name')}: "
                  f"{item.get('measurement_quantity')} {item.get('measurement_type')}, "
                  f"€{item.get('line_total_paid_amount')} "
                  f"(unit: €{item.get('price_per_measurement_unit')})")

        # Print receipt metadata
        print(f"\n--- Receipt Metadata ---")
        print(f"Date: {result.get('date_of_purchase')}")
        print(f"Store: {result.get('store_location')}")
        print(f"Total (incl. BTW): €{result.get('total_incl_btw')}")
        print(f"Total korting: €{result.get('total_korting')}")
        print(f"Calculated total: €{result.get('calculated_total', 0):.2f}")

        return {
            "test_id": test_file["id"],
            "path": test_file["path"],
            "status": result.get("final_status"),
            "confidence": result.get("overall_confidence", 0),
            "items_count": len(result.get("merged_items", [])),
            "ocr_quality": result.get("ocr_quality_score", 0),
            "validation_passed": result.get("validation_passed", False),
            "verification_confidence": result.get("verification_confidence", 0),
            "errors": result.get("errors", []),
        }

    except Exception as e:
        print(f"\n❌ FAILED: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            "test_id": test_file["id"],
            "path": test_file["path"],
            "status": "failed",
            "error": str(e),
        }


# ============================================================
# Main test runners
# ============================================================

_LIVE_TEST_ROOT = None


def isolate_live_tests():
    """Keep live integration runs out of the real purchase database."""
    global _LIVE_TEST_ROOT
    if _LIVE_TEST_ROOT is None:
        _LIVE_TEST_ROOT = Path(tempfile.mkdtemp(prefix="supermkt-live-tests-"))
        settings.PROCESSED_DIR = str(_LIVE_TEST_ROOT / "processed")
        settings.PROCESSED_DB = str(_LIVE_TEST_ROOT / "processed" / "processed_data.db")
        settings.CHECKPOINTS_DIR = str(_LIVE_TEST_ROOT / "checkpoints")
        settings.TOKEN_USAGE_DB = str(_LIVE_TEST_ROOT / "checkpoints" / "token_usage.db")
        print(f"Isolated live-test outputs: {_LIVE_TEST_ROOT}")


def run_ah_tests():
    """Run all 4 AH test receipts."""
    isolate_live_tests()
    print("\n" + "#" * 70)
    print("# AH PIPELINE LIVE TEST")
    print("# Testing 4 receipts: earliest, early, middle, latest")
    print("#" * 70)

    # Build pipeline
    print("\nBuilding AH pipeline...")
    pipeline = build_ah_pipeline()
    print("Pipeline ready.")

    results = []
    for test_file in AH_TEST_FILES:
        result = test_ah_receipt(pipeline, test_file)
        results.append(result)

    # Summary
    print_summary("AH", results)
    return results


def run_jumbo_tests():
    """Run all 4 Jumbo test receipts."""
    isolate_live_tests()
    print("\n" + "#" * 70)
    print("# JUMBO PIPELINE LIVE TEST")
    print("# Testing 4 receipts: earliest, early, middle, latest")
    print("#" * 70)

    # Build pipeline
    print("\nBuilding Jumbo pipeline...")
    pipeline = build_jumbo_pipeline()
    print("Pipeline ready.")

    results = []
    for test_file in JUMBO_TEST_FILES:
        result = test_jumbo_receipt(pipeline, test_file)
        results.append(result)

    # Summary
    print_summary("Jumbo", results)
    return results


def print_summary(store: str, results: list):
    """Print test summary."""
    print("\n" + "=" * 70)
    print(f"{store} TEST SUMMARY")
    print("=" * 70)

    passed = sum(1 for r in results if r.get("status") == "approved")
    review = sum(1 for r in results if r.get("status") == "review")
    rejected = sum(1 for r in results if r.get("status") == "rejected")
    failed = sum(1 for r in results if r.get("status") == "failed")

    print(f"\nTotal: {len(results)}")
    print(f"  ✓ Approved: {passed}")
    print(f"  ⚠ Review:   {review}")
    print(f"  ✗ Rejected: {rejected}")
    print(f"  ❌ Failed:   {failed}")

    print(f"\nDetails:")
    for r in results:
        status_icon = {
            "approved": "✓",
            "review": "⚠",
            "rejected": "✗",
            "failed": "❌",
        }.get(r.get("status"), "?")
        print(f"  {status_icon} {r['test_id']}: {r.get('status')} "
              f"(conf: {r.get('confidence', 0):.2f}, "
              f"items: {r.get('items_count', 0)})")

    # Save results
    results_path = Path(settings.PROCESSED_DIR) / f"v2_test_results_{store.lower()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to: {results_path}")
    print("=" * 70)

    # Print cost report
    print_token_report()

    # Print output statistics
    print_output_stats()


def print_output_stats():
    """Print output statistics (files + database)."""
    print("\n" + "#" * 70)
    print("# OUTPUT STATISTICS")
    print("#" * 70)

    writer = OutputWriter()
    writer.print_stats()

    # Also print database stats
    db = ProcessedDataStore(settings.PROCESSED_DB)
    db.print_stats()

    print("#" * 70)


def print_token_report():
    """Print token usage and cost report."""
    print("\n" + "#" * 70)
    print("# TOKEN USAGE & COST REPORT")
    print("#" * 70)

    db_path = settings.TOKEN_USAGE_DB
    if not Path(db_path).exists():
        print("No token usage database found.")
        return

    report = CostReport(db_path)
    report.print_report()

    # Save report to file
    report_path = report.save_report()
    print(f"\nFull report saved to: {report_path}")
    print("#" * 70)


def inspect_test_checkpoints():
    """Inspect checkpoints for all test receipts."""
    print("\n" + "=" * 70)
    print("CHECKPOINT INSPECTION FOR TEST RECEIPTS")
    print("=" * 70)

    for test_file in AH_TEST_FILES:
        thread_id = f"test_ah_{test_file['id']}"
        inspect_receipt(thread_id, "ah")

    for test_file in JUMBO_TEST_FILES:
        thread_id = f"test_jumbo_{test_file['id']}"
        inspect_receipt(thread_id, "jumbo")


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()

    if command != "inspect" and not TEST_FILES_PATH.exists():
        print(f"Missing {TEST_FILES_PATH}. Copy test_files.example.json and fill in your receipt paths.")
        sys.exit(1)

    if command == "ah":
        run_ah_tests()
    elif command == "jumbo":
        run_jumbo_tests()
    elif command == "all":
        run_ah_tests()
        run_jumbo_tests()
    elif command == "inspect":
        inspect_test_checkpoints()
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
