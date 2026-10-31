"""
Build the graph db (processed/graph.db) from the processing db (processed/processed_data.db).

The graph db holds only the final, corrected data for graph ingestion:

    store        ah / jumbo
    category     v2 categories
    subcategory  active v2 subcategories
    ingredient   active ingredients (stage 3D)
    product      one per (store, receipt name) that was bought, with its v2 subcategory and ingredient
    receipt      one per receipt: store, date, item count, total
    purchase     one per receipt line: product, quantity, unit ('unit' | 'kg'), unit price, total
    build_info   when and from what it was built, plus the check totals
    view purchase_detail   purchase joined with everything above

It is rebuilt from scratch every time and never edited by hand: fix data in the processing
db and rebuild. The processing db is opened read-only. The new file is written next to the
target and swapped in only after every check passes.

Ids of category, subcategory and ingredient are kept from the processing db.
"""

import os
import sqlite3
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List


STORES = {"ah": "Albert Heijn", "jumbo": "Jumbo"}
UNITS = {"discrete_units": "unit", "weight_in_grams": "kg"}   # weights are already stored in kg

SCHEMA = """
CREATE TABLE store (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL
);

CREATE TABLE category (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    position INTEGER NOT NULL
);

CREATE TABLE subcategory (
    id INTEGER PRIMARY KEY,
    category_id INTEGER NOT NULL REFERENCES category(id),
    name TEXT NOT NULL,
    position INTEGER NOT NULL,
    UNIQUE (category_id, name)
);

CREATE TABLE ingredient (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    is_food INTEGER NOT NULL
);

CREATE TABLE product (
    id INTEGER PRIMARY KEY,
    store_id INTEGER NOT NULL REFERENCES store(id),
    item_name TEXT NOT NULL,            -- receipt text
    name_es TEXT,                       -- Spanish product name
    subcategory_id INTEGER NOT NULL REFERENCES subcategory(id),
    ingredient_id INTEGER NOT NULL REFERENCES ingredient(id),
    UNIQUE (store_id, item_name)
);

CREATE TABLE receipt (
    id TEXT PRIMARY KEY,
    store_id INTEGER NOT NULL REFERENCES store(id),
    date TEXT NOT NULL,
    month TEXT,
    item_count INTEGER NOT NULL,
    total REAL NOT NULL
);

CREATE TABLE purchase (
    id INTEGER PRIMARY KEY,
    receipt_id TEXT NOT NULL REFERENCES receipt(id),
    product_id INTEGER NOT NULL REFERENCES product(id),
    quantity REAL,
    unit TEXT NOT NULL,                 -- unit | kg
    unit_price REAL,
    total REAL NOT NULL
);

CREATE TABLE build_info (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX idx_subcategory_category ON subcategory(category_id);
CREATE INDEX idx_product_subcategory ON product(subcategory_id);
CREATE INDEX idx_product_ingredient ON product(ingredient_id);
CREATE INDEX idx_receipt_store ON receipt(store_id);
CREATE INDEX idx_receipt_date ON receipt(date);
CREATE INDEX idx_purchase_receipt ON purchase(receipt_id);
CREATE INDEX idx_purchase_product ON purchase(product_id);

CREATE VIEW purchase_detail AS
SELECT pu.id AS purchase_id, r.id AS receipt_id, r.date, r.month, st.code AS store,
       p.item_name, p.name_es, i.name AS ingredient, i.is_food,
       c.name AS category, s.name AS subcategory,
       pu.quantity, pu.unit, pu.unit_price, pu.total
FROM purchase pu
JOIN receipt r ON r.id = pu.receipt_id
JOIN product p ON p.id = pu.product_id
JOIN store st ON st.id = p.store_id
JOIN ingredient i ON i.id = p.ingredient_id
JOIN subcategory s ON s.id = p.subcategory_id
JOIN category c ON c.id = s.category_id;
"""

