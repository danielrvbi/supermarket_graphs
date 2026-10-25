"""
Sync v1 labels (item_labels) into v2 labels (product_category).

For each product in item_labels, its v1 (category, subcategory) is looked up in v1_map:
- one target   -> written directly (source=map)
- several      -> split: the LLM picks one of only those candidates (source=split_llm);
                  with no_llm the product is stored with no subcategory (source=pending_split)

Skipped: manual v2 labels, and labels whose synced_from still equals the product's
current v1 label (so re-running only touches new products and changed v1 labels).
item_labels and classified_data are only read.
"""

import sqlite3
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Protocol, Tuple

from v2.stage3c_taxonomy.store import LABEL_SEP, TaxonomyStore


BATCH_SIZE = 25
CONFIDENCE_SCORES = {"high": 0.9, "medium": 0.7, "low": 0.4}


@dataclass
class SyncReport:
    mapped: int = 0
    split_llm: int = 0
    pending_split: int = 0
    skipped_manual: int = 0
    skipped_current: int = 0
    unmapped: Dict[str, int] = field(default_factory=dict)
    splits: Dict[str, int] = field(default_factory=dict)   # v1 label -> products to split
    llm_calls: int = 0
    written: int = 0
    dry_run: bool = False


class SplitPicker(Protocol):
    """Picks one candidate label per product. Returns {item_name: (label, confidence, reasoning)}."""

    calls: int

    def pick(self, v1_label: str, candidates: List[str], products: List[Dict]) -> Dict[str, Tuple[str, str, str]]:
        ...


def read_v1_labels(db_path: str) -> List[Dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT item_name, store, producto_es, category, subcategory, needs_review FROM item_labels"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def sync(
    db: TaxonomyStore,
    picker: Optional[SplitPicker] = None,
    dry_run: bool = False,
    limit: Optional[int] = None,
) -> SyncReport:
    """
    Bring product_category up to date with item_labels.

    Args:
        picker: LLM split picker; None = leave splits as pending_split
        dry_run: report what would happen, write nothing, call no LLM
        limit: only process the first N products that need work
    """
    report = SyncReport(dry_run=dry_run)
    mapping = db.v1_map()
    existing = db.get_product_labels()
    to_write: List[Dict] = []
    to_split: Dict[str, List[Dict]] = defaultdict(list)

    todo = 0
    for product in read_v1_labels(db.db_path):
        v1_label = f"{product['category']}{LABEL_SEP}{product['subcategory']}"
        current = existing.get(product["item_name"])
        if current and current["source"] == "manual":
            report.skipped_manual += 1
            continue
        if current and current["synced_from"] == v1_label and current["source"] != "pending_split":
            report.skipped_current += 1
            continue
        targets = mapping.get((product["category"], product["subcategory"]))
        if not targets:
            report.unmapped[v1_label] = report.unmapped.get(v1_label, 0) + 1
            continue
        if limit is not None and todo >= limit:
            break
        todo += 1

        if len(targets) == 1:
            report.mapped += 1
            to_write.append({
                "item_name": product["item_name"],
                "subcategory_id": targets[0][0],
                "source": "map",
                "confidence": 1.0,
                "needs_review": product["needs_review"],
                "evidence": {"v1": v1_label},
                "synced_from": v1_label,
            })
        else:
            to_split[v1_label].append(product)

    report.splits = {label: len(products) for label, products in to_split.items()}
    if dry_run:
        report.pending_split = sum(report.splits.values())
        return report

    report.written = db.upsert_product_labels(to_write)

    # one write per split group, so a failure later doesn't lose finished groups
    for v1_label, products in to_split.items():
        category, subcategory = v1_label.split(LABEL_SEP, 1)
        targets = mapping[(category, subcategory)]
        ids = {label: sub_id for sub_id, label in targets}
        candidates = list(ids)
        picks = _pick_all(picker, v1_label, candidates, products) if picker else {}
        to_write = []

        for product in products:
            evidence = {"v1": v1_label, "candidates": candidates}
            pick = picks.get(product["item_name"])
            if pick is None:
                report.pending_split += 1
                to_write.append({
                    "item_name": product["item_name"], "subcategory_id": None,
                    "source": "pending_split", "needs_review": True,
                    "evidence": evidence, "synced_from": v1_label,
                })
                continue
            label, confidence, reasoning = pick
            report.split_llm += 1
            to_write.append({
                "item_name": product["item_name"],
                "subcategory_id": ids[label],
                "source": "split_llm",
                "confidence": CONFIDENCE_SCORES[confidence],
                "needs_review": confidence != "high" or bool(product["needs_review"]),
                "evidence": {**evidence, "reasoning": reasoning, "llm_confidence": confidence},
                "synced_from": v1_label,
            })
        report.written += db.upsert_product_labels(to_write)

    report.llm_calls = picker.calls if picker else 0
    return report


