"""
Offline accuracy check against old_data.csv.

Holds out a random sample of labelled products, classifies them using only the
remaining products as neighbours (no writes to item_labels), and compares with
the hand labels.

Usage:
    python -m v2.stage3_classification.eval              # 100 held-out products, no Tavily
    python -m v2.stage3_classification.eval --n 50 --seed 1
    python -m v2.stage3_classification.eval --n 30 --search   # weak matches use Tavily (cached)
"""

import argparse
import random
from collections import Counter

from v2.common.settings import settings
from v2.stage3_classification.matcher import Embedder, Matcher, passes_gate
from v2.stage3_classification.search import ProductSearch
from v2.stage3_classification.seed import load_old_labels
from v2.stage3_classification.store import ClassificationStore


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Evaluate classification on held-out old_data")
    parser.add_argument("--n", type=int, default=100, help="Products to hold out")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--search", action="store_true",
                        help="Use Tavily for weak matches, like the real run (uses search credits)")
    args = parser.parse_args()

    from v2.stage3_classification.classifier import Classifier

    labels = load_old_labels(settings.OLD_DATA_CSV)
    random.Random(args.seed).shuffle(labels)
    test, train = labels[: args.n], labels[args.n:]

    db = ClassificationStore(settings.PROCESSED_DB)
    matcher = Matcher(train, Embedder(db))
    neighbours = matcher.neighbours([t["item_name"] for t in test])
    classifier = Classifier(stage="classify_eval")
    searcher = ProductSearch(db) if args.search else None

    stats = Counter()
    misses = []
    for truth, nbrs in zip(test, neighbours):
        gate = passes_gate(nbrs)
        store = truth["store"] or "ah"
        search = searcher.search(store, truth["item_name"]) if searcher and not gate else None
        result = classifier.classify(truth["item_name"], store, nbrs, gate, search)
        group = "gate" if gate else "no_gate"
        cat_ok = result.category == truth["category"]
        sub_ok = cat_ok and result.subcategory == truth["subcategory"]
        stats.update({
            f"{group}_n": 1,
            f"{group}_cat": cat_ok,
            f"{group}_sub": sub_ok,
            f"{group}_nn_cat": bool(nbrs) and nbrs[0].category == truth["category"],
            f"{group}_review": result.needs_review,
            f"{group}_wrong_unflagged": not cat_ok and not result.needs_review,
        })
        if not sub_ok:
            misses.append((truth, result))

    print("=" * 70)
    print(f"EVAL: {args.n} held-out products, {len(train)} as neighbours "
          f"({'Tavily for weak matches' if searcher else 'no web search'})")
    print("=" * 70)
    for group, title in [("gate", "Confident match (no search needed)"),
                         ("no_gate", "Weak match (would use Tavily)")]:
        n = stats[f"{group}_n"]
        if not n:
            continue
        pct = lambda k: f"{stats[f'{group}_{k}'] / n:.0%}"
        print(f"{title}: {n} items")
        print(f"  LLM category:      {pct('cat')}   (nearest neighbour alone: {pct('nn_cat')})")
        print(f"  LLM subcategory:   {pct('sub')}")
        print(f"  flagged review:    {pct('review')}")
        print(f"  wrong & unflagged: {pct('wrong_unflagged')}")
    total = stats["gate_n"] + stats["no_gate_n"]
    print(f"Overall category: {(stats['gate_cat'] + stats['no_gate_cat']) / total:.0%}, "
          f"subcategory: {(stats['gate_sub'] + stats['no_gate_sub']) / total:.0%}")

    print("\nMisses (truth -> predicted):")
    for truth, r in misses:
        mark = "cat" if r.category != truth["category"] else "sub"
        print(f"  [{mark}] {truth['item_name']:22} {truth['category']} > {truth['subcategory']:20} "
              f"-> {r.category} > {r.subcategory}  ({r.evidence['llm_confidence']}"
              f"{', review' if r.needs_review else ''})")


if __name__ == "__main__":
    main()
