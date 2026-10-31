"""
Seed item_labels from the hand-labelled old_data.csv.

- Product names are stripped/uppercased to match normalized_data.item_name
- Labels are mapped onto the frozen taxonomy via SUBCATEGORY_ALIASES
- Products labelled differently over time keep their most recent label
- Never overwrites manual labels (only replaces earlier old_data seeds)
"""

from typing import Dict, List

import pandas as pd

from v2.common.non_products import is_non_product_item
from v2.stage3_classification.store import ClassificationStore
from v2.stage3_classification.taxonomy import canonicalize


STORE_BY_MARKET = {"Albert Heijn": "ah", "Jumbo": "jumbo"}


def load_old_labels(csv_path: str) -> List[Dict]:
    """
    Read old_data.csv and return one canonical label per product name.

    Raises:
        ValueError: if a (category, subcategory) pair has no alias in the taxonomy.
    """
    df = pd.read_csv(csv_path)
    df.columns = [c.strip() for c in df.columns]
    df = df.dropna(subset=["Product", "Category", "Subcategory"])

    df = (
        df.assign(
            item_name=df["Product"].str.strip().str.upper(),
            date=pd.to_datetime(df["Date"], errors="coerce"),
        )
        .sort_values("date")
        .drop_duplicates(subset=["item_name"], keep="last")
    )

    labels = []
    unmapped = set()
    for row in df.itertuples():
        # Skip non-product receipt lines (deposits, savings stamps, cashback,
        # discounts, payment metadata) — they must never become product labels.
        if is_non_product_item(row.item_name):
            continue
        mapped = canonicalize(row.Category, row.Subcategory)
        if mapped is None:
            unmapped.add((row.Category, row.Subcategory))
            continue
        category, subcategory = mapped
        labels.append({
            "item_name": row.item_name,
            "store": STORE_BY_MARKET.get(str(row.MRKT).strip()),
            "producto_es": str(row.Producto).strip() if pd.notna(row.Producto) else None,
            "category": category,
            "subcategory": subcategory,
        })

    if unmapped:
        raise ValueError(f"Add these old labels to SUBCATEGORY_ALIASES: {sorted(unmapped)}")

    return labels


def seed_labels(db: ClassificationStore, csv_path: str) -> int:
    """Upsert old_data labels into item_labels. Returns number of products seeded."""
    labels = load_old_labels(csv_path)
    for label in labels:
        db.upsert_label(
            **label,
            source="old_data",
            confidence=1.0,
            overwrite_sources=["old_data"],
        )
    return len(labels)
