"""
Classification script: reads normalized_data, writes item_labels + classified_data.

Usage:
    python -m v2.stage3_classification.run                 # Classify all new items
    python -m v2.stage3_classification.run --store ah      # AH only
    python -m v2.stage3_classification.run --limit 20      # First 20 new items (for testing)
    python -m v2.stage3_classification.run --dry-run       # Show tiers, no Tavily/LLM calls, no writes
    python -m v2.stage3_classification.run --no-search     # Never call Tavily
    python -m v2.stage3_classification.run --rebuild       # Re-classify all LLM-labelled items

Per unique item name:
    Tier 0  exact match in item_labels (old_data.csv seeds + every earlier result)
    Tier 1  embedding neighbours among trusted labels; gate = top1 >= 0.80 and top-3 agree
    Tier 2  gate failed -> Tavily search on the store's website (cached per item)
    Tier 3  Mistral picks producto_es + 'Category > Subcategory' from the frozen taxonomy
Results are written to item_labels, so the next run treats them as Tier 0.
"""

import argparse
import sys
from collections import Counter
from datetime import datetime

from tqdm import tqdm

from v2.common.cost_report import CostReport
from v2.common.non_products import is_non_product_item
from v2.common.settings import settings
from v2.stage3_classification.matcher import Embedder, Matcher, passes_gate
from v2.stage3_classification.search import ProductSearch
from v2.stage3_classification.seed import load_old_labels, seed_labels
from v2.stage3_classification.store import ClassificationStore, TRUSTED_SOURCES


