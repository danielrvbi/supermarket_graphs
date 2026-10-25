"""
Output writer for V2 pipeline results.

Writes:
1. One JSON file per receipt (in clean/review/rejected subdirectories)
2. Old aggregated JSON files (as backup)
3. Clean receipts to SQLite database (processed_data table)
"""

import json
import logging
import os
import re
import tempfile
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Dict, Literal
from datetime import datetime

from v2.common.non_products import is_non_product_item
from v2.common.settings import settings
from v2.stage1_extraction.store import ProcessedDataStore


@contextmanager
def staged_outputs(outputs):
    """Publish a group of files; restore previous bytes on ordinary exceptions.

    Enclose the database transaction inside this context so commit failures also
    restore files. This is exception rollback, not cross-filesystem crash recovery.
    """
    temporary = []
    published = []
    retained = set()

    def stage(path, contents):
        fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        target = Path(name)
        temporary.append(target)
        with os.fdopen(fd, "wb") as stream:
            stream.write(contents)
        return target

    try:
        staged = []
        for path, contents in outputs:
            recovery = stage(path, path.read_bytes()) if path.exists() else None
            staged.append((path, stage(path, contents), recovery))

        def publish():
            for path, replacement, recovery in staged:
                os.replace(replacement, path)
                published.append((path, recovery))

        yield publish
    except BaseException as original:
        failures = []
        for path, recovery in reversed(published):
            try:
                if recovery is None:
                    path.unlink(missing_ok=True)
                else:
                    os.replace(recovery, path)
            except OSError as error:
                failures.append(f"{path}: {error}; recovery copy: {recovery}")
        if failures:
            retained = {recovery for _, recovery in published if recovery is not None}
            raise RuntimeError("Output restoration failed: " + "; ".join(failures)) from original
        raise
    finally:
        for path in temporary:
            if path not in retained:
                try:
                    path.unlink(missing_ok=True)
                except OSError as error:
                    logging.getLogger(__name__).warning("Could not remove temporary output %s: %s", path, error)


def sanitize_filename(name: str) -> str:
    """
    Convert receipt filename to safe JSON filename.

    Examples:
        "AH_kassabon_2024-03-08_1621_1080.pdf" -> "AH_kassabon_2024-03-08_1621_1080.json"
        "Screenshot 2026-05-12 at 22.10.29.png" -> "Screenshot_2026-05-12_at_22_10_29.json"
    """
    # Remove extension
    stem = Path(name).stem
    # Replace spaces, dots (in time), and multiple dashes with underscores
    safe = re.sub(r'[\s\.]+', '_', stem)
    # Remove multiple underscores
    safe = re.sub(r'_+', '_', safe)
    # Remove leading/trailing underscores
    safe = safe.strip('_')
    return f"{safe}.json"


def generate_receipt_id(store: str, receipt_path: str) -> str:
    """Generate a unique receipt ID from store and path."""
    stem = Path(receipt_path).stem
    safe_stem = re.sub(r'[\s\.]+', '_', stem)
    safe_stem = re.sub(r'_+', '_', safe_stem).strip('_')
    return f"{store}_{safe_stem}"


