"""
CLI for stage 3D ingredients.

Usage:
    python -m v2.stage3d_ingredients.cli init                     # Apply OVERRIDES from seed_ingredients.py
    python -m v2.stage3d_ingredients.cli assign --dry-run --no-llm [--show-prompt]   # Batches + cost estimate, no API
    python -m v2.stage3d_ingredients.cli assign --subcategory "Verduras > Lechuga y Ensaladas" [--dry-run]
    python -m v2.stage3d_ingredients.cli assign --category Verduras [--dry-run]
    python -m v2.stage3d_ingredients.cli assign --max-subcategories 5 [--dry-run]
    python -m v2.stage3d_ingredients.cli status                   # Progress per subcategory + tokens spent
    python -m v2.stage3d_ingredients.cli show [--subcategory "C > S"] [--shared]
    python -m v2.stage3d_ingredients.cli list [--all]             # Products needing review
    python -m v2.stage3d_ingredients.cli set <item_name> <ingredient> [--non-food]
    python -m v2.stage3d_ingredients.cli approve (<item_name> | --subcategory "C > S" | --ingredient <name>)
    python -m v2.stage3d_ingredients.cli rename <old> <new> [--dry-run]
    python -m v2.stage3d_ingredients.cli merge <from> <into> [--dry-run]
    python -m v2.stage3d_ingredients.cli log

A live assign (LLM calls) needs one of --subcategory / --category / --max-subcategories /
--all. --dry-run calls the LLM but writes nothing; add --no-llm to skip the LLM too.
item_labels and the v2 taxonomy are never modified. `set` links are never overwritten.
"""

import argparse
import json
import sqlite3
import sys
from collections import defaultdict

from v2.common.settings import settings
from v2.stage3d_ingredients.assign import (
    STAGE, AssignReport, LLMIngredientNamer, assign, estimate_cost, label_of, pending_work,
)
from v2.stage3d_ingredients.seed_ingredients import OVERRIDES
from v2.stage3d_ingredients.store import IngredientError, IngredientStore


def _money(value) -> str:
    return "n/a" if value is None else f"${value:.4f}"


def print_report(report: AssignReport, show_prompt: bool, preview: bool):
    prefix = "[dry run] " if report.dry_run else ""
    for r in report.results:
        print(f"\n== {r.label}  ({r.products} products, {r.vocabulary} existing ingredients, "
              f"~{r.est_input_tokens} in / ~{r.est_output_tokens} out tokens)")
        if show_prompt:
            for prompt in r.prompts:
                print("-" * 60 + "\n" + prompt + "\n" + "-" * 60)
        for g in sorted(r.groups, key=lambda g: g["ingredient"]):
            marks = ("NEW " if g["new"] else "    ") + ("" if g["is_food"] else "[non-food] ")
            conf = "" if g["confidence"] == "high" else f" ({g['confidence']})"
            print(f"  {marks}{g['ingredient']}{conf}")
            for p in g["products"]:
                print(f"        [{p['store']:5}] {p['item_name']:24} {p['producto_es'] or ''}")
        if r.pending:
            print(f"  pending: {', '.join(r.pending)}")
        for e in r.errors:
            print(f"  ! {e}")

    est_cost = estimate_cost(report.est_input_tokens, report.est_output_tokens, report.model)
    print(f"\n{prefix}subcategories: {len(report.results)}  "
          f"products: {sum(r.products for r in report.results)}  "
          f"(not selected: {report.remaining_subcategories} subcategories with work)")
    print(f"skipped: {report.skipped_manual} manual, {report.skipped_current} up to date, "
          f"{report.no_subcategory} without a v2 subcategory")
    print(f"estimate ({report.model}): ~{report.est_input_tokens} input + ~{report.est_output_tokens} output tokens "
          f"= {_money(est_cost)}")
    if not preview:
        print(f"assigned: {report.assigned}  new ingredients: {report.new_ingredients}  "
              f"flagged: {report.flagged}  pending: {report.pending}  LLM calls: {report.llm_calls}"
              + ("" if report.dry_run else f"  rows written: {report.written}"))


