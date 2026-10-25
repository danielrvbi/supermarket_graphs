"""
SQLite store for the v2 taxonomy.

Tables (all in processed/processed_data.db), alongside the untouched v1 labels in
item_labels / classified_data:
- category:            v2 categories
- subcategory:         v2 subcategories (active=0 once merged away)
- product_category:    one v2 label per product (item_name, as in item_labels)
- v1_map:              v1 (category, subcategory) -> v2 subcategory; several rows = split
- taxonomy_change_log: every operation applied, with its arguments and products affected
- view classified_v2:  classified_data + its v2 category/subcategory

Labels point to subcategory ids, so renames and moves don't touch product_category.
Every operation runs in one transaction and can be previewed with dry_run=True
(applied, counted, rolled back).
"""

import json
import sqlite3
import unicodedata
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

from v2.common.db import SQLiteStore


OTHER = "Otros"
LABEL_SEP = " > "

SCHEMA = """
CREATE TABLE IF NOT EXISTS category (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    position INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS subcategory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES category(id),
    name TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    UNIQUE (category_id, name)
);

CREATE TABLE IF NOT EXISTS product_category (
    item_name TEXT PRIMARY KEY,     -- item_labels.item_name
    subcategory_id INTEGER REFERENCES subcategory(id),   -- NULL while a split is pending
    source TEXT NOT NULL,           -- map | split_llm | pending_split | manual
    confidence REAL,
    needs_review INTEGER DEFAULT 0,
    evidence TEXT,                  -- JSON: v1 label, candidates, llm reasoning
    synced_from TEXT,               -- v1 'Category > Subcategory' this label was derived from
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_product_category_sub ON product_category(subcategory_id);
CREATE INDEX IF NOT EXISTS idx_product_category_review ON product_category(needs_review);

CREATE TABLE IF NOT EXISTS v1_map (
    old_category TEXT NOT NULL,
    old_subcategory TEXT NOT NULL,
    subcategory_id INTEGER NOT NULL REFERENCES subcategory(id),
    PRIMARY KEY (old_category, old_subcategory, subcategory_id)
);

CREATE TABLE IF NOT EXISTS taxonomy_change_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    op TEXT NOT NULL,
    payload TEXT NOT NULL,          -- JSON arguments
    items_affected INTEGER NOT NULL,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

# Created only when classified_data exists (stage 3 has run)
VIEW = """
CREATE VIEW IF NOT EXISTS classified_v2 AS
SELECT cd.*, c.name AS category_v2, s.name AS subcategory_v2,
       pc.source AS label_source_v2, pc.needs_review AS needs_review_v2
