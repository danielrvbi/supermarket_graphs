"""
CLI for the v2 taxonomy.

Usage:
    python -m v2.stage3c_taxonomy.cli init                       # Create v2 tables from seed_v2.py (once)
    python -m v2.stage3c_taxonomy.cli overrides                  # Re-apply V2_OVERRIDES as manual labels
    python -m v2.stage3c_taxonomy.cli sync [--dry-run] [--no-llm] [--limit N]
    python -m v2.stage3c_taxonomy.cli show [--counts]            # v2 taxonomy (+ products per label)
    python -m v2.stage3c_taxonomy.cli list [--all] [--source S]  # v2 labels needing review
    python -m v2.stage3c_taxonomy.cli set <item_name> <category> <subcategory>
    python -m v2.stage3c_taxonomy.cli approve <item_name>
    python -m v2.stage3c_taxonomy.cli log                        # Applied taxonomy changes

    python -m v2.stage3c_taxonomy.cli add-category <name>
    python -m v2.stage3c_taxonomy.cli add-subcategory <category> <name>
    python -m v2.stage3c_taxonomy.cli rename <category> <old> <new>
    python -m v2.stage3c_taxonomy.cli rename-category <old> <new>
    python -m v2.stage3c_taxonomy.cli move <category> <subcategory> <to_category>
    python -m v2.stage3c_taxonomy.cli merge <category> <subcategory> <into_category> <into_subcategory>
    python -m v2.stage3c_taxonomy.cli split <category> <subcategory> <new1> [<new2> ...]
    python -m v2.stage3c_taxonomy.cli remove-category <name>

v1 labels (item_labels, classified_data) are never modified. Taxonomy change commands
take --dry-run (applied, counted, rolled back). `set` labels are never overwritten by sync.
"""

import argparse
import json
import sys

from v2.common.settings import settings
from v2.stage3c_taxonomy.seed_v2 import V1_MAP, V2_OVERRIDES, V2_TAXONOMY
from v2.stage3c_taxonomy.store import LABEL_SEP, TaxonomyError, TaxonomyStore
from v2.stage3c_taxonomy.sync import LLMSplitPicker, sync


def cmd_sync(db: TaxonomyStore, dry_run: bool, no_llm: bool, limit):
    picker = None if (dry_run or no_llm) else LLMSplitPicker()
    report = sync(db, picker=picker, dry_run=dry_run, limit=limit)
    prefix = "[dry run] " if dry_run else ""
    print(f"{prefix}mapped 1:1: {report.mapped}   split by LLM: {report.split_llm}   "
          f"pending split: {report.pending_split}")
    print(f"skipped: {report.skipped_manual} manual, {report.skipped_current} already up to date")
    if report.splits:
        print("\nSplits:")
        for label, n in sorted(report.splits.items(), key=lambda x: -x[1]):
            print(f"  {n:4}  {label}")
    if report.unmapped:
        print("\nv1 labels with no entry in v1_map (not synced):")
        for label, n in sorted(report.unmapped.items()):
            print(f"  {n:4}  {label}")
    if not dry_run:
        print(f"\nLLM calls: {report.llm_calls}   rows written: {report.written}")


def cmd_show(db: TaxonomyStore, with_counts: bool):
    counts = db.counts() if with_counts else {}
    for category, subs in db.taxonomy().items():
        if with_counts:
            print(f"{category} ({sum(counts.get((category, s), 0) for s in subs)}):")
            for s in subs:
                print(f"  {counts.get((category, s), 0):5}  {s}")
        else:
            print(f"{category}: {', '.join(subs)}")
    if with_counts:
        pending = db.list_labels(source="pending_split")
        if pending:
            print(f"\nPending split (no v2 subcategory yet): {len(pending)}")


def cmd_list(db: TaxonomyStore, show_all: bool, source):
    labels = db.list_labels(needs_review=None if show_all else True, source=source)
    print(f"{len(labels)} labels\n")
    for l in labels:
        flag = "!" if l["needs_review"] else " "
        label = f"{l['category']}{LABEL_SEP}{l['subcategory']}" if l["subcategory_id"] else "(pending)"
        evidence = json.loads(l["evidence"] or "{}")
        print(f"{flag} {l['store'] or '':5} {l['item_name']:22} {l['producto_es'] or '':38} -> {label:45} "
              f"({l['source']}, from {evidence.get('v1', '?')})")


def cmd_log(db: TaxonomyStore):
    for entry in reversed(db.change_log()):
        print(f"{entry['applied_at'][:19]}  {entry['op']:20} {entry['items_affected']:5} items  {entry['payload']}")