def cmd_assign(db: IngredientStore, args):
    preview = args.no_llm
    if preview and not args.dry_run:
        print("--no-llm only previews: add --dry-run")
        sys.exit(1)
    selected = args.subcategory or args.category or args.max_subcategories is not None or args.all
    if not preview and not selected:
        print("A run with LLM calls needs --subcategory, --category, --max-subcategories N or --all")
        sys.exit(1)
    model = args.model or settings.INGREDIENT_MODEL
    namer = None if preview else LLMIngredientNamer(model=model)
    report = assign(db, namer=namer, subcategory=args.subcategory, category=args.category,
                    max_subcategories=args.max_subcategories, dry_run=args.dry_run, model=model,
                    keep_prompts=args.show_prompt)
    if not report.results:
        print("Nothing to assign for this selection.")
    print_report(report, args.show_prompt, preview)


def cmd_status(db: IngredientStore):
    conn = db.connect()
    try:
        work, _ = pending_work(db, conn)
        products = db.products(conn)
        links = db.get_links(conn)
    finally:
        conn.close()
    stats = defaultdict(lambda: {"products": 0, "llm": 0, "manual": 0, "pending": 0, "flagged": 0})
    for p in products:
        if p["subcategory_id"] is None:
            continue
        s = stats[label_of(p)]
        s["products"] += 1
        link = links.get(p["item_name"])
        if link:
            s[link["source"]] += 1
            s["flagged"] += link["needs_review"]
    print(f"{'subcategory':52} {'prod':>5} {'llm':>5} {'man':>5} {'pend':>5} {'flag':>5} {'todo':>5}")
    for label, s in stats.items():
        todo = len(work.get(label, []))
        print(f"{label[:52]:52} {s['products']:5} {s['llm']:5} {s['manual']:5} {s['pending']:5} "
              f"{s['flagged']:5} {todo:5}")
    total = {k: sum(s[k] for s in stats.values()) for k in ("products", "llm", "manual", "pending", "flagged")}
    print(f"{'TOTAL':52} {total['products']:5} {total['llm']:5} {total['manual']:5} {total['pending']:5} "
          f"{total['flagged']:5} {sum(len(v) for v in work.values()):5}")
    print(f"subcategories with work left: {len(work)}")

    try:
        usage = sqlite3.connect(settings.TOKEN_USAGE_DB)
        rows = usage.execute(
            "SELECT model, COUNT(*), SUM(input_tokens), SUM(output_tokens), SUM(total_cost_usd) "
            "FROM token_usage WHERE stage=? GROUP BY model", (STAGE,)
        ).fetchall()
        usage.close()
    except sqlite3.Error:
        rows = []
    for model, calls, tin, tout, cost in rows:
        print(f"spent ({model}): {calls} calls, {tin} input + {tout} output tokens = {_money(cost)}")
    if not rows:
        print("spent: no LLM calls recorded yet")


def cmd_show(db: IngredientStore, subcategory, shared: bool):
    ingredients = db.ingredient_summary(subcategory, shared)
    for ing in ingredients:
        stores = sorted({p["store"] or "?" for p in ing["products"]})
        tag = "" if ing["is_food"] else " [non-food]"
        print(f"{ing['name']}{tag}  ({len(ing['products'])} products: {', '.join(stores)})")
        for p in ing["products"]:
            flag = "!" if p["needs_review"] else " "
            print(f"  {flag} [{p['store'] or '':5}] {p['item_name']:24} {p['producto_es'] or ''}")
    print(f"\n{len(ingredients)} ingredients")


