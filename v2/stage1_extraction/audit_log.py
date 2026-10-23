"""
Audit logger for V2 pipeline.

Logs every decision, checkpoint, and pipeline execution for full traceability.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

from v2.common.settings import settings


class AuditLogger:
    """Logs pipeline execution details for auditing and debugging."""

    def __init__(self, log_path: str = None):
        self.log_path = Path(log_path or (Path(settings.PROCESSED_DIR) / "v2_audit_log.json"))
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._logs: Dict = self._load()

    def _load(self) -> Dict:
        """Load existing audit log."""
        if self.log_path.exists():
            try:
                with open(self.log_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def _save(self):
        """Save audit log to disk."""
        with open(self.log_path, "w", encoding="utf-8") as f:
            json.dump(self._logs, f, indent=2, ensure_ascii=False, default=str)

    def start_receipt(
        self,
        thread_id: str,
        receipt_path: str,
        store: str,
        pipeline_version: str = "v2.0.0",
    ) -> dict:
        """
        Start logging a new receipt.

        Returns:
            The log entry dict (to be updated as pipeline progresses)
        """
        entry = {
            "thread_id": thread_id,
            "receipt_path": receipt_path,
            "store": store,
            "pipeline_version": pipeline_version,
            "started_at": datetime.now().isoformat(),
            "completed_at": None,
            "checkpoints": [],
            "deterministic_vs_llm": None,
            "validation_results": None,
            "verification_result": None,
            "corrections_applied": [],
            "final_confidence": None,
            "final_status": None,
            "errors": [],
        }
        self._logs[thread_id] = entry
        self._save()
        return entry

    def log_checkpoint(
        self,
        thread_id: str,
        node_name: str,
        status: str,
        state_snapshot: dict,
        metadata: dict = None,
    ):
        """Log a checkpoint from a pipeline node."""
        if thread_id not in self._logs:
            return

        checkpoint = {
            "node": node_name,
            "timestamp": datetime.now().isoformat(),
            "status": status,
            "items_count": len(state_snapshot.get("merged_items", [])),
            "confidence": state_snapshot.get("overall_confidence", 0.0),
            "errors": state_snapshot.get("errors", []),
            "metadata": metadata or {},
        }
        self._logs[thread_id]["checkpoints"].append(checkpoint)
        self._save()

    def log_extraction_comparison(
        self,
        thread_id: str,
        deterministic_items: List[dict],
        llm_items: List[dict],
        merged_items: List[dict],
    ):
        """Log comparison between deterministic and LLM extraction."""
        if thread_id not in self._logs:
            return

        # Find differences
        det_names = {item.get("item_name", "").upper() for item in deterministic_items}
        llm_names = {item.get("item_name", "").upper() for item in llm_items}

        self._logs[thread_id]["deterministic_vs_llm"] = {
            "deterministic_count": len(deterministic_items),
            "llm_count": len(llm_items),
            "merged_count": len(merged_items),
            "items_only_in_deterministic": list(det_names - llm_names),
            "items_only_in_llm": list(llm_names - det_names),
            "items_in_both": list(det_names & llm_names),
        }
        self._save()

    def log_validation(
        self,
        thread_id: str,
        arithmetic_ok: bool,
        arithmetic_errors: List[str],
        reconciliation_ok: bool,
        reconciliation_error: Optional[str],
        duplicates_found: List,
        sanity_warnings: List[str],
    ):
        """Log validation results."""
        if thread_id not in self._logs:
            return

        self._logs[thread_id]["validation_results"] = {
            "arithmetic_ok": arithmetic_ok,
            "arithmetic_errors": arithmetic_errors,
            "reconciliation_ok": reconciliation_ok,
            "reconciliation_error": reconciliation_error,
            "duplicates_found": len(duplicates_found),
            "sanity_warnings": sanity_warnings,
        }
        self._save()

    def log_verification(
        self,
        thread_id: str,
        confidence: float,
        discrepancies: List[str],
        verifier_notes: str,
    ):
        """Log AI verification results."""
        if thread_id not in self._logs:
            return

        self._logs[thread_id]["verification_result"] = {
            "confidence": confidence,
            "discrepancies": discrepancies,
            "verifier_notes": verifier_notes,
        }
        self._save()

    def log_correction(
        self,
        thread_id: str,
        correction: dict,
    ):
        """Log a correction applied by the pipeline."""
        if thread_id not in self._logs:
            return

        self._logs[thread_id]["corrections_applied"].append({
            "timestamp": datetime.now().isoformat(),
            **correction,
        })
        self._save()

    def complete_receipt(
        self,
        thread_id: str,
        final_confidence: float,
        final_status: str,
    ):
        """Mark a receipt as completed."""
        if thread_id not in self._logs:
            return

        self._logs[thread_id]["completed_at"] = datetime.now().isoformat()
        self._logs[thread_id]["final_confidence"] = final_confidence
        self._logs[thread_id]["final_status"] = final_status
        self._save()

    def log_error(self, thread_id: str, error: str):
        """Log an error for a receipt."""
        if thread_id not in self._logs:
            return

        self._logs[thread_id]["errors"].append({
            "timestamp": datetime.now().isoformat(),
            "error": error,
        })
        self._save()

    def get_receipt_log(self, thread_id: str) -> Optional[dict]:
        """Get the audit log for a specific receipt."""
        return self._logs.get(thread_id)

    def print_receipt_log(self, thread_id: str):
        """Pretty-print the audit log for a receipt."""
        log = self.get_receipt_log(thread_id)
        if not log:
            print(f"No log found for {thread_id}")
            return

        print("=" * 70)
        print(f"Audit Log: {thread_id}")
        print("=" * 70)
        print(f"Receipt: {log['receipt_path']}")
        print(f"Store: {log['store']}")
        print(f"Started: {log['started_at']}")
        print(f"Completed: {log.get('completed_at', 'N/A')}")
        print(f"Final Status: {log.get('final_status', 'N/A')}")
        print(f"Final Confidence: {log.get('final_confidence', 'N/A')}")
        print()

        print("Checkpoints:")
        for i, cp in enumerate(log.get("checkpoints", []), 1):
            status_icon = "✓" if cp["status"] == "success" else "✗"
            print(f"  {i}. [{status_icon}] {cp['node']}")
            print(f"      Items: {cp['items_count']}, Confidence: {cp['confidence']:.2f}")
            if cp.get("errors"):
                print(f"      Errors: {cp['errors']}")

        if log.get("deterministic_vs_llm"):
            dvl = log["deterministic_vs_llm"]
            print(f"\nExtraction Comparison:")
            print(f"  Deterministic: {dvl['deterministic_count']} items")
            print(f"  LLM: {dvl['llm_count']} items")
            print(f"  Merged: {dvl['merged_count']} items")
            if dvl["items_only_in_deterministic"]:
                print(f"  Only in deterministic: {dvl['items_only_in_deterministic']}")
            if dvl["items_only_in_llm"]:
                print(f"  Only in LLM: {dvl['items_only_in_llm']}")

        if log.get("validation_results"):
            vr = log["validation_results"]
            print(f"\nValidation:")
            print(f"  Arithmetic: {'✓' if vr['arithmetic_ok'] else '✗'}")
            print(f"  Reconciliation: {'✓' if vr['reconciliation_ok'] else '✗'}")
            if vr.get("reconciliation_error"):
                print(f"    Error: {vr['reconciliation_error']}")
            print(f"  Duplicates: {vr['duplicates_found']}")
            if vr.get("sanity_warnings"):
                print(f"  Warnings: {vr['sanity_warnings']}")

        if log.get("verification_result"):
            ver = log["verification_result"]
            print(f"\nVerification:")
            print(f"  Confidence: {ver['confidence']:.2f}")
            print(f"  Discrepancies: {len(ver['discrepancies'])}")
            if ver.get("verifier_notes"):
                print(f"  Notes: {ver['verifier_notes']}")

        if log.get("corrections_applied"):
            print(f"\nCorrections Applied: {len(log['corrections_applied'])}")
            for corr in log["corrections_applied"]:
                print(f"  - {corr}")

        if log.get("errors"):
            print(f"\nErrors: {len(log['errors'])}")
            for err in log["errors"]:
                print(f"  - {err['error']}")

        print("=" * 70)
