"""
CLI tool for reviewing item labels.

Usage:
    python -m v2.stage3_classification.review.cli list                 # Items flagged for review
    python -m v2.stage3_classification.review.cli list --all           # All LLM labels
    python -m v2.stage3_classification.review.cli show <item_name>
    python -m v2.stage3_classification.review.cli approve <item_name>  # Keep label, clear flag
    python -m v2.stage3_classification.review.cli set <item_name> <category> <subcategory> [--producto "..."]
    python -m v2.stage3_classification.review.cli taxonomy             # Allowed labels

`approve` and `set` rebuild classified_data. `set` stores the label with source=manual,
which is never overwritten and is used as a neighbour for future items.
"""

import argparse
import json

from v2.common.settings import settings
from v2.stage3_classification.store import ClassificationStore
from v2.stage3_classification.taxonomy import TAXONOMY, is_valid


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
        print(f"Invalid label {category!r} > {subcategory!r}. See: review.cli taxonomy")
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


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Review stage 3 item labels")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list")
    p.add_argument("--all", action="store_true", help="Show all LLM labels, not just flagged")
    sub.add_parser("show").add_argument("item_name")
    sub.add_parser("approve").add_argument("item_name")
    p = sub.add_parser("set")
    p.add_argument("item_name")
    p.add_argument("category")
    p.add_argument("subcategory")
    p.add_argument("--producto", default=None, help="Spanish product name")
    sub.add_parser("taxonomy")

    args = parser.parse_args()
    db = ClassificationStore(settings.PROCESSED_DB)

    if args.command == "list":
        cmd_list(db, args.all)
    elif args.command == "show":
        cmd_show(db, args.item_name.upper())
    elif args.command == "approve":
        cmd_approve(db, args.item_name.upper())
    elif args.command == "set":
        cmd_set(db, args.item_name.upper(), args.category, args.subcategory, args.producto)
    elif args.command == "taxonomy":
        cmd_taxonomy()


if __name__ == "__main__":
    main()
