import copy
import json
import sqlite3

import pytest

from v2.stage3_classification.store import SCHEMA
from v2.stage3b_classification_review.apply_reviews import apply, checksum, connect, preview


@pytest.fixture
def sample(tmp_path):
    path = tmp_path / "data.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute("CREATE TABLE normalized_data (id INTEGER PRIMARY KEY, item_name TEXT, "
                 "line_total_paid_amount REAL, date_of_purchase TEXT, store TEXT)")
    conn.execute("INSERT INTO normalized_data VALUES (1,'SOAP',2.5,'2026-01-01','ah')")
    conn.execute("INSERT INTO item_labels (item_name,store,producto_es,category,subcategory,source,confidence,evidence) "
                 "VALUES ('SOAP','ah','Soap','Hogar','Limpieza','old_data',1,?)", (json.dumps({"reasoning": "original"}),))
    conn.execute("INSERT INTO classified_data (normalized_id,receipt_id,store,item_name,line_total_paid_amount,category,subcategory) "
                 "VALUES (1,'receipt','ah','SOAP',2.5,'Hogar','Limpieza')")
    conn.commit()
    conn.close()
    conn = connect(path)
    before = dict(conn.execute("SELECT * FROM item_labels").fetchone())
    conn.close()
    manifest = {"version": 1, "audit_id": "test", "decisions": [{
        "item_name": "SOAP", "approval": "user_approved", "approval_reference": "test approval",
        "expected_before": before, "target": {"category": "Higiene", "subcategory": "Jabón"},
    }]}
    return path, manifest, tmp_path / "backup.db"


def test_preview_readonly(sample):
    path, manifest, _ = sample
    before = path.read_bytes()
    assert not preview(path, manifest)["blockers"]
    assert path.read_bytes() == before


def test_apply_preserves_evidence_and_ids_and_is_idempotent(sample):
    path, manifest, backup = sample
    assert apply(path, manifest, checksum(manifest), backup)["status"] == "applied"
    conn = connect(path)
    label = dict(conn.execute("SELECT * FROM item_labels").fetchone())
    assert label["source"] == "manual"
    assert label["producto_es"] == "Soap"
    assert json.loads(label["evidence"])["reasoning"] == "original"
    row = conn.execute("SELECT id,line_total_paid_amount,category FROM classified_data").fetchone()
    assert tuple(row) == (1, 2.5, "Higiene")
    conn.close()
    before = path.read_bytes()
    assert apply(path, manifest, checksum(manifest), backup)["status"] == "already_applied"
    assert path.read_bytes() == before


@pytest.mark.parametrize("change", ["approval", "taxonomy", "duplicate", "stale", "condition"])
def test_rejects_unsafe_manifest(sample, change):
    path, manifest, backup = sample
    entry = manifest["decisions"][0]
    if change == "approval":
        entry["approval"] = "pending"
    elif change == "taxonomy":
        entry["target"]["subcategory"] = "Invented"
    elif change == "duplicate":
        manifest["decisions"].append(copy.deepcopy(entry))
    elif change == "stale":
        entry["expected_before"]["producto_es"] = "Stale"
    else:
        entry["conditions"] = ["Name approval pending"]
    before = path.read_bytes()
    with pytest.raises(ValueError):
        apply(path, manifest, checksum(manifest), backup)
    assert path.read_bytes() == before


def test_transaction_rolls_back_after_update_failure(sample):
    path, manifest, backup = sample
    conn = sqlite3.connect(path)
    conn.execute("CREATE TRIGGER reject_classified BEFORE UPDATE ON classified_data "
                 "BEGIN SELECT RAISE(ABORT,'injected failure'); END")
    conn.commit()
    conn.close()
    before = path.read_bytes()
    with pytest.raises(sqlite3.IntegrityError):
        apply(path, manifest, checksum(manifest), backup)
    assert path.read_bytes() == before


def test_checksum_gate(sample):
    path, manifest, backup = sample
    with pytest.raises(ValueError, match="checksum"):
        apply(path, manifest, "wrong", backup)


def test_missing_coverage_blocks_apply(sample):
    path, manifest, backup = sample
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM classified_data")
    conn.commit()
    conn.close()
    assert preview(path, manifest)["blockers"]
    with pytest.raises(ValueError, match="coverage"):
        apply(path, manifest, checksum(manifest), backup)


def test_backup_contains_before_image(sample):
    path, manifest, backup = sample
    apply(path, manifest, checksum(manifest), backup)
    conn = connect(backup)
    assert dict(conn.execute("SELECT * FROM item_labels").fetchone()) == manifest["decisions"][0]["expected_before"]
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='classification_review_runs'").fetchone()[0] == 0
    conn.close()


def test_keep_category_and_name_only(sample):
    path, manifest, backup = sample
    manifest["decisions"][0]["target"] = {"category": "Hogar", "subcategory": "Limpieza", "producto_es": "Dish soap"}
    apply(path, manifest, checksum(manifest), backup)
    conn = connect(path)
    row = conn.execute("SELECT category,subcategory,producto_es,source FROM item_labels").fetchone()
    assert tuple(row) == ("Hogar", "Limpieza", "Dish soap", "manual")
    conn.close()


def test_pending_final_approval_can_be_previewed_but_not_applied(sample):
    path, manifest, backup = sample
    manifest["decisions"][0]["approval"] = "pending_final_preview"
    assert "Final preview approval required: SOAP" in preview(path, manifest)["blockers"]
    before = path.read_bytes()
    with pytest.raises(ValueError, match="approval required"):
        apply(path, manifest, checksum(manifest), backup)
    assert path.read_bytes() == before
