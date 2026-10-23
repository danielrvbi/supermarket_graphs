"""
Normalization script: reads from processed_data, writes to normalized_data.

Usage:
    python -m v2.run_normalization              # Normalize all
    python -m v2.run_normalization --store ah   # AH only
    python -m v2.run_normalization --store jumbo # Jumbo only
    python -m v2.run_normalization --rebuild    # Clear and rebuild table
    python -m v2.run_normalization --dry-run    # Preview changes
    python -m v2.run_normalization --limit 100  # Process first 100 items

This script:
1. Reads raw items from processed_data table
2. Applies deterministic normalization rules (ported from V1 step2_normalization.py)
3. Writes cleaned items to normalized_data table
4. Prints summary statistics

No LLM calls - 100% deterministic.
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

from tqdm import tqdm

from v2.config.settings import settings
from v2.shared.database_writer import DatabaseWriter
from v2.normalization.normalizer import Normalizer


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Normalize processed receipt data (deterministic, no LLM)"
    )
    parser.add_argument(
        "--store",
        choices=["ah", "jumbo", "all"],
        default="all",
        help="Which store to normalize (default: all)",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Clear normalized_data table before running",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing to database",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of items to process (for testing)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed progress",
    )
    return parser.parse_args()


def print_summary(normalizer: Normalizer, db_writer: DatabaseWriter, dry_run: bool):
    """Print normalization summary."""
    stats = normalizer.get_stats()

    print("\n" + "=" * 60)
    print("NORMALIZATION SUMMARY")
    print("=" * 60)
    print(f"Mode:            {'DRY RUN' if dry_run else 'WRITE'}")
    print(f"Total items:     {stats['total_items']}")
    print(f"Kept items:      {stats['kept_items']}")
    print(f"Filtered out:    {stats['filtered_out']}")
    print()
    print("Rules applied:")
    for rule, count in sorted(stats["rules_applied"].items(), key=lambda x: -x[1]):
        print(f"  {rule:30} {count:5} times")
    print("=" * 60)

    if not dry_run:
        print()
        db_writer.print_normalization_stats()


def main():
    """Main entry point."""
    args = parse_args()

    print("=" * 60)
    print("V2 NORMALIZATION SCRIPT")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 60)
    print(f"Store:  {args.store}")
    print(f"Mode:   {'DRY RUN' if args.dry_run else 'WRITE'}")
    print(f"Rebuild: {args.rebuild}")
    if args.limit:
        print(f"Limit:  {args.limit} items")
    print()

    # Connect to database
    db_path = settings.PROCESSED_DB
    print(f"Database: {db_path}")
    db_writer = DatabaseWriter(db_path)

    # Clear table if rebuild requested
    if args.rebuild and not args.dry_run:
        print("Clearing normalized_data table...")
        db_writer.clear_normalized_table()
        print("Table cleared.")
        print()

    # Determine store filter
    store_filter: Optional[str] = None
    if args.store in ("ah", "jumbo"):
        store_filter = args.store

    # Read raw items from processed_data
    print("Reading raw items from processed_data...")
    raw_items = db_writer.read_processed_items(store=store_filter, limit=args.limit)
    print(f"Found {len(raw_items)} items to normalize")
    print()

    if not raw_items:
        print("No items to normalize!")
        return

    # Show sample of raw data
    if args.verbose:
        print("Sample raw items:")
        for item in raw_items[:3]:
            print(f"  - {item.get('item_name')} | {item.get('store')} | {item.get('date_of_purchase')}")
        print()

    # Normalize items
    print("Normalizing items...")
    normalizer = Normalizer()

    normalized_count = 0
    filtered_count = 0

    # Process with progress bar
    iterator = tqdm(raw_items, desc="Normalizing", unit="item", disable=not sys.stdout.isatty())

    for raw_item in iterator:
        # Normalize the item
        result = normalizer.normalize_item(raw_item)

        if result.filtered_out:
            filtered_count += 1
            continue

        # Write to database (unless dry run)
        if not args.dry_run:
            db_writer.insert_normalized_item(
                source_id=result.source_id,
                receipt_id=result.receipt_id,
                store=result.store,
                date_of_purchase=result.date_of_purchase,
                month_of_purchase=result.month_of_purchase,
                item_name=result.item_name,
                measurement_type=result.measurement_type,
                measurement_quantity=result.measurement_quantity,
                price_per_measurement_unit=result.price_per_measurement_unit,
                line_total_paid_amount=result.line_total_paid_amount,
                normalization_rules=result.normalization_rules,
            )

        normalized_count += 1

    print()
    print(f"Normalized: {normalized_count} items")
    print(f"Filtered:   {filtered_count} items")
    print()

    # Print summary
    print_summary(normalizer, db_writer, args.dry_run)

    if args.dry_run:
        print("\n[DRY RUN] No changes were written to the database.")
        print("Run without --dry-run to apply changes.")

    print()
    print(f"Finished: {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
