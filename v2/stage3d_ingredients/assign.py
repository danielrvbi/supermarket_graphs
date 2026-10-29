"""
Propose an ingredient for every product, one v2 subcategory at a time.

All products of a subcategory, from both stores, go into one LLM call (chunks of
CHUNK_SIZE for big ones), so the model groups the same food under one name instead of
inventing variations. The call also sees the ingredients already used in that category
(in the db, or proposed in other files) and must reuse them. Returned names are matched
to known ones by ingredient_key (accents, case, plurals); other names are marked new.

assign never writes the db: each subcategory becomes one JSONL file in proposals/
(see proposals.py). After review, apply.py writes a file to the db.

Skipped: manual links, llm links whose inputs (producto_es, store, v2 subcategory) are
unchanged, and subcategories that already have a proposal file (unless redo).
Products without a v2 subcategory are not proposed.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Literal, Optional, Protocol, Tuple

from v2.stage3d_ingredients import proposals
from v2.stage3d_ingredients.prompts import (
    INGREDIENT_SYSTEM_PROMPT, INGREDIENT_USER_PROMPT_TEMPLATE, render_products, render_vocabulary,
)
from v2.stage3d_ingredients.store import (
    LABEL_SEP, IngredientError, IngredientStore, clean_name, evidence_dict, ingredient_key, product_inputs,
)


CHUNK_SIZE = 60
CONFIDENCE_SCORES = {"high": 0.9, "medium": 0.7, "low": 0.4}
STAGE = "ingredient_assign"

# Estimate only (no tokenizer call); calibrated on the first live call (1265 in / 510 out, 32 products)
CHARS_PER_TOKEN = 3.5
SCHEMA_TOKENS = 370            # structured-output tool definition
OUTPUT_TOKENS_PER_CALL = 40
OUTPUT_TOKENS_PER_PRODUCT = 15


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
    lines: List[Dict] = field(default_factory=list)       # proposal lines
    errors: List[str] = field(default_factory=list)
    file: Optional[Path] = None                            # written proposal


@dataclass
class AssignReport:
    results: List[SubcategoryResult] = field(default_factory=list)
    proposed: int = 0
    pending: int = 0
    new_ingredients: int = 0
    skipped_manual: int = 0
    skipped_current: int = 0
    skipped_proposed: int = 0          # products in a proposal file waiting for review
    no_subcategory: int = 0
    remaining_subcategories: int = 0   # with work, not selected this run
    stopped_by_budget: Optional[str] = None   # first subcategory not run because of the budget
    llm_calls: int = 0
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


def pending_work(db: IngredientStore, conn, root: Optional[Path] = None,
                 redo: bool = False) -> Tuple[Dict[str, List[Dict]], Dict[str, int]]:
    """{subcategory label: products needing an ingredient} in taxonomy order, plus skip counts."""
    links = db.get_links(conn)
    waiting = set() if redo else set(proposals.proposed(root))
    work: Dict[str, List[Dict]] = {}
    skipped = {"manual": 0, "current": 0, "proposed": 0, "no_subcategory": 0}
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
        if label_of(product) in waiting:
            skipped["proposed"] += 1
            continue
        work.setdefault(label_of(product), []).append(product)
    return work, skipped


def select(work: Dict[str, List[Dict]], subcategory: Optional[str] = None, category: Optional[str] = None,
           max_subcategories: Optional[int] = None) -> List[str]:
    labels = list(work)
    if subcategory:
        wanted = proposals.normalize_label(subcategory)
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


class Known:
    """Ingredient names known so far: the db's, other proposal files', and this run's."""

    def __init__(self, db: IngredientStore, conn, root: Optional[Path]):
        self.db, self.conn = db, conn
        self.names: Dict[str, str] = {}       # key -> name, from proposals and this run
        for lines in proposals.proposed(root).values():
            for line in lines:
                if line.get("ingredient"):
                    self.add(line["ingredient"])
        self.by_category: Dict[str, List[str]] = {}

    def add(self, name: str, category: Optional[str] = None):
        self.names.setdefault(ingredient_key(name), name)
        if category:
            names = self.by_category.setdefault(category, [])
            if name not in names:
                names.append(name)

    def resolve(self, name: str) -> Tuple[str, bool]:
        """(canonical spelling, new) for a cleaned name."""
        row = self.db.find(self.conn, name)
        if row is not None:
            return row["name"], False
        known = self.names.get(ingredient_key(name))
        return (known, False) if known else (name, True)

    def vocabulary(self, category: str, subcategory: str, label: str, root: Optional[Path]) -> List[str]:
        names = (self.db.vocabulary(self.conn, category, subcategory)
                 + proposals.category_names(category, exclude_label=label, root=root)
                 + self.by_category.get(category, []))
        seen, result = set(), []
        for n in names:   # names that break the rules are not offered for reuse
            if ingredient_key(n) not in seen and not too_specific(n):
                seen.add(ingredient_key(n))
                result.append(n)
        return result


