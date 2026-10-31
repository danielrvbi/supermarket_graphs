"""
SQLite store for stage 3D: product -> ingredient.

Tables (all in processed/processed_data.db), next to the untouched item_labels and v2
taxonomy tables:
- ingredient:             canonical names (lowercase, singular, Spanish, no brand);
                          active=0 + merged_into once merged away
- product_ingredient:     one ingredient per product (item_name, as in item_labels), written
                          only by apply.py (checked proposals) and the manual operations
- ingredient_change_log:  every manual operation, with its arguments and products affected
- view classified_ingredients: classified_v2 + its ingredient

Products point to ingredient ids, so a rename touches one row. Two names that only
differ by accents, case or a plural ending are the same ingredient (see ingredient_key).
"""

import json
import re
import sqlite3
import unicodedata
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

from v2.common.db import SQLiteStore


LABEL_SEP = " > "

SCHEMA = """
CREATE TABLE IF NOT EXISTS ingredient (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    is_food INTEGER NOT NULL DEFAULT 1,
    active INTEGER NOT NULL DEFAULT 1,
    merged_into INTEGER REFERENCES ingredient(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS product_ingredient (
    item_name TEXT PRIMARY KEY,     -- item_labels.item_name
    ingredient_id INTEGER REFERENCES ingredient(id),
    source TEXT NOT NULL,           -- llm (applied proposal) | manual (edited proposal or `set`)
    confidence REAL,
    needs_review INTEGER DEFAULT 0,
    evidence TEXT,                  -- JSON: inputs snapshot, llm name/reasoning, review_reasons
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_product_ingredient_ing ON product_ingredient(ingredient_id);
CREATE INDEX IF NOT EXISTS idx_product_ingredient_review ON product_ingredient(needs_review);

CREATE TABLE IF NOT EXISTS ingredient_change_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    op TEXT NOT NULL,
    payload TEXT NOT NULL,          -- JSON arguments
    items_affected INTEGER NOT NULL,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

# Created only when stage 3C's classified_v2 view exists
VIEW = """
CREATE VIEW IF NOT EXISTS classified_ingredients AS
SELECT cv.*, i.name AS ingredient, i.is_food AS is_food
FROM classified_v2 cv
LEFT JOIN product_ingredient pi ON pi.item_name = cv.item_name
LEFT JOIN ingredient i ON i.id = pi.ingredient_id
"""

# Products of stage 3 with their stage 3C label
PRODUCTS_SQL = """
SELECT l.item_name, l.store, l.producto_es,
       pc.subcategory_id, pc.needs_review AS upstream_review,
       c.name AS category, s.name AS subcategory, c.position AS cat_pos, s.position AS sub_pos
