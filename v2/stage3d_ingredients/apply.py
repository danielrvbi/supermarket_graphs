"""
Write a checked proposal file (proposals/*.jsonl) to the db, then move it to
proposals/<category>/applied/<subcategory>.<timestamp>.jsonl (earlier applies are kept).

Per line:
- ingredient null              -> skipped (product stays unassigned; proposed again next assign)
- ingredient == llm_ingredient -> source=llm
- ingredient edited by hand    -> source=manual (never overwritten by assign)
- inputs no longer match the product (producto_es / store / v2 subcategory changed) -> stale, skipped
- product already linked by hand -> skipped
- is_food edited (!= llm_is_food) -> written to the ingredient, even one that already exists

Applied links are needs_review=0: reviewing the file is the review. The whole file is one
transaction, logged in ingredient_change_log; an invalid name aborts it.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from v2.stage3d_ingredients import proposals
from v2.stage3d_ingredients.store import (
    PRODUCTS_SQL, IngredientError, IngredientStore, clean_name, ingredient_key, product_inputs,
)


CONFIDENCE_SCORES = {"high": 0.9, "medium": 0.7, "low": 0.4}


@dataclass
class ApplyReport:
    file: str
    llm: int = 0
    manual: int = 0
    unassigned: List[str] = field(default_factory=list)
    stale: List[str] = field(default_factory=list)
    kept_manual: List[str] = field(default_factory=list)
    unknown: List[str] = field(default_factory=list)
    new_ingredients: int = 0
    is_food_changed: List[str] = field(default_factory=list)   # ingredient names
    dry_run: bool = False
    moved_to: str = ""


def is_food_edited(line: Dict) -> bool:
    """is_food changed by the reviewer (files without llm_is_food: any explicit value counts)."""
    if line.get("is_food") is None:
        return False
    return "llm_is_food" not in line or bool(line["is_food"]) != bool(line["llm_is_food"])


def apply_file(db: IngredientStore, path: Path, dry_run: bool = False) -> ApplyReport:
    path = Path(path)
    lines = proposals.read(path)
    report = ApplyReport(file=path.name, dry_run=dry_run)

    bad = []
    edited_food: Dict[str, bool] = {}     # ingredient key -> edited is_food
    for n, line in enumerate(lines, 1):
        if line.get("ingredient"):
            try:
                key = ingredient_key(clean_name(line["ingredient"]))
            except IngredientError as e:
                bad.append(f"line {n} ({line['item_name']}): {e}")
                continue
            if is_food_edited(line):
                if edited_food.setdefault(key, bool(line["is_food"])) != bool(line["is_food"]):
                    bad.append(f"line {n} ({line['item_name']}): is_food of {line['ingredient']!r} "
                               f"differs from another edited line")
    if bad:
        raise IngredientError("Fix these lines first:\n  " + "\n  ".join(bad))

    def op(conn):
        links = db.get_links(conn)
        reviewed_at = datetime.now().isoformat(timespec="seconds")
        rows: List[Dict] = []
        for line in lines:
            item = line["item_name"]
            product = conn.execute(PRODUCTS_SQL + " WHERE l.item_name = ?", (item,)).fetchone()
            if product is None:
                report.unknown.append(item)
                continue
            if product_inputs(product) != line.get("inputs"):
                report.stale.append(item)
                continue
            if links.get(item, {}).get("source") == "manual":
                report.kept_manual.append(item)
                continue
            if not line.get("ingredient"):
                report.unassigned.append(item)
                continue
            name = clean_name(line["ingredient"])
            edited = ingredient_key(name) != ingredient_key(line.get("llm_ingredient") or "")
            is_food = True if line.get("is_food") is None else bool(line["is_food"])
            ing_id, created = db.get_or_create(conn, name, is_food)
            report.new_ingredients += created
            if not created and is_food_edited(line):
                row = conn.execute("SELECT name, is_food FROM ingredient WHERE id=?", (ing_id,)).fetchone()
                if bool(row["is_food"]) != is_food:
                    conn.execute("UPDATE ingredient SET is_food=? WHERE id=?", (int(is_food), ing_id))
                    report.is_food_changed.append(row["name"])
            if edited:
                report.manual += 1
            else:
                report.llm += 1
            rows.append({
                "item_name": item, "ingredient_id": ing_id,
                "source": "manual" if edited else "llm",
                "confidence": 1.0 if edited else CONFIDENCE_SCORES.get(line.get("confidence"), 0.4),
                "needs_review": False,
                "evidence": {
                    "inputs": line["inputs"], "subcategory": proposals.label_of_line(line),
                    "model": line.get("model"), "llm_ingredient": line.get("llm_ingredient"),
                    "llm_confidence": line.get("confidence"), "reasoning": line.get("reasoning"),
                    "proposal": path.name, "proposed_at": line.get("proposed_at"), "reviewed_at": reviewed_at,
                },
            })
        db.upsert_links(conn, rows)
        return len(rows)

    db._run("apply", {"file": path.name}, op, dry_run)
    if not dry_run:
        target = proposals.applied_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        path.replace(target)
        report.moved_to = str(target)
    return report
