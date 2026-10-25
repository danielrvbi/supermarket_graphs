"""
Unit tests for stage 3D (temp db, no API calls).

Usage:
    python -m pytest v2/stage3d_ingredients/tests -v
"""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from v2.stage3_classification.store import ClassificationStore
from v2.stage3c_taxonomy.seed_v2 import V1_MAP, V2_TAXONOMY
from v2.stage3c_taxonomy.store import TaxonomyStore
from v2.stage3d_ingredients.assign import Group, assign, pending_work
from v2.stage3d_ingredients.store import IngredientError, IngredientStore, ingredient_key


SALAD = "Verduras > Lechuga y Ensaladas"
MILK = "Lácteos y Huevos > Leche Vegetal"
HAIR = "Cuidado Personal y Salud > Cuidado del Cabello"

PRODUCTS = [
    # item_name, store, producto_es, v2 label
    ("JUMBO SPINAZIE GEWAS", "jumbo", "Espinaca Jumbo", SALAD),
    ("AH SPINAZIE", "ah", "Espinacas AH", SALAD),
    ("AH IJSBERGSLA", "ah", "Lechuga Iceberg AH", SALAD),
    ("OATLY", "ah", "Leche de Avena Oatly", MILK),
    ("BARISTA HAVER 500 MI", "jumbo", "Bebida de Avena Barista Oatly", MILK),
    ("H&S SHAMPOO", "ah", "Shampoo H&S", HAIR),
]

# What the fake model answers per product
ANSWERS = {
    "JUMBO SPINAZIE GEWAS": ("Espinaca", True),
    "AH SPINAZIE": ("espinacas", True),          # plural: must land on the same ingredient
    "AH IJSBERGSLA": ("lechuga", True),
    "OATLY": ("leche de avena", True),
    "BARISTA HAVER 500 MI": ("leche de avena", True),
    "H&S SHAMPOO": ("champú", False),
}


class FakeNamer:
    """Groups products by ANSWERS; can fail whole subcategories or mangle ids."""

    model = "fake"

    def __init__(self, answers=None, fail=(), drop=(), duplicate=(), confidence="high"):
        self.answers = answers or ANSWERS
        self.fail, self.drop, self.duplicate = set(fail), set(drop), set(duplicate)
        self.confidence = confidence
        self.calls = 0
        self.seen = []    # (label, vocabulary, item names)

    def name(self, subcategory, vocabulary, products):
        self.calls += 1
        self.seen.append((subcategory, list(vocabulary), [p["item_name"] for p in products]))
        if subcategory in self.fail:
            raise RuntimeError("boom")
        groups = {}
        for i, p in enumerate(products, 1):
            if p["item_name"] in self.drop:
                continue
            name, is_food = self.answers[p["item_name"]]
            groups.setdefault((name, is_food), []).append(i)
        result = [Group(n, f, self.confidence, ids, "fake") for (n, f), ids in groups.items()]
        for p in products:
            if p["item_name"] in self.duplicate:
                i = [q["item_name"] for q in products].index(p["item_name"]) + 1
                result.append(Group("otra cosa", True, "high", [i], "dup"))
        return result


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "data.db")
    labels = ClassificationStore(path)
    taxonomy = TaxonomyStore(path)
    taxonomy.init_from_seed(V2_TAXONOMY, V1_MAP)
    for item_name, store, producto_es, label in PRODUCTS:
        labels.upsert_label(item_name, "Hogar", "Otros", "old_data", producto_es=producto_es, store=store)
        taxonomy.set_manual(item_name, *label.split(" > "))
    return IngredientStore(path)


def links(db):
    return {r["item_name"]: r for r in db.list_links(needs_review=None)}


def ingredient_names(db):
    conn = sqlite3.connect(db.db_path)
    try:
        return sorted(r[0] for r in conn.execute("SELECT name FROM ingredient WHERE active=1"))
    finally:
        conn.close()


