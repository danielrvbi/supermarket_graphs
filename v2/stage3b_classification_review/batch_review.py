"""
Batch review queries for classification audit.

Provides SQL queries and utilities for reviewing items in batches of 50,
designed for use by Explore sub-agents during classification audits.

Usage:
    python -m v2.stage3b_classification_review.batch_review 0 50
    python -m v2.stage3b_classification_review.batch_review --count
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional

from v2.common.settings import settings


# SQL query for batch review - returns one row per unique item with:
# - Current label (Spanish name, category, subcategory, source, confidence)
# - Purchase statistics (count, stores, price range, total spend, quantity range)
# - Top 5 neighbours (similar products with their categories)
# - Recent 3 purchases (date, store, price, quantity)
BATCH_QUERY = """
WITH ordered_items AS (
    SELECT item_name,
           ROW_NUMBER() OVER (ORDER BY item_name) - 1 AS idx
    FROM (SELECT item_name FROM normalized_data UNION SELECT item_name FROM item_labels)
),
batch AS (SELECT item_name FROM ordered_items WHERE idx >= :offset AND idx < :offset + :limit),
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


def get_total_items(db_path: Optional[str] = None) -> int:
    """Get total number of unique items to review."""
    path = Path(db_path or settings.PROCESSED_DB).resolve()
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    try:
        conn.execute('PRAGMA query_only=ON')
        count = conn.execute("""
            SELECT COUNT(*) FROM (
                SELECT item_name FROM normalized_data
                UNION
                SELECT item_name FROM item_labels
            )
        """).fetchone()[0]
        return count
    finally:
        conn.close()


def query_batch(offset: int, limit: int, db_path: Optional[str] = None) -> List[Dict]:
    """
    Query a batch of items for review.
    
    Args:
        offset: Starting index (0-based)
        limit: Number of items to return
        db_path: Optional database path (defaults to settings.PROCESSED_DB)
    
    Returns:
        List of dictionaries with item data
    """
    path = Path(db_path or settings.PROCESSED_DB).resolve()
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA query_only=ON')
        rows = conn.execute(BATCH_QUERY, {'offset': offset, 'limit': limit}).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def format_batch_table(rows: List[Dict]) -> str:
    """Format batch results as a text table."""
    lines = []
    lines.append(f"{'Item':<22} | {'Spanish Name':<28} | {'Category':<22} | {'Src':<10} | {'Conf':<5} | {'#':<3} | {'Stores':<10} | {'Price':<15} | {'Neighbours'}")
    lines.append("-" * 180)
    
    for r in rows:
        price = f"EUR {r['min_price']}-{r['max_price']}" if r['min_price'] else "-"
        neigh = (r['neighbours'] or "-")[:60]
        cat = f"{r['category'] or '-'} > {r['subcategory'] or '-'}"
        lines.append(
            f"{r['item_name'][:22]:<22} | {(r['producto_es'] or '-')[:28]:<28} | "
            f"{cat[:22]:<22} | {r['source'] or '-':<10} | {r['confidence'] or 0:<5} | "
            f"{r['purchases']:<3} | {(r['stores'] or '-'):<10} | {price:<15} | {neigh}"
        )
        if r['recent_purchases']:
            lines.append(f"{'':22} | Recent: {r['recent_purchases'][:100]}")
    
    return "\n".join(lines)


def format_batch_json(rows: List[Dict]) -> str:
    """Format batch results as JSONL (one JSON object per line)."""
    return "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)


def get_batch_info(offset: int, limit: int, db_path: Optional[str] = None) -> Dict:
    """Get information about a batch without querying all data."""
    total = get_total_items(db_path)
    batch_num = offset // limit + 1
    total_batches = (total + limit - 1) // limit
    
    return {
        'offset': offset,
        'limit': limit,
        'batch_number': batch_num,
        'total_batches': total_batches,
        'total_items': total,
        'is_last_batch': batch_num == total_batches,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Query batches of items for classification review"
    )
    parser.add_argument("offset", type=int, nargs="?", default=0, help="Starting index (0-based)")
    parser.add_argument("limit", type=int, nargs="?", default=50, help="Number of items")
    parser.add_argument("--count", action="store_true", help="Show total item count only")
    parser.add_argument("--json", action="store_true", help="Output as JSONL instead of table")
    parser.add_argument("--info", action="store_true", help="Show batch info only")
    
    args = parser.parse_args()
    
    if args.count:
        total = get_total_items()
        print(f"Total unique items: {total}")
        print(f"Batches of 50: {(total + 49) // 50}")
        return 0
    
    if args.info:
        info = get_batch_info(args.offset, args.limit)
        print(f"Batch {info['batch_number']} of {info['total_batches']}")
        print(f"Offset: {info['offset']}, Limit: {info['limit']}")
        print(f"Total items: {info['total_items']}")
        print(f"Is last batch: {info['is_last_batch']}")
        return 0
    
    rows = query_batch(args.offset, args.limit)
    
    if args.json:
        print(format_batch_json(rows))
    else:
        info = get_batch_info(args.offset, args.limit)
        print(f"Batch {info['batch_number']} of {info['total_batches']} (offset={args.offset}, limit={args.limit}, items={len(rows)})\n")
        print(format_batch_table(rows))
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