# One row per purchase line in the processing db, with the product's current labels
SOURCE_LINES = """
SELECT cd.id, cd.receipt_id, cd.store, cd.date_of_purchase, cd.month_of_purchase, cd.item_name,
       cd.measurement_type, cd.measurement_quantity, cd.price_per_measurement_unit,
       cd.line_total_paid_amount,
       l.producto_es, pc.subcategory_id, s.active AS subcategory_active,
       pi.ingredient_id, i.active AS ingredient_active
FROM classified_data cd
LEFT JOIN item_labels l ON l.item_name = cd.item_name
LEFT JOIN product_category pc ON pc.item_name = cd.item_name
LEFT JOIN subcategory s ON s.id = pc.subcategory_id
LEFT JOIN product_ingredient pi ON pi.item_name = cd.item_name
LEFT JOIN ingredient i ON i.id = pi.ingredient_id
ORDER BY cd.date_of_purchase, cd.receipt_id, cd.id
"""


class BuildError(RuntimeError):
    """The processing db is not complete or consistent enough to build from."""


@dataclass
class BuildReport:
    path: str
    counts: Dict[str, int] = field(default_factory=dict)
    spend: float = 0.0
    source_spend: float = 0.0


def _cents(x) -> int:
    return round((x or 0) * 100)


def _git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def build(source_db: str, target_db: str) -> BuildReport:
    """Build target_db from source_db. Raises BuildError (leaving target untouched) if a check fails."""
    if not Path(source_db).exists():
        raise BuildError(f"Processing db not found: {source_db}")
    src = sqlite3.connect(f"{Path(source_db).resolve().as_uri()}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    try:
        lines = [dict(r) for r in src.execute(SOURCE_LINES).fetchall()]
        categories = src.execute("SELECT id, name, position FROM category ORDER BY position").fetchall()
        subcategories = src.execute(
            "SELECT id, category_id, name, position FROM subcategory WHERE active = 1 ORDER BY category_id, position"
        ).fetchall()
        ingredients = src.execute("SELECT id, name, is_food FROM ingredient WHERE active = 1 ORDER BY id").fetchall()
        source_rows, source_receipts, source_spend = src.execute(
            "SELECT COUNT(*), COUNT(DISTINCT receipt_id), SUM(line_total_paid_amount) FROM classified_data"
        ).fetchone()
    finally:
        src.close()

    _check_lines(lines)

    stores = {code: n for n, code in enumerate(sorted({l["store"] for l in lines}), 1)}
    products: Dict[tuple, int] = {}
    product_rows, receipts, purchases = [], {}, []
    for line in lines:
        key = (line["store"], line["item_name"])
        if key not in products:
            products[key] = len(products) + 1
            product_rows.append((products[key], stores[line["store"]], line["item_name"], line["producto_es"],
                                 line["subcategory_id"], line["ingredient_id"]))
        r = receipts.setdefault(line["receipt_id"], {
            "store": line["store"], "date": line["date_of_purchase"], "month": line["month_of_purchase"],
            "count": 0, "cents": 0,
        })
        if r["store"] != line["store"] or r["date"] != line["date_of_purchase"]:
            raise BuildError(f"Receipt {line['receipt_id']} has lines with different stores or dates")
        r["count"] += 1
        r["cents"] += _cents(line["line_total_paid_amount"])
        purchases.append((line["id"], line["receipt_id"], products[key], line["measurement_quantity"],
                          UNITS[line["measurement_type"]], line["price_per_measurement_unit"],
                          line["line_total_paid_amount"]))

    used_subs = {p[4] for p in product_rows}
    used_ings = {p[5] for p in product_rows}
    if not used_subs <= {s["id"] for s in subcategories}:
        raise BuildError("Some products point to a subcategory that is not active")
    if not used_ings <= {i["id"] for i in ingredients}:
        raise BuildError("Some products point to an ingredient that is not active")
    ingredients = [i for i in ingredients if i["id"] in used_ings]   # drop names no bought product uses

    target = Path(target_db)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".building")
    if tmp.exists():
        tmp.unlink()
    out = sqlite3.connect(tmp)
    try:
        out.executescript(SCHEMA)
        out.executemany("INSERT INTO store VALUES (?, ?, ?)",
                        [(n, code, STORES.get(code, code)) for code, n in stores.items()])
        out.executemany("INSERT INTO category VALUES (?, ?, ?)", [tuple(c) for c in categories])
        out.executemany("INSERT INTO subcategory VALUES (?, ?, ?, ?)", [tuple(s) for s in subcategories])
        out.executemany("INSERT INTO ingredient VALUES (?, ?, ?)", [tuple(i) for i in ingredients])
        out.executemany("INSERT INTO product VALUES (?, ?, ?, ?, ?, ?)", product_rows)
        out.executemany("INSERT INTO receipt VALUES (?, ?, ?, ?, ?, ?)", [
            (rid, stores[r["store"]], r["date"], r["month"], r["count"], r["cents"] / 100)
            for rid, r in receipts.items()
        ])
        out.executemany("INSERT INTO purchase VALUES (?, ?, ?, ?, ?, ?, ?)", purchases)

        report = BuildReport(path=str(target), source_spend=round(source_spend or 0, 2))
        for table in ("store", "category", "subcategory", "ingredient", "product", "receipt", "purchase"):
            report.counts[table] = out.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        report.spend = round(out.execute("SELECT SUM(total) FROM purchase").fetchone()[0] or 0, 2)
        _check_totals(out, report, source_rows, source_receipts, source_spend)

        info = {
            "built_at": datetime.now().isoformat(timespec="seconds"),
            "source_db": str(source_db),
            "git_commit": _git_commit(),
            "spend_total": f"{report.spend:.2f}",
            **{f"count_{k}": str(v) for k, v in report.counts.items()},
        }
        out.executemany("INSERT INTO build_info VALUES (?, ?)", info.items())
        out.commit()
    except Exception:
        out.close()
        tmp.unlink(missing_ok=True)
        raise
    out.close()
    os.replace(tmp, target)
    return report


