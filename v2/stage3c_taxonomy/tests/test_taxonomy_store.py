"""
Unit tests for stage 3C (temp db, no API calls).

Usage:
    python -m pytest v2/stage3c_taxonomy/tests -v
"""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from v2.stage3_classification.store import ClassificationStore
from v2.stage3_classification.taxonomy import TAXONOMY
from v2.stage3c_taxonomy.seed_v2 import V1_MAP, V2_TAXONOMY
from v2.stage3c_taxonomy.store import TaxonomyError, TaxonomyStore, split_label
from v2.stage3c_taxonomy.sync import sync


class FakePicker:
    """Picks the first candidate whose subcategory name appears in producto_es, else the first."""

    def __init__(self, skip=()):
        self.calls = 0
        self.skip = set(skip)

    def pick(self, v1_label, candidates, products):
        self.calls += 1
        picks = {}
        for p in products:
            if p["item_name"] in self.skip:
                continue
            match = next((c for c in candidates if split_label(c)[1].split()[0] in (p["producto_es"] or "")),
                         candidates[0])
            picks[p["item_name"]] = (match, "high", "fake")
        return picks


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "data.db")
    labels = ClassificationStore(path)
    labels.upsert_label("CRUESLI", "Hogar", "Cereal", "old_data", producto_es="Cereal")
    labels.upsert_label("KIPFILET", "Carnes", "Pollo", "old_data", producto_es="Pollo AH")
    labels.upsert_label("KIPGEHAKT", "Carnes", "Pollo", "old_data", producto_es="Carne Molida de Pollo")
    labels.upsert_label("MOSTERD", "Hogar", "Salsas", "embed_llm", producto_es="Mostaza", needs_review=True)
    store = TaxonomyStore(path)
    store.init_from_seed(V2_TAXONOMY, V1_MAP)
    return store


def v2_label(db, item_name):
    row = db.list_labels(source=None)
    found = {r["item_name"]: r for r in row}[item_name]
    return found["category"], found["subcategory"], found["source"], found["needs_review"]


def test_seed_is_complete():
    old = {(c, s) for c, subs in TAXONOMY.items() for s in subs}
    assert set(V1_MAP) == old
    valid = {f"{c} > {s}" for c, subs in V2_TAXONOMY.items() for s in subs}
    for target in V1_MAP.values():
        for label in [target] if isinstance(target, str) else target:
            assert label in valid, label
    assert all(subs[-1] == "Otros" for subs in V2_TAXONOMY.values())


def test_init_roundtrips_seed(db):
    assert db.taxonomy() == V2_TAXONOMY
    mapping = db.v1_map()
    assert [label for _, label in mapping[("Hogar", "Cereal")]] == ["Despensa > Cereales y Avena"]
    assert len(mapping[("Carnes", "Pollo")]) == 4
    with pytest.raises(TaxonomyError):
        db.init_from_seed(V2_TAXONOMY, V1_MAP)


def test_sync_maps_and_splits_without_touching_v1(db):
    before = Path(db.db_path).read_bytes()
    conn = sqlite3.connect(db.db_path)
    v1_before = conn.execute("SELECT * FROM item_labels ORDER BY item_name").fetchall()
    conn.close()

    report = sync(db, picker=FakePicker())
    assert (report.mapped, report.split_llm, report.pending_split) == (1, 3, 0)
    assert v2_label(db, "CRUESLI")[:3] == ("Despensa", "Cereales y Avena", "map")
    assert v2_label(db, "KIPFILET")[:2] == ("Carnes y Pescado", "Pollo")
    assert v2_label(db, "KIPGEHAKT")[:2] == ("Carnes y Pescado", "Carne Molida")
    assert v2_label(db, "MOSTERD")[3] == 1   # v1 review flag carries over

    conn = sqlite3.connect(db.db_path)
    assert conn.execute("SELECT * FROM item_labels ORDER BY item_name").fetchall() == v1_before
    conn.close()
    assert before != Path(db.db_path).read_bytes()


def test_dry_run_writes_nothing(db):
    before = Path(db.db_path).read_bytes()
    report = sync(db, picker=FakePicker(), dry_run=True)
    assert report.mapped == 1 and report.splits == {"Carnes > Pollo": 2, "Hogar > Salsas": 1}
    assert Path(db.db_path).read_bytes() == before


def test_no_llm_leaves_pending_then_resync_resolves(db):
    report = sync(db, picker=None)
    assert report.pending_split == 3
    assert v2_label(db, "KIPFILET")[2] == "pending_split"
    report = sync(db, picker=FakePicker())
    assert report.split_llm == 3 and report.skipped_current == 1


def test_resync_is_idempotent_and_follows_v1_changes(db):
    sync(db, picker=FakePicker())
    report = sync(db, picker=FakePicker())
    assert report.skipped_current == 4 and report.mapped == report.split_llm == 0

    ClassificationStore(db.db_path).upsert_label("CRUESLI", "Pasta/Sopas", "Granos", "manual")
    report = sync(db, picker=FakePicker())
    assert report.mapped == 1
    assert v2_label(db, "CRUESLI")[:2] == ("Despensa", "Arroz y Granos")


def test_manual_never_overwritten(db):
    db.set_manual("CRUESLI", "Despensa", "Otros")
    sync(db, picker=FakePicker())
    assert v2_label(db, "CRUESLI")[:3] == ("Despensa", "Otros", "manual")


