"""Explicit, atomic application of approved review manifests; preview by default."""

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from v2.stage3_classification.taxonomy import is_valid


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def checksum(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def connect(path, readonly=True):
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError(f"Database does not exist: {path}")
    conn = sqlite3.connect(path.as_uri() + ("?mode=ro" if readonly else "?mode=rw"), uri=True)
    conn.row_factory = sqlite3.Row
    if readonly:
        conn.execute("PRAGMA query_only=ON")
    return conn


def validate(manifest):
    if manifest.get("version") != 1 or not manifest.get("audit_id"):
        raise ValueError("Expected version 1 manifest with audit_id")
    seen = set()
    for entry in manifest.get("decisions", []):
        name = entry["item_name"]
        if name in seen:
            raise ValueError(f"Duplicate item: {name}")
        seen.add(name)
        if entry.get("approval") not in {"user_approved", "pending_final_preview"} or not entry.get("approval_reference"):
            raise ValueError(f"Unapproved decision: {name}")
        target = entry["target"]
        if set(target) - {"category", "subcategory", "producto_es"}:
            raise ValueError(f"Unexpected target fields: {name}")
        if not is_valid(target["category"], target["subcategory"]):
            raise ValueError(f"Invalid taxonomy: {name}")
        if "producto_es" in target and not isinstance(target["producto_es"], str):
            raise ValueError(f"Invalid Spanish name: {name}")
        if entry["expected_before"].get("item_name") != name:
            raise ValueError(f"Invalid before-image: {name}")
    if not seen:
        raise ValueError("Empty manifest")


def inspect(conn, manifest):
    validate(manifest)
    report = {"manifest_sha256": checksum(manifest), "items": [], "blockers": []}
    integrity = [r[0] for r in conn.execute("PRAGMA integrity_check")]
    report["integrity"] = integrity
    report["foreign_key_violations"] = [tuple(r) for r in conn.execute("PRAGMA foreign_key_check")]
    if integrity != ["ok"]:
        report["blockers"].append("Database integrity check failed")
    for entry in manifest["decisions"]:
        name = entry["item_name"]
        if entry["approval"] != "user_approved":
            report["blockers"].append(f"Final preview approval required: {name}")
        row = conn.execute("SELECT * FROM item_labels WHERE item_name=?", (name,)).fetchone()
        before = dict(row) if row else None
        if before != entry["expected_before"]:
            report["blockers"].append(f"Stale or missing label: {name}")
        for condition in entry.get("conditions", []):
            report["blockers"].append(f"{name}: {condition}")
        affected = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(line_total_paid_amount),0), "
            "MIN(date_of_purchase), MAX(date_of_purchase), GROUP_CONCAT(DISTINCT store) "
            "FROM normalized_data WHERE item_name=?", (name,),
        ).fetchone()
        bad_coverage = conn.execute(
            "SELECT COUNT(*) FROM normalized_data n WHERE n.item_name=? AND "
            "(SELECT COUNT(*) FROM classified_data c WHERE c.normalized_id=n.id) != 1", (name,),
        ).fetchone()[0]
        if bad_coverage:
            report["blockers"].append(f"Classified row coverage mismatch: {name}")
        report["items"].append({
            "item_name": name, "before": before, "target": entry["target"],
            "purchases": affected[0], "spend": affected[1],
            "first_purchase": affected[2], "last_purchase": affected[3], "stores": affected[4],
            "metadata_target": {"source": "manual", "confidence": 1.0, "needs_review": 0},
        })
    return report


def preview(path, manifest):
    conn = connect(path)
    try:
        conn.execute("BEGIN")
        return inspect(conn, manifest)
    finally:
        conn.close()