class OutputWriter:
    """Writes pipeline results to JSON files and SQLite database."""

    def __init__(self, processed_dir: str = None):
        self.processed_dir = Path(processed_dir or settings.PROCESSED_DIR)
        self.processed_dir.mkdir(parents=True, exist_ok=True)

        # New per-receipt directories
        self.clean_dir = self.processed_dir / "clean"
        self.review_dir = self.processed_dir / "review"
        self.rejected_dir = self.processed_dir / "rejected"

        for base_dir in [self.clean_dir, self.review_dir, self.rejected_dir]:
            (base_dir / "ah").mkdir(parents=True, exist_ok=True)
            (base_dir / "jumbo").mkdir(parents=True, exist_ok=True)

        # Old aggregated files (backup)
        self.backup_files = {
            ("ah", "clean"): self.processed_dir / "v2_ah_clean.json",
            ("ah", "review"): self.processed_dir / "v2_ah_review.json",
            ("ah", "rejected"): self.processed_dir / "v2_ah_rejected.json",
            ("jumbo", "clean"): self.processed_dir / "v2_jumbo_clean.json",
            ("jumbo", "review"): self.processed_dir / "v2_jumbo_review.json",
            ("jumbo", "rejected"): self.processed_dir / "v2_jumbo_rejected.json",
        }
        self._backup_data = {key: self._load_file(path) for key, path in self.backup_files.items()}

        # SQLite database writer
        self.db_writer = ProcessedDataStore(str(self.processed_dir / "processed_data.db"))

    def _load_file(self, path: Path) -> Dict:
        """Load existing JSON file or return empty dict."""
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def write_receipt(
        self,
        store: Literal["ah", "jumbo"],
        receipt_path: str,
        receipt_data: dict,
        status: Literal["clean", "review", "rejected"],
        metadata: dict = None,
    ):
        """
        Write a receipt to the appropriate output.

        Stage both JSON files, validate/write clean receipts in a transaction,
        publish files, then commit. Failures restore previous files and DB rows.

        Args:
            store: "ah" or "jumbo"
            receipt_path: Path to the original receipt file
            receipt_data: Receipt data matching RawReceipt schema
            status: "clean" (approved), "review" (needs human review), or "rejected"
            metadata: Additional metadata to store alongside
        """
        # Generate IDs and paths
        receipt_id = generate_receipt_id(store, receipt_path)
        json_filename = sanitize_filename(receipt_path)

        # Determine output directory
        status_dir = {
            "clean": self.clean_dir,
            "review": self.review_dir,
            "rejected": self.rejected_dir,
        }[status]
        json_path = status_dir / store / json_filename

        # Build full receipt data with metadata
        full_data = {
            "receipt_id": receipt_id,
            "receipt_path": receipt_path,
            "store": store,
            "date_of_purchase": receipt_data.get("date_of_purchase"),
            "items": receipt_data.get("items", []),
            "metadata": {
                **(metadata or {}),
                "processed_at": datetime.now().isoformat(),
                "pipeline_version": "v2.0.0",
                "thread_id": metadata.get("thread_id") if metadata else None,
            },
        }

        # Build a new backup without changing the in-memory committed snapshot.
        backup_key = (store, status)
        backup_data = self._backup_data[backup_key].copy()

        backup_entry = receipt_data.copy()
        if metadata:
            backup_entry["_metadata"] = {
                **metadata,
                "processed_at": datetime.now().isoformat(),
                "pipeline_version": "v2.0.0",
            }

        backup_data[receipt_path] = backup_entry

        transaction = nullcontext()
        if status == "clean":
            # Keep all items in JSON output, but exclude known non-product
            # receipt lines (deposits, savings stamps, cashback, etc.) from
            # the product database.
            all_items = receipt_data.get("items", [])
            db_items = [
                item for item in all_items
                if not is_non_product_item(item.get("item_name"))
            ]
            skipped = len(all_items) - len(db_items)
            if skipped:
                skipped_names = [
                    item.get("item_name") for item in all_items
                    if is_non_product_item(item.get("item_name"))
                ]
                print(f"  [FILTERED] {skipped} non-product line(s) excluded from DB: {skipped_names}")

            transaction = self.db_writer.receipt_transaction(
                receipt_id=receipt_id,
                receipt_path=receipt_path,
                receipt_json_path=str(json_path),
                store=store,
                date_of_purchase=receipt_data.get("date_of_purchase"),
                items=db_items,
                confidence=metadata.get("confidence", 0.0) if metadata else 0.0,
            )

        outputs = [(path, json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"))
                   for path, data in ((json_path, full_data), (self.backup_files[backup_key], backup_data))]
        with staged_outputs(outputs) as publish:
            with transaction:
                publish()
        self._backup_data[backup_key] = backup_data
        print(f"  [{status.upper()}] {json_filename} → {json_path.relative_to(self.processed_dir)}")
        if status == "clean":
            print(f"  [DATABASE] {len(db_items)} items → processed_data.db")

    def get_stats(self) -> dict:
        """Get statistics about processed receipts."""
        db_stats = self.db_writer.get_stats()

        # Count files in directories
        file_counts = {}
        for status, base_dir in [("clean", self.clean_dir), ("review", self.review_dir), ("rejected", self.rejected_dir)]:
            for store in ["ah", "jumbo"]:
                store_dir = base_dir / store
                count = len(list(store_dir.glob("*.json"))) if store_dir.exists() else 0
                file_counts[f"{store}_{status}"] = count

        return {
            "database": db_stats,
            "files": file_counts,
            "backup_files": {f"{k[0]}_{k[1]}": len(v) for k, v in self._backup_data.items()},
        }

    def print_stats(self):
        """Print statistics about processed receipts."""
        stats = self.get_stats()

        print("\n" + "=" * 60)
        print("V2 PIPELINE STATISTICS")
        print("=" * 60)

        print("\nPer-Receipt JSON Files:")
        for key, count in sorted(stats["files"].items()):
            print(f"  {key:15}: {count:4} files")

        print("\nDatabase (processed_data.db):")
        db = stats["database"]
        print(f"  Total receipts:  {db['total_receipts']}")
        print(f"  Total items:     {db['total_items']}")
        print(f"  Stores:          {db['stores']}")
        for store, data in db["by_store"].items():
            print(f"    {store:10} | {data['receipts']:3} receipts | {data['items']:4} items")

        print("\nBackup Files (aggregated JSON):")
        for key, count in sorted(stats["backup_files"].items()):
            print(f"  {key:15}: {count:4} receipts")

        print("=" * 60)