def test_key_ignores_accents_case_and_plurals():
    assert ingredient_key("Espinacas") == ingredient_key("espinaca")
    assert ingredient_key("Limones") == ingredient_key("limón")
    assert ingredient_key("Leche de Avena") == ingredient_key("leche de avena")
    assert ingredient_key("pan") != ingredient_key("papa")


def test_one_call_per_subcategory_and_cross_store_sharing(db):
    namer = FakeNamer()
    report = assign(db, namer, max_subcategories=10)
    assert namer.calls == 3
    assert {label for label, _, _ in namer.seen} == {SALAD, MILK, HAIR}
    l = links(db)
    assert l["JUMBO SPINAZIE GEWAS"]["ingredient"] == l["AH SPINAZIE"]["ingredient"] == "espinaca"
    assert l["OATLY"]["ingredient"] == l["BARISTA HAVER 500 MI"]["ingredient"] == "leche de avena"
    assert ingredient_names(db) == ["champú", "espinaca", "leche de avena", "lechuga"]
    assert report.assigned == 6 and report.new_ingredients == 4 and report.pending == 0

    shared = {i["name"] for i in db.ingredient_summary(shared=True)}
    assert shared == {"espinaca", "leche de avena"}
    nonfood = {i["name"]: i["is_food"] for i in db.ingredient_summary()}
    assert nonfood["champú"] == 0


def test_new_names_are_flagged_reused_names_are_not(db):
    db.set_manual("JUMBO SPINAZIE GEWAS", "espinaca")
    namer = FakeNamer()
    assign(db, namer, subcategory=SALAD)
    _, vocabulary, items = namer.seen[0]
    assert vocabulary == ["espinaca"] and "JUMBO SPINAZIE GEWAS" not in items
    l = links(db)
    assert l["AH SPINAZIE"]["needs_review"] == 0       # reused existing
    assert l["AH IJSBERGSLA"]["needs_review"] == 1     # new ingredient
    assert l["JUMBO SPINAZIE GEWAS"]["source"] == "manual"


def test_selection_touches_only_selected_subcategories(db):
    assign(db, FakeNamer(), subcategory="Verduras>Lechuga y Ensaladas")
    assert set(links(db)) == {"JUMBO SPINAZIE GEWAS", "AH SPINAZIE", "AH IJSBERGSLA"}
    report = assign(db, FakeNamer(), max_subcategories=1)
    assert len(report.results) == 1 and report.results[0].label in (MILK, HAIR)
    assert report.remaining_subcategories == 1


def test_rerun_skips_current_and_manual_then_follows_changes(db):
    assign(db, FakeNamer(), max_subcategories=10)
    db.set_manual("OATLY", "bebida de avena")
    namer = FakeNamer()
    report = assign(db, namer, max_subcategories=10)
    assert namer.calls == 0 and report.skipped_current == 5 and report.skipped_manual == 1
    assert links(db)["OATLY"]["ingredient"] == "bebida de avena"

    ClassificationStore(db.db_path).upsert_label("AH IJSBERGSLA", "Hogar", "Otros", "manual",
                                                 producto_es="Lechuga Romana AH", store="ah")
    namer = FakeNamer()
    assign(db, namer, max_subcategories=10)
    assert namer.seen == [(SALAD, ["espinaca", "lechuga"], ["AH IJSBERGSLA"])]


def test_failed_call_leaves_subcategory_pending_and_others_written(db):
    report = assign(db, FakeNamer(fail={SALAD}), max_subcategories=10)
    l = links(db)
    assert l["AH SPINAZIE"]["source"] == "pending" and l["AH SPINAZIE"]["ingredient_id"] is None
    assert l["OATLY"]["source"] == "llm"
    assert report.pending == 3 and report.results[0].errors
    report = assign(db, FakeNamer(), max_subcategories=10)
    assert report.assigned == 3 and links(db)["AH SPINAZIE"]["ingredient"] == "espinaca"


def test_missing_and_duplicate_ids_stay_pending(db):
    assign(db, FakeNamer(drop={"AH SPINAZIE"}, duplicate={"AH IJSBERGSLA"}), subcategory=SALAD)
    l = links(db)
    assert l["JUMBO SPINAZIE GEWAS"]["ingredient"] == "espinaca"
    assert l["AH SPINAZIE"]["source"] == "pending"
    assert l["AH IJSBERGSLA"]["source"] == "pending"
    assert "otra cosa" not in ingredient_names(db)


