#!/usr/bin/env python3
"""
Guarded cleanup: remove KOOPZEGELS records from product tables.

This script:
1. Rechecks the exact expected records exist before deleting.
2. Deletes them in a single transaction.
3. Verifies each deletion count matches expectations.
4. Verifies no unrelated rows were modified.
5. Rolls back on any mismatch.

Usage:
    python scripts/cleanup_non_products.py --dry-run   # Preview only
    python scripts/cleanup_non_products.py              # Execute
"""

import argparse
import collections
import sqlite3
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parents[1]))

from v2.common.settings import settings


# Exact records identified during inspection
EXPECTED_DELETIONS = [
    {
        "table": "classified_data",
        "sql": """
            DELETE FROM classified_data
            WHERE id IN (38996, 39069, 39273)
              AND normalized_id IN (7498, 7542, 7608)
              AND store = 'ah'
              AND item_name = 'KOOPZEGELS'
        """,
        "expected_count": 3,
        "guard_sql": """
            SELECT COUNT(*) FROM classified_data
            WHERE id IN (38996, 39069, 39273)
              AND normalized_id IN (7498, 7542, 7608)
              AND store = 'ah'
              AND item_name = 'KOOPZEGELS'
        """,
    },
    {
        "table": "normalized_data",
        "sql": """
            DELETE FROM normalized_data
            WHERE id IN (7498, 7542, 7608)
              AND source_id IN (1366, 1472, 3187)
              AND store = 'ah'
              AND item_name = 'KOOPZEGELS'
        """,
        "expected_count": 3,
        "guard_sql": """
            SELECT COUNT(*) FROM normalized_data
            WHERE id IN (7498, 7542, 7608)
              AND source_id IN (1366, 1472, 3187)
              AND store = 'ah'
              AND item_name = 'KOOPZEGELS'
        """,
    },
    {
        "table": "processed_data",
        "sql": """
            DELETE FROM processed_data
            WHERE id IN (1366, 1472, 3187)
              AND store = 'ah'
              AND item_name = 'KOOPZEGELS'
        """,
        "expected_count": 3,
        "guard_sql": """
            SELECT COUNT(*) FROM processed_data
            WHERE id IN (1366, 1472, 3187)
              AND store = 'ah'
              AND item_name = 'KOOPZEGELS'
        """,
    },
    {
        "table": "item_labels",
        "sql": """
            DELETE FROM item_labels
            WHERE item_name = 'KOOPZEGELS'
              AND store = 'ah'
              AND source = 'embed_llm'
        """,
        "expected_count": 1,
        "guard_sql": """
            SELECT COUNT(*) FROM item_labels
            WHERE item_name = 'KOOPZEGELS'
              AND store = 'ah'
              AND source = 'embed_llm'
        """,
    },
    {
        "table": "search_cache",
        "sql": """
            DELETE FROM search_cache
            WHERE store = 'ah'
              AND item_name = 'KOOPZEGELS'
              AND success = 0
        """,
        "expected_count": 1,
        "guard_sql": """
            SELECT COUNT(*) FROM search_cache
            WHERE store = 'ah'
              AND item_name = 'KOOPZEGELS'
              AND success = 0
        """,
    },
    {
        "table": "embedding_cache",
        "sql": """
            DELETE FROM embedding_cache
            WHERE model = 'mistral-embed'
              AND text = 'KOOPZEGELS'
        """,
        "expected_count": 1,
        "guard_sql": """
            SELECT COUNT(*) FROM embedding_cache
            WHERE model = 'mistral-embed'
              AND text = 'KOOPZEGELS'
        """,
    },
]

# Tables to snapshot for unrelated-row verification
SNAPSHOT_TABLES = [
    "processed_data",
    "normalized_data",
    "classified_data",
    "item_labels",
    "search_cache",
    "embedding_cache",
]


def snapshot_table(conn: sqlite3.Connection, table: str) -> collections.Counter:
    """Return a Counter of all rows in a table (for before/after comparison)."""
    rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
    return collections.Counter(rows)


