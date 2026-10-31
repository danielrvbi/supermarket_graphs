"""Real file/SQLite rollback tests; no pipeline or network calls."""

import copy
import json
import sqlite3

import pytest

from v2.stage1_extraction import output_writer
from v2.stage1_extraction.output_writer import OutputWriter
from v2.stage2_normalization.store import NormalizedDataStore


def receipt(total):
    return {"date_of_purchase": "2026-01-01", "items": [{
        "item_name": "MILK", "measurement_type": "discrete_units", "measurement_quantity": 1,
        "price_per_measurement_unit": total, "line_total_paid_amount": total,
    }]}


def snapshot(writer):
    return ({path: path.read_bytes() for path in writer.processed_dir.rglob("*.json")},
            writer.db_writer.query_items(), copy.deepcopy(writer._backup_data))


def assert_unchanged(writer, before):
    assert snapshot(writer) == before
    assert not list(writer.processed_dir.rglob("*.tmp"))


def test_rejected_reprocessing_keeps_all_outputs_and_memory(tmp_path):
    writer = OutputWriter(str(tmp_path))
    writer.write_receipt("ah", "r.pdf", receipt(2), "clean")
    raw = writer.db_writer.query_items()[0]
    norm = NormalizedDataStore(writer.db_writer.db_path)
    norm.insert_normalized_item(raw["id"], raw["receipt_id"], "ah", "2026-01-01", "2026-01-01",
                                "MILK", "discrete_units", 1, 2, 2, [])
    before = snapshot(writer)
    with pytest.raises(ValueError, match="Referenced receipt item changed"):
        writer.write_receipt("ah", "r.pdf", receipt(3), "clean")
    assert_unchanged(writer, before)
    writer.write_receipt("ah", "r.pdf", receipt(2), "clean")
    assert writer.db_writer.query_items()[0]["id"] == raw["id"]


@pytest.mark.parametrize("status", ["clean", "review", "rejected"])
@pytest.mark.parametrize("existing", [True, False])
def test_second_file_failure_restores_or_removes_outputs(tmp_path, monkeypatch, status, existing):
    writer = OutputWriter(str(tmp_path))
    if existing:
        writer.write_receipt("ah", "r.pdf", receipt(2), status)
    before = snapshot(writer)
    replace = output_writer.os.replace
    calls = 0

    def fail_second(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("publication failed")
        return replace(source, destination)

    monkeypatch.setattr(output_writer.os, "replace", fail_second)
    with pytest.raises(OSError, match="publication failed"):
        writer.write_receipt("ah", "r.pdf", receipt(3), status)
    assert_unchanged(writer, before)


def test_sql_failure_never_publishes_files(tmp_path):
    writer = OutputWriter(str(tmp_path))
    writer.write_receipt("ah", "r.pdf", receipt(2), "clean")
    conn = sqlite3.connect(writer.db_writer.db_path)
    try:
        conn.execute("CREATE TRIGGER fail_insert BEFORE INSERT ON processed_data "
                     "BEGIN SELECT RAISE(ABORT, 'injected SQL failure'); END")
        conn.commit()
    finally:
        conn.close()
    before = snapshot(writer)
    with pytest.raises(sqlite3.IntegrityError, match="injected SQL failure"):
        writer.write_receipt("ah", "r.pdf", receipt(3), "clean")
    assert_unchanged(writer, before)


@pytest.mark.parametrize("existing", [True, False])
def test_commit_failure_restores_outputs_and_rolls_back_sql(tmp_path, monkeypatch, existing):
    writer = OutputWriter(str(tmp_path))
    if existing:
        writer.write_receipt("ah", "r.pdf", receipt(2), "clean")
    before = snapshot(writer)

    class FailCommit(sqlite3.Connection):
        def commit(self):
            raise sqlite3.OperationalError("injected commit failure")

    def connect():
        conn = sqlite3.connect(writer.db_writer.db_path, factory=FailCommit)
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    monkeypatch.setattr(writer.db_writer, "_connect", connect)
    with pytest.raises(sqlite3.OperationalError, match="injected commit failure"):
        writer.write_receipt("ah", "r.pdf", receipt(3), "clean")
    assert_unchanged(writer, before)


def test_serialization_failure_leaves_outputs_unchanged(tmp_path):
    writer = OutputWriter(str(tmp_path))
    writer.write_receipt("ah", "r.pdf", receipt(2), "clean")
    before = snapshot(writer)
    with pytest.raises(TypeError):
        writer.write_receipt("ah", "r.pdf", receipt(3), "clean", metadata={"invalid": object()})
    assert_unchanged(writer, before)


def test_staging_failure_cleans_up_without_changing_files_or_sql(tmp_path, monkeypatch):
    writer = OutputWriter(str(tmp_path))
    writer.write_receipt("ah", "r.pdf", receipt(2), "clean")
    before = snapshot(writer)
    mkstemp = output_writer.tempfile.mkstemp
    calls = 0

    def fail_backup_staging(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("disk full")
        return mkstemp(*args, **kwargs)

    monkeypatch.setattr(output_writer.tempfile, "mkstemp", fail_backup_staging)
    with pytest.raises(OSError, match="disk full"):
        writer.write_receipt("ah", "r.pdf", receipt(3), "clean")
    assert_unchanged(writer, before)


def test_restoration_failure_retains_recovery_copy_and_reports_it(tmp_path, monkeypatch):
    writer = OutputWriter(str(tmp_path))
    writer.write_receipt("ah", "r.pdf", receipt(2), "clean")
    before = snapshot(writer)
    receipt_path = tmp_path / "clean" / "ah" / "r.json"
    original = receipt_path.read_bytes()
    replace = output_writer.os.replace
    calls = 0

    def fail_after_first(source, destination):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise OSError("filesystem unavailable")
        return replace(source, destination)

    monkeypatch.setattr(output_writer.os, "replace", fail_after_first)
    with pytest.raises(RuntimeError, match="Output restoration failed.*recovery copy:") as error:
        writer.write_receipt("ah", "r.pdf", receipt(3), "clean")
    recovery = list(receipt_path.parent.glob(".r.json.*.tmp"))
    assert len(recovery) == 1 and recovery[0].read_bytes() == original
    assert str(recovery[0]) in str(error.value)
    assert writer.db_writer.query_items() == before[1]
    assert writer._backup_data == before[2]


def test_success_publishes_both_files_before_committing(tmp_path, monkeypatch):
    writer = OutputWriter(str(tmp_path))
    writer.write_receipt("ah", "r.pdf", receipt(2), "clean")
    old_id = writer.db_writer.query_items()[0]["id"]

    class ObserveCommit(sqlite3.Connection):
        def commit(self):
            assert json.loads((tmp_path / "clean/ah/r.json").read_text())["items"][0]["line_total_paid_amount"] == 3
            assert json.loads((tmp_path / "v2_ah_clean.json").read_text())["r.pdf"]["items"][0]["line_total_paid_amount"] == 3
            super().commit()

    monkeypatch.setattr(writer.db_writer, "_connect", lambda: sqlite3.connect(writer.db_writer.db_path, factory=ObserveCommit))
    writer.write_receipt("ah", "r.pdf", receipt(3), "clean")
    assert writer.db_writer.query_items()[0]["id"] == old_id
    assert writer.db_writer.query_items()[0]["line_total_paid_amount"] == 3
    assert writer._backup_data[("ah", "clean")]["r.pdf"]["items"][0]["line_total_paid_amount"] == 3
    assert not list(tmp_path.rglob("*.tmp"))