LLM_SOURCES = ("embed_llm", "search_llm")


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Classify normalized items (old_data match -> embeddings -> Tavily -> LLM)"
    )
    parser.add_argument("--store", choices=["ah", "jumbo", "all"], default="all",
                        help="Which store to classify (default: all)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Classify at most N new items (for testing)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would happen; no Tavily/LLM calls, no label writes")
    parser.add_argument("--no-search", action="store_true",
                        help="Never call Tavily (low-match items get flagged for review)")
    parser.add_argument("--retry-failed-search", action="store_true",
                        help="Re-query items whose cached search failed or was empty")
    parser.add_argument("--rebuild", action="store_true",
                        help="Delete LLM labels (embed_llm/search_llm) and classify again; "
                             "old_data and manual labels are kept, caches are reused")
    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()

    print("=" * 60)
    print("V2 CLASSIFICATION SCRIPT")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 60)
    print(f"Store:   {args.store}")
    print(f"Mode:    {'DRY RUN' if args.dry_run else 'WRITE'}")
    print(f"Search:  {'off' if args.no_search else 'Tavily (cached)'}")
    if args.limit:
        print(f"Limit:   {args.limit} items")
    print()

    db = ClassificationStore(settings.PROCESSED_DB)
    print(f"Database: {settings.PROCESSED_DB}")

    # Seed / refresh old_data labels (idempotent, never touches manual labels).
    # Dry run keeps them in memory instead of writing.
    old_labels = load_old_labels(settings.OLD_DATA_CSV)
    if not args.dry_run:
        seed_labels(db, settings.OLD_DATA_CSV)
    print(f"Seeded {len(old_labels)} products from {settings.OLD_DATA_CSV}")

    if args.rebuild and not args.dry_run:
        removed = db.delete_labels(LLM_SOURCES)
        print(f"Rebuild: removed {removed} LLM labels")

    # Tier 0: exact match
    store_filter = args.store if args.store in ("ah", "jumbo") else None
    items = db.get_unique_items(store=store_filter)
    # Never classify non-product receipt lines (deposits, savings stamps,
    # cashback, discounts, payment metadata).
    items = [i for i in items if not is_non_product_item(i["item_name"])]
    known = db.labelled_names() | {l["item_name"] for l in old_labels}
    new_items = [i for i in items if i["item_name"] not in known]

    rows_total = sum(i["n_rows"] for i in items)
    rows_known = sum(i["n_rows"] for i in items if i["item_name"] in known)
    print(f"Unique items: {len(items)} ({rows_total} rows)")
    print(f"Tier 0 exact: {len(items) - len(new_items)} items ({rows_known} rows)")
    print(f"New items:    {len(new_items)}")

    if args.limit:
        new_items = new_items[: args.limit]

    tiers = Counter()
    review_items = []

    if new_items:
        # Tier 1: neighbours among trusted labels
        print("\nEmbedding item names...")
        embedder = Embedder(db)
        trusted = {l["item_name"]: l for l in old_labels}
        trusted.update({l["item_name"]: l for l in db.get_labels(sources=TRUSTED_SOURCES)})
        matcher = Matcher(list(trusted.values()), embedder)
        all_neighbours = matcher.neighbours([i["item_name"] for i in new_items])
        gates = [passes_gate(n) for n in all_neighbours]
        print(f"Embedding API calls: {embedder.api_calls} (rest cached)")

        n_gate = sum(gates)
        print(f"Tier 1 confident match: {n_gate}")
        print(f"Tier 2 needs search:    {len(new_items) - n_gate}")

        if args.dry_run:
            pending = sum(1 for i, g in zip(new_items, gates)
                          if not g and not db.get_search(i["store"], i["item_name"]))
            print(f"\n[DRY RUN] Would call Tavily for {0 if args.no_search else pending} items "
                  f"and the LLM for {len(new_items)} items.")
            for item, neighbours, gate in list(zip(new_items, all_neighbours, gates))[:15]:
                top = neighbours[0] if neighbours else None
                hint = f"{top.item_name} [{top.category} > {top.subcategory}] {top.score:.2f}" if top else "-"
                print(f"  {'GATE  ' if gate else 'SEARCH'} {item['store']:5} {item['item_name']:22} ~ {hint}")
            return

        from v2.stage3_classification.classifier import Classifier

        searcher = ProductSearch(db)
        classifier = Classifier()
        failures = []

        iterator = tqdm(list(zip(new_items, all_neighbours, gates)), desc="Classifying",
                        unit="item", disable=not sys.stdout.isatty())
        for item, neighbours, gate in iterator:
            store, name = item["store"], item["item_name"]
            try:
                search = None
                if not gate and not args.no_search:
                    search = searcher.search(store, name, retry_failed=args.retry_failed_search)

                result = classifier.classify(name, store, neighbours, gate, search)
            except Exception as e:
                failures.append((store, name, str(e)[:200]))
                continue

            db.upsert_label(
                item_name=result.item_name,
                store=result.store,
                producto_es=result.producto_es,
                category=result.category,
                subcategory=result.subcategory,
                source=result.source,
                confidence=result.confidence,
                needs_review=result.needs_review,
                evidence=result.evidence,
            )
            tiers[result.source] += 1
            if result.needs_review:
                review_items.append(result)

        print()
        print(f"Tavily: {searcher.api_calls} API calls, {searcher.cache_hits} cache hits")
        print(f"LLM:    {classifier.calls} calls")
        if failures:
            print(f"Failed: {len(failures)} items (rerun to retry)")
            for store, name, err in failures[:10]:
                print(f"  {store:5} {name}: {err}")

    if args.dry_run:
        print("\n[DRY RUN] No changes were written to the database.")
        return

    rows = db.rebuild_classified()
    print(f"\nRebuilt classified_data: {rows} rows")

    print_summary(tiers, review_items)
    db.print_classification_stats()

    for stage in CostReport(settings.TOKEN_USAGE_DB).by_stage():
        if stage["stage"] == "classify":
            print(f"Classification LLM cost (all runs): ${stage['cost_usd']:.4f} over {stage['calls']} calls")

    print()
    print(f"Finished: {datetime.now().isoformat()}")


def print_summary(tiers: Counter, review_items):
    """Print this run's results."""
    print("\n" + "=" * 60)
    print("CLASSIFICATION SUMMARY")
    print("=" * 60)
    print(f"Labelled via embeddings + LLM: {tiers.get('embed_llm', 0)}")
    print(f"Labelled via search + LLM:     {tiers.get('search_llm', 0)}")
    print(f"Flagged for review:            {len(review_items)}")
    for r in review_items[:20]:
        print(f"  {r.store:5} {r.item_name:22} -> {r.producto_es} | {r.category} > {r.subcategory}")
    if len(review_items) > 20:
        print(f"  ... {len(review_items) - 20} more (python -m v2.stage3_classification.review.cli list)")
    print("=" * 60)


if __name__ == "__main__":
    main()
