"""
Run full batch processing for all remaining receipts.

Processes all unprocessed AH and Jumbo receipts through the V2 pipeline.
Shows progress and saves results incrementally.
"""

import json
import sqlite3
import sys
from pathlib import Path
from datetime import datetime
from tqdm import tqdm

from v2.config.settings import settings
from v2.ah_pipeline.graph import build_ah_pipeline, run_ah_receipt
from v2.jumbo_pipeline.graph import build_jumbo_pipeline, run_jumbo_receipt
from v2.shared.output_writer import OutputWriter
from v2.shared.database_writer import DatabaseWriter
from v2.shared.cost_report import CostReport


def get_processed_paths() -> set:
    """Get set of already processed receipt paths from database."""
    conn = sqlite3.connect(settings.PROCESSED_DB)
    processed = {row[0] for row in conn.execute("SELECT DISTINCT receipt_path FROM processed_data")}
    conn.close()
    return processed


def get_remaining_receipts(store: str) -> list:
    """Get list of unprocessed receipt paths for a store."""
    processed = get_processed_paths()
    
    if store == "ah":
        folder = Path("raw_receipts/ah")
        files = sorted(folder.glob("*.pdf"))
    else:
        folder = Path("raw_receipts/jumbo")
        files = sorted(folder.glob("*.png"))
    
    remaining = [f for f in files if str(f) not in processed]
    return remaining


def process_ah_batch(pipeline, receipts: list, start_idx: int = 0):
    """Process a batch of AH receipts."""
    results = []
    
    for i, receipt_path in enumerate(tqdm(receipts, desc="AH receipts", unit="receipt"), start=start_idx):
        name = Path(receipt_path).name
        thread_id = f"full_batch_ah_{start_idx + i}"
        
        try:
            result = run_ah_receipt(pipeline, str(receipt_path), thread_id=thread_id)
            
            status = result.get("final_status", "unknown")
            conf = result.get("overall_confidence", 0)
            items = len(result.get("merged_items", []))
            
            results.append({
                "store": "ah",
                "file": str(receipt_path),
                "name": name,
                "status": status,
                "confidence": conf,
                "items": items,
                "thread_id": thread_id,
            })
            
        except Exception as e:
            results.append({
                "store": "ah",
                "file": str(receipt_path),
                "name": name,
                "status": "error",
                "confidence": 0,
                "items": 0,
                "error": str(e),
                "thread_id": thread_id,
            })
    
    return results


def process_jumbo_batch(pipeline, receipts: list, start_idx: int = 0):
    """Process a batch of Jumbo receipts."""
    results = []
    
    for i, receipt_path in enumerate(tqdm(receipts, desc="Jumbo receipts", unit="receipt"), start=start_idx):
        name = Path(receipt_path).name
        thread_id = f"full_batch_jumbo_{start_idx + i}"
        
        try:
            result = run_jumbo_receipt(pipeline, str(receipt_path), thread_id=thread_id)
            
            status = result.get("final_status", "unknown")
            conf = result.get("overall_confidence", 0)
            items = len(result.get("merged_items", []))
            
            results.append({
                "store": "jumbo",
                "file": str(receipt_path),
                "name": name,
                "status": status,
                "confidence": conf,
                "items": items,
                "thread_id": thread_id,
            })
            
        except Exception as e:
            results.append({
                "store": "jumbo",
                "file": str(receipt_path),
                "name": name,
                "status": "error",
                "confidence": 0,
                "items": 0,
                "error": str(e),
                "thread_id": thread_id,
            })
    
    return results


def save_results(results: list, filename: str):
    """Save results to JSON file."""
    path = Path(settings.PROCESSED_DIR) / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    return path


