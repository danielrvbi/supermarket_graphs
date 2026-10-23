"""
Output writer for V2 pipeline results.

Writes to separate files for clean/review/rejected receipts.
V1 files are left untouched.
"""

import json
import os
from pathlib import Path
from typing import Dict, Literal
from datetime import datetime

from v2.config.settings import settings


class OutputWriter:
    """Writes pipeline results to JSON files."""

    def __init__(self, processed_dir: str = None):
        self.processed_dir = Path(processed_dir or settings.PROCESSED_DIR)
        self.processed_dir.mkdir(parents=True, exist_ok=True)

        # Output files
        self.files = {
            ("ah", "clean"): self.processed_dir / "v2_ah_clean.json",
            ("ah", "review"): self.processed_dir / "v2_ah_review.json",
            ("ah", "rejected"): self.processed_dir / "v2_ah_rejected.json",
            ("jumbo", "clean"): self.processed_dir / "v2_jumbo_clean.json",
            ("jumbo", "review"): self.processed_dir / "v2_jumbo_review.json",
            ("jumbo", "rejected"): self.processed_dir / "v2_jumbo_rejected.json",
        }

        # Load existing data
        self._data = {key: self._load_file(path) for key, path in self.files.items()}

    def _load_file(self, path: Path) -> Dict:
        """Load existing JSON file or return empty dict."""
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def _save_file(self, path: Path, data: Dict):
        """Save data to JSON file."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def write_receipt(
        self,
        store: Literal["ah", "jumbo"],
        receipt_path: str,
        receipt_data: dict,
        status: Literal["clean", "review", "rejected"],
        metadata: dict = None,
    ):
        """
        Write a receipt to the appropriate output file.

        Args:
            store: "ah" or "jumbo"
            receipt_path: Path to the original receipt file
            receipt_data: Receipt data matching RawReceipt schema
            status: "clean" (approved), "review" (needs human review), or "rejected"
            metadata: Additional metadata to store alongside (for review/rejected)
        """
        key = (store, status)
        data = self._data[key]

        # Store receipt data
        entry = receipt_data.copy()
        if metadata:
            entry["_metadata"] = {
                **metadata,
                "processed_at": datetime.now().isoformat(),
                "pipeline_version": "v2.0.0",
            }

        data[receipt_path] = entry
        self._data[key] = data
        self._save_file(self.files[key], data)

        print(f"  [{status.upper()}] {receipt_path} → {self.files[key].name}")

    def get_stats(self) -> dict:
        """Get statistics about processed receipts."""
        return {
            key: len(data)
            for key, data in self._data.items()
        }

    def print_stats(self):
        """Print statistics about processed receipts."""
        stats = self.get_stats()
        print("\n" + "=" * 50)
        print("V2 Pipeline Statistics")
        print("=" * 50)
        for (store, status), count in sorted(stats.items()):
            print(f"  {store.upper():6} {status:8}: {count:4} receipts")
        print("=" * 50)
