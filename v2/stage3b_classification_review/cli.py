"""
CLI tool for reviewing item labels.

Usage:
    python -m v2.stage3b_classification_review.cli list                 # Items flagged for review
    python -m v2.stage3b_classification_review.cli list --all           # All LLM labels
    python -m v2.stage3b_classification_review.cli show <item_name>
    python -m v2.stage3b_classification_review.cli approve <item_name>  # Keep label, clear flag
    python -m v2.stage3b_classification_review.cli set <item_name> <category> <subcategory> [--producto "..."]
    python -m v2.stage3b_classification_review.cli taxonomy             # Allowed labels
    python -m v2.stage3b_classification_review.cli validate <category> <subcategory>  # Validate a label
    python -m v2.stage3b_classification_review.cli batch <offset> <limit>  # Query batch for audit

`approve` and `set` rebuild classified_data. `set` stores the label with source=manual,
which is never overwritten and is used as a neighbour for future items.

The `validate` and `batch` commands are new in stage 3B and support the audit workflow.
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from v2.common.settings import settings
from v2.stage3_classification.store import ClassificationStore
from v2.stage3_classification.taxonomy import TAXONOMY, is_valid
from v2.stage3b_classification_review.validator import validate_label, suggest_correction


def cmd_list(db: ClassificationStore, show_all: bool):
    """List flagged (or all LLM-made) labels."""
    labels = (
        db.get_labels(sources=["embed_llm", "search_llm"]) if show_all
        else db.get_labels(needs_review=True)
    )
    title = "LLM labels" if show_all else "Needs review"
    print(f"\n{'='*90}")
    print(f"{title} ({len(labels)} items)")
    print(f"{'='*90}\n")
    for l in labels:
        flag = "!" if l["needs_review"] else " "
        print(f"{flag} {l['store'] or '':5} {l['item_name']:22} -> {l['producto_es'] or '':32} "
              f"{l['category']} > {l['subcategory']}  ({l['source']}, {l['confidence']})")


def cmd_show(db: ClassificationStore, item_name: str):
    """Show one label with its evidence (neighbours, search results, LLM reasoning)."""
    label = db.get_label(item_name)
    if not label:
        print(f"No label for {item_name!r}")
        return
    evidence = json.loads(label.pop("evidence") or "{}")
    for key, value in label.items():
        print(f"{key:14} {value}")
    if evidence:
        print("\nEvidence:")
        print(f"  reasoning:  {evidence.get('reasoning')}")
        print(f"  gate:       {evidence.get('gate_passed')}")
        print(f"  search:     {evidence.get('search_query')}")
        print("  neighbours:")
        for n in evidence.get("neighbours", []):
            print(f"    {n['score']:.2f} {n['item_name']:22} {n['category']} > {n['subcategory']}")
    search = db.get_search(label["store"] or "", item_name)
    if search and search["success"]:
        print("\nSearch results:")
        for r in search["results"]:
            print(f"  [{r['title']}] {r['url']}\n    {r['content'][:200]}")


def cmd_approve(db: ClassificationStore, item_name: str):
    """Keep the label, clear the review flag."""
    if not db.set_review_flag(item_name, False):
        print(f"No label for {item_name!r}")
        return
    db.rebuild_classified()
    print(f"Approved {item_name}")


def cmd_set(db: ClassificationStore, item_name: str, category: str, subcategory: str, producto: str):
    """Overwrite a label by hand (source=manual)."""
    if not is_valid(category, subcategory):
        print(f"Invalid label {category!r} > {subcategory!r}.")
        # Suggest a correction
        corrected = suggest_correction(category, subcategory)
        print(f"Did you mean: {corrected}?")
        print("See: python -m v2.stage3b_classification_review.cli taxonomy")
        return
    existing = db.get_label(item_name) or {}
    db.upsert_label(
        item_name=item_name,
        store=existing.get("store"),
        producto_es=producto or existing.get("producto_es"),
        category=category,
        subcategory=subcategory,
        source="manual",
        confidence=1.0,
        needs_review=False,
    )
    db.rebuild_classified()
    print(f"Set {item_name} -> {category} > {subcategory}")


def cmd_taxonomy():
    """Print the allowed labels."""
    for category, subs in TAXONOMY.items():
        print(f"{category}: {', '.join(subs)}")


def cmd_validate(category: str, subcategory: str):
    """Validate a label against the frozen taxonomy."""
    is_valid_result, msg = validate_label(category, subcategory)
    print(f"{category} > {subcategory}")
    print(f"Valid: {is_valid_result}")
    print(f"Message: {msg}")
    if not is_valid_result:
        corrected = suggest_correction(category, subcategory)
        print(f"Suggested correction: {corrected}")
    return 0 if is_valid_result else 1


BATCH_QUERY = """
WITH ordered_items AS (
    SELECT item_name,
           ROW_NUMBER() OVER (ORDER BY item_name) - 1 AS idx
    FROM (SELECT item_name FROM normalized_data UNION SELECT item_name FROM item_labels)
),
batch AS (SELECT item_name FROM ordered_items WHERE idx >= ? AND idx < ?),
purchase_stats AS (
    SELECT n.item_name, COUNT(*) AS purchase_count, COUNT(DISTINCT n.store) AS store_count,
           GROUP_CONCAT(DISTINCT n.store) AS stores,
           MIN(n.price_per_measurement_unit) AS min_price,
           MAX(n.price_per_measurement_unit) AS max_price,
           ROUND(AVG(n.price_per_measurement_unit), 2) AS avg_price,
           ROUND(SUM(n.line_total_paid_amount), 2) AS total_spend,
           MIN(n.measurement_quantity) AS min_qty, MAX(n.measurement_quantity) AS max_qty
    FROM normalized_data n GROUP BY n.item_name
)
SELECT b.item_name, l.producto_es, l.category, l.subcategory, l.source, l.confidence,
       COALESCE(p.purchase_count, 0) AS purchases, p.stores,
       p.min_price, p.max_price, p.avg_price, p.total_spend, p.min_qty, p.max_qty,
       (SELECT GROUP_CONCAT(nb.item_name || ' [' || nb.category || ' > ' || nb.subcategory || ']', ' | ')
        FROM json_each(json_extract(l.evidence, '$.neighbours')) je
        JOIN item_labels nb ON nb.item_name = json_extract(je.value, '$.item_name') LIMIT 5) AS neighbours,
       (SELECT GROUP_CONCAT(n2.date_of_purchase || ' ' || n2.store || ' EUR ' || n2.line_total_paid_amount ||
             CASE WHEN n2.measurement_type = 'weight_in_grams'
                  THEN ' (' || ROUND(n2.measurement_quantity * 1000) || 'g)'
                  ELSE ' (x' || n2.measurement_quantity || ')' END, ' | ')
        FROM normalized_data n2 WHERE n2.item_name = b.item_name
        ORDER BY n2.date_of_purchase DESC LIMIT 3) AS recent_purchases