def cmd_list(db: IngredientStore, show_all: bool):
    links = db.list_links(needs_review=None if show_all else True)
    print(f"{len(links)} products\n")
    for l in links:
        flag = "!" if l["needs_review"] else " "
        reasons = ",".join(json.loads(l["evidence"] or "{}").get("review_reasons", []))
        print(f"{flag} {l['store'] or '':5} {l['item_name']:24} {l['producto_es'] or '':38} -> "
              f"{l['ingredient'] or '(pending)':28} ({l['source']}{'; ' + reasons if reasons else ''})")


def cmd_log(db: IngredientStore):
    for entry in reversed(db.change_log()):
        print(f"{entry['applied_at'][:19]}  {entry['op']:10} {entry['items_affected']:5} items  {entry['payload']}")


def main():
    parser = argparse.ArgumentParser(description="Stage 3D: product -> ingredient")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Apply OVERRIDES from seed_ingredients.py as manual links")
    sub.add_parser("overrides", help="Same as init")
    p = sub.add_parser("assign", help="Assign ingredients, one subcategory per LLM call")
    p.add_argument("--subcategory", help='"Category > Subcategory"')
    p.add_argument("--category")
    p.add_argument("--max-subcategories", type=int, help="Next N subcategories with work")
    p.add_argument("--all", action="store_true", help="Every subcategory with work")
    p.add_argument("--dry-run", action="store_true", help="Write nothing")
    p.add_argument("--no-llm", action="store_true", help="With --dry-run: no LLM, show batches and estimate")
    p.add_argument("--show-prompt", action="store_true", help="Print the prompt of each call")
    p.add_argument("--model", help=f"Mistral model (default {settings.INGREDIENT_MODEL})")
    sub.add_parser("status", help="Progress per subcategory and tokens spent")
    p = sub.add_parser("show", help="Ingredients and their products")
    p.add_argument("--subcategory")
    p.add_argument("--shared", action="store_true", help="Only ingredients with products from both stores")
    sub.add_parser("list", help="Products needing review").add_argument("--all", action="store_true")
    p = sub.add_parser("set", help="Link a product to an ingredient by hand")
    p.add_argument("item_name")
    p.add_argument("ingredient")
    p.add_argument("--non-food", action="store_true")
    p = sub.add_parser("approve", help="Clear review flags")
    p.add_argument("item_name", nargs="?")
    p.add_argument("--subcategory")
    p.add_argument("--ingredient")
    p.add_argument("--dry-run", action="store_true")
    for name, help_text, a, b in (("rename", "Rename an ingredient", "old", "new"),
                                  ("merge", "Merge an ingredient into another", "source", "into")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument(a)
        p.add_argument(b)
        p.add_argument("--dry-run", action="store_true", help="Preview without saving")
    sub.add_parser("log", help="Show applied manual changes")

    args = parser.parse_args()
    db = IngredientStore(settings.PROCESSED_DB)

    try:
        if args.command in ("init", "overrides"):
            applied = db.apply_overrides(OVERRIDES)
            return print(f"Tables ready. Applied {len(applied)}/{len(OVERRIDES)} overrides as manual links")
        if args.command == "assign":
            return cmd_assign(db, args)
        if args.command == "status":
            return cmd_status(db)
        if args.command == "show":
            return cmd_show(db, args.subcategory, args.shared)
        if args.command == "list":
            return cmd_list(db, args.all)
        if args.command == "log":
            return cmd_log(db)
        if args.command == "set":
            result = db.set_manual(args.item_name.upper(), args.ingredient,
                                   is_food=False if args.non_food else None)
        elif args.command == "approve":
            result = db.approve(args.item_name.upper() if args.item_name else None,
                                args.subcategory, args.ingredient, args.dry_run)
        elif args.command == "rename":
            result = db.rename(args.old, args.new, args.dry_run)
        elif args.command == "merge":
            result = db.merge(args.source, args.into, args.dry_run)
    except IngredientError as e:
        print(f"Error: {e}")
        sys.exit(1)

    prefix = "[dry run] " if result.pop("dry_run") else ""
    print(prefix + json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
