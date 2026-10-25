"""
Assign an ingredient to every product (product_ingredient), one v2 subcategory at a time.

All products of a subcategory, from both stores, go into one LLM call (chunks of
CHUNK_SIZE for big ones), so the model groups the same food under one name instead of
inventing variations. The call also sees the ingredients already used in that category
and must reuse them. Returned names are matched to existing ingredients by
ingredient_key (accents, case, plurals); other names become new ingredients, flagged
for review.

Skipped: manual links and llm links whose inputs (producto_es, store, v2 subcategory)
are unchanged. Products without a v2 subcategory are not assigned.
item_labels and the v2 taxonomy tables are only read.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Protocol, Tuple

from v2.stage3d_ingredients.prompts import (
    INGREDIENT_SYSTEM_PROMPT, INGREDIENT_USER_PROMPT_TEMPLATE, render_products, render_vocabulary,
)
from v2.stage3d_ingredients.store import (
    LABEL_SEP, IngredientError, IngredientStore, evidence_dict, product_inputs,
)


CHUNK_SIZE = 60
CONFIDENCE_SCORES = {"high": 0.9, "medium": 0.7, "low": 0.4}
STAGE = "ingredient_assign"

# Estimate only (no tokenizer call): Spanish/Dutch text runs ~3.5 characters per token
CHARS_PER_TOKEN = 3.5
SCHEMA_TOKENS = 150            # structured-output tool definition
OUTPUT_TOKENS_PER_CALL = 40
OUTPUT_TOKENS_PER_PRODUCT = 20


@dataclass
class Group:
    ingredient: str
    is_food: bool
    confidence: str             # high | medium | low
    ids: List[int]              # 1-based positions in the products list
    reasoning: str = ""


class IngredientNamer(Protocol):
    """Groups one subcategory's products into ingredients."""

    calls: int
    model: str

    def name(self, subcategory: str, vocabulary: List[str], products: List[Dict]) -> List[Group]:
        ...


@dataclass
class SubcategoryResult:
    label: str
    products: int
    vocabulary: int = 0
    est_input_tokens: int = 0
    est_output_tokens: int = 0
    prompts: List[str] = field(default_factory=list)
    groups: List[Dict] = field(default_factory=list)      # {ingredient, new, is_food, confidence, products}
    pending: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


@dataclass
class AssignReport:
    results: List[SubcategoryResult] = field(default_factory=list)
    assigned: int = 0
    pending: int = 0
    new_ingredients: int = 0
    flagged: int = 0
    skipped_manual: int = 0
    skipped_current: int = 0
    no_subcategory: int = 0
    remaining_subcategories: int = 0   # with work, not selected this run
    llm_calls: int = 0
    written: int = 0
    model: str = ""
    dry_run: bool = False

    @property
    def est_input_tokens(self) -> int:
        return sum(r.est_input_tokens for r in self.results)

    @property
    def est_output_tokens(self) -> int:
        return sum(r.est_output_tokens for r in self.results)


def label_of(product: Dict) -> str:
    return f"{product['category']}{LABEL_SEP}{product['subcategory']}"


def pending_work(db: IngredientStore, conn) -> Tuple[Dict[str, List[Dict]], Dict[str, int]]:
    """{subcategory label: products needing an ingredient} in taxonomy order, plus skip counts."""
    links = db.get_links(conn)
    work: Dict[str, List[Dict]] = {}
    skipped = {"manual": 0, "current": 0, "no_subcategory": 0}
    for product in db.products(conn):
        if product["subcategory_id"] is None:
            skipped["no_subcategory"] += 1
            continue
        link = links.get(product["item_name"])
        if link and link["source"] == "manual":
            skipped["manual"] += 1
            continue
        if (link and link["source"] == "llm"
                and evidence_dict(link["evidence"]).get("inputs") == product_inputs(product)):
            skipped["current"] += 1
            continue
        work.setdefault(label_of(product), []).append(product)
    return work, skipped