FROM item_labels l
LEFT JOIN product_category pc ON pc.item_name = l.item_name
LEFT JOIN subcategory s ON s.id = pc.subcategory_id
LEFT JOIN category c ON c.id = s.category_id
"""


class IngredientError(ValueError):
    """An operation that would leave the ingredients inconsistent."""


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower().strip()


def _stem(word: str) -> str:
    """
    Reduce singular and plural to the same stem (not a real word, only compared):
    tomate/tomates -> tomat, limon/limones -> limon, pan/panes -> pan, nuez/nueces -> nuec.
    """
    if len(word) <= 3:
        return word
    if word.endswith("s"):
        word = word[:-1]          # fresas -> fresa, tomates -> tomate, limones -> limone
    if word.endswith("e") and len(word) > 3 and word[-2] not in "aeiou":
        word = word[:-1]          # tomate -> tomat, limone -> limon, pane -> pan
    if word.endswith("z"):
        word = word[:-1] + "c"    # nuez -> nuec (nueces -> nuece -> nuec)
    return word


def ingredient_key(name: str) -> str:
    """Identity of a name: no accents, case, punctuation or plural endings."""
    words = re.findall(r"[a-z0-9]+", _plain(name))
    return " ".join(_stem(w) for w in words)


def clean_name(name: str) -> str:
    """Canonical spelling: trimmed, single spaces, lowercase."""
    name = " ".join((name or "").split()).lower()
    if not ingredient_key(name) or "|" in name or LABEL_SEP.strip() in name:
        raise IngredientError(f"Invalid ingredient name {name!r}")
    return name


def evidence_dict(raw) -> Dict:
    if isinstance(raw, dict):
        return dict(raw)
    try:
        value = json.loads(raw or "{}")
    except (ValueError, TypeError):
        return {"original_evidence": raw}
    return value if isinstance(value, dict) else {"original_evidence": value}


def product_inputs(product) -> Dict:
    """What an assignment depends on; a change re-assigns the product."""
    return {"version": 1, "producto_es": product["producto_es"], "store": product["store"],
            "subcategory_id": product["subcategory_id"]}


class IngredientStore(SQLiteStore):
    """
    Ingredients and their product links.

    Usage:
        db = IngredientStore("processed/processed_data.db")
        db.set_manual("JUMBO SPINAZIE GEWAS", "espinaca")
        db.merge("espinacas baby", "espinaca", dry_run=True)
    """

    SCHEMA = SCHEMA

    def _ensure_schema(self):
        super()._ensure_schema()
        conn = self._connect()
        try:
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='view' AND name='classified_v2'"
            ).fetchone():
                conn.execute(VIEW)
        finally:
            conn.close()

    def connect(self) -> sqlite3.Connection:
        """Connection for a multi-step run (assign keeps one open)."""
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------

    def products(self, conn=None) -> List[Dict]:
        """item_labels with their v2 category/subcategory, in taxonomy order."""
        own = conn is None
        conn = conn or self.connect()
        try:
            rows = conn.execute(
                PRODUCTS_SQL + " ORDER BY c.position, s.position, l.producto_es, l.item_name"
            ).fetchall()
        finally:
            if own:
                conn.close()
        return [dict(r) for r in rows]

    def get_links(self, conn=None) -> Dict[str, Dict]:
        """{item_name: product_ingredient row}"""
        own = conn is None
        conn = conn or self.connect()
        try:
            rows = conn.execute("SELECT * FROM product_ingredient").fetchall()
        finally:
            if own:
                conn.close()
        return {r["item_name"]: dict(r) for r in rows}

    def vocabulary(self, conn, category: str, subcategory: str) -> List[str]:
        """
        Active ingredients already linked to products of this category: this subcategory's
        first, then its siblings'. Read through `conn` so a run sees its own new names.
        """
        rows = conn.execute("""
            SELECT i.name, MAX(s.name = ?) AS here
            FROM product_ingredient pi
            JOIN ingredient i ON i.id = pi.ingredient_id AND i.active = 1
            JOIN product_category pc ON pc.item_name = pi.item_name
            JOIN subcategory s ON s.id = pc.subcategory_id
            JOIN category c ON c.id = s.category_id
            WHERE c.name = ?
            GROUP BY i.id ORDER BY here DESC, i.name
        """, (subcategory, category)).fetchall()
        return [r[0] for r in rows]

    def find(self, conn, name: str) -> Optional[sqlite3.Row]:
        """
        The ingredient with exactly this name, else the active one with the same key
        (following merges), or None. Exact first, so two names sharing a key can be merged.
        """
        row = conn.execute("SELECT * FROM ingredient WHERE name = ?", (" ".join(name.split()).lower(),)).fetchone()
        if row is not None:
            return self._follow(conn, row)
        key = ingredient_key(name)
        for row in conn.execute("SELECT * FROM ingredient ORDER BY active DESC, id").fetchall():
            if ingredient_key(row["name"]) == key:
                return self._follow(conn, row)
        return None

    def duplicate_keys(self, conn=None) -> List[List[str]]:
        """Groups of active ingredients that share a key (left over from an older key); merge them."""
        own = conn is None
        conn = conn or self.connect()
        try:
            names = [r[0] for r in conn.execute("SELECT name FROM ingredient WHERE active = 1 ORDER BY id")]
        finally:
            if own:
                conn.close()
        groups: Dict[str, List[str]] = {}
        for name in names:
            groups.setdefault(ingredient_key(name), []).append(name)
        return [g for g in groups.values() if len(g) > 1]

    def ingredient_summary(self, subcategory_label: Optional[str] = None, shared: bool = False) -> List[Dict]:
        """Active ingredients with their products ([store] item_name (producto_es))."""
        sql = """
            SELECT i.id, i.name, i.is_food, l.store, l.item_name, l.producto_es,
                   pi.needs_review, pi.source, c.name AS category, s.name AS subcategory
            FROM ingredient i
            JOIN product_ingredient pi ON pi.ingredient_id = i.id
            LEFT JOIN item_labels l ON l.item_name = pi.item_name
            LEFT JOIN product_category pc ON pc.item_name = pi.item_name
            LEFT JOIN subcategory s ON s.id = pc.subcategory_id
            LEFT JOIN category c ON c.id = s.category_id
            WHERE i.active = 1
            ORDER BY i.name, l.store, l.item_name
        """
        conn = self.connect()
        try:
            rows = [dict(r) for r in conn.execute(sql).fetchall()]
        finally:
            conn.close()
        by_ing: Dict[int, Dict] = {}
        for r in rows:
            ing = by_ing.setdefault(r["id"], {"name": r["name"], "is_food": r["is_food"], "products": []})
            ing["products"].append(r)
        result = list(by_ing.values())
        if subcategory_label:
            result = [i for i in result
                      if any(f"{p['category']}{LABEL_SEP}{p['subcategory']}" == subcategory_label
                             for p in i["products"])]
        if shared:
            result = [i for i in result if len({p["store"] for p in i["products"]}) > 1]
        return result

    def list_links(self, needs_review: Optional[bool] = True) -> List[Dict]:
        where = "" if needs_review is None else f"WHERE pi.needs_review = {int(needs_review)}"
        conn = self.connect()
        try:
            rows = conn.execute(f"""
                SELECT pi.*, i.name AS ingredient, l.store, l.producto_es,
                       c.name AS category, s.name AS subcategory
                FROM product_ingredient pi
                LEFT JOIN ingredient i ON i.id = pi.ingredient_id
                LEFT JOIN item_labels l ON l.item_name = pi.item_name
                LEFT JOIN product_category pc ON pc.item_name = pi.item_name
                LEFT JOIN subcategory s ON s.id = pc.subcategory_id
                LEFT JOIN category c ON c.id = s.category_id
                {where}
                ORDER BY c.position, s.position, i.name, pi.item_name
            """).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]

    def change_log(self, limit: int = 50) -> List[Dict]:
        conn = self.connect()
        try:
            rows = conn.execute(
                "SELECT * FROM ingredient_change_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # writes used by assign (caller owns the transaction)
    # ------------------------------------------------------------------

    def get_or_create(self, conn, name: str, is_food: bool) -> Tuple[int, bool]:
        """(ingredient id, created) for name, reusing an ingredient with the same key."""
        name = clean_name(name)
        row = self.find(conn, name)
        if row is not None:
            return row["id"], False
        cur = conn.execute("INSERT INTO ingredient (name, is_food) VALUES (?, ?)", (name, int(bool(is_food))))
        return cur.lastrowid, True

    def upsert_links(self, conn, rows: Iterable[Dict]) -> int:
        """
        Write product_ingredient rows (keys: item_name, ingredient_id, source, confidence,
        needs_review, evidence). Never overwrites a manual link.
        """
        now = datetime.now().isoformat()
        values = [
            (
                r["item_name"], r["ingredient_id"], r["source"], r.get("confidence"),
                int(bool(r.get("needs_review"))),
                json.dumps(r["evidence"], ensure_ascii=False) if r.get("evidence") else None, now,
            )
            for r in rows
        ]
        before = conn.total_changes
        conn.executemany("""
            INSERT INTO product_ingredient
            (item_name, ingredient_id, source, confidence, needs_review, evidence, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(item_name) DO UPDATE SET
                ingredient_id=excluded.ingredient_id, source=excluded.source,
                confidence=excluded.confidence, needs_review=excluded.needs_review,
                evidence=excluded.evidence, updated_at=excluded.updated_at
            WHERE product_ingredient.source != 'manual'
        """, values)
        return conn.total_changes - before

    # ------------------------------------------------------------------
    # manual operations (logged)
    # ------------------------------------------------------------------

    def set_manual(self, item_name: str, name: str, is_food: Optional[bool] = None, dry_run: bool = False) -> Dict:
        """Link a product by hand (source=manual, never overwritten by assign)."""

        def op(conn):
            product = conn.execute(PRODUCTS_SQL + " WHERE l.item_name = ?", (item_name,)).fetchone()
            if product is None:
                raise IngredientError(f"Unknown product {item_name!r}")
            ing_id, created = self.get_or_create(conn, name, True if is_food is None else is_food)
            if is_food is not None and not created:
                conn.execute("UPDATE ingredient SET is_food=? WHERE id=?", (int(is_food), ing_id))
            conn.execute("""
                INSERT INTO product_ingredient (item_name, ingredient_id, source, confidence, needs_review, evidence, updated_at)
                VALUES (?, ?, 'manual', 1.0, 0, ?, ?)
                ON CONFLICT(item_name) DO UPDATE SET ingredient_id=excluded.ingredient_id, source='manual',
                    confidence=1.0, needs_review=0, evidence=excluded.evidence, updated_at=excluded.updated_at
            """, (item_name, ing_id, json.dumps({"inputs": product_inputs(product)}, ensure_ascii=False),
                  datetime.now().isoformat()))
            return 1

        return self._run("set", {"item_name": item_name, "ingredient": name, "is_food": is_food}, op, dry_run)

    def apply_overrides(self, overrides: Dict[str, str]) -> List[str]:
        """Store {item_name: ingredient} as manual links, for products that exist. Returns those applied."""
        applied = []
        for item_name, name in overrides.items():
            try:
                self.set_manual(item_name, name)
            except IngredientError:
                continue
            applied.append(item_name)
        return applied

    def rename(self, old: str, new: str, dry_run: bool = False) -> Dict:
        new = clean_name(new)

        def op(conn):
            row = self._require(conn, old)
            other = self.find(conn, new)
            if other is not None and other["id"] != row["id"]:
                raise IngredientError(f"{other['name']!r} already exists; use merge")
            conn.execute("UPDATE ingredient SET name=? WHERE id=?", (new, row["id"]))
            return self._products_of(conn, row["id"])

        return self._run("rename", {"old": old, "new": new}, op, dry_run)

    def merge(self, source: str, into: str, dry_run: bool = False) -> Dict:
        """Retire an ingredient, sending its products to another one."""

        def op(conn):
            src = self._require(conn, source)
            dst = self._require(conn, into)
            if src["id"] == dst["id"]:
                raise IngredientError("Cannot merge an ingredient into itself")
            affected = conn.execute(
                "UPDATE product_ingredient SET ingredient_id=?, updated_at=? WHERE ingredient_id=?",
                (dst["id"], datetime.now().isoformat(), src["id"]),
            ).rowcount
            conn.execute("UPDATE ingredient SET active=0, merged_into=? WHERE id=?", (dst["id"], src["id"]))
            return affected

        return self._run("merge", {"from": source, "into": into}, op, dry_run)

    def restore(self, name: str, dry_run: bool = False) -> Dict:
        """Make a merged-away ingredient active again, with no products (merge into it to move them)."""

        def op(conn):
            row = conn.execute("SELECT * FROM ingredient WHERE name = ?", (clean_name(name),)).fetchone()
            if row is None or row["active"]:
                raise IngredientError(f"{name!r} is not a merged-away ingredient")
            conn.execute("UPDATE ingredient SET active=1, merged_into=NULL WHERE id=?", (row["id"],))
            return 0

        return self._run("restore", {"ingredient": name}, op, dry_run)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _run(self, op_name: str, payload: Dict, op, dry_run: bool = False) -> Dict:
        """Apply op in one transaction; log it, or roll back for a dry run."""
        conn = self.connect()
        try:
            affected = op(conn)
            if dry_run:
                conn.rollback()
            else:
                conn.execute(
                    "INSERT INTO ingredient_change_log (op, payload, items_affected, applied_at) VALUES (?, ?, ?, ?)",
                    (op_name, json.dumps(payload, ensure_ascii=False), affected, datetime.now().isoformat()),
                )
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return {"op": op_name, **payload, "items_affected": affected, "dry_run": dry_run}

    def _require(self, conn, name: str) -> sqlite3.Row:
        row = self.find(conn, name)
        if row is None:
            raise IngredientError(f"Unknown ingredient {name!r}")
        return row

    @staticmethod
    def _follow(conn, row: sqlite3.Row) -> sqlite3.Row:
        seen = set()
        while not row["active"] and row["merged_into"] and row["id"] not in seen:
            seen.add(row["id"])
            row = conn.execute("SELECT * FROM ingredient WHERE id=?", (row["merged_into"],)).fetchone()
        return row

    @staticmethod
    def _products_of(conn, ingredient_id: int) -> int:
        return conn.execute(
            "SELECT COUNT(*) FROM product_ingredient WHERE ingredient_id=?", (ingredient_id,)
        ).fetchone()[0]