FROM batch b
LEFT JOIN item_labels l ON l.item_name = b.item_name
LEFT JOIN purchase_stats p ON p.item_name = b.item_name
ORDER BY b.item_name;
"""


def cmd_batch(offset: int, limit: int):
    """Query a batch of items for audit review."""
    db_path = Path(settings.PROCESSED_DB).resolve()
    conn = sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA query_only=ON')
    
    try:
        rows = conn.execute(BATCH_QUERY, (offset, offset + limit)).fetchall()
        
        print(f"Batch: offset={offset}, limit={limit}, items={len(rows)}")
        print(f"{'Item':<22} | {'Spanish Name':<28} | {'Category':<22} | {'Src':<10} | {'Conf':<5} | {'#':<3} | {'Stores':<10} | {'Price':<15} | {'Neighbours'}")
        print("-" * 180)
        for r in rows:
            price = f"EUR {r['min_price']}-{r['max_price']}" if r['min_price'] else "-"
            neigh = (r['neighbours'] or "-")[:60]
            cat = f"{r['category'] or '-'} > {r['subcategory'] or '-'}"
            print(f"{r['item_name'][:22]:<22} | {(r['producto_es'] or '-')[:28]:<28} | {cat[:22]:<22} | {r['source'] or '-':<10} | {r['confidence'] or 0:<5} | {r['purchases']:<3} | {(r['stores'] or '-'):<10} | {price:<15} | {neigh}")
            if r['recent_purchases']:
                print(f"{'':22} | Recent: {r['recent_purchases'][:100]}")
    finally:
        conn.close()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Review and audit stage 3 item labels")
    sub = parser.add_subparsers(dest="command", required=True)

    # Original review commands
    p = sub.add_parser("list", help="List items flagged for review")
    p.add_argument("--all", action="store_true", help="Show all LLM labels, not just flagged")
    sub.add_parser("show", help="Show one label with evidence").add_argument("item_name")
    sub.add_parser("approve", help="Keep label, clear review flag").add_argument("item_name")
    p = sub.add_parser("set", help="Set a manual label")
    p.add_argument("item_name")
    p.add_argument("category")
    p.add_argument("subcategory")
    p.add_argument("--producto", default=None, help="Spanish product name")
    sub.add_parser("taxonomy", help="Print allowed labels")
    
    # New stage 3B commands
    p = sub.add_parser("validate", help="Validate a label against frozen taxonomy")
    p.add_argument("category")
    p.add_argument("subcategory")
    
    p = sub.add_parser("batch", help="Query a batch of items for audit review")
    p.add_argument("offset", type=int, help="Starting index (0-based)")
    p.add_argument("limit", type=int, help="Number of items to return")
    
    args = parser.parse_args()
    
    if args.command == "batch":
        cmd_batch(args.offset, args.limit)
        return
    
    if args.command == "validate":
        sys.exit(cmd_validate(args.category, args.subcategory))
    
    if args.command == "taxonomy":
        cmd_taxonomy()
        return
    
    db = ClassificationStore(settings.PROCESSED_DB)

    if args.command == "list":
        cmd_list(db, args.all)
    elif args.command == "show":
        cmd_show(db, args.item_name.upper())
    elif args.command == "approve":
        cmd_approve(db, args.item_name.upper())
    elif args.command == "set":
        cmd_set(db, args.item_name.upper(), args.category, args.subcategory, args.producto)


if __name__ == "__main__":
    main()