def _check_lines(lines: List[Dict]):
    problems = []
    for name, test in (
        ("no v2 subcategory", lambda l: l["subcategory_id"] is None),
        ("no ingredient", lambda l: l["ingredient_id"] is None),
        ("unknown measurement type", lambda l: l["measurement_type"] not in UNITS),
        ("no date", lambda l: not l["date_of_purchase"]),
        ("no line total", lambda l: l["line_total_paid_amount"] is None),
    ):
        bad = sorted({l["item_name"] for l in lines if test(l)})
        if bad:
            problems.append(f"{len(bad)} products with {name}: {', '.join(bad[:5])}{' …' if len(bad) > 5 else ''}")
    if problems:
        raise BuildError("Processing db is not ready:\n  " + "\n  ".join(problems))


def _check_totals(out, report: BuildReport, source_rows: int, source_receipts: int, source_spend: float):
    if report.counts["purchase"] != source_rows:
        raise BuildError(f"{report.counts['purchase']} purchases written, {source_rows} in the processing db")
    if report.counts["receipt"] != source_receipts:
        raise BuildError(f"{report.counts['receipt']} receipts written, {source_receipts} in the processing db")
    if _cents(report.spend) != _cents(source_spend):
        raise BuildError(f"Spend {report.spend:.2f} differs from the processing db ({source_spend:.2f})")
    off = out.execute("""
        SELECT COUNT(*) FROM receipt r
        WHERE ROUND(r.total, 2) != ROUND((SELECT SUM(total) FROM purchase p WHERE p.receipt_id = r.id), 2)
    """).fetchone()[0]
    if off:
        raise BuildError(f"{off} receipts whose total differs from the sum of their lines")