def assign(
    db: IngredientStore,
    namer: Optional[IngredientNamer] = None,
    subcategory: Optional[str] = None,
    category: Optional[str] = None,
    max_subcategories: Optional[int] = None,
    dry_run: bool = False,
    model: str = "",
    keep_prompts: bool = False,
    redo: bool = False,
    root: Optional[Path] = None,
    budget: Optional[float] = None,
) -> AssignReport:
    """
    Propose ingredients for the selected subcategories' products. Never writes the db.

    Args:
        namer: groups products into ingredients; None = preview only (needs dry_run): no LLM,
               just the batches, vocabulary and token estimate
        subcategory / category / max_subcategories: which subcategories to run
        dry_run: call the namer (if any) but write no proposal file
        redo: propose again for subcategories that already have a proposal file (overwrites it)
        root: proposals directory (default proposals.PROPOSALS_DIR)
        budget: max estimated USD for this run's LLM calls; stops before the subcategory
                that would exceed it (estimate at the model's pricing, see estimate_tokens)
    """
    if namer is None and not dry_run:
        raise ValueError("assign without a namer is a preview: pass dry_run=True")
    report = AssignReport(model=namer.model if namer else model, dry_run=dry_run)
    conn = db.connect()
    try:
        work, skipped = pending_work(db, conn, root, redo)
        report.skipped_manual, report.skipped_current = skipped["manual"], skipped["current"]
        report.skipped_proposed, report.no_subcategory = skipped["proposed"], skipped["no_subcategory"]
        labels = select(work, subcategory, category, max_subcategories)
        report.remaining_subcategories = len(work) - len(labels)
        known = Known(db, conn, root)

        spent = 0.0
        for label in labels:
            products = work[label]
            cat, sub = label.split(LABEL_SEP, 1)
            if namer is not None and budget is not None:
                cost = subcategory_cost(known, label, products, report.model, root)
                if spent + cost > budget:
                    report.stopped_by_budget = label
                    break
                spent += cost
            result = SubcategoryResult(label=label, products=len(products))
            report.results.append(result)
            for start in range(0, len(products), CHUNK_SIZE):
                chunk = products[start:start + CHUNK_SIZE]
                vocabulary = known.vocabulary(cat, sub, label, root)   # includes earlier chunks' names
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
                except Exception as e:  # bad LLM output or API error: no file, retried next run
                    groups, error = [], f"{type(e).__name__}: {str(e)[:160]}"
                    result.errors.append(error)
                    print(f"  ! {label}: call for {len(chunk)} products failed ({error})")
                result.lines += build_lines(label, chunk, groups, known, report, namer.model, error)
            if namer is not None and not dry_run and not result.errors:
                result.file = proposals.write(proposals.path_for(label, root), result.lines)
        report.llm_calls = namer.calls if namer else 0
    finally:
        conn.close()
    return report


TOO_SPECIFIC = re.compile(r"[()]|\bpara (saltear|wok|horno|hornear|ensalada)\b")
MAX_WORDS = 4


def too_specific(name: Optional[str]) -> bool:
    """Names the prompt forbids (parentheses, cooking use, > MAX_WORDS words); flagged for review."""
    return bool(name) and (bool(TOO_SPECIFIC.search(name)) or len(name.split()) > MAX_WORDS)


def subcategory_cost(known: "Known", label: str, products: List[Dict], model: str,
                     root: Optional[Path]) -> float:
    """Estimated USD for one subcategory (vocabulary as it is now; later chunks may see a little more)."""
    cat, sub = label.split(LABEL_SEP, 1)
    vocabulary = known.vocabulary(cat, sub, label, root)
    total = 0.0
    for start in range(0, len(products), CHUNK_SIZE):
        chunk = products[start:start + CHUNK_SIZE]
        total += estimate_cost(*estimate_tokens(render_prompt(label, vocabulary, chunk), len(chunk)), model) or 0.0
    return total


def proposal_line(product: Dict, label: str, ingredient: Optional[str], is_food: Optional[bool], new: bool,
                  confidence: Optional[str], reasoning: str, model: str, pending: Optional[str] = None) -> Dict:
    category, subcategory = label.split(LABEL_SEP, 1)
    return {
        "item_name": product["item_name"], "store": product["store"], "producto_es": product["producto_es"],
        "category": category, "subcategory": subcategory,
        "ingredient": ingredient, "is_food": is_food, "llm_ingredient": ingredient, "new": new,
        "confidence": confidence, "reasoning": reasoning, "model": model, "pending": pending,
        "too_specific": too_specific(ingredient),
        "inputs": product_inputs(product), "proposed_at": datetime.now().isoformat(timespec="seconds"),
    }


def build_lines(label: str, products: List[Dict], groups: List[Group], known: Known,
                report: AssignReport, model: str, error: Optional[str] = None) -> List[Dict]:
    """Turn the namer's groups into proposal lines; invalid or missing ids get no ingredient."""
    category = label.split(LABEL_SEP, 1)[0]
    counts = Counter(i for g in groups for i in g.ids)
    picks: Dict[int, Tuple[str, bool, Group]] = {}
    for group in groups:
        valid = [i for i in group.ids if 1 <= i <= len(products) and counts[i] == 1]
        if not valid:
            continue
        try:
            name, new = known.resolve(clean_name(group.ingredient))
        except IngredientError:
            continue
        if new:
            report.new_ingredients += 1
        known.add(name, category)
        for i in valid:
            picks[i] = (name, new, group)

    lines = []
    for i, product in enumerate(products, 1):
        pick = picks.get(i)
        if pick is None:
            why = error or ("duplicate_id" if counts[i] > 1 else "missing")
            lines.append(proposal_line(product, label, None, None, False, None, "", model, pending=why))
            report.pending += 1
            continue
        name, new, group = pick
        lines.append(proposal_line(product, label, name, group.is_food, new, group.confidence,
                                   group.reasoning, model))
        report.proposed += 1
    return lines


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
