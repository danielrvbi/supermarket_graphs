"""
SQLite store for stage 1 output.

Stores one row per item in the `processed_data` table.
Only clean (approved) receipts are inserted.
"""

import sqlite3
from datetime import datetime
from typing import List, Dict, Optional

from v2.common.db import SQLiteStore


SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Receipt identification
    receipt_id TEXT NOT NULL,
    receipt_path TEXT NOT NULL,
    receipt_json_path TEXT NOT NULL,
    store TEXT NOT NULL,

    -- Receipt metadata (repeated for each item row)
    date_of_purchase TEXT,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Item details (one row per item)
    item_index INTEGER NOT NULL,
    item_name TEXT NOT NULL,
    measurement_type TEXT,
    measurement_quantity REAL,
    price_per_measurement_unit REAL,
    line_total_paid_amount REAL,

    -- Processing metadata
    confidence REAL,

    -- Prevent duplicates
    UNIQUE(receipt_id, item_index)
);

CREATE INDEX IF NOT EXISTS idx_processed_data_store ON processed_data(store);
CREATE INDEX IF NOT EXISTS idx_processed_data_date ON processed_data(date_of_purchase);
CREATE INDEX IF NOT EXISTS idx_processed_data_item ON processed_data(item_name);
CREATE INDEX IF NOT EXISTS idx_processed_data_receipt ON processed_data(receipt_id);
CREATE INDEX IF NOT EXISTS idx_processed_data_processed ON processed_data(processed_at);
"""


class ProcessedDataStore(SQLiteStore):
    """
    SQLite store for the processed_data table.

    Usage:
        db = ProcessedDataStore("processed/processed_data.db")
        db.insert_receipt(
            receipt_id="ah_AH_kassabon_2024-03-08_1621_1080",
            receipt_path="raw_receipts/ah/AH_kassabon_2024-03-08_1621_1080.pdf",
            receipt_json_path="processed/clean/ah/AH_kassabon_2024-03-08_1621_1080.json",
            store="ah",
            date_of_purchase="2024/03/08",
            items=[...],
            confidence=0.99,
        )
    """

    SCHEMA = SCHEMA

    def insert_receipt(
        self,
        receipt_id: str,
        receipt_path: str,
        receipt_json_path: str,
        store: str,
        date_of_purchase: Optional[str],
        items: List[Dict],
        confidence: float,
    ):
        """
        Insert all items from a receipt into processed_data table.

        Args:
            receipt_id: Unique receipt identifier
            receipt_path: Original receipt file path
            receipt_json_path: Path to the clean JSON file
            store: 'ah' or 'jumbo'
            date_of_purchase: Purchase date string
            items: List of item dicts
            confidence: Receipt confidence score
        """
        conn = self._connect()
        try:
            processed_at = datetime.now().isoformat()

            conn.execute("BEGIN IMMEDIATE")
            has_normalized = conn.execute("SELECT 1 FROM sqlite_master WHERE name='normalized_data'").fetchone()
            for row in conn.execute("SELECT id,item_index,item_name,measurement_type,measurement_quantity,"
                                    "price_per_measurement_unit,line_total_paid_amount,date_of_purchase,store "
                                    "FROM processed_data WHERE receipt_id=?", (receipt_id,)).fetchall():
                if has_normalized and conn.execute("SELECT 1 FROM normalized_data WHERE source_id=?", (row[0],)).fetchone():
                    incoming = items[row[1]] if row[1] < len(items) else None
                    values = None if incoming is None else tuple(incoming.get(k) for k in (
                        "item_name", "measurement_type", "measurement_quantity",
                        "price_per_measurement_unit", "line_total_paid_amount",
                    )) + (date_of_purchase, store)
                    if values != row[2:]:
                        raise ValueError("Referenced receipt item changed or removed; coordinated downstream refresh required")

            for idx, item in enumerate(items):
                conn.execute(
                    """
                    INSERT INTO processed_data
                    (receipt_id, receipt_path, receipt_json_path, store,
                     date_of_purchase, processed_at, item_index, item_name,
                     measurement_type, measurement_quantity,
                     price_per_measurement_unit, line_total_paid_amount, confidence)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(receipt_id,item_index) DO UPDATE SET
                        receipt_path=excluded.receipt_path, receipt_json_path=excluded.receipt_json_path,
                        store=excluded.store, date_of_purchase=excluded.date_of_purchase,
                        processed_at=excluded.processed_at, item_name=excluded.item_name,
                        measurement_type=excluded.measurement_type, measurement_quantity=excluded.measurement_quantity,
                        price_per_measurement_unit=excluded.price_per_measurement_unit,
                        line_total_paid_amount=excluded.line_total_paid_amount, confidence=excluded.confidence
                    """,
                    (
                        receipt_id,
                        receipt_path,
                        receipt_json_path,
                        store,
                        date_of_purchase,
                        processed_at,
                        idx,
                        item.get("item_name"),
                        item.get("measurement_type"),
                        item.get("measurement_quantity"),
                        item.get("price_per_measurement_unit"),
                        item.get("line_total_paid_amount"),
                        confidence,
                    ),
                )
            conn.execute("DELETE FROM processed_data WHERE receipt_id=? AND item_index>=?", (receipt_id, len(items)))
            conn.commit()
        finally:
            conn.close()

    def receipt_exists(self, receipt_id: str) -> bool:
        """Check if a receipt already exists in the database."""
        conn = self._connect()
        cursor = conn.execute(
            "SELECT 1 FROM processed_data WHERE receipt_id = ? LIMIT 1",
            (receipt_id,),
        )
        result = cursor.fetchone() is not None
        conn.close()
        return result

    def get_stats(self) -> Dict:
        """Get database statistics."""
        conn = self._connect()

        # Total counts
        cursor = conn.execute("""
            SELECT
                COUNT(DISTINCT receipt_id) as total_receipts,
                COUNT(*) as total_items,
                COUNT(DISTINCT store) as stores
            FROM processed_data
        """)
        row = cursor.fetchone()

        # By store
        cursor = conn.execute("""
            SELECT store, COUNT(DISTINCT receipt_id) as receipts, COUNT(*) as items
            FROM processed_data
            GROUP BY store
        """)
        by_store = {r[0]: {"receipts": r[1], "items": r[2]} for r in cursor.fetchall()}

        # Date range
        cursor = conn.execute("""
            SELECT MIN(date_of_purchase), MAX(date_of_purchase)
            FROM processed_data
            WHERE date_of_purchase IS NOT NULL
        """)
        date_range = cursor.fetchone()

        conn.close()

        return {
            "total_receipts": row[0] or 0,
            "total_items": row[1] or 0,
            "stores": row[2] or 0,
            "by_store": by_store,
            "date_range": {
                "earliest": date_range[0] if date_range else None,
                "latest": date_range[1] if date_range else None,
            },
        }

    def print_stats(self):
        """Print database statistics."""
        stats = self.get_stats()

        print("=" * 50)
        print("PROCESSED DATA DATABASE STATISTICS")
        print("=" * 50)
        print(f"Database: {self.db_path}")
        print()
        print(f"Total receipts:  {stats['total_receipts']}")
        print(f"Total items:     {stats['total_items']}")
        print(f"Stores:          {stats['stores']}")
        print()
        print("By Store:")
        for store, data in stats["by_store"].items():
            print(f"  {store:10} | {data['receipts']:3} receipts | {data['items']:4} items")
        print()
        if stats["date_range"]["earliest"]:
            print(f"Date range: {stats['date_range']['earliest']} to {stats['date_range']['latest']}")
        print("=" * 50)

    def query_items(
        self,
        store: Optional[str] = None,
        item_name: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """Query items with filters."""
        conn = self._connect()
        conn.row_factory = sqlite3.Row

        query = "SELECT * FROM processed_data WHERE 1=1"
        params = []

        if store:
            query += " AND store = ?"
            params.append(store)
        if item_name:
            query += " AND item_name LIKE ?"
            params.append(f"%{item_name}%")
        if date_from:
            query += " AND date_of_purchase >= ?"
            params.append(date_from)
        if date_to:
            query += " AND date_of_purchase <= ?"
            params.append(date_to)

        query += " ORDER BY processed_at DESC LIMIT ?"
        params.append(limit)

        cursor = conn.execute(query, params)
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return results

    def get_item_history(self, item_name: str) -> List[Dict]:
        """Get price history for a specific item."""
        conn = self._connect()
        conn.row_factory = sqlite3.Row

        cursor = conn.execute(
            """
            SELECT date_of_purchase, store, price_per_measurement_unit,
                   line_total_paid_amount, measurement_quantity, receipt_id
            FROM processed_data
            WHERE item_name = ? AND price_per_measurement_unit IS NOT NULL
            ORDER BY date_of_purchase
            """,
            (item_name,),
        )
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return results

    def read_processed_items(
        self,
        store: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict]:
        """
        Read raw items from processed_data table (input to stage 2).

        Args:
            store: Filter by store ('ah' or 'jumbo')
            limit: Maximum number of rows to return

        Returns:
            List of raw item dictionaries
        """
        conn = self._connect()
        conn.row_factory = sqlite3.Row

        query = "SELECT * FROM processed_data WHERE 1=1"
        params = []

        if store:
            query += " AND store = ?"
            params.append(store)

        query += " ORDER BY receipt_id, item_index"

        if limit:
            query += " LIMIT ?"
            params.append(limit)

        cursor = conn.execute(query, params)
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return results
