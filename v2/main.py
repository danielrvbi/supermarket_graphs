"""
V2 Pipeline Main Entry Point.

Usage:
    python -m v2.main ah <receipt_path>       # Process single AH receipt
    python -m v2.main jumbo <receipt_path>    # Process single Jumbo receipt
    python -m v2.main ah-batch <folder>       # Process all AH receipts in folder
    python -m v2.main jumbo-batch <folder>    # Process all Jumbo receipts in folder
    python -m v2.main test ah                 # Run AH live tests
    python -m v2.main test jumbo              # Run Jumbo live tests
    python -m v2.main test all                # Run all live tests
    python -m v2.main stats                   # Show processing statistics
    python -m v2.main normalize               # Normalize processed data (deterministic)
    python -m v2.main normalize --store ah    # Normalize AH only
    python -m v2.main normalize --rebuild     # Clear and rebuild normalized table
    python -m v2.main normalize --dry-run     # Preview normalization changes
    python -m v2.main inspect <thread_id>     # Inspect checkpoints for a receipt
"""

import sys
from pathlib import Path

from v2.config.settings import settings
from v2.shared.output_writer import OutputWriter


def process_single_ah(receipt_path: str):
    """Process a single AH receipt."""
    from v2.ah_pipeline.graph import build_ah_pipeline, run_ah_receipt

    print(f"Processing AH receipt: {receipt_path}")
    pipeline = build_ah_pipeline()
    result = run_ah_receipt(pipeline, receipt_path)

    print(f"\nResult: {result.get('final_status')}")
    print(f"Confidence: {result.get('overall_confidence', 0):.2f}")
    print(f"Items: {len(result.get('merged_items', []))}")


def process_single_jumbo(receipt_path: str):
    """Process a single Jumbo receipt."""
    from v2.jumbo_pipeline.graph import build_jumbo_pipeline, run_jumbo_receipt

    print(f"Processing Jumbo receipt: {receipt_path}")
    pipeline = build_jumbo_pipeline()
    result = run_jumbo_receipt(pipeline, receipt_path)

    print(f"\nResult: {result.get('final_status')}")
    print(f"Confidence: {result.get('overall_confidence', 0):.2f}")
    print(f"Items: {len(result.get('merged_items', []))}")


def process_batch_ah(folder: str):
    """Process all AH receipts in a folder."""
    from v2.ah_pipeline.graph import build_ah_pipeline, run_ah_receipt

    folder_path = Path(folder)
    pdf_files = sorted(folder_path.glob("*.pdf"))

    print(f"Found {len(pdf_files)} AH receipts to process")
    pipeline = build_ah_pipeline()

    for i, pdf_file in enumerate(pdf_files, 1):
        print(f"\n[{i}/{len(pdf_files)}] Processing: {pdf_file.name}")
        try:
            run_ah_receipt(pipeline, str(pdf_file))
        except Exception as e:
            print(f"  ERROR: {e}")

    # Show stats
    OutputWriter().print_stats()


def process_batch_jumbo(folder: str):
    """Process all Jumbo receipts in a folder."""
    from v2.jumbo_pipeline.graph import build_jumbo_pipeline, run_jumbo_receipt

    folder_path = Path(folder)
    png_files = sorted(folder_path.glob("*.png"))

    print(f"Found {len(png_files)} Jumbo receipts to process")
    pipeline = build_jumbo_pipeline()

    for i, png_file in enumerate(png_files, 1):
        print(f"\n[{i}/{len(png_files)}] Processing: {png_file.name}")
        try:
            run_jumbo_receipt(pipeline, str(png_file))
        except Exception as e:
            print(f"  ERROR: {e}")

    # Show stats
    OutputWriter().print_stats()


def show_stats():
    """Show processing statistics."""
    OutputWriter().print_stats()


def run_normalization():
    """Run normalization script."""
    from v2.run_normalization import main as normalize_main
    normalize_main()


def inspect_receipt(thread_id: str, store: str = "ah"):
    """Inspect checkpoints for a receipt."""
    from v2.debug.inspect import inspect_receipt as do_inspect
    do_inspect(thread_id, store)


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "ah" and len(sys.argv) >= 3:
        process_single_ah(sys.argv[2])
    elif command == "jumbo" and len(sys.argv) >= 3:
        process_single_jumbo(sys.argv[2])
    elif command == "ah-batch" and len(sys.argv) >= 3:
        process_batch_ah(sys.argv[2])
    elif command == "jumbo-batch" and len(sys.argv) >= 3:
        process_batch_jumbo(sys.argv[2])
    elif command == "test" and len(sys.argv) >= 3:
        from v2.tests.test_live import main as test_main
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        test_main()
    elif command == "stats":
        show_stats()
    elif command == "normalize":
        # Pass remaining args to normalization script
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        run_normalization()
    elif command == "inspect" and len(sys.argv) >= 3:
        store = sys.argv[3] if len(sys.argv) >= 4 else "ah"
        inspect_receipt(sys.argv[2], store)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