FROM classified_data cd
LEFT JOIN product_category pc ON pc.item_name = cd.item_name
LEFT JOIN subcategory s ON s.id = pc.subcategory_id
LEFT JOIN category c ON c.id = s.category_id
"""


class TaxonomyError(ValueError):
    """An operation that would leave the taxonomy inconsistent."""


def _sort_key(name: str) -> Tuple[int, str]:
    """Alphabetical ignoring accents/case, with Otros always last."""
    if name == OTHER:
        return (1, "")
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return (0, plain.lower())


def _clean(name: str) -> str:
    name = name.strip()
    if not name or LABEL_SEP.strip() in name:
        raise TaxonomyError(f"Invalid name {name!r}")
    return name


def split_label(label: str) -> Tuple[str, str]:
    """'Category > Subcategory' -> (category, subcategory)."""
    category, subcategory = label.split(LABEL_SEP, 1)
    return category.strip(), subcategory.strip()


class TaxonomyStore(SQLiteStore):
    """
    The v2 taxonomy and its product labels.

    Usage:
        db = TaxonomyStore("processed/processed_data.db")
        db.init_from_seed(V2_TAXONOMY, V1_MAP)
        db.rename_subcategory("Frutas", "Bayas", "Frutos Rojos", dry_run=True)
    """

    SCHEMA = SCHEMA

    def _ensure_schema(self):
        super()._ensure_schema()
        conn = self._connect()
        try:
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='classified_data'"
            ).fetchone():
                conn.execute(VIEW)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------

    def is_initialised(self) -> bool:
        conn = self._connect()
        try:
            return conn.execute("SELECT COUNT(*) FROM subcategory").fetchone()[0] > 0
        finally:
            conn.close()

    def taxonomy(self) -> Dict[str, List[str]]:
        """Active {category: [subcategories]} in display order."""
        conn = self._connect()
        try:
            rows = conn.execute("""
                SELECT c.name, s.name FROM subcategory s JOIN category c ON c.id = s.category_id
                WHERE s.active = 1 ORDER BY c.position, s.position
            """).fetchall()
        finally:
            conn.close()
        taxonomy: Dict[str, List[str]] = {}
        for category, subcategory in rows:
            taxonomy.setdefault(category, []).append(subcategory)
        return taxonomy

    def v1_map(self) -> Dict[Tuple[str, str], List[Tuple[int, str]]]:
        """{(old category, old subcategory): [(subcategory id, 'Category > Subcategory'), ...]}"""
        conn = self._connect()
        try:
            rows = conn.execute("""
                SELECT m.old_category, m.old_subcategory, s.id, c.name, s.name
                FROM v1_map m JOIN subcategory s ON s.id = m.subcategory_id
                JOIN category c ON c.id = s.category_id
                WHERE s.active = 1 ORDER BY c.position, s.position
            """).fetchall()
        finally:
            conn.close()
        mapping: Dict[Tuple[str, str], List[Tuple[int, str]]] = {}
        for old_cat, old_sub, sub_id, cat, sub in rows:
            mapping.setdefault((old_cat, old_sub), []).append((sub_id, f"{cat}{LABEL_SEP}{sub}"))
        return mapping

    def counts(self) -> Dict[Tuple[str, str], int]:
        """Number of products per v2 (category, subcategory)."""
        conn = self._connect()
        try:
            rows = conn.execute("""
                SELECT c.name, s.name, COUNT(*) FROM product_category pc
                JOIN subcategory s ON s.id = pc.subcategory_id
                JOIN category c ON c.id = s.category_id GROUP BY 1, 2
            """).fetchall()
        finally:
            conn.close()
        return {(c, s): n for c, s, n in rows}

    def get_product_labels(self) -> Dict[str, Dict]:
        """{item_name: product_category row}"""
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT * FROM product_category").fetchall()
        finally:
            conn.close()
        return {r["item_name"]: dict(r) for r in rows}

    def list_labels(self, needs_review: Optional[bool] = None, source: Optional[str] = None) -> List[Dict]:
        """product_category joined with names and the v1 product info."""
        where, params = [], []
        if needs_review is not None:
            where.append("pc.needs_review = ?")
            params.append(int(needs_review))
        if source:
            where.append("pc.source = ?")
            params.append(source)
        sql = """
            SELECT pc.*, c.name AS category, s.name AS subcategory, l.producto_es, l.store
            FROM product_category pc
            LEFT JOIN subcategory s ON s.id = pc.subcategory_id
            LEFT JOIN category c ON c.id = s.category_id
            LEFT JOIN item_labels l ON l.item_name = pc.item_name
        """
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY c.position, s.position, pc.item_name"
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()

    def change_log(self, limit: int = 50) -> List[Dict]:
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM taxonomy_change_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # product labels (used by sync and review)
    # ------------------------------------------------------------------

    def upsert_product_labels(self, rows: Iterable[Dict]) -> int:
        """
        Write product_category rows (keys: item_name, subcategory_id, source, confidence,
        needs_review, evidence, synced_from). Never overwrites a manual label.
        """
        now = datetime.now().isoformat()
        values = [
            (
                r["item_name"], r["subcategory_id"], r["source"], r.get("confidence"),
                int(bool(r.get("needs_review"))),
                json.dumps(r["evidence"], ensure_ascii=False) if r.get("evidence") else None,
                r.get("synced_from"), now,
            )
            for r in rows
        ]
        conn = self._connect()
        try:
            before = conn.total_changes
            conn.executemany("""
                INSERT INTO product_category
                (item_name, subcategory_id, source, confidence, needs_review, evidence, synced_from, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(item_name) DO UPDATE SET
                    subcategory_id=excluded.subcategory_id, source=excluded.source,
                    confidence=excluded.confidence, needs_review=excluded.needs_review,
                    evidence=excluded.evidence, synced_from=excluded.synced_from,
                    updated_at=excluded.updated_at
                WHERE product_category.source != 'manual'
            """, values)
            conn.commit()
            return conn.total_changes - before
        finally:
            conn.close()

    def set_manual(self, item_name: str, category: str, subcategory: str) -> None:
        """Set a v2 label by hand (source=manual, never overwritten by sync)."""
        conn = self._connect()
        try:
            sub_id = self._sub_id(conn, category, subcategory)
            conn.execute("""
                INSERT INTO product_category (item_name, subcategory_id, source, confidence, needs_review, updated_at)
                VALUES (?, ?, 'manual', 1.0, 0, ?)
                ON CONFLICT(item_name) DO UPDATE SET subcategory_id=excluded.subcategory_id,
                    source='manual', confidence=1.0, needs_review=0, updated_at=excluded.updated_at
            """, (item_name, sub_id, datetime.now().isoformat()))
            conn.commit()
        finally:
            conn.close()

    def apply_overrides(self, overrides: Dict[str, str]) -> List[str]:
        """
        Store {item_name: 'Category > Subcategory'} as manual labels, for products that
        exist in item_labels. Returns the item names applied.
        """
        conn = self._connect()
        try:
            known = {r[0] for r in conn.execute("SELECT item_name FROM item_labels").fetchall()}
        except sqlite3.OperationalError:
            known = set()
        finally:
            conn.close()
        applied = []
        for item_name, label in overrides.items():
            if item_name in known:
                self.set_manual(item_name, *split_label(label))
                applied.append(item_name)
        return applied

    def approve(self, item_name: str) -> bool:
        """Keep the v2 label, clear the review flag."""
        conn = self._connect()
        try:
            changed = conn.execute(
                "UPDATE product_category SET needs_review=0 WHERE item_name=? AND subcategory_id IS NOT NULL",
                (item_name,),
            ).rowcount
            conn.commit()
            return bool(changed)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # taxonomy operations
    # ------------------------------------------------------------------

    def init_from_seed(self, taxonomy: Dict[str, List[str]], v1_map: Dict) -> Dict:
        """Load the v2 taxonomy + v1 map. Refuses if already initialised."""
        if self.is_initialised():
            raise TaxonomyError("v2 taxonomy is already initialised")

        def op(conn):
            for category, subs in taxonomy.items():
                cat_id = conn.execute("INSERT INTO category (name) VALUES (?)", (category,)).lastrowid
                for sub in subs:
                    self._insert_subcategory(conn, cat_id, sub)
            for (old_cat, old_sub), target in v1_map.items():
                for label in [target] if isinstance(target, str) else target:
                    conn.execute(
                        "INSERT INTO v1_map VALUES (?, ?, ?)",
                        (old_cat, old_sub, self._sub_id(conn, *split_label(label))),
                    )
            return 0

        return self._run("init", {"categories": len(taxonomy)}, op)

    def add_category(self, name: str, dry_run: bool = False) -> Dict:
        """New category (gets an Otros subcategory automatically)."""
        name = _clean(name)

        def op(conn):
            if self._cat_id(conn, name, required=False) is not None:
                raise TaxonomyError(f"Category {name!r} already exists")
            cat_id = conn.execute("INSERT INTO category (name) VALUES (?)", (name,)).lastrowid
            self._insert_subcategory(conn, cat_id, OTHER)
            return 0

        return self._run("add_category", {"name": name}, op, dry_run)

    def add_subcategory(self, category: str, name: str, dry_run: bool = False) -> Dict:
        """New subcategory (reactivates a retired one with the same name)."""
        name = _clean(name)

        def op(conn):
            cat_id = self._cat_id(conn, category)
            row = conn.execute(
                "SELECT id, active FROM subcategory WHERE category_id=? AND name=?", (cat_id, name)
            ).fetchone()
            if row and row[1]:
                raise TaxonomyError(f"{category}{LABEL_SEP}{name} already exists")
            if row:
                conn.execute("UPDATE subcategory SET active=1 WHERE id=?", (row[0],))
            else:
                self._insert_subcategory(conn, cat_id, name)
            return 0

        return self._run("add_subcategory", {"category": category, "name": name}, op, dry_run)

    def rename_subcategory(self, category: str, old: str, new: str, dry_run: bool = False) -> Dict:
        new = _clean(new)

        def op(conn):
            self._forbid_other(old)
            sub_id = self._sub_id(conn, category, old)
            self._require_free(conn, self._cat_id(conn, category), category, new)
            conn.execute("UPDATE subcategory SET name=? WHERE id=?", (new, sub_id))
            return self._products_in(conn, sub_id)

        return self._run("rename_subcategory", {"category": category, "old": old, "new": new}, op, dry_run)

    def rename_category(self, old: str, new: str, dry_run: bool = False) -> Dict:
        new = _clean(new)

        def op(conn):
            cat_id = self._cat_id(conn, old)
            if self._cat_id(conn, new, required=False) is not None:
                raise TaxonomyError(f"Category {new!r} already exists")
            conn.execute("UPDATE category SET name=? WHERE id=?", (new, cat_id))
            return conn.execute("""
                SELECT COUNT(*) FROM product_category pc JOIN subcategory s ON s.id = pc.subcategory_id
                WHERE s.category_id = ?
            """, (cat_id,)).fetchone()[0]

        return self._run("rename_category", {"old": old, "new": new}, op, dry_run)

    def move_subcategory(self, category: str, name: str, to_category: str, dry_run: bool = False) -> Dict:
        """Move a subcategory (and its products) to another category, keeping its name."""

        def op(conn):
            self._forbid_other(name)
            sub_id = self._sub_id(conn, category, name)
            to_id = self._cat_id(conn, to_category)
            self._require_free(conn, to_id, to_category, name, hint="; use merge")
            conn.execute("UPDATE subcategory SET category_id=? WHERE id=?", (to_id, sub_id))
            return self._products_in(conn, sub_id)

        return self._run(
            "move_subcategory", {"category": category, "name": name, "to": to_category}, op, dry_run
        )

    def merge_subcategory(
        self, category: str, name: str, into_category: str, into_name: str, dry_run: bool = False
    ) -> Dict:
        """Retire a subcategory, sending its products and v1 map entries to another one."""

        def op(conn):
            self._forbid_other(name)
            sub_id = self._sub_id(conn, category, name)
            into_id = self._sub_id(conn, into_category, into_name)
            if sub_id == into_id:
                raise TaxonomyError("Cannot merge a subcategory into itself")
            affected = conn.execute(
                "UPDATE product_category SET subcategory_id=?, updated_at=? WHERE subcategory_id=?",
                (into_id, datetime.now().isoformat(), sub_id),
            ).rowcount
            conn.execute("UPDATE OR IGNORE v1_map SET subcategory_id=? WHERE subcategory_id=?", (into_id, sub_id))
            conn.execute("DELETE FROM v1_map WHERE subcategory_id=?", (sub_id,))  # duplicates left by IGNORE
            conn.execute("UPDATE subcategory SET active=0 WHERE id=?", (sub_id,))
            return affected

        payload = {"category": category, "name": name, "into": [into_category, into_name]}
        return self._run("merge_subcategory", payload, op, dry_run)

    def split_subcategory(self, category: str, name: str, into: Iterable[str], dry_run: bool = False) -> Dict:
        """
        Add new sibling subcategories and flag the source's products for review.

        Products keep their label until reviewed (`set`). Once the source is empty,
        merge it into one of the new ones (or Otros) to retire it.
        """
        new_names = [_clean(n) for n in into]

        def op(conn):
            cat_id = self._cat_id(conn, category)
            sub_id = self._sub_id(conn, category, name)
            for new in new_names:
                self._require_free(conn, cat_id, category, new)
                self._insert_subcategory(conn, cat_id, new)
            return conn.execute(
                "UPDATE product_category SET needs_review=1 WHERE subcategory_id=? AND source != 'manual'",
                (sub_id,),
            ).rowcount

        return self._run(
            "split_subcategory", {"category": category, "name": name, "into": new_names}, op, dry_run
        )

    def remove_category(self, name: str, dry_run: bool = False) -> Dict:
        """Retire a category that has no products left."""

        def op(conn):
            cat_id = self._cat_id(conn, name)
            used = conn.execute("""
                SELECT COUNT(*) FROM product_category pc JOIN subcategory s ON s.id = pc.subcategory_id
                WHERE s.category_id = ?
            """, (cat_id,)).fetchone()[0]
            if used:
                raise TaxonomyError(f"{used} products still in {name!r}; move or merge them first")
            conn.execute("UPDATE subcategory SET active=0 WHERE category_id=?", (cat_id,))
            return 0

        return self._run("remove_category", {"name": name}, op, dry_run)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _run(self, op_name: str, payload: Dict, op, dry_run: bool = False) -> Dict:
        """Apply op in one transaction; log it, or roll back for a dry run."""
        conn = self._connect()
        try:
            affected = op(conn)
            self._renumber(conn)
            if dry_run:
                conn.rollback()
            else:
                conn.execute(
                    "INSERT INTO taxonomy_change_log (op, payload, items_affected, applied_at) VALUES (?, ?, ?, ?)",
                    (op_name, json.dumps(payload, ensure_ascii=False), affected, datetime.now().isoformat()),
                )
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return {"op": op_name, **payload, "items_affected": affected, "dry_run": dry_run}

    def _cat_id(self, conn, name: str, required: bool = True) -> Optional[int]:
        row = conn.execute("SELECT id FROM category WHERE name=?", (name,)).fetchone()
        if row is None and required:
            raise TaxonomyError(f"Unknown category {name!r}")
        return row[0] if row else None

    def _sub_id(self, conn, category: str, name: str) -> int:
        row = conn.execute(
            """SELECT s.id FROM subcategory s JOIN category c ON c.id = s.category_id
               WHERE c.name=? AND s.name=? AND s.active=1""",
            (category, name),
        ).fetchone()
        if row is None:
            raise TaxonomyError(f"Unknown subcategory {category}{LABEL_SEP}{name}")
        return row[0]

    @staticmethod
    def _require_free(conn, cat_id: int, category: str, name: str, hint: str = ""):
        if conn.execute("SELECT 1 FROM subcategory WHERE category_id=? AND name=?", (cat_id, name)).fetchone():
            raise TaxonomyError(f"{category}{LABEL_SEP}{name} already exists (active or retired){hint}")

    @staticmethod
    def _forbid_other(name: str):
        if name == OTHER:
            raise TaxonomyError(f"{OTHER!r} can't be renamed, moved, merged or split")

    @staticmethod
    def _insert_subcategory(conn, cat_id: int, name: str) -> int:
        return conn.execute(
            "INSERT INTO subcategory (category_id, name) VALUES (?, ?)", (cat_id, name)
        ).lastrowid

    @staticmethod
    def _products_in(conn, sub_id: int) -> int:
        return conn.execute(
            "SELECT COUNT(*) FROM product_category WHERE subcategory_id=?", (sub_id,)
        ).fetchone()[0]

    @staticmethod
    def _renumber(conn):
        """Keep categories in insertion order and subcategories alphabetical, Otros last."""
        for pos, (cat_id,) in enumerate(conn.execute("SELECT id FROM category ORDER BY id").fetchall()):
            conn.execute("UPDATE category SET position=? WHERE id=?", (pos, cat_id))
        subs = conn.execute("SELECT id, category_id, name FROM subcategory").fetchall()
        by_cat: Dict[int, List] = {}
        for sub_id, cat_id, name in subs:
            by_cat.setdefault(cat_id, []).append((sub_id, name))
        for rows in by_cat.values():
            for pos, (sub_id, _) in enumerate(sorted(rows, key=lambda r: _sort_key(r[1]))):
                conn.execute("UPDATE subcategory SET position=? WHERE id=?", (pos, sub_id))