def _pick_all(picker: SplitPicker, v1_label: str, candidates: List[str], products: List[Dict]) -> Dict:
    """Batch the products; retry missing ones once in smaller batches. Failed batches stay missing."""
    picks: Dict = {}

    def run(batch):
        try:
            picks.update(picker.pick(v1_label, candidates, batch))
        except Exception as e:  # bad LLM output or API error: leave these products pending
            print(f"  ! {v1_label}: batch of {len(batch)} failed ({type(e).__name__}: {str(e)[:120]})")

    for start in range(0, len(products), BATCH_SIZE):
        run(products[start:start + BATCH_SIZE])
    missing = [p for p in products if p["item_name"] not in picks]
    for start in range(0, len(missing), 5):
        run(missing[start:start + 5])
    return picks


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower().strip()


def resolve_label(raw: str, candidates: List[str]) -> Optional[str]:
    """
    Map the LLM's label onto a candidate: exact, else the only candidate whose subcategory
    equals or contains the returned subcategory ('Frutas > Tropicales' -> 'Frutas > Frutas Tropicales').
    """
    if raw in candidates:
        return raw
    wanted = _plain(raw.split(LABEL_SEP.strip())[-1])
    if not wanted:
        return None
    subs = {c: _plain(c.split(LABEL_SEP, 1)[1]) for c in candidates}
    exact = [c for c, sub in subs.items() if sub == wanted]
    if len(exact) == 1:
        return exact[0]
    contains = [c for c, sub in subs.items() if wanted in sub or sub in wanted]
    return contains[0] if len(contains) == 1 else None


class LLMSplitPicker:
    """Mistral picks one candidate per product, constrained to the candidate list."""

    def __init__(self, stage: str = "taxonomy_sync"):
        from v2.common.settings import settings
        from v2.common.token_tracker import TokenTracker

        self.tracker = TokenTracker(settings.TOKEN_USAGE_DB)
        self.stage = stage
        self.calls = 0

    def pick(self, v1_label: str, candidates: List[str], products: List[Dict]) -> Dict[str, Tuple[str, str, str]]:
        from langchain_core.messages import HumanMessage, SystemMessage
        from pydantic import BaseModel, Field

        from v2.common.mistral_client import get_mistral_llm
        from v2.stage3c_taxonomy.prompts import SPLIT_SYSTEM_PROMPT, SPLIT_USER_PROMPT_TEMPLATE

        class Assignment(BaseModel):
            id: int = Field(description="The product's number in the list")
            label: str = Field(description="One of the allowed labels, copied exactly")
            confidence: Literal["high", "medium", "low"]
            reasoning: str = Field(description="A few words")

        class Assignments(BaseModel):
            assignments: List[Assignment]

        llm = get_mistral_llm(temperature=0.0).with_structured_output(Assignments)
        prompt = SPLIT_USER_PROMPT_TEMPLATE.format(
            v1_label=v1_label,
            candidates="\n".join(f"- {c}" for c in candidates),
            products="\n".join(
                f"{i}. {p['item_name']} | {p['producto_es'] or ''} | {p['store'] or ''}"
                for i, p in enumerate(products, 1)
            ),
        )
        callback = self.tracker.create_callback(stage=self.stage, file_path=v1_label)
        output: Assignments = llm.invoke(
            [SystemMessage(content=SPLIT_SYSTEM_PROMPT), HumanMessage(content=prompt)],
            config={"callbacks": [callback]},
        )
        self.calls += 1

        picks = {}
        for a in output.assignments:
            label = resolve_label(a.label, candidates)
            if 1 <= a.id <= len(products) and label:
                picks[products[a.id - 1]["item_name"]] = (label, a.confidence, a.reasoning)
        return picks
