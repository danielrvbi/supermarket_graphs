"""
V2 Pipeline Main Entry Point.

Stage 1 - extraction (raw receipts -> processed_data):
    python -m v2.main extract ah <receipt_path>       # Process single AH receipt
    python -m v2.main extract jumbo <receipt_path>    # Process single Jumbo receipt
    python -m v2.main extract-batch ah <folder>       # Process all AH receipts in folder
    python -m v2.main extract-batch jumbo <folder>    # Process all Jumbo receipts in folder
    python -m v2.main extract-all                     # Process all unprocessed receipts
    python -m v2.main test ah|jumbo|all               # Run live extraction tests
    python -m v2.main inspect <thread_id> [ah|jumbo]  # Inspect checkpoints for a receipt
    python -m v2.main stats                           # Show processing statistics

Stage 2 - normalization (processed_data -> normalized_data):
    python -m v2.main normalize               # Normalize processed data (deterministic)
    python -m v2.main normalize --store ah    # Normalize AH only
    python -m v2.main normalize --rebuild     # Clear and rebuild normalized table
    python -m v2.main normalize --dry-run     # Preview normalization changes

Stage 3 - classification (normalized_data -> classified_data):
    python -m v2.main classify                # Classify new items (old_data -> embeddings -> Tavily -> LLM)
    python -m v2.main classify --dry-run      # Preview tiers without Tavily/LLM calls
    python -m v2.main classify --limit 20     # Classify first 20 new items
    python -m v2.main classify --no-search    # Skip Tavily
    python -m v2.main review-labels list      # Items flagged for review
    python -m v2.main review-labels set <item> <category> <subcategory>

Stage 3D - ingredients (item_labels + v2 taxonomy -> JSONL proposals -> product_ingredient):
    python -m v2.main ingredients assign --dry-run --no-llm   # Batches + cost estimate, no API calls
    python -m v2.main ingredients assign --subcategory "Verduras > Lechuga y Ensaladas"   # Writes a JSONL
    python -m v2.main ingredients apply --subcategory "Verduras > Lechuga y Ensaladas"    # Checked JSONL -> db
    python -m v2.main ingredients status

Aliases: ah, jumbo, ah-batch, jumbo-batch (same as extract / extract-batch).
"""

import sys

from v2.stage1_extraction.output_writer import OutputWriter


ALIASES = {
    "ah": ("extract", "ah"),
    "jumbo": ("extract", "jumbo"),
    "ah-batch": ("extract-batch", "ah"),
    "jumbo-batch": ("extract-batch", "jumbo"),
}


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()
    args = sys.argv[2:]

    if command in ALIASES:
        command, store = ALIASES[command]
        args = [store] + args

    if command == "extract" and len(args) >= 2 and args[0] in ("ah", "jumbo"):
        from v2.stage1_extraction.run import process_single
        process_single(args[0], args[1])
    elif command == "extract-batch" and len(args) >= 2 and args[0] in ("ah", "jumbo"):
        from v2.stage1_extraction.run import process_folder
        process_folder(args[0], args[1])
    elif command == "extract-all":
        from v2.stage1_extraction.run import main as extract_all
        extract_all()
    elif command == "test" and args:
        from v2.stage1_extraction.tests.test_live import main as test_main
        sys.argv = [sys.argv[0]] + args
        test_main()
    elif command == "stats":
        OutputWriter().print_stats()
    elif command == "inspect" and args:
        from v2.stage1_extraction.debug.inspect import inspect_receipt
        store = args[1] if len(args) >= 2 else "ah"
        inspect_receipt(args[0], store)
    elif command == "normalize":
        # Pass remaining args to normalization script
        from v2.stage2_normalization.run import main as normalize_main
        sys.argv = [sys.argv[0]] + args
        normalize_main()
    elif command == "classify":
        from v2.stage3_classification.run import main as classify_main
        sys.argv = [sys.argv[0]] + args
        classify_main()
    elif command == "review-labels" and args:
        from v2.stage3b_classification_review.cli import main as review_main
        sys.argv = [sys.argv[0]] + args
        review_main()
    elif command == "ingredients" and args:
        from v2.stage3d_ingredients.cli import main as ingredients_main
        sys.argv = [sys.argv[0]] + args
        ingredients_main()
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