def apply(path, manifest, approved_checksum, backup_path):
    validate(manifest)
    digest = checksum(manifest)
    if approved_checksum != digest:
        raise ValueError("Approved checksum does not match manifest")
    conn = connect(path, readonly=False)
    try:
        conn.execute("BEGIN IMMEDIATE")
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name='classification_review_runs'").fetchone()
        if exists:
            previous = conn.execute(
                "SELECT after_json FROM classification_review_changes WHERE manifest_sha256=?", (digest,),
            ).fetchall()
            if previous:
                for record in previous:
                    after = json.loads(record[0])
                    current = conn.execute("SELECT * FROM item_labels WHERE item_name=?", (after["item_name"],)).fetchone()
                    if not current or dict(current) != after:
                        raise ValueError("Previously applied review has subsequent changes")
                conn.rollback()
                return {"status": "already_applied", "manifest_sha256": digest}
        report = inspect(conn, manifest)
        if report["blockers"]:
            raise ValueError("; ".join(report["blockers"]))
        # The reserved write lock prevents another writer changing the backup baseline.
        backup_path = Path(backup_path)
        if backup_path.exists() or backup_path.resolve() == Path(path).resolve():
            raise ValueError("Backup must be a new, separate file")
        source = connect(path)
        backup = sqlite3.connect(backup_path)
        try:
            source.backup(backup)
            if backup.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("Backup integrity check failed")
        finally:
            backup.close()
            source.close()
        conn.execute("CREATE TABLE IF NOT EXISTS classification_review_runs "
                     "(manifest_sha256 TEXT PRIMARY KEY, audit_id TEXT NOT NULL, manifest_json TEXT NOT NULL, applied_at TEXT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS classification_review_changes "
                     "(manifest_sha256 TEXT NOT NULL, item_name TEXT NOT NULL, before_json TEXT NOT NULL, "
                     "after_json TEXT NOT NULL, PRIMARY KEY(manifest_sha256,item_name))")
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("INSERT INTO classification_review_runs VALUES (?,?,?,?)",
                     (digest, manifest["audit_id"], canonical(manifest), now))
        for entry in manifest["decisions"]:
            before = entry["expected_before"]
            try:
                evidence = json.loads(before["evidence"]) if before["evidence"] else {}
            except (ValueError, TypeError):
                evidence = {"original_evidence_raw": before["evidence"]}
            if not isinstance(evidence, dict):
                evidence = {"original_evidence": evidence}
            history = evidence.get("classification_reviews", [])
            if not isinstance(history, list):
                raise ValueError("Incompatible review evidence history")
            evidence["classification_reviews"] = history + [{
                "manifest_sha256": digest, "approval_reference": entry["approval_reference"],
                "rationale": entry.get("rationale"), "identity_status": entry.get("identity_status"),
            }]
            after = dict(before, **entry["target"], source="manual", confidence=1.0,
                         needs_review=0, evidence=canonical(evidence), updated_at=now)
            conn.execute("UPDATE item_labels SET category=?,subcategory=?,producto_es=?,source=?,confidence=?,"
                         "needs_review=?,evidence=?,updated_at=? WHERE item_name=?",
                         tuple(after[k] for k in ("category", "subcategory", "producto_es", "source", "confidence",
                                                  "needs_review", "evidence", "updated_at", "item_name")))
            conn.execute("INSERT INTO classification_review_changes VALUES (?,?,?,?)",
                         (digest, after["item_name"], canonical(before), canonical(after)))
            conn.execute("UPDATE classified_data SET category=?,subcategory=?,producto_es=?,label_source=?,"
                         "confidence=?,needs_review=?,classified_at=? WHERE normalized_id IN "
                         "(SELECT id FROM normalized_data WHERE item_name=?)",
                         tuple(after[k] for k in ("category", "subcategory", "producto_es", "source", "confidence", "needs_review"))
                         + (now, after["item_name"]))
            mismatch = conn.execute(
                "SELECT COUNT(*) FROM classified_data c JOIN normalized_data n ON n.id=c.normalized_id "
                "WHERE n.item_name=? AND (c.category IS NOT ? OR c.subcategory IS NOT ? OR "
                "c.producto_es IS NOT ? OR c.label_source IS NOT 'manual' OR c.needs_review IS NOT 0)",
                (after["item_name"], after["category"], after["subcategory"], after["producto_es"]),
            ).fetchone()[0]
            if mismatch:
                raise ValueError("Classified data verification failed")
        if [r[0] for r in conn.execute("PRAGMA integrity_check")] != ["ok"]:
            raise ValueError("Post-apply integrity failure")
        if [tuple(r) for r in conn.execute("PRAGMA foreign_key_check")] != report["foreign_key_violations"]:
            raise ValueError("Foreign key baseline changed")
        conn.commit()
        return {"status": "applied", "manifest_sha256": digest, "items": len(manifest["decisions"])}
    finally:
        conn.close()  # Rolls back all uncommitted changes on errors.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approved-sha256")
    parser.add_argument("--backup")
    args = parser.parse_args()
    manifest = json.loads(Path(args.manifest).read_text())
    if args.apply:
        if not args.approved_sha256 or not args.backup:
            parser.error("Apply requires --approved-sha256 and --backup")
        result = apply(args.db, manifest, args.approved_sha256, args.backup)
    else:
        result = preview(args.db, manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
