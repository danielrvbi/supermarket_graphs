"""
Unit tests for stage 3D (temp db, no API calls).

Usage:
    python -m pytest v2/stage3d_ingredients/tests -v
"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from v2.stage3_classification.store import ClassificationStore
from v2.stage3c_taxonomy.seed_v2 import V1_MAP, V2_TAXONOMY
from v2.stage3c_taxonomy.store import TaxonomyStore
from v2.stage3d_ingredients import proposals
from v2.stage3d_ingredients.apply import apply_file
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


@pytest.fixture
def root(tmp_path):
    return tmp_path / "proposals"


def propose(db, root, namer, **kw):
    kw.setdefault("max_subcategories", 10)
    return assign(db, namer, root=root, **kw)


def lines_of(root, label):
    return {l["item_name"]: l for l in proposals.read(proposals.path_for(label, root))}


def apply_all(db, root):
    return [apply_file(db, p) for p in proposals.files(root)]


def links(db):
    return {r["item_name"]: r for r in db.list_links(needs_review=None)}


def ingredient_names(db):
    conn = sqlite3.connect(db.db_path)
    try:
        return sorted(r[0] for r in conn.execute("SELECT name FROM ingredient WHERE active=1"))
    finally:
        conn.close()


def db_rows(db):
    conn = sqlite3.connect(db.db_path)
    try:
        return (conn.execute("SELECT * FROM ingredient").fetchall(),
                conn.execute("SELECT * FROM product_ingredient").fetchall())
    finally:
        conn.close()


def test_key_ignores_accents_case_and_plurals():
    assert ingredient_key("Espinacas") == ingredient_key("espinaca")
    assert ingredient_key("Limones") == ingredient_key("limón")
    assert ingredient_key("Leche de Avena") == ingredient_key("leche de avena")
    assert ingredient_key("pan") != ingredient_key("papa")
    assert ingredient_key("tomate") == ingredient_key("tomates")
    assert ingredient_key("pan") == ingredient_key("panes")
    assert ingredient_key("nuez") == ingredient_key("nueces")
    assert ingredient_key("leche") == ingredient_key("leches")
    assert ingredient_key("salsa de tomates") == ingredient_key("salsa de tomate")
    assert ingredient_key("sal") != ingredient_key("salsa")


def test_singular_and_plural_share_one_ingredient(db):
    conn = db.connect()
    try:
        first, created = db.get_or_create(conn, "tomate", True)
        assert created
        assert db.get_or_create(conn, "tomates", True) == (first, False)
        conn.execute("INSERT INTO ingredient (name) VALUES ('tomates')")   # left over from the old key
        assert db.duplicate_keys(conn) == [["tomate", "tomates"]]
        conn.commit()
    finally:
        conn.close()
    assert db.merge("tomate", "tomates")["items_affected"] == 0   # exact names, not the shared key
    assert db.duplicate_keys() == [] and ingredient_names(db) == ["tomates"]


def test_assign_writes_one_jsonl_per_subcategory_and_no_db_rows(db, root):
    namer = FakeNamer()
    report = propose(db, root, namer)
    assert namer.calls == 3
    assert db_rows(db) == ([], [])
    assert sorted(p.name for p in proposals.files(root)) == sorted(
        proposals.path_for(l, root).name for l in (SALAD, MILK, HAIR))
    salad = lines_of(root, SALAD)
    assert salad["JUMBO SPINAZIE GEWAS"]["ingredient"] == salad["AH SPINAZIE"]["ingredient"] == "espinaca"
    assert salad["AH SPINAZIE"]["llm_ingredient"] == "espinaca" and salad["AH SPINAZIE"]["store"] == "ah"
    milk = lines_of(root, MILK)
    assert milk["OATLY"]["ingredient"] == milk["BARISTA HAVER 500 MI"]["ingredient"] == "leche de avena"
    assert lines_of(root, HAIR)["H&S SHAMPOO"]["is_food"] is False
    assert report.proposed == 6 and report.new_ingredients == 4 and report.pending == 0


def test_proposed_subcategories_are_skipped_until_redo(db, root):
    propose(db, root, FakeNamer(), subcategory=SALAD)
    namer = FakeNamer()
    report = propose(db, root, namer)
    assert {label for label, _, _ in namer.seen} == {MILK, HAIR} and report.skipped_proposed == 3
    namer = FakeNamer(answers={**ANSWERS, "AH IJSBERGSLA": ("lechuga iceberg", True)})
    propose(db, root, namer, subcategory=SALAD, redo=True)
    assert namer.calls == 1 and lines_of(root, SALAD)["AH IJSBERGSLA"]["ingredient"] == "lechuga iceberg"


def test_names_in_other_proposals_are_reused_and_offered(db, root):
    propose(db, root, FakeNamer(), subcategory=SALAD)
    other = "Verduras > Otros"
    ClassificationStore(db.db_path).upsert_label("BIO SPINAZIE", "Hogar", "Otros", "old_data",
                                                 producto_es="Espinacas Bio", store="jumbo")
    TaxonomyStore(db.db_path).set_manual("BIO SPINAZIE", *other.split(" > "))
    namer = FakeNamer(answers={"BIO SPINAZIE": ("Espinacas", True)})
    propose(db, root, namer, subcategory=other)
    assert set(namer.seen[0][1]) == {"espinaca", "lechuga"}       # vocabulary from the salad file
    line = lines_of(root, other)["BIO SPINAZIE"]
    assert line["ingredient"] == "espinaca" and line["new"] is False


def test_apply_writes_db_and_moves_file(db, root):
    propose(db, root, FakeNamer())
    reports = apply_all(db, root)
    assert sum(r.llm for r in reports) == 6 and proposals.files(root) == []
    assert len(list(root.glob("*/applied/*.jsonl"))) == 3
    l = links(db)
    assert l["JUMBO SPINAZIE GEWAS"]["ingredient"] == l["AH SPINAZIE"]["ingredient"] == "espinaca"
    assert all(r["source"] == "llm" and r["needs_review"] == 0 for r in l.values())
    assert ingredient_names(db) == ["champú", "espinaca", "leche de avena", "lechuga"]
    assert {i["name"] for i in db.ingredient_summary(shared=True)} == {"espinaca", "leche de avena"}
    assert {i["name"]: i["is_food"] for i in db.ingredient_summary()}["champú"] == 0
    assert db.change_log()[0]["op"] == "apply"


def test_edited_lines_become_manual_and_none_stays_unassigned(db, root):
    propose(db, root, FakeNamer(), subcategory=SALAD)
    path = proposals.path_for(SALAD, root)
    lines = proposals.read(path)
    for line in lines:
        if line["item_name"] == "AH IJSBERGSLA":
            line["ingredient"] = "Lechuga Iceberg"
        if line["item_name"] == "AH SPINAZIE":
            line["ingredient"] = None
    proposals.write(path, lines)
    report = apply_file(db, path)
    assert (report.llm, report.manual, report.unassigned) == (1, 1, ["AH SPINAZIE"])
    l = links(db)
    assert l["AH IJSBERGSLA"]["source"] == "manual" and l["AH IJSBERGSLA"]["ingredient"] == "lechuga iceberg"
    assert "AH SPINAZIE" not in l
    work, _ = pending_work(db, db.connect(), root)
    assert [p["item_name"] for p in work[SALAD]] == ["AH SPINAZIE"]


def test_apply_dry_run_and_invalid_names_write_nothing(db, root):
    propose(db, root, FakeNamer(), subcategory=SALAD)
    path = proposals.path_for(SALAD, root)
    report = apply_file(db, path, dry_run=True)
    assert report.llm == 3 and db_rows(db) == ([], []) and path.exists()
    lines = proposals.read(path)
    lines[0]["ingredient"] = "  "
    proposals.write(path, lines)
    with pytest.raises(IngredientError):
        apply_file(db, path)
    assert db_rows(db) == ([], []) and path.exists()


def test_stale_lines_are_skipped(db, root):
    propose(db, root, FakeNamer(), subcategory=SALAD)
    ClassificationStore(db.db_path).upsert_label("AH IJSBERGSLA", "Hogar", "Otros", "manual",
                                                 producto_es="Lechuga Romana AH", store="ah")
    report = apply_file(db, proposals.path_for(SALAD, root))
    assert report.stale == ["AH IJSBERGSLA"] and report.llm == 2


def test_rerun_skips_applied_and_manual_then_follows_changes(db, root):
    propose(db, root, FakeNamer())
    apply_all(db, root)
    db.set_manual("OATLY", "bebida de avena")
    namer = FakeNamer()
    report = propose(db, root, namer)
    assert namer.calls == 0 and report.skipped_current == 5 and report.skipped_manual == 1

    ClassificationStore(db.db_path).upsert_label("AH IJSBERGSLA", "Hogar", "Otros", "manual",
                                                 producto_es="Lechuga Romana AH", store="ah")
    namer = FakeNamer()
    propose(db, root, namer)
    assert namer.seen == [(SALAD, ["espinaca", "lechuga"], ["AH IJSBERGSLA"])]
    assert lines_of(root, SALAD)["AH IJSBERGSLA"]["new"] is False


def test_failed_call_writes_no_file(db, root):
    report = propose(db, root, FakeNamer(fail={SALAD}))
    assert not proposals.path_for(SALAD, root).exists() and proposals.path_for(MILK, root).exists()
    assert next(r for r in report.results if r.label == SALAD).errors
    namer = FakeNamer()
    propose(db, root, namer)
    assert [label for label, _, _ in namer.seen] == [SALAD]


def test_missing_and_duplicate_ids_get_no_ingredient(db, root):
    propose(db, root, FakeNamer(drop={"AH SPINAZIE"}, duplicate={"AH IJSBERGSLA"}), subcategory=SALAD)
    salad = lines_of(root, SALAD)
    assert salad["JUMBO SPINAZIE GEWAS"]["ingredient"] == "espinaca"
    assert (salad["AH SPINAZIE"]["ingredient"], salad["AH SPINAZIE"]["pending"]) == (None, "missing")
    assert (salad["AH IJSBERGSLA"]["ingredient"], salad["AH IJSBERGSLA"]["pending"]) == (None, "duplicate_id")


def test_selection_touches_only_selected_subcategories(db, root):
    propose(db, root, FakeNamer(), subcategory="Verduras>Lechuga y Ensaladas")
    assert [p.name for p in proposals.files(root)] == [proposals.path_for(SALAD, root).name]
    report = propose(db, root, FakeNamer(), max_subcategories=1)
    assert len(report.results) == 1 and report.results[0].label in (MILK, HAIR)
    assert report.remaining_subcategories == 1


def test_dry_runs_write_nothing(db, root):
    before = Path(db.db_path).read_bytes()
    report = assign(db, None, dry_run=True, model="mistral-large-latest", keep_prompts=True, root=root)
    assert len(report.results) == 3 and report.est_input_tokens > 0 and report.est_output_tokens > 0
    salad = next(r for r in report.results if r.label == SALAD)
    assert ". JUMBO SPINAZIE GEWAS | Espinaca Jumbo | jumbo" in salad.prompts[0]
    report = propose(db, root, FakeNamer(), dry_run=True)
    assert report.proposed == 6 and not root.exists()
    assert Path(db.db_path).read_bytes() == before
    with pytest.raises(ValueError):
        assign(db, None, root=root)


def test_chunks_see_names_from_earlier_chunks(db, root, monkeypatch):
    import v2.stage3d_ingredients.assign as assign_module
    monkeypatch.setattr(assign_module, "CHUNK_SIZE", 2)
    namer = FakeNamer()
    propose(db, root, namer, subcategory=SALAD)
    assert namer.calls == 2
    assert namer.seen[0][1] == [] and namer.seen[1][1] == ["espinaca"]
    assert len(lines_of(root, SALAD)) == 3


def test_merge_rename_and_approve(db, root):
    propose(db, root, FakeNamer(answers={**ANSWERS, "BARISTA HAVER 500 MI": ("leche de avena barista", True)}))
    apply_all(db, root)
    assert db.merge("leche de avena barista", "leche de avena", dry_run=True)["items_affected"] == 1
    assert links(db)["BARISTA HAVER 500 MI"]["ingredient"] == "leche de avena barista"
    db.merge("leche de avena barista", "leche de avena")
    assert links(db)["BARISTA HAVER 500 MI"]["ingredient"] == "leche de avena"
    assert db.find(db.connect(), "leche de avena barista")["name"] == "leche de avena"   # follows merge

    db.rename("lechuga", "lechuga iceberg")
    assert links(db)["AH IJSBERGSLA"]["ingredient"] == "lechuga iceberg"
    with pytest.raises(IngredientError):
        db.rename("espinaca", "Lechuga Iceberg")


def test_upstream_tables_are_not_modified(db, root):
    conn = sqlite3.connect(db.db_path)
    before = (conn.execute("SELECT * FROM item_labels ORDER BY item_name").fetchall(),
              conn.execute("SELECT item_name, subcategory_id, source FROM product_category ORDER BY 1").fetchall())
    conn.close()
    propose(db, root, FakeNamer())
    apply_all(db, root)
    conn = sqlite3.connect(db.db_path)
    after = (conn.execute("SELECT * FROM item_labels ORDER BY item_name").fetchall(),
             conn.execute("SELECT item_name, subcategory_id, source FROM product_category ORDER BY 1").fetchall())
    conn.close()
    assert before == after


def test_pending_work_skips_products_without_v2_label(db, root):
    ClassificationStore(db.db_path).upsert_label("NEW THING", "Hogar", "Otros", "old_data", producto_es="Cosa")
    conn = db.connect()
    work, skipped = pending_work(db, conn, root)
    conn.close()
    assert skipped["no_subcategory"] == 1 and sum(len(v) for v in work.values()) == 6


def test_proposal_lines_are_valid_json(db, root):
    propose(db, root, FakeNamer(), subcategory=SALAD)
    raw = proposals.path_for(SALAD, root).read_text(encoding="utf-8").splitlines()
    assert len(raw) == 3 and all(json.loads(r)["category"] == "Verduras" for r in raw)


def test_too_specific_names_are_marked():
    from v2.stage3d_ingredients.assign import too_specific
    assert too_specific("verduras para horno (calabacín, pimiento)")
    assert too_specific("mezcla italiana para saltear")
    assert too_specific("lechuga iceberg con maíz y rábanos")
    assert not too_specific("verduras para sopa") and not too_specific("leche de avena")


def test_one_folder_per_category(db, root):
    assert proposals.path_for("Verduras>Lechuga y Ensaladas", root) == root / "verduras" / "lechuga_y_ensaladas.jsonl"
    propose(db, root, FakeNamer())
    assert sorted(p.parent.name for p in proposals.files(root)) == ["cuidado_personal_y_salud", "lacteos_y_huevos", "verduras"]
    assert [p.name for p in proposals.files(root, category="Verduras")] == ["lechuga_y_ensaladas.jsonl"]


def test_budget_stops_before_the_call_that_would_exceed_it(db, root):
    namer = FakeNamer()
    namer.model = "mistral-large-latest"     # priced, ~$0.002 per small subcategory
    report = propose(db, root, namer, budget=0.003)
    assert namer.calls == 1 and report.stopped_by_budget and len(proposals.files(root)) == 1
    namer = FakeNamer()
    namer.model = "mistral-large-latest"
    report = propose(db, root, namer, budget=0.0001)
    assert namer.calls == 0 and report.stopped_by_budget


def edit_lines(path, **changes):
    """changes: {item_name: {key: value}}"""
    lines = proposals.read(path)
    for line in lines:
        line.update(changes.get(line["item_name"], {}))
    proposals.write(path, lines)


def is_food_of(db, name):
    return {i["name"]: i["is_food"] for i in db.ingredient_summary()}[name]


def test_edited_is_food_updates_an_existing_ingredient(db, root):
    propose(db, root, FakeNamer(), subcategory=HAIR)
    path = proposals.path_for(HAIR, root)
    lines = proposals.read(path)
    apply_file(db, path)
    assert is_food_of(db, "champú") == 0
    proposals.write(path, lines)      # the same proposal again, now corrected
    edit_lines(path, **{"H&S SHAMPOO": {"is_food": True}})
    report = apply_file(db, path)
    assert report.is_food_changed == ["champú"] and is_food_of(db, "champú") == 1


def test_unedited_is_food_keeps_a_manual_flag(db, root):
    db.set_manual("JUMBO SPINAZIE GEWAS", "espinaca", is_food=False)
    propose(db, root, FakeNamer(), subcategory=SALAD)
    report = apply_file(db, proposals.path_for(SALAD, root))
    assert report.is_food_changed == [] and is_food_of(db, "espinaca") == 0


def test_conflicting_is_food_edits_abort(db, root):
    propose(db, root, FakeNamer(), subcategory=SALAD)
    path = proposals.path_for(SALAD, root)
    edit_lines(path, **{"AH SPINAZIE": {"is_food": False},
                        "JUMBO SPINAZIE GEWAS": {"llm_is_food": False}})
    with pytest.raises(IngredientError):
        apply_file(db, path)
    assert db_rows(db) == ([], []) and path.exists()


def test_each_apply_keeps_its_own_archived_file(db, root):
    propose(db, root, FakeNamer(), subcategory=SALAD)
    path = proposals.path_for(SALAD, root)
    lines = proposals.read(path)
    edit_lines(path, **{"AH IJSBERGSLA": {"ingredient": "lechuga iceberg"}})
    first = Path(apply_file(db, path).moved_to)
    proposals.write(path, lines)      # a later file for the same subcategory
    second = Path(apply_file(db, path).moved_to)
    assert first != second and first.exists() and second.exists()
    assert {l["ingredient"] for l in proposals.read(first)} == {"espinaca", "lechuga iceberg"}
    assert {l["ingredient"] for l in proposals.read(second)} == {"espinaca", "lechuga"}


def test_budget_refuses_a_model_without_pricing(db, root):
    namer = FakeNamer()     # model "fake" has no pricing
    with pytest.raises(ValueError, match="No pricing"):
        propose(db, root, namer, budget=0)
    assert namer.calls == 0 and proposals.files(root) == []


def test_restore_undoes_a_merge_the_other_way(db, root):
    propose(db, root, FakeNamer(), subcategory=MILK)
    apply_all(db, root)
    db.set_manual("OATLY", "bebida de avena")
    db.merge("bebida de avena", "leche de avena")
    with pytest.raises(IngredientError):
        db.restore("leche de avena")          # still active
    db.restore("bebida de avena")
    assert db.merge("leche de avena", "bebida de avena")["items_affected"] == 2
    assert ingredient_names(db) == ["bebida de avena"]
    assert {l["ingredient"] for l in links(db).values()} == {"bebida de avena"}