def main():
    parser = argparse.ArgumentParser(description="v2 taxonomy: tables, sync and editing")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Create v2 taxonomy + v1 map from seed_v2.py")
    p = sub.add_parser("sync", help="Sync v1 labels into v2 labels")
    p.add_argument("--dry-run", action="store_true", help="Report only: no writes, no LLM")
    p.add_argument("--no-llm", action="store_true", help="Store splits as pending instead of calling the LLM")
    p.add_argument("--limit", type=int, default=None, help="Only process N products")
    sub.add_parser("show", help="Print the v2 taxonomy").add_argument("--counts", action="store_true")
    p = sub.add_parser("list", help="List v2 labels needing review")
    p.add_argument("--all", action="store_true", help="All labels, not just flagged")
    p.add_argument("--source", default=None, help="map | split_llm | pending_split | manual")
    p = sub.add_parser("set", help="Set a v2 label by hand")
    p.add_argument("item_name")
    p.add_argument("category")
    p.add_argument("subcategory")
    sub.add_parser("approve", help="Keep the v2 label, clear the flag").add_argument("item_name")
    sub.add_parser("log", help="Show applied taxonomy changes")
    sub.add_parser("overrides", help="Apply V2_OVERRIDES from seed_v2.py as manual labels")

    def change(name, help_text, *args, nargs_last=None):
        p = sub.add_parser(name, help=help_text)
        for a in args:
            p.add_argument(a)
        if nargs_last:
            p.add_argument(nargs_last, nargs="+")
        p.add_argument("--dry-run", action="store_true", help="Preview without saving")

    change("add-category", "Add a category", "name")
    change("add-subcategory", "Add a subcategory", "category", "name")
    change("rename", "Rename a subcategory", "category", "old", "new")
    change("rename-category", "Rename a category", "old", "new")
    change("move", "Move a subcategory to another category", "category", "subcategory", "to_category")
    change("merge", "Merge a subcategory into another", "category", "subcategory", "into_category", "into_subcategory")
    change("split", "Add sibling subcategories and flag products for review", "category", "subcategory", nargs_last="into")
    change("remove-category", "Retire an empty category", "name")

    args = parser.parse_args()
    db = TaxonomyStore(settings.PROCESSED_DB)

    if args.command not in ("init",) and not db.is_initialised():
        print("v2 taxonomy not initialised; run: python -m v2.stage3c_taxonomy.cli init")
        sys.exit(1)

    try:
        if args.command == "sync":
            return cmd_sync(db, args.dry_run, args.no_llm, args.limit)
        if args.command == "show":
            return cmd_show(db, args.counts)
        if args.command == "list":
            return cmd_list(db, args.all, args.source)
        if args.command == "log":
            return cmd_log(db)
        if args.command == "overrides":
            applied = db.apply_overrides(V2_OVERRIDES)
            return print(f"Applied {len(applied)}/{len(V2_OVERRIDES)} overrides as manual labels")
        if args.command == "set":
            db.set_manual(args.item_name.upper(), args.category, args.subcategory)
            return print(f"Set {args.item_name.upper()} -> {args.category}{LABEL_SEP}{args.subcategory}")
        if args.command == "approve":
            ok = db.approve(args.item_name.upper())
            return print(f"Approved {args.item_name.upper()}" if ok else f"No v2 label for {args.item_name!r}")

        dry = getattr(args, "dry_run", False)
        if args.command == "init":
            result = db.init_from_seed(V2_TAXONOMY, V1_MAP)
            result["overrides"] = len(db.apply_overrides(V2_OVERRIDES))
        elif args.command == "add-category":
            result = db.add_category(args.name, dry)
        elif args.command == "add-subcategory":
            result = db.add_subcategory(args.category, args.name, dry)
        elif args.command == "rename":
            result = db.rename_subcategory(args.category, args.old, args.new, dry)
        elif args.command == "rename-category":
            result = db.rename_category(args.old, args.new, dry)
        elif args.command == "move":
            result = db.move_subcategory(args.category, args.subcategory, args.to_category, dry)
        elif args.command == "merge":
            result = db.merge_subcategory(args.category, args.subcategory, args.into_category, args.into_subcategory, dry)
        elif args.command == "split":
            result = db.split_subcategory(args.category, args.subcategory, args.into, dry)
        elif args.command == "remove-category":
            result = db.remove_category(args.name, dry)
    except TaxonomyError as e:
        print(f"Error: {e}")
        sys.exit(1)

    prefix = "[dry run] " if result.pop("dry_run") else ""
    print(prefix + json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