def print_summary(all_results: list):
    """Print summary of all results."""
    print("\n" + "=" * 70)
    print("FULL BATCH SUMMARY")
    print("=" * 70)
    
    ah_results = [r for r in all_results if r["store"] == "ah"]
    jumbo_results = [r for r in all_results if r["store"] == "jumbo"]
    
    for store, results in [("AH", ah_results), ("Jumbo", jumbo_results)]:
        approved = sum(1 for r in results if r["status"] == "approved")
        review = sum(1 for r in results if r["status"] == "review")
        rejected = sum(1 for r in results if r["status"] == "rejected")
        error = sum(1 for r in results if r["status"] == "error")
        total = len(results)
        
        if total > 0:
            avg_conf = sum(r["confidence"] for r in results) / total
            total_items = sum(r["items"] for r in results)
            
            print(f"\n{store}:")
            print(f"  Total:    {total}")
            print(f"  Approved: {approved} ({approved/total*100:.1f}%)")
            print(f"  Review:   {review} ({review/total*100:.1f}%)")
            print(f"  Rejected: {rejected} ({rejected/total*100:.1f}%)")
            print(f"  Error:    {error} ({error/total*100:.1f}%)")
            print(f"  Avg confidence: {avg_conf:.3f}")
            print(f"  Total items: {total_items}")
    
    # Overall
    total = len(all_results)
    approved = sum(1 for r in all_results if r["status"] == "approved")
    review = sum(1 for r in all_results if r["status"] == "review")
    rejected = sum(1 for r in all_results if r["status"] == "rejected")
    error = sum(1 for r in all_results if r["status"] == "error")
    
    print(f"\n{'=' * 70}")
    print(f"OVERALL: {total} receipts")
    print(f"  Approved: {approved} ({approved/total*100:.1f}%)")
    print(f"  Review:   {review} ({review/total*100:.1f}%)")
    print(f"  Rejected: {rejected} ({rejected/total*100:.1f}%)")
    print(f"  Error:    {error} ({error/total*100:.1f}%)")
    print(f"{'=' * 70}")
    
    # Show review/rejected items
    problem_items = [r for r in all_results if r["status"] in ("review", "rejected", "error")]
    if problem_items:
        print(f"\nItems needing attention ({len(problem_items)}):")
        for r in problem_items[:20]:
            print(f"  [{r['status'].upper()}] {r['name'][:50]} (conf: {r['confidence']:.2f}, items: {r['items']})")
        if len(problem_items) > 20:
            print(f"  ... and {len(problem_items) - 20} more")


def main():
    """Main entry point."""
    print("=" * 70)
    print("V2 FULL BATCH PROCESSING")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 70)
    
    # Get remaining receipts
    print("\nChecking remaining receipts...")
    ah_remaining = get_remaining_receipts("ah")
    jumbo_remaining = get_remaining_receipts("jumbo")
    
    print(f"\nAH remaining:    {len(ah_remaining)}")
    print(f"Jumbo remaining: {len(jumbo_remaining)}")
    print(f"Total remaining: {len(ah_remaining) + len(jumbo_remaining)}")
    
    if not ah_remaining and not jumbo_remaining:
        print("\nNo receipts to process!")
        return
    
    # Build pipelines
    print("\nBuilding pipelines...")
    ah_pipeline = build_ah_pipeline()
    jumbo_pipeline = build_jumbo_pipeline()
    print("Pipelines ready.")
    
    all_results = []
    
    # Process AH receipts
    if ah_remaining:
        print(f"\n{'#' * 70}")
        print(f"# PROCESSING {len(ah_remaining)} AH RECEIPTS")
        print(f"{'#' * 70}")
        ah_results = process_ah_batch(ah_pipeline, ah_remaining)
        all_results.extend(ah_results)
        
        # Save intermediate results
        save_results(ah_results, f"batch_results_ah_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        print(f"\nAH batch complete. Results saved.")
    
    # Process Jumbo receipts
    if jumbo_remaining:
        print(f"\n{'#' * 70}")
        print(f"# PROCESSING {len(jumbo_remaining)} JUMBO RECEIPTS")
        print(f"{'#' * 70}")
        jumbo_results = process_jumbo_batch(jumbo_pipeline, jumbo_remaining, start_idx=len(ah_remaining))
        all_results.extend(jumbo_results)
        
        # Save intermediate results
        save_results(jumbo_results, f"batch_results_jumbo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        print(f"\nJumbo batch complete. Results saved.")
    
    # Save all results
    save_results(all_results, f"batch_results_all_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    
    # Print summary
    print_summary(all_results)
    
    # Print database stats
    print("\n")
    OutputWriter().print_stats()
    print()
    DatabaseWriter(settings.PROCESSED_DB).print_stats()
    
    # Print cost report
    print()
    CostReport(settings.TOKEN_USAGE_DB).print_report()
    
    # Save final cost report
    report = CostReport(settings.TOKEN_USAGE_DB)
    report_path = report.save_report()
    
    print(f"\n{'=' * 70}")
    print(f"FULL BATCH COMPLETE")
    print(f"Finished: {datetime.now().isoformat()}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
