"""
SQLite store for stage 3 output.

Tables (all in processed/processed_data.db):
- item_labels:     one label per unique item name (the growing product dictionary)
- search_cache:    Tavily results per (store, item_name), so a product is never searched twice
- embedding_cache: embedding vectors per (model, text)
- classified_data: normalized_data rows joined with their labels (rebuilt each run)
"""

import json
import sqlite3
from datetime import datetime
from typing import Dict, Iterable, List, Optional

import numpy as np

from v2.common.db import SQLiteStore


SCHEMA = """
CREATE TABLE IF NOT EXISTS item_labels (
    item_name TEXT PRIMARY KEY,
    store TEXT,
    producto_es TEXT,
    category TEXT NOT NULL,
    subcategory TEXT NOT NULL,
    source TEXT NOT NULL,           -- old_data | embed_llm | search_llm | manual
    confidence REAL,
    needs_review INTEGER DEFAULT 0,
    evidence TEXT,                  -- JSON: neighbours, search query, llm reasoning
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_item_labels_source ON item_labels(source);
CREATE INDEX IF NOT EXISTS idx_item_labels_review ON item_labels(needs_review);

CREATE TABLE IF NOT EXISTS search_cache (
    store TEXT NOT NULL,
    item_name TEXT NOT NULL,
    query TEXT NOT NULL,
    success INTEGER NOT NULL,
    results TEXT,                   -- JSON list of {url, title, content}
    error TEXT,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (store, item_name)
);

CREATE TABLE IF NOT EXISTS embedding_cache (
    model TEXT NOT NULL,
    text TEXT NOT NULL,
    vector BLOB NOT NULL,           -- float32 bytes
    PRIMARY KEY (model, text)
);

CREATE TABLE IF NOT EXISTS classified_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    normalized_id INTEGER REFERENCES normalized_data(id),
    receipt_id TEXT NOT NULL,
    store TEXT NOT NULL,
    date_of_purchase TEXT,
    month_of_purchase TEXT,
    item_name TEXT NOT NULL,
    measurement_type TEXT,
    measurement_quantity REAL,
    price_per_measurement_unit REAL,
    line_total_paid_amount REAL,
    producto_es TEXT,
    category TEXT,
    subcategory TEXT,
    label_source TEXT,
    confidence REAL,
    needs_review INTEGER,
    classified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_classified_category ON classified_data(category);
CREATE INDEX IF NOT EXISTS idx_classified_month ON classified_data(month_of_purchase);
CREATE INDEX IF NOT EXISTS idx_classified_item ON classified_data(item_name);
"""

# Sources whose labels are trusted enough to act as neighbours for new items
TRUSTED_SOURCES = ("old_data", "manual")


