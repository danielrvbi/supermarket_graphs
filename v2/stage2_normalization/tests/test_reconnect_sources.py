import sqlite3

import pytest

from v2.stage1_extraction.store import SCHEMA as RAW_SCHEMA
from v2.stage2_normalization.store import SCHEMA as NORMAL_SCHEMA
from v2.stage2_normalization.reconnect_sources import repair


@pytest.fixture
def broken(tmp_path):
    path = tmp_path / "broken.db"
    conn = sqlite3.connect(path)
    conn.executescript(RAW_SCHEMA + NORMAL_SCHEMA)
    conn.execute("INSERT INTO processed_data (id,receipt_id,receipt_path,receipt_json_path,store,item_index,item_name,"
                 "date_of_purchase,measurement_type,measurement_quantity,price_per_measurement_unit,line_total_paid_amount) "
                 "VALUES (10,'r','r.pdf','r.json','ah',0,'SOAP','2025-01-01','discrete_units',1,2,2)")
    conn.execute("INSERT INTO normalized_data (source_id,receipt_id,store,item_name,date_of_purchase,month_of_purchase,"
                 "measurement_type,measurement_quantity,price_per_measurement_unit,line_total_paid_amount) "
                 "VALUES (1,'r','ah','SOAP','2025-01-01','2025-01-01','discrete_units',1,2,2)")
    conn.commit()
    conn.close()
    return path


def test_preview_and_apply(broken, tmp_path):
    before = broken.read_bytes()
    assert len(repair(broken)["mappings"]) == 1
    assert broken.read_bytes() == before
    assert repair(broken, tmp_path / "backup.db", 1)["status"] == "applied"
    conn = sqlite3.connect(broken)
    assert conn.execute("SELECT source_id FROM normalized_data").fetchone()[0] == 10
    assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    conn.close()
    assert repair(broken, tmp_path / "unused.db")["status"] == "no_changes"


def test_wrong_count_blocks(broken, tmp_path):
    before = broken.read_bytes()
    with pytest.raises(ValueError):
        repair(broken, tmp_path / "backup.db", 25)
    assert broken.read_bytes() == before


def test_missing_match_blocks(broken, tmp_path):
    conn = sqlite3.connect(broken)
    conn.execute("UPDATE processed_data SET item_name='OTHER'")
    conn.commit()
    conn.close()
    before = broken.read_bytes()
    with pytest.raises(ValueError):
        repair(broken, tmp_path / "backup.db")
    assert broken.read_bytes() == before


def test_failure_rolls_back(broken, tmp_path):
    conn = sqlite3.connect(broken)
    conn.execute("CREATE TRIGGER block_repair BEFORE UPDATE ON normalized_data BEGIN SELECT RAISE(ABORT,'test'); END")
    conn.commit()
    conn.close()
    before = broken.read_bytes()
    with pytest.raises(sqlite3.IntegrityError):
        repair(broken, tmp_path / "backup.db")
    assert broken.read_bytes() == before


def test_reprocessing_preserves_parent_and_rejects_changed_items(broken, tmp_path):
    from v2.stage1_extraction.store import ProcessedDataStore

    repair(broken, tmp_path / "backup.db", 1)
    store = ProcessedDataStore(str(broken))
    item = dict(item_name="SOAP", measurement_type="discrete_units", measurement_quantity=1,
                price_per_measurement_unit=2, line_total_paid_amount=2)
    args = dict(receipt_id="r", receipt_path="r.pdf", receipt_json_path="r.json", store="ah",
                date_of_purchase="2025-01-01", items=[item], confidence=1)
    store.insert_receipt(**args)
    conn = sqlite3.connect(broken)
    assert conn.execute("SELECT id FROM processed_data").fetchone()[0] == 10
    assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    conn.close()
    before = broken.read_bytes()
    with pytest.raises(ValueError, match="Referenced"):
        store.insert_receipt(**dict(args, items=[dict(item, item_name="CHANGED")]))
    assert broken.read_bytes() == before
    with pytest.raises(ValueError):
        store.insert_receipt(**dict(args, items=[]))


def test_normalization_upsert_preserves_id_and_foreign_keys_enabled(broken, tmp_path):
    from v2.stage2_normalization.store import NormalizedDataStore

    repair(broken, tmp_path / "backup.db", 1)
    store = NormalizedDataStore(str(broken))
    conn = store._connect()
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    old_id = conn.execute("SELECT id FROM normalized_data").fetchone()[0]
    conn.execute("CREATE TABLE classified_data (normalized_id REFERENCES normalized_data(id))")
    conn.execute("INSERT INTO classified_data VALUES (?)", (old_id,))
    conn.commit()
    conn.close()
    store.insert_normalized_item(10,"r","ah","2025-01-01","2025-01-01","SOAP",
                                 "discrete_units",1,2,2,[])
    conn = store._connect()
    assert conn.execute("SELECT id FROM normalized_data").fetchone()[0] == old_id
    assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    conn.close()
    with pytest.raises(ValueError, match="coordinated"):
        store.clear_normalized_table()