def test_low_confidence_is_flagged(db):
    db.set_manual("JUMBO SPINAZIE GEWAS", "espinaca")
    assign(db, FakeNamer(confidence="medium"), subcategory=SALAD)
    assert links(db)["AH SPINAZIE"]["needs_review"] == 1


def test_dry_runs_write_nothing(db):
    before = Path(db.db_path).read_bytes()
    report = assign(db, None, dry_run=True, model="mistral-large-latest", keep_prompts=True)
    assert len(report.results) == 3 and report.est_input_tokens > 0 and report.est_output_tokens > 0
    salad = next(r for r in report.results if r.label == SALAD)
    assert ". JUMBO SPINAZIE GEWAS | Espinaca Jumbo | jumbo" in salad.prompts[0]
    report = assign(db, FakeNamer(), max_subcategories=10, dry_run=True)
    assert report.assigned == 6
    assert Path(db.db_path).read_bytes() == before
    with pytest.raises(ValueError):
        assign(db, None)


def test_chunks_see_names_from_earlier_chunks(db, monkeypatch):
    import v2.stage3d_ingredients.assign as assign_module
    monkeypatch.setattr(assign_module, "CHUNK_SIZE", 2)
    namer = FakeNamer()
    assign(db, namer, subcategory=SALAD)
    assert namer.calls == 2
    assert namer.seen[0][1] == [] and namer.seen[1][1]   # second chunk gets the first chunk's names


def test_merge_rename_and_approve(db):
    assign(db, FakeNamer(answers={**ANSWERS, "BARISTA HAVER 500 MI": ("leche de avena barista", True)}),
           max_subcategories=10)
    assert db.merge("leche de avena barista", "leche de avena", dry_run=True)["items_affected"] == 1
    assert links(db)["BARISTA HAVER 500 MI"]["ingredient"] == "leche de avena barista"
    db.merge("leche de avena barista", "leche de avena")
    assert links(db)["BARISTA HAVER 500 MI"]["ingredient"] == "leche de avena"
    assert db.find(db.connect(), "leche de avena barista")["name"] == "leche de avena"   # follows merge

    db.rename("lechuga", "lechuga iceberg")
    assert links(db)["AH IJSBERGSLA"]["ingredient"] == "lechuga iceberg"
    with pytest.raises(IngredientError):
        db.rename("espinaca", "Lechuga Iceberg")

    assert db.approve(subcategory_label=SALAD)["items_affected"] == 3
    assert all(links(db)[i]["needs_review"] == 0 for i in ("AH SPINAZIE", "AH IJSBERGSLA"))
    assert db.approve(ingredient="leche de avena")["items_affected"] == 2
    assert [e["op"] for e in db.change_log()][:2] == ["approve", "approve"]


def test_upstream_tables_are_not_modified(db):
    conn = sqlite3.connect(db.db_path)
    before = (conn.execute("SELECT * FROM item_labels ORDER BY item_name").fetchall(),
              conn.execute("SELECT item_name, subcategory_id, source FROM product_category ORDER BY 1").fetchall())
    conn.close()
    assign(db, FakeNamer(), max_subcategories=10)
    conn = sqlite3.connect(db.db_path)
    after = (conn.execute("SELECT * FROM item_labels ORDER BY item_name").fetchall(),
             conn.execute("SELECT item_name, subcategory_id, source FROM product_category ORDER BY 1").fetchall())
    conn.close()
    assert before == after


def test_pending_work_skips_products_without_v2_label(db):
    ClassificationStore(db.db_path).upsert_label("NEW THING", "Hogar", "Otros", "old_data", producto_es="Cosa")
    conn = db.connect()
    work, skipped = pending_work(db, conn)
    conn.close()
    assert skipped["no_subcategory"] == 1 and sum(len(v) for v in work.values()) == 6