class ClassificationStore(SQLiteStore):
    """
    SQLite store for the stage 3 tables.

    Usage:
        db = ClassificationStore("processed/processed_data.db")
        db.get_label("AH KIPFILET")
    """

    SCHEMA = SCHEMA

    # ------------------------------------------------------------------
    # item_labels
    # ------------------------------------------------------------------

    def upsert_label(
        self,
        item_name: str,
        category: str,
        subcategory: str,
        source: str,
        producto_es: Optional[str] = None,
        store: Optional[str] = None,
        confidence: Optional[float] = None,
        needs_review: bool = False,
        evidence: Optional[Dict] = None,
        overwrite_sources: Optional[Iterable[str]] = None,
    ) -> bool:
        """
        Insert or update a label. Return whether a row was written.

        Args:
            overwrite_sources: if given, an existing row is only replaced when its
                source is in this list (e.g. seeding must never clobber manual labels).
        """
        values = (
            item_name, store, producto_es, category, subcategory, source, confidence,
            int(needs_review), json.dumps(evidence, ensure_ascii=False) if evidence else None,
            datetime.now().isoformat(),
        )
        sql = """
            INSERT INTO item_labels
            (item_name, store, producto_es, category, subcategory, source, confidence,
             needs_review, evidence, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(item_name) DO UPDATE SET
                store=excluded.store, producto_es=excluded.producto_es,
                category=excluded.category, subcategory=excluded.subcategory,
                source=excluded.source, confidence=excluded.confidence,
                needs_review=excluded.needs_review, evidence=excluded.evidence,
                updated_at=excluded.updated_at
        """
        params = list(values)
        if overwrite_sources is not None:
            sources = list(overwrite_sources)
            sql += f" WHERE item_labels.source IN ({','.join('?' * len(sources))})"
            params += sources

        conn = self._connect()
        try:
            cur = conn.execute(sql, params)
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def get_label(self, item_name: str) -> Optional[Dict]:
        """Get the label for one item name."""
        rows = self._query("SELECT * FROM item_labels WHERE item_name = ?", [item_name])
        return rows[0] if rows else None

    def get_labels(
        self,
        sources: Optional[Iterable[str]] = None,
        needs_review: Optional[bool] = None,
    ) -> List[Dict]:
        """Query labels, optionally filtered by source and review flag."""
        query = "SELECT * FROM item_labels WHERE 1=1"
        params: list = []
        if sources is not None:
            sources = list(sources)
            query += f" AND source IN ({','.join('?' * len(sources))})"
            params += sources
        if needs_review is not None:
            query += " AND needs_review = ?"
            params.append(int(needs_review))
        query += " ORDER BY item_name"
        return self._query(query, params)

    def labelled_names(self) -> set:
        """All item names that already have a label."""
        return {r["item_name"] for r in self._query("SELECT item_name FROM item_labels")}

    def set_review_flag(self, item_name: str, needs_review: bool) -> bool:
        """Set/clear needs_review. Returns False if the item has no label."""
        conn = self._connect()
        try:
            cur = conn.execute(
                "UPDATE item_labels SET needs_review = ?, updated_at = ? WHERE item_name = ?",
                (int(needs_review), datetime.now().isoformat(), item_name),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def delete_labels(self, sources: Iterable[str]) -> int:
        """Explicitly delete labels from the given sources."""
        sources = list(sources)
        conn = self._connect()
        try:
            cur = conn.execute(
                f"DELETE FROM item_labels WHERE source IN ({','.join('?' * len(sources))})",
                sources,
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # search_cache
    # ------------------------------------------------------------------

    def get_search(self, store: str, item_name: str) -> Optional[Dict]:
        """Get a cached search result (results decoded from JSON)."""
        rows = self._query(
            "SELECT * FROM search_cache WHERE store = ? AND item_name = ?", [store, item_name]
        )
        if not rows:
            return None
        row = rows[0]
        row["results"] = json.loads(row["results"]) if row["results"] else []
        row["success"] = bool(row["success"])
        return row

    def save_search(
        self,
        store: str,
        item_name: str,
        query: str,
        success: bool,
        results: List[Dict],
        error: Optional[str] = None,
    ):
        """Cache a search result (successful or not)."""
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO search_cache
                (store, item_name, query, success, results, error, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    store, item_name, query, int(success),
                    json.dumps(results, ensure_ascii=False), error, datetime.now().isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # embedding_cache
    # ------------------------------------------------------------------

    def get_embeddings(self, model: str, texts: List[str]) -> Dict[str, np.ndarray]:
        """Get cached vectors for the given texts (missing texts are omitted)."""
        found: Dict[str, np.ndarray] = {}
        conn = self._connect()
        try:
            # Chunk to stay under SQLite's variable limit
            for i in range(0, len(texts), 500):
                chunk = texts[i:i + 500]
                cur = conn.execute(
                    f"SELECT text, vector FROM embedding_cache WHERE model = ? "
                    f"AND text IN ({','.join('?' * len(chunk))})",
                    [model, *chunk],
                )
                for text, blob in cur.fetchall():
                    found[text] = np.frombuffer(blob, dtype=np.float32)
        finally:
            conn.close()
        return found

    def save_embeddings(self, model: str, vectors: Dict[str, np.ndarray]):
        """Cache vectors."""
        conn = self._connect()
        try:
            conn.executemany(
                "INSERT OR REPLACE INTO embedding_cache (model, text, vector) VALUES (?, ?, ?)",
                [(model, t, np.asarray(v, dtype=np.float32).tobytes()) for t, v in vectors.items()],
            )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # normalized_data -> classified_data
    # ------------------------------------------------------------------

    def get_unique_items(self, store: Optional[str] = None) -> List[Dict]:
        """Unique (store, item_name) pairs from normalized_data with row counts."""
        query = """
            SELECT store, item_name, COUNT(*) AS n_rows
            FROM normalized_data
            WHERE 1=1
        """
        params: list = []
        if store:
            query += " AND store = ?"
            params.append(store)
        query += " GROUP BY store, item_name ORDER BY store, item_name"
        return self._query(query, params)

    def rebuild_classified(self) -> int:
        """Rebuild classified_data from normalized_data + item_labels. Returns row count."""
        conn = self._connect()
        try:
            conn.execute("DELETE FROM classified_data")
            conn.execute(
                """
                INSERT INTO classified_data
                (normalized_id, receipt_id, store, date_of_purchase, month_of_purchase,
                 item_name, measurement_type, measurement_quantity,
                 price_per_measurement_unit, line_total_paid_amount,
                 producto_es, category, subcategory, label_source, confidence,
                 needs_review, classified_at)
                SELECT n.id, n.receipt_id, n.store, n.date_of_purchase, n.month_of_purchase,
                       n.item_name, n.measurement_type, n.measurement_quantity,
                       n.price_per_measurement_unit, n.line_total_paid_amount,
                       l.producto_es, l.category, l.subcategory, l.source, l.confidence,
                       l.needs_review, ?
                FROM normalized_data n
                LEFT JOIN item_labels l ON l.item_name = n.item_name
                ORDER BY n.date_of_purchase, n.id
                """,
                (datetime.now().isoformat(),),
            )
            conn.commit()
            return conn.execute("SELECT COUNT(*) FROM classified_data").fetchone()[0]
        finally:
            conn.close()

    def get_classification_stats(self) -> Dict:
        """Counts by label source / review flag, plus unlabelled rows."""
        conn = self._connect()
        try:
            by_source = dict(conn.execute(
                "SELECT source, COUNT(*) FROM item_labels GROUP BY source"
            ).fetchall())
            review = conn.execute(
                "SELECT COUNT(*) FROM item_labels WHERE needs_review = 1"
            ).fetchone()[0]
            rows, unlabelled = conn.execute(
                "SELECT COUNT(*), SUM(category IS NULL) FROM classified_data"
            ).fetchone()
            searches = dict(conn.execute(
                "SELECT success, COUNT(*) FROM search_cache GROUP BY success"
            ).fetchall())
        finally:
            conn.close()
        return {
            "labels_by_source": by_source,
            "needs_review": review,
            "classified_rows": rows or 0,
            "unlabelled_rows": unlabelled or 0,
            "searches_cached": {"ok": searches.get(1, 0), "failed": searches.get(0, 0)},
        }

    def print_classification_stats(self):
        """Print classification statistics."""
        stats = self.get_classification_stats()

        print("=" * 50)
        print("CLASSIFICATION STATISTICS")
        print("=" * 50)
        print(f"Database: {self.db_path}")
        print()
        print("Labels by source:")
        for source, count in sorted(stats["labels_by_source"].items()):
            print(f"  {source:12} {count:5}")
        print(f"Needs review:    {stats['needs_review']}")
        print(f"Search cache:    {stats['searches_cached']['ok']} ok, "
              f"{stats['searches_cached']['failed']} failed")
        print()
        print(f"classified_data: {stats['classified_rows']} rows "
              f"({stats['unlabelled_rows']} without label)")
        print("=" * 50)

    # ------------------------------------------------------------------

    def _query(self, query: str, params: Optional[list] = None) -> List[Dict]:
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute(query, params or []).fetchall()]
        finally:
            conn.close()
