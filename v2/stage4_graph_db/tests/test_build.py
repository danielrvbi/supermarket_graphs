"""
Unit tests for stage 4 (temp dbs, no API calls).

Usage:
    python -m pytest v2/stage4_graph_db/tests -v
"""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from v2.stage3_classification.store import ClassificationStore
from v2.stage3c_taxonomy.seed_v2 import V1_MAP, V2_TAXONOMY
from v2.stage3c_taxonomy.store import TaxonomyStore
from v2.stage3d_ingredients.store import IngredientStore
from v2.stage4_graph_db.build import BuildError, build


SALAD = ("Verduras", "Lechuga y Ensaladas")
CHEESE = ("Lácteos y Huevos", "Queso Madurado")

# item_name, label store, producto_es, v2 subcategory, ingredient
PRODUCTS = [
    ("AH SPINAZIE", "ah", "Espinaca AH", SALAD, "espinaca"),
    ("JUMBO SPINAZIE GEWAS", "jumbo", "Espinaca Jumbo", SALAD, "espinaca"),
    ("HARIBO", "ah", "Gominolas Haribo", SALAD, "gominola"),     # bought at both stores below
    ("JONGE KAAS", "jumbo", "Queso Joven", CHEESE, "queso gouda"),
    ("NEVER BOUGHT", "ah", "Nunca", SALAD, "lechuga"),
]

# receipt_id, store, date, item_name, measurement_type, quantity, unit price, total
LINES = [
    ("ah_1", "ah", "2026-01-05", "AH SPINAZIE", "discrete_units", 2.0, 1.5, 3.0),
    ("ah_1", "ah", "2026-01-05", "HARIBO", "discrete_units", 1.0, 2.29, 2.29),
    ("jumbo_1", "jumbo", "2026-01-07", "JUMBO SPINAZIE GEWAS", "discrete_units", 1.0, 1.79, 1.79),
    ("jumbo_1", "jumbo", "2026-01-07", "HARIBO", "discrete_units", 1.0, 1.99, 1.99),
    ("jumbo_1", "jumbo", "2026-01-07", "JONGE KAAS", "weight_in_grams", 0.512, 12.5, 6.4),
]


def add_lines(path, lines):
    conn = sqlite3.connect(path)
    conn.executemany("""
        INSERT INTO classified_data (receipt_id, store, date_of_purchase, month_of_purchase, item_name,
            measurement_type, measurement_quantity, price_per_measurement_unit, line_total_paid_amount)
        VALUES (?, ?, ?, substr(?, 1, 7) || '-01', ?, ?, ?, ?, ?)
    """, [(r, s, d, d, i, m, q, p, t) for r, s, d, i, m, q, p, t in lines])
    conn.commit()
    conn.close()


@pytest.fixture
def source(tmp_path):
    path = str(tmp_path / "processing.db")
    labels = ClassificationStore(path)
    taxonomy = TaxonomyStore(path)
    taxonomy.init_from_seed(V2_TAXONOMY, V1_MAP)
    for item_name, store, producto_es, (cat, sub), _ in PRODUCTS:
        labels.upsert_label(item_name, "Hogar", "Otros", "old_data", producto_es=producto_es, store=store)
        taxonomy.set_manual(item_name, cat, sub)
    ingredients = IngredientStore(path)
    for item_name, *_, ingredient in PRODUCTS:
        ingredients.set_manual(item_name, ingredient)
    add_lines(path, LINES)
    return path


def rows(path, sql):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_build_writes_the_clean_tables(source, tmp_path):
    out = str(tmp_path / "graph.db")
    report = build(source, out)
    assert report.counts["store"] == 2 and report.counts["receipt"] == 2 and report.counts["purchase"] == 5
    assert report.counts["product"] == 5          # HARIBO once per store; NEVER BOUGHT left out
    assert report.counts["ingredient"] == 3       # 'lechuga' only had the unbought product
    assert report.spend == report.source_spend == 15.47
    tables = {r[0] for r in rows(out, "SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"store", "category", "subcategory", "ingredient", "product", "receipt", "purchase", "build_info"}


def test_products_are_per_store_and_meet_at_the_ingredient(source, tmp_path):
    out = str(tmp_path / "graph.db")
    build(source, out)
    haribo = rows(out, "SELECT s.code FROM product p JOIN store s ON s.id=p.store_id WHERE item_name='HARIBO' ORDER BY 1")
    assert haribo == [("ah",), ("jumbo",)]
    spinach = rows(out, """SELECT DISTINCT store FROM purchase_detail WHERE ingredient='espinaca' ORDER BY 1""")
    assert spinach == [("ah",), ("jumbo",)]


def test_receipts_units_and_detail_view(source, tmp_path):
    out = str(tmp_path / "graph.db")
    build(source, out)
    assert rows(out, "SELECT id, item_count, total FROM receipt ORDER BY id") == [("ah_1", 2, 5.29), ("jumbo_1", 3, 10.18)]
    assert rows(out, "SELECT unit, quantity FROM purchase_detail WHERE item_name='JONGE KAAS'") == [("kg", 0.512)]
    detail = rows(out, "SELECT category, subcategory, name_es FROM purchase_detail WHERE item_name='AH SPINAZIE'")
    assert detail == [("Verduras", "Lechuga y Ensaladas", "Espinaca AH")]
    info = dict(rows(out, "SELECT key, value FROM build_info"))
    assert info["count_purchase"] == "5" and info["spend_total"] == "15.47"


def test_missing_ingredient_fails_and_keeps_the_old_file(source, tmp_path):
    out = tmp_path / "graph.db"
    build(source, str(out))
    before = out.read_bytes()
    conn = sqlite3.connect(source)
    conn.execute("DELETE FROM product_ingredient WHERE item_name='HARIBO'")
    conn.commit()
    conn.close()
    with pytest.raises(BuildError, match="no ingredient"):
        build(source, str(out))
    assert out.read_bytes() == before
    assert not (tmp_path / "graph.db.building").exists()


def test_inactive_ingredient_fails(source, tmp_path):
    IngredientStore(source).merge("gominola", "espinaca")
    conn = sqlite3.connect(source)
    conn.execute("UPDATE product_ingredient SET ingredient_id=(SELECT id FROM ingredient WHERE name='gominola') "
                 "WHERE item_name='HARIBO'")
    conn.commit()
    conn.close()
    with pytest.raises(BuildError, match="not active"):
        build(source, str(tmp_path / "graph.db"))


def test_source_is_not_modified(source, tmp_path):
    before = Path(source).read_bytes()
    build(source, str(tmp_path / "graph.db"))
    assert Path(source).read_bytes() == before


def test_rebuild_replaces_the_file(source, tmp_path):
    out = str(tmp_path / "graph.db")
    build(source, out)
    add_lines(source, [("ah_2", "ah", "2026-02-01", "AH SPINAZIE", "discrete_units", 1.0, 1.5, 1.5)])
    report = build(source, out)
    assert report.counts["receipt"] == 3 and rows(out, "SELECT COUNT(*) FROM purchase") == [(6,)]