def test_missing_picks_retried_then_pending(db):
    picker = FakePicker(skip={"KIPFILET"})
    report = sync(db, picker=picker)
    assert report.pending_split == 1
    assert v2_label(db, "KIPFILET")[2] == "pending_split"


def test_rename_and_move_keep_labels_via_ids(db):
    sync(db, picker=FakePicker())
    result = db.rename_subcategory("Despensa", "Cereales y Avena", "Desayuno")
    assert result["items_affected"] == 1
    assert v2_label(db, "CRUESLI")[:2] == ("Despensa", "Desayuno")
    db.add_category("Desayuno y Untables")
    db.move_subcategory("Despensa", "Desayuno", "Desayuno y Untables")
    assert v2_label(db, "CRUESLI")[:2] == ("Desayuno y Untables", "Desayuno")
    # v1 map follows the id too
    assert [l for _, l in db.v1_map()[("Hogar", "Cereal")]] == ["Desayuno y Untables > Desayuno"]


def test_merge_repoints_products_and_map(db):
    sync(db, picker=FakePicker())
    db.merge_subcategory("Despensa", "Cereales y Avena", "Despensa", "Arroz y Granos")
    assert v2_label(db, "CRUESLI")[:2] == ("Despensa", "Arroz y Granos")
    assert "Cereales y Avena" not in db.taxonomy()["Despensa"]
    assert [l for _, l in db.v1_map()[("Hogar", "Cereal")]] == ["Despensa > Arroz y Granos"]


def test_split_flags_products(db):
    sync(db, picker=FakePicker())
    db.approve("CRUESLI")
    db.split_subcategory("Despensa", "Cereales y Avena", ["Avena", "Granola"])
    assert {"Avena", "Granola"} <= set(db.taxonomy()["Despensa"])
    assert v2_label(db, "CRUESLI")[3] == 1


def test_dry_run_op_changes_nothing(db):
    before = Path(db.db_path).read_bytes()
    db.rename_category("Despensa", "Alacena", dry_run=True)
    assert Path(db.db_path).read_bytes() == before


def test_guards(db):
    with pytest.raises(TaxonomyError):
        db.rename_subcategory("Frutas", "Otros", "Varias")
    with pytest.raises(TaxonomyError):
        db.add_subcategory("Frutas", "Bayas")
    with pytest.raises(TaxonomyError):
        db.move_subcategory("Bebidas", "Agua", "Bebidas")
    sync(db, picker=FakePicker())
    with pytest.raises(TaxonomyError):
        db.remove_category("Despensa")
    with pytest.raises(TaxonomyError):
        db.set_manual("CRUESLI", "Despensa", "Nope")


def test_classified_v2_view(tmp_path):
    path = str(tmp_path / "data.db")
    labels = ClassificationStore(path)   # creates classified_data
    labels.upsert_label("CRUESLI", "Hogar", "Cereal", "old_data")
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO classified_data (receipt_id, store, item_name, line_total_paid_amount, category, subcategory) "
                 "VALUES ('r1', 'ah', 'CRUESLI', 3.5, 'Hogar', 'Cereal')")
    conn.commit()
    conn.close()
    db = TaxonomyStore(path)
    db.init_from_seed(V2_TAXONOMY, V1_MAP)
    sync(db)
    conn = sqlite3.connect(path)
    row = conn.execute("SELECT category, category_v2, subcategory_v2, line_total_paid_amount FROM classified_v2").fetchone()
    conn.close()
    assert row == ("Hogar", "Despensa", "Cereales y Avena", 3.5)


def test_resolve_label():
    from v2.stage3c_taxonomy.sync import resolve_label
    cands = ["Frutas > Bayas", "Frutas > Cítricos", "Frutas > Frutas Tropicales", "Frutas > Otros"]
    assert resolve_label("Frutas > Bayas", cands) == "Frutas > Bayas"
    assert resolve_label("Frutas > Tropicales", cands) == "Frutas > Frutas Tropicales"
    assert resolve_label("citricos", cands) == "Frutas > Cítricos"
    assert resolve_label("Verduras > Tomate", cands) is None


def test_picker_error_keeps_other_groups(db):
    class Flaky(FakePicker):
        def pick(self, v1_label, candidates, products):
            if v1_label == "Hogar > Salsas":
                raise ValueError("bad output")
            return super().pick(v1_label, candidates, products)

    report = sync(db, picker=Flaky())
    assert report.split_llm == 2 and report.pending_split == 1
    assert v2_label(db, "MOSTERD")[2] == "pending_split"


def test_overrides_are_valid_and_survive_sync(db):
    from v2.stage3c_taxonomy.seed_v2 import V2_OVERRIDES
    valid = {f"{c} > {s}" for c, subs in V2_TAXONOMY.items() for s in subs}
    assert all(label in valid for label in V2_OVERRIDES.values())

    applied = db.apply_overrides({"MOSTERD": "Despensa > Aderezos", "NOT A PRODUCT": "Despensa > Otros"})
    assert applied == ["MOSTERD"]
    sync(db, picker=FakePicker())
    assert v2_label(db, "MOSTERD") == ("Despensa", "Aderezos", "manual", 0)