def select(work: Dict[str, List[Dict]], subcategory: Optional[str] = None, category: Optional[str] = None,
           max_subcategories: Optional[int] = None) -> List[str]:
    labels = list(work)
    if subcategory:
        wanted = LABEL_SEP.join(part.strip() for part in subcategory.split(LABEL_SEP.strip(), 1))
        labels = [l for l in labels if l == wanted]
    if category:
        labels = [l for l in labels if l.split(LABEL_SEP, 1)[0] == category]
    if max_subcategories is not None:
        labels = labels[:max_subcategories]
    return labels


def render_prompt(label: str, vocabulary: List[str], products: List[Dict]) -> str:
    return INGREDIENT_USER_PROMPT_TEMPLATE.format(
        subcategory=label, vocabulary=render_vocabulary(vocabulary), products=render_products(products),
    )


def estimate_tokens(prompt: str, n_products: int) -> Tuple[int, int]:
    tokens_in = round((len(INGREDIENT_SYSTEM_PROMPT) + len(prompt)) / CHARS_PER_TOKEN) + SCHEMA_TOKENS
    return tokens_in, OUTPUT_TOKENS_PER_CALL + OUTPUT_TOKENS_PER_PRODUCT * n_products


def estimate_cost(tokens_in: int, tokens_out: int, model: str) -> Optional[float]:
    from v2.common.pricing import get_pricing
    try:
        p = get_pricing(model)
    except ValueError:
        return None
    return (tokens_in * p["input_per_mtok_usd"] + tokens_out * p["output_per_mtok_usd"]) / 1_000_000


def assign(
    db: IngredientStore,
    namer: Optional[IngredientNamer] = None,
    subcategory: Optional[str] = None,
    category: Optional[str] = None,
    max_subcategories: Optional[int] = None,
    dry_run: bool = False,
    model: str = "",
    keep_prompts: bool = False,
) -> AssignReport:
    """
    Assign ingredients to the selected subcategories' products.

    Args:
        namer: groups products into ingredients; None = preview only (needs dry_run): no LLM,
               just the batches, vocabulary and token estimate
        subcategory / category / max_subcategories: which subcategories to run
        dry_run: call the namer (if any) but roll everything back
        keep_prompts: store the rendered prompts in the results
    """
    if namer is None and not dry_run:
        raise ValueError("assign without a namer is a preview: pass dry_run=True")
    report = AssignReport(model=namer.model if namer else model, dry_run=dry_run)
    conn = db.connect()
    try:
        work, skipped = pending_work(db, conn)
        report.skipped_manual, report.skipped_current = skipped["manual"], skipped["current"]
        report.no_subcategory = skipped["no_subcategory"]
        labels = select(work, subcategory, category, max_subcategories)
        report.remaining_subcategories = len(work) - len(labels)

        for label in labels:
            products = work[label]
            result = SubcategoryResult(label=label, products=len(products))
            report.results.append(result)
            cat, sub = label.split(LABEL_SEP, 1)
            for start in range(0, len(products), CHUNK_SIZE):
                chunk = products[start:start + CHUNK_SIZE]
                vocabulary = db.vocabulary(conn, cat, sub)   # includes names chosen by earlier chunks
                prompt = render_prompt(label, vocabulary, chunk)
                tokens_in, tokens_out = estimate_tokens(prompt, len(chunk))
                result.vocabulary = max(result.vocabulary, len(vocabulary))
                result.est_input_tokens += tokens_in
                result.est_output_tokens += tokens_out
                if keep_prompts:
                    result.prompts.append(prompt)
                if namer is None:
                    continue
                try:
                    groups = namer.name(label, vocabulary, chunk)
                    error = None
                except Exception as e:  # bad LLM output or API error: leave these products pending
                    groups, error = [], f"{type(e).__name__}: {str(e)[:160]}"
                    result.errors.append(error)
                    print(f"  ! {label}: call for {len(chunk)} products failed ({error})")
                rows = apply_groups(db, conn, label, chunk, groups, report, result, namer.model, error)
                report.written += db.upsert_links(conn, rows)
            if not dry_run:
                conn.commit()   # one commit per subcategory: a later failure keeps finished ones
        report.llm_calls = namer.calls if namer else 0
    finally:
        if dry_run:
            conn.rollback()
        conn.close()
    return report


