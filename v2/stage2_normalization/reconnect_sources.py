"""Repair uniquely matched orphan source links. Preview unless --apply is supplied."""

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from v2.stage2_normalization.normalizer import Normalizer


FIELDS = ("receipt_id", "store", "date_of_purchase", "month_of_purchase", "item_name",
          "measurement_type", "measurement_quantity", "price_per_measurement_unit", "line_total_paid_amount")


def mappings(conn):
    normalizer = Normalizer()
    result = []
    for row in conn.execute("SELECT n.* FROM normalized_data n LEFT JOIN processed_data p "
                            "ON p.id=n.source_id WHERE n.source_id IS NOT NULL AND p.id IS NULL ORDER BY n.id").fetchall():
        before = dict(row)
        candidates = []
        for raw in conn.execute("SELECT * FROM processed_data WHERE receipt_id=? AND store=?",
                                (before["receipt_id"], before["store"])):
            normalized = normalizer.normalize_item(dict(raw)).to_dict()
            if not normalized["filtered_out"] and all(before[k] == normalized[k] for k in FIELDS):
                candidates.append(dict(raw))
        if len(candidates) != 1:
            raise ValueError(f"Non-unique replacement for normalized ID {before['id']}")
        target = candidates[0]
        if conn.execute("SELECT 1 FROM normalized_data WHERE source_id=?", (target["id"],)).fetchone():
            raise ValueError("Replacement already referenced")
        result.append({"before": before, "replacement": target})
    ids = [r["replacement"]["id"] for r in result]
    if len(ids) != len(set(ids)):
        raise ValueError("Multiple orphan rows share a replacement")
    return result


def fingerprint(conn, query):
    h = hashlib.sha256()
    for row in conn.execute(query):
        h.update(json.dumps(list(row), default=lambda v: v.hex(), ensure_ascii=False).encode())
        h.update(b"\n")
    return h.hexdigest()


def repair(db, backup=None, expected_count=None):
    path = Path(db).resolve()
    conn = sqlite3.connect(path.as_uri() + ("?mode=rw" if backup else "?mode=ro"), uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        if not backup:
            conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN IMMEDIATE" if backup else "BEGIN")
        changes = mappings(conn)
        if expected_count is not None and len(changes) != expected_count:
            raise ValueError("Unexpected orphan count")
        if not backup or not changes:
            return {"status": "preview" if not backup else "no_changes", "mappings": changes}
        backup_path = Path(backup)
        if backup_path.exists() or backup_path.resolve() == path:
            raise ValueError("Backup must be a new separate file")
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        unchanged = {t: fingerprint(conn, 'SELECT * FROM "'+t+'" ORDER BY rowid')
                     for t in tables if t != "normalized_data"}
        columns = [r[1] for r in conn.execute("PRAGMA table_info(normalized_data)") if r[1] != "source_id"]
        query = "SELECT " + ",".join(columns) + " FROM normalized_data ORDER BY id"
        normalized_before = fingerprint(conn, query)
        source = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        dest = sqlite3.connect(backup_path)
        try:
            source.backup(dest)
            if dest.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("Backup failed integrity check")
        finally:
            dest.close()
            source.close()
        for change in changes:
            before, target = change["before"], change["replacement"]
            count = conn.execute("UPDATE normalized_data SET source_id=? WHERE id=? AND source_id=?",
                                 (target["id"], before["id"], before["source_id"])).rowcount
            if count != 1:
                raise ValueError("Stale repair mapping")
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Foreign key violations remain")
        if conn.execute("PRAGMA integrity_check").fetchall()[0][0] != "ok":
            raise ValueError("Integrity check failed")
        if normalized_before != fingerprint(conn, query):
            raise ValueError("Non-reference normalized fields changed")
        for table, digest in unchanged.items():
            if digest != fingerprint(conn, 'SELECT * FROM "'+table+'" ORDER BY rowid'):
                raise ValueError(f"Unrelated table changed: {table}")
        conn.commit()
        return {"status": "applied", "backup": str(backup), "mappings": changes,
                "verified_at_utc": datetime.now(timezone.utc).isoformat(),
                "foreign_key_violations": 0, "other_tables_unchanged": sorted(unchanged)}
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup")
    args = parser.parse_args()
    if args.apply and not args.backup:
        parser.error("--apply requires --backup")
    print(json.dumps(repair(args.db, args.backup if args.apply else None), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
