"""
Intermediate JSONL proposals: one folder per v2 category, one file per subcategory,
one line per product.

assign writes them, a person checks (and may edit) them, apply writes them to the db.

    proposals/<category>/<subcategory>.jsonl            waiting for review
    proposals/<category>/applied/<subcategory>.<timestamp>.jsonl    already written to the db (one per apply)

Line keys:
    item_name, store, producto_es, category, subcategory
    ingredient      editable: the name that apply will write (null = leave unassigned)
    is_food         editable
    llm_ingredient  what the model returned (as resolved); never edit
    llm_is_food     what the model returned for is_food; never edit
    new             no ingredient with this name existed when proposed
    confidence, reasoning, model, pending (why there is no ingredient), inputs, proposed_at
    too_specific    the name breaks the naming rules (parentheses, cooking use, > 4 words)

An edited `ingredient` (different from llm_ingredient) is applied as a manual link.
An edited `is_food` (different from llm_is_food) updates the ingredient, even one that exists.
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from v2.stage3d_ingredients.store import LABEL_SEP, _plain


PROPOSALS_DIR = Path(__file__).parent / "proposals"


def normalize_label(label: str) -> str:
    """'Verduras>Lechuga y Ensaladas' -> 'Verduras > Lechuga y Ensaladas'"""
    return LABEL_SEP.join(part.strip() for part in label.split(LABEL_SEP.strip(), 1))


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _plain(text)).strip("_")


def category_dir(category: str, root: Optional[Path] = None) -> Path:
    return (root or PROPOSALS_DIR) / slug(category)


def path_for(label: str, root: Optional[Path] = None) -> Path:
    category, subcategory = normalize_label(label).split(LABEL_SEP, 1)
    return category_dir(category, root) / f"{slug(subcategory)}.jsonl"


def applied_path(path: Path, when: Optional[datetime] = None) -> Path:
    """applied/<subcategory>.<timestamp>.jsonl, never an existing file (each apply keeps its own copy)."""
    stamp = (when or datetime.now()).strftime("%Y%m%dT%H%M%S")
    folder, n = path.parent / "applied", 1
    while True:
        target = folder / f"{path.stem}.{stamp}{'' if n == 1 else f'-{n}'}.jsonl"
        if not target.exists():
            return target
        n += 1


def write(path: Path, lines: Iterable[Dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    tmp.replace(path)
    return path


def read(path: Path) -> List[Dict]:
    with Path(path).open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def files(root: Optional[Path] = None, category: Optional[str] = None) -> List[Path]:
    """Proposal files waiting for review (applied/ files are one level deeper, so not matched)."""
    root = root or PROPOSALS_DIR
    pattern = f"{slug(category)}/*.jsonl" if category else "*/*.jsonl"
    return sorted(root.glob(pattern)) if root.exists() else []


def label_of_line(line: Dict) -> str:
    return f"{line['category']}{LABEL_SEP}{line['subcategory']}"


def proposed(root: Optional[Path] = None) -> Dict[str, List[Dict]]:
    """{subcategory label: lines} of every file waiting for review."""
    result: Dict[str, List[Dict]] = {}
    for path in files(root):
        lines = read(path)
        if lines:
            result[label_of_line(lines[0])] = lines
    return result


def category_names(category: str, exclude_label: Optional[str] = None, root: Optional[Path] = None) -> List[str]:
    """Ingredient names proposed (not yet applied) for other subcategories of this category."""
    names = []
    for label, lines in proposed(root).items():
        if label == exclude_label or label.split(LABEL_SEP, 1)[0] != category:
            continue
        names += [l["ingredient"] for l in lines if l.get("ingredient")]
    return sorted(set(names))