def main():
    parser = argparse.ArgumentParser(description="Guarded KOOPZEGELS cleanup")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no changes")
    args = parser.parse_args()

    db_path = settings.PROCESSED_DB
    print(f"Database: {db_path}")
    print(f"Mode: {'DRY RUN (no changes)' if args.dry_run else 'EXECUTE'}\n")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        # ============================================================
        # Step 1: Pre-checks — verify expected records exist
        # ============================================================
        print("=" * 60)
        print("PRE-CHECKS")
        print("=" * 60)

        for spec in EXPECTED_DELETIONS:
            count = conn.execute(spec["guard_sql"]).fetchone()[0]
            status = "OK" if count == spec["expected_count"] else "MISMATCH"
            print(f"  {spec['table']:20} expected={spec['expected_count']} found={count} [{status}]")
            if count != spec["expected_count"]:
                print(f"\nERROR: {spec['table']} has {count} matching rows, expected {spec['expected_count']}")
                print("Aborting — database state does not match inspection. No changes made.")
                return 1

        # ============================================================
        # Step 2: Snapshot all tables for unrelated-row verification
        # ============================================================
        print("\n" + "=" * 60)
        print("SNAPSHOT (for unrelated-row verification)")
        print("=" * 60)

        before_snapshots = {}
        for table in SNAPSHOT_TABLES:
            before_snapshots[table] = snapshot_table(conn, table)
            print(f"  {table:20} {sum(before_snapshots[table].values()):5} rows")

        fk_before = set(conn.execute("PRAGMA foreign_key_check").fetchall())
        print(f"  Foreign key violations (pre-existing): {len(fk_before)}")

        if args.dry_run:
            print("\n[DRY RUN] No changes will be made.")
            print("Run without --dry-run to execute the cleanup.")
            return 0

        # ============================================================
        # Step 3: Execute deletions in a single transaction
        # ============================================================
        print("\n" + "=" * 60)
        print("EXECUTING DELETIONS")
        print("=" * 60)

        conn.execute("BEGIN IMMEDIATE")

        total_deleted = 0
        for spec in EXPECTED_DELETIONS:
            cursor = conn.execute(spec["sql"])
            deleted = cursor.rowcount
            total_deleted += deleted
            status = "OK" if deleted == spec["expected_count"] else "MISMATCH"
            print(f"  {spec['table']:20} deleted={deleted} expected={spec['expected_count']} [{status}]")
            if deleted != spec["expected_count"]:
                print(f"\nERROR: {spec['table']} deleted {deleted} rows, expected {spec['expected_count']}")
                print("Rolling back — no changes will be saved.")
                conn.rollback()
                return 1

        print(f"\n  Total deleted: {total_deleted} records")

        # ============================================================
        # Step 4: Verify no unrelated rows were modified
        # ============================================================
        print("\n" + "=" * 60)
        print("VERIFICATION")
        print("=" * 60)

        all_ok = True
        for table in SNAPSHOT_TABLES:
            after_snapshot = snapshot_table(conn, table)
            before = before_snapshots[table]
            after = after_snapshot

            # Rows that were deleted (in before but not in after)
            deleted_rows = before - after
            # Rows that were added or modified (in after but not in before)
            added_or_modified = after - before

            expected_deleted = sum(
                spec["expected_count"] for spec in EXPECTED_DELETIONS
                if spec["table"] == table
            )

            actual_deleted = sum(deleted_rows.values())

            print(f"\n  {table}:")
            print(f"    Rows before: {sum(before.values())}")
            print(f"    Rows after:  {sum(after.values())}")
            print(f"    Deleted:     {actual_deleted} (expected {expected_deleted})")
            print(f"    Added/modified: {sum(added_or_modified.values())} (must be 0)")

            if actual_deleted != expected_deleted:
                print(f"    [FAIL] Deleted count mismatch!")
                all_ok = False

            if sum(added_or_modified.values()) > 0:
                print(f"    [FAIL] Unrelated rows were modified!")
                all_ok = False

            # Verify all deleted rows are KOOPZEGELS-related
            if deleted_rows:
                cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]
                name_col_idx = None
                for idx, col in enumerate(cols):
                    if col in ("item_name", "text"):
                        name_col_idx = idx
                        break
                if name_col_idx is not None:
                    for row, count in deleted_rows.items():
                        if row[name_col_idx] != "KOOPZEGELS":
                            print(f"    [FAIL] Deleted row is not KOOPZEGELS: {row[name_col_idx]}")
                            all_ok = False

        # Check foreign key violations haven't increased
        fk_after = set(conn.execute("PRAGMA foreign_key_check").fetchall())
        print(f"\n  Foreign key violations after: {len(fk_after)} (was {len(fk_before)})")
        if len(fk_after) > len(fk_before):
            print(f"  [FAIL] New foreign key violations introduced!")
            all_ok = False
        elif fk_after != fk_before:
            # Same count but different violations — check if any new ones
            new_violations = fk_after - fk_before
            if new_violations:
                print(f"  [FAIL] New foreign key violations: {new_violations}")
                all_ok = False

        # Integrity check
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        print(f"  Integrity check: {integrity}")
        if integrity != "ok":
            print(f"  [FAIL] Integrity check failed!")
            all_ok = False

        # ============================================================
        # Step 5: Commit or rollback
        # ============================================================
        print("\n" + "=" * 60)
        if all_ok:
            conn.commit()
            print("RESULT: SUCCESS — all checks passed, changes committed.")
            print("=" * 60)
            return 0
        else:
            conn.rollback()
            print("RESULT: FAILED — verification failed, all changes rolled back.")
            print("=" * 60)
            return 1

    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
