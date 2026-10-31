"""
SQLite store for stage 2 output.

Stores one row per normalized item in the `normalized_data` table.
Input comes from stage 1's `processed_data` table.
"""

import json
import sqlite3
from datetime import datetime
from typing import List, Dict, Optional

from v2.common.db import SQLiteStore


SCHEMA = """
CREATE TABLE IF NOT EXISTS normalized_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Source reference
    source_id INTEGER REFERENCES processed_data(id),
    receipt_id TEXT NOT NULL,
    store TEXT NOT NULL,

    -- Dates (standardized)
    date_of_purchase TEXT,
    month_of_purchase TEXT,

    -- Normalized item fields
    item_name TEXT NOT NULL,
    measurement_type TEXT,
    measurement_quantity REAL,
    price_per_measurement_unit REAL,
    line_total_paid_amount REAL,

    -- Metadata
    normalized_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    normalization_rules TEXT,

    -- Prevent duplicates
    UNIQUE(receipt_id, item_name, measurement_quantity, line_total_paid_amount)
);

CREATE INDEX IF NOT EXISTS idx_normalized_store ON normalized_data(store);
CREATE INDEX IF NOT EXISTS idx_normalized_date ON normalized_data(date_of_purchase);
CREATE INDEX IF NOT EXISTS idx_normalized_month ON normalized_data(month_of_purchase);
CREATE INDEX IF NOT EXISTS idx_normalized_item ON normalized_data(item_name);
CREATE INDEX IF NOT EXISTS idx_normalized_receipt ON normalized_data(receipt_id);
CREATE INDEX IF NOT EXISTS idx_normalized_source ON normalized_data(source_id);
"""


class NormalizedDataStore(SQLiteStore):
    """
    SQLite store for the normalized_data table.

    Usage:
        db = NormalizedDataStore("processed/processed_data.db")
        db.insert_normalized_item(source_id=1, receipt_id="...", ...)
    """

    SCHEMA = SCHEMA

    def insert_normalized_item(
        self,
        source_id: Optional[int],
        receipt_id: str,
        store: str,
        date_of_purchase: Optional[str],
        month_of_purchase: Optional[str],
        item_name: str,
        measurement_type: Optional[str],
        measurement_quantity: Optional[float],
        price_per_measurement_unit: Optional[float],
        line_total_paid_amount: Optional[float],
        normalization_rules: List[str],
    ):
        """
        Insert a normalized item into the normalized_data table.

        Args:
            source_id: ID of the source row in processed_data
            receipt_id: Unique receipt identifier
            store: 'ah' or 'jumbo'
            date_of_purchase: Standardized date (YYYY-MM-DD)
            month_of_purchase: Month start date (YYYY-MM-01)
            item_name: Normalized item name
            measurement_type: 'discrete_units' or 'weight_in_grams'
            measurement_quantity: Normalized quantity
            price_per_measurement_unit: Price per unit
            line_total_paid_amount: Total amount paid
            normalization_rules: List of applied rule names
        """
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO normalized_data
                (source_id, receipt_id, store, date_of_purchase, month_of_purchase,
                 item_name, measurement_type, measurement_quantity,
                 price_per_measurement_unit, line_total_paid_amount,
                 normalization_rules, normalized_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(receipt_id,item_name,measurement_quantity,line_total_paid_amount)
                DO UPDATE SET source_id=excluded.source_id, store=excluded.store,
                    date_of_purchase=excluded.date_of_purchase, month_of_purchase=excluded.month_of_purchase,
                    measurement_type=excluded.measurement_type, price_per_measurement_unit=excluded.price_per_measurement_unit,
                    normalization_rules=excluded.normalization_rules, normalized_at=excluded.normalized_at
                """,
                (
                    source_id,
                    receipt_id,
                    store,
                    date_of_purchase,
                    month_of_purchase,
                    item_name,
                    measurement_type,
                    measurement_quantity,
                    price_per_measurement_unit,
                    line_total_paid_amount,
                    json.dumps(normalization_rules),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def clear_normalized_table(self):
        """Delete all rows from normalized_data table."""
        conn = self._connect()
        try:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='classified_data'").fetchone():
                if conn.execute("SELECT 1 FROM classified_data LIMIT 1").fetchone():
                    raise ValueError("Classified output exists; use a coordinated rebuild instead of clearing normalized rows")
            conn.execute("DELETE FROM normalized_data")
            conn.commit()
        finally:
            conn.close()

    def get_normalized_items(
        self,
        store: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict]:
        """
        Query items from normalized_data table.

        Args:
            store: Filter by store ('ah' or 'jumbo')
            limit: Maximum number of rows to return

        Returns:
            List of item dictionaries
        """
        conn = self._connect()
        conn.row_factory = sqlite3.Row

        query = "SELECT * FROM normalized_data WHERE 1=1"
        params = []

        if store:
            query += " AND store = ?"
            params.append(store)

        query += " ORDER BY normalized_at DESC"

        if limit:
            query += " LIMIT ?"
            params.append(limit)

        cursor = conn.execute(query, params)
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return results

    def get_normalization_stats(self) -> Dict:
        """Get statistics about normalized data."""
        conn = self._connect()

        # Total counts
        cursor = conn.execute("""
            SELECT
                COUNT(*) as total_items,
                COUNT(DISTINCT receipt_id) as total_receipts,
                COUNT(DISTINCT store) as stores
            FROM normalized_data
        """)
        row = cursor.fetchone()

        # By store
        cursor = conn.execute("""
            SELECT store, COUNT(*) as items, COUNT(DISTINCT receipt_id) as receipts
            FROM normalized_data
            GROUP BY store
        """)
        by_store = {r[0]: {"items": r[1], "receipts": r[2]} for r in cursor.fetchall()}

        # Date range
        cursor = conn.execute("""
            SELECT MIN(date_of_purchase), MAX(date_of_purchase)
            FROM normalized_data
            WHERE date_of_purchase IS NOT NULL
        """)
        date_range = cursor.fetchone()

        # Top normalization rules
        cursor = conn.execute("""
            SELECT normalization_rules, COUNT(*) as count
            FROM normalized_data
            WHERE normalization_rules IS NOT NULL
            GROUP BY normalization_rules
            ORDER BY count DESC
            LIMIT 10
        """)
        top_rules = [(r[0], r[1]) for r in cursor.fetchall()]

        conn.close()

        return {
            "total_items": row[0] or 0,
            "total_receipts": row[1] or 0,
            "stores": row[2] or 0,
            "by_store": by_store,
            "date_range": {
                "earliest": date_range[0] if date_range else None,
                "latest": date_range[1] if date_range else None,
            },
            "top_rule_combinations": top_rules,
        }

    def print_normalization_stats(self):
        """Print normalized data statistics."""
        stats = self.get_normalization_stats()

        print("=" * 50)
        print("NORMALIZED DATA STATISTICS")
        print("=" * 50)
        print(f"Database: {self.db_path}")
        print()
        print(f"Total items:     {stats['total_items']}")
        print(f"Total receipts:  {stats['total_receipts']}")
        print(f"Stores:          {stats['stores']}")
        print()
        print("By Store:")
        for store, data in stats["by_store"].items():
            print(f"  {store:10} | {data['receipts']:3} receipts | {data['items']:4} items")
        print()
        if stats["date_range"]["earliest"]:
            print(f"Date range: {stats['date_range']['earliest']} to {stats['date_range']['latest']}")
        print("=" * 50)