def apply_groups(db: IngredientStore, conn, label: str, products: List[Dict], groups: List[Group],
                 report: AssignReport, result: SubcategoryResult, model: str,
                 error: Optional[str] = None) -> List[Dict]:
    """Turn the namer's groups into product_ingredient rows; invalid or missing ids stay pending."""
    counts = Counter(i for g in groups for i in g.ids)
    created_here = set()
    picks: Dict[int, Tuple[int, Group]] = {}
    for group in groups:
        valid = [i for i in group.ids if 1 <= i <= len(products) and counts[i] == 1]
        if not valid:
            continue
        try:
            ing_id, created = db.get_or_create(conn, group.ingredient, group.is_food)
        except IngredientError:
            continue
        if created:
            created_here.add(ing_id)
            report.new_ingredients += 1
        for i in valid:
            picks[i] = (ing_id, group)

    names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM ingredient").fetchall()}
    by_ingredient: Dict[int, Dict] = {}
    rows = []
    for i, product in enumerate(products, 1):
        reasons = ["upstream"] if product["upstream_review"] else []
        evidence = {"inputs": product_inputs(product), "subcategory": label, "model": model}
        pick = picks.get(i)
        if pick is None:
            why = error or ("duplicate_id" if counts[i] > 1 else "missing")
            rows.append({"item_name": product["item_name"], "ingredient_id": None, "source": "pending",
                         "needs_review": True,
                         "evidence": {**evidence, "pending": why, "review_reasons": reasons + ["pending"]}})
            result.pending.append(product["item_name"])
            report.pending += 1
            continue
        ing_id, group = pick
        if ing_id in created_here:
            reasons.append("new_ingredient")
        if group.confidence != "high":
            reasons.append("confidence")
        rows.append({
            "item_name": product["item_name"], "ingredient_id": ing_id, "source": "llm",
            "confidence": CONFIDENCE_SCORES.get(group.confidence, 0.4),
            "needs_review": bool(reasons),
            "evidence": {**evidence, "llm_ingredient": group.ingredient, "llm_confidence": group.confidence,
                         "reasoning": group.reasoning, "review_reasons": reasons},
        })
        report.assigned += 1
        report.flagged += bool(reasons)
        entry = by_ingredient.setdefault(ing_id, {
            "ingredient": names[ing_id], "new": ing_id in created_here, "is_food": group.is_food,
            "confidence": group.confidence, "products": [],
        })
        entry["products"].append(product)
    result.groups.extend(by_ingredient.values())
    return rows


class LLMIngredientNamer:
    """Mistral groups one subcategory's products into ingredients."""

    def __init__(self, model: Optional[str] = None, stage: str = STAGE):
        from v2.common.settings import settings
        from v2.common.token_tracker import TokenTracker

        self.model = model or settings.INGREDIENT_MODEL
        self.tracker = TokenTracker(settings.TOKEN_USAGE_DB)
        self.stage = stage
        self.calls = 0

    def name(self, subcategory: str, vocabulary: List[str], products: List[Dict]) -> List[Group]:
        from langchain_core.messages import HumanMessage, SystemMessage
        from pydantic import BaseModel, Field

        from v2.common.mistral_client import get_mistral_llm

        class IngredientGroup(BaseModel):
            ingredient: str = Field(description="Generic Spanish name, lowercase, singular")
            is_food: bool
            confidence: Literal["high", "medium", "low"]
            product_ids: List[int] = Field(description="Numbers of the products in this group")
            reasoning: str = Field(description="A few words")

        class IngredientGroups(BaseModel):
            groups: List[IngredientGroup]

        llm = get_mistral_llm(temperature=0.0, model=self.model).with_structured_output(IngredientGroups)
        callback = self.tracker.create_callback(stage=self.stage, file_path=subcategory)
        output: IngredientGroups = llm.invoke(
            [SystemMessage(content=INGREDIENT_SYSTEM_PROMPT),
             HumanMessage(content=render_prompt(subcategory, vocabulary, products))],
            config={"callbacks": [callback]},
        )
        self.calls += 1
        return [Group(g.ingredient, g.is_food, g.confidence, g.product_ids, g.reasoning) for g in output.groups]
