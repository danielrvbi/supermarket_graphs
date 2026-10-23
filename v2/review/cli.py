"""
CLI tool for reviewing flagged receipts.

Usage:
    python -m v2.review.cli list
    python -m v2.review.cli show <receipt_path>
    python -m v2.review.cli approve <receipt_path>
    python -m v2.review.cli reject <receipt_path>
"""

import json
import sys
from pathlib import Path
from typing import Optional

from v2.config.settings import settings


def load_review_queue(store: str = "ah") -> dict:
    """Load the review queue for a store."""
    path = Path(settings.PROCESSED_DIR) / f"v2_{store}_review.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def load_clean(store: str = "ah") -> dict:
    """Load the clean (approved) receipts for a store."""
    path = Path(settings.PROCESSED_DIR) / f"v2_{store}_clean.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_clean(store: str, data: dict):
    """Save clean receipts."""
    path = Path(settings.PROCESSED_DIR) / f"v2_{store}_clean.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def save_review(store: str, data: dict):
    """Save review queue."""
    path = Path(settings.PROCESSED_DIR) / f"v2_{store}_review.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def cmd_list(store: str = "ah"):
    """List receipts in the review queue."""
    queue = load_review_queue(store)
    print(f"\n{'='*70}")
    print(f"Review Queue: {store.upper()} ({len(queue)} receipts)")
    print(f"{'='*70}\n")

    for i, (path, data) in enumerate(queue.items(), 1):
        meta = data.get("_metadata", {})
        confidence = meta.get("confidence", 0)
        print(f"{i}. {Path(path).name}")
        print(f"   Confidence: {confidence:.2f}")
        print(f"   Items: {len(data.get('items', []))}")
        if meta.get("discrepancies"):
            print(f"   Discrepancies: {len(meta['discrepancies'])}")
        print()


def cmd_show(receipt_path: str, store: str = "ah"):
    """Show details of a receipt in the review queue."""
    queue = load_review_queue(store)

    if receipt_path not in queue:
        print(f"Receipt not found in review queue: {receipt_path}")
        return

    data = queue[receipt_path]
    meta = data.get("_metadata", {})

    print(f"\n{'='*70}")
    print(f"Receipt: {receipt_path}")
    print(f"{'='*70}")
    print(f"Date: {data.get('date_of_purchase', 'N/A')}")
    print(f"Confidence: {meta.get('confidence', 0):.2f}")
    print(f"OCR Quality: {meta.get('ocr_quality', 'N/A')}")
    print()

    print("Items:")
    for item in data.get("items", []):
        print(f"  - {item.get('item_name')}: "
              f"{item.get('measurement_quantity')} {item.get('measurement_type')}, "
              f"€{item.get('line_total_paid_amount')}")

    if meta.get("discrepancies"):
        print(f"\nDiscrepancies:")
        for d in meta["discrepancies"]:
            print(f"  - {d}")

    if meta.get("warnings"):
        print(f"\nWarnings:")
        for w in meta["warnings"]:
            print(f"  - {w}")

    print(f"\n{'='*70}")


def cmd_approve(receipt_path: str, store: str = "ah"):
    """Approve a receipt from the review queue (move to clean)."""
    queue = load_review_queue(store)
    clean = load_clean(store)

    if receipt_path not in queue:
        print(f"Receipt not found in review queue: {receipt_path}")
        return

    # Move to clean
    data = queue.pop(receipt_path)
    # Remove metadata before adding to clean (or keep it)
    clean[receipt_path] = data

    save_review(store, queue)
    save_clean(store, clean)

    print(f"✓ Approved: {receipt_path}")
    print(f"  Review queue: {len(queue)} remaining")
    print(f"  Clean: {len(clean)} total")


def cmd_reject(receipt_path: str, store: str = "ah"):
    """Reject a receipt from the review queue."""
    queue = load_review_queue(store)

    if receipt_path not in queue:
        print(f"Receipt not found in review queue: {receipt_path}")
        return

    # Remove from queue
    del queue[receipt_path]
    save_review(store, queue)

    print(f"✗ Rejected: {receipt_path}")
    print(f"  Review queue: {len(queue)} remaining")


def main():
    """Main CLI entry point."""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]
    store = "ah"  # default

    # Parse store flag
    args = sys.argv[2:]
    if "--jumbo" in args:
        store = "jumbo"
        args.remove("--jumbo")
    elif "--ah" in args:
        args.remove("--ah")

    if command == "list":
        cmd_list(store)
    elif command == "show" and len(args) >= 1:
        cmd_show(args[0], store)
    elif command == "approve" and len(args) >= 1:
        cmd_approve(args[0], store)
    elif command == "reject" and len(args) >= 1:
        cmd_reject(args[0], store)
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
