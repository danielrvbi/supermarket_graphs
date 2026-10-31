"""
Unit tests for stage 3 (deterministic - no Mistral or Tavily calls).

Usage:
    python -m pytest v2/stage3_classification/tests -v
"""

import sys
from pathlib import Path

import numpy as np
import pytest

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parents[3]))

from v2.stage3_classification.matcher import Embedder, Matcher, Neighbour, passes_gate, strip_prefixes
from v2.stage3_classification.search import ProductSearch, is_product_page
from v2.stage3_classification.seed import load_old_labels, seed_labels
from v2.stage3_classification.store import ClassificationStore
from v2.stage3_classification.taxonomy import (
    SUBCATEGORY_ALIASES,
    TAXONOMY,
    all_labels,
    canonicalize,
    is_valid,
    split_label,
)


# ============================================================
# Fakes
# ============================================================

class FakeEmbeddings:
    """Bag-of-characters vectors: deterministic and similar for similar strings."""

    def __init__(self):
        self.calls = 0

    def embed_documents(self, texts):
        self.calls += 1
        out = []
        for t in texts:
            v = np.zeros(64)
            for ch in t:
                v[ord(ch) % 64] += 1
            out.append(v.tolist())
        return out


class FakeTavily:
    def __init__(self, results=None, fail=False):
        self.results = results if results is not None else [
            {"url": "https://www.ah.nl/producten/product/wi1/ah-kipfilet", "title": "AH Kipfilet",
             "content": "Kipfilet 300 g"}
        ]
        self.fail = fail
        self.queries = []

    def search(self, query, include_domains=None, **kwargs):
        self.queries.append((query, include_domains))
        if self.fail:
            raise RuntimeError("quota exceeded")
        return {"results": self.results}


@pytest.fixture
def db(tmp_path):
    return ClassificationStore(str(tmp_path / "test.db"))


def nb(category, score, name="X"):
    return Neighbour(item_name=name, producto_es=None, category=category, subcategory=TAXONOMY[category][0], score=score)


# ============================================================
# Taxonomy
# ============================================================

def test_alias_targets_are_valid():
    for old, new in SUBCATEGORY_ALIASES.items():
        assert is_valid(*new), f"{old} -> {new} is not in TAXONOMY"


def test_aliases_do_not_shadow_canonical_pairs():
    for old in SUBCATEGORY_ALIASES:
        assert not is_valid(*old), f"{old} is canonical and should not be aliased"


def test_canonicalize():
    assert canonicalize("Lácteos", "Yogurt") == ("Lácteos", "Yogur")
    assert canonicalize("Hogar", "Huevos") == ("Lácteos", "Huevos")
    assert canonicalize(" Carnes ", "Pollo ") == ("Carnes", "Pollo")
    assert canonicalize("Carnes", "Dinosaurio") is None


def test_labels_roundtrip():
    labels = all_labels()
    assert len(labels) == len(set(labels))
    for label in labels:
        assert is_valid(*split_label(label))
    assert all(TAXONOMY[c][-1] == "Otros" for c in TAXONOMY)


# ============================================================
# Matcher
# ============================================================

def test_strip_prefixes():
    assert strip_prefixes("AH BIO KIPFI") == "KIPFI"
    assert strip_prefixes("JUMBO PANEER NATUREL") == "PANEER NATUREL"
    assert strip_prefixes("JMB SALADEMIX") == "SALADEMIX"
    assert strip_prefixes("AHOY CHIPS") == "AHOY CHIPS"  # whole words only
    assert strip_prefixes("AH") == "AH"                  # never empty


def test_gate():
    assert passes_gate([nb("Carnes", 0.85), nb("Carnes", 0.8), nb("Carnes", 0.7)], 0.8)
    assert not passes_gate([nb("Carnes", 0.79), nb("Carnes", 0.78), nb("Carnes", 0.7)], 0.8)
    assert not passes_gate([nb("Carnes", 0.9), nb("Lácteos", 0.85), nb("Carnes", 0.8)], 0.8)
    assert not passes_gate([], 0.8)


def test_embedder_caches(db):
    fake = FakeEmbeddings()
    emb = Embedder(db, model="fake", client=fake)
    first = emb.embed(["KIPFILET", "MELK", "KIPFILET"])
    assert first.shape == (3, 64)
    assert np.allclose(np.linalg.norm(first, axis=1), 1)
    assert fake.calls == 1

    again = Embedder(db, model="fake", client=fake).embed(["MELK", "KIPFILET"])
    assert fake.calls == 1  # served from embedding_cache
    assert np.allclose(again[1], first[0])


def test_matcher_neighbours_excludes_self(db):
    labels = [
        {"item_name": "AH KIPFILET", "producto_es": "Pechuga de Pollo AH", "category": "Carnes", "subcategory": "Pollo"},
        {"item_name": "HALFV MELK", "producto_es": "Leche", "category": "Lácteos", "subcategory": "Leche"},
    ]
    matcher = Matcher(labels, Embedder(db, model="fake", client=FakeEmbeddings()))
    [hits] = matcher.neighbours(["AH BIO KIPFILET"], k=2)
    assert hits[0].item_name == "AH KIPFILET"
    assert hits[0].score >= hits[1].score

    [hits] = matcher.neighbours(["AH KIPFILET"], k=2)
    assert [h.item_name for h in hits] == ["HALFV MELK"]


# ============================================================
# Search cache
# ============================================================

def test_search_called_once_per_item(db):
    tavily = FakeTavily()
    search = ProductSearch(db, client=tavily)
    first = search.search("ah", "AH BIO KIPFI")
    assert first["success"] and not first["cached"]
    assert tavily.queries == [("Albert Heijn KIPFI", ["ah.nl"])]

    second = ProductSearch(db, client=tavily).search("ah", "AH BIO KIPFI")
    assert second["cached"] and second["results"] == first["results"]
    assert len(tavily.queries) == 1


def test_search_widens_when_store_site_empty(db):
    tavily = FakeTavily(results=[])
    result = ProductSearch(db, client=tavily).search("jumbo", "JUMBO DUMIL")
    assert [d for _, d in tavily.queries] == [["jumbo.com"], None]
    assert not result["success"]


def test_search_ignores_non_product_pages(db):
    tavily = FakeTavily(results=[
        {"url": "https://werk.ah.nl/en/about-albert-heijn", "title": "Over ons", "content": "125,000 colleagues"},
        {"url": "https://www.ah.nl/allerhande/recept/R-1/salade", "title": "Recept", "content": "..."},
    ])
    result = ProductSearch(db, client=tavily).search("ah", "EUR ITAL KRD")
    assert not result["success"]                       # flagged for review downstream
    assert len(tavily.queries) == 2                    # store site, then the whole web
    assert db.get_search("ah", "EUR ITAL KRD")["error"] == "no product page on store site"


def test_is_product_page():
    assert is_product_page("https://www.ah.nl/producten/product/wi212148/ah-bramen")
    assert is_product_page("https://www.jumbo.com/producten/jumbo-winterpeen-ca-150-g-786683STK")
    assert not is_product_page("https://www.jumbo.com/aanbiedingen/nu")
    assert not is_product_page("https://www.jumbo.com/recepten/patatas-bravas-1438672-7")
    assert not is_product_page(None)


def test_failed_search_cached_until_retry(db):
    ProductSearch(db, client=FakeTavily(fail=True)).search("ah", "EDET")
    assert db.get_search("ah", "EDET")["error"] == "quota exceeded"

    tavily = FakeTavily()
    assert ProductSearch(db, client=tavily).search("ah", "EDET")["cached"]
    assert tavily.queries == []

    retried = ProductSearch(db, client=tavily).search("ah", "EDET", retry_failed=True)
    assert retried["success"] and len(tavily.queries) == 1


# ============================================================
# Seeding / labels
# ============================================================

OLD_CSV = """Month,Week,Date,Product,Producto,Category,Subcategory,Unit Price RAW,# Units RAW,Total Price RAW, Unit Price ,# Units, Total Price , RANK ,MRKT
2024-01-01,2024-W01,2024-01-02, ah yoghurt ,Yogur AH,Lácteos,Yogurt,€1,1,€1, € 1 ,1, € 1 ,,Albert Heijn
2024-02-01,2024-W06,2024-02-05,AH YOGHURT,Yogur Natural AH,Lácteos,Yogur,€1,1,€1, € 1 ,1, € 1 ,,Albert Heijn
2024-01-01,2024-W01,2024-01-02,AH EIEREN,Huevos AH,Hogar,Huevos,€3,1,€3, € 3 ,1, € 3 ,,Albert Heijn
,,,,,,,,,,,,,,
"""


def test_seed_resolves_conflicts_and_aliases(tmp_path, db):
    csv = tmp_path / "old.csv"
    csv.write_text(OLD_CSV, encoding="utf-8")

    labels = {l["item_name"]: l for l in load_old_labels(str(csv))}
    assert set(labels) == {"AH YOGHURT", "AH EIEREN"}
    assert labels["AH YOGHURT"]["producto_es"] == "Yogur Natural AH"  # most recent wins
    assert (labels["AH EIEREN"]["category"], labels["AH EIEREN"]["subcategory"]) == ("Lácteos", "Huevos")
    assert labels["AH EIEREN"]["store"] == "ah"

    assert seed_labels(db, str(csv)) == 2


def test_seed_never_overwrites_manual(tmp_path, db):
    csv = tmp_path / "old.csv"
    csv.write_text(OLD_CSV, encoding="utf-8")
    db.upsert_label("AH EIEREN", "Hogar", "Otros", source="manual")
    seed_labels(db, str(csv))
    assert db.get_label("AH EIEREN")["source"] == "manual"
    assert db.get_label("AH YOGHURT")["source"] == "old_data"


NON_PRODUCT_CSV = """Month,Week,Date,Product,Producto,Category,Subcategory,Unit Price RAW,# Units RAW,Total Price RAW, Unit Price ,# Units, Total Price , RANK ,MRKT
2024-01-01,2024-W01,2024-01-02,AH YOGHURT,Yogur AH,Lácteos,Yogurt,€1,1,€1, € 1 ,1, € 1 ,,Albert Heijn
2024-01-01,2024-W01,2024-01-02,KOOPZEGELS,Cupones AH,Hogar,Otros,€0,1,€0, € 0 ,1, € 0 ,,Albert Heijn
2024-01-01,2024-W01,2024-01-02,STATIEGELD,Deposit,Hogar,Otros,€0,1,€0, € 0 ,1, € 0 ,,Albert Heijn
2024-01-01,2024-W01,2024-01-02,CASHBACK,Cashback,Hogar,Otros,€0,1,€0, € 0 ,1, € 0 ,,Albert Heijn
2024-01-01,2024-W01,2024-01-02,KORTING,Discount,Hogar,Otros,€0,1,€0, € 0 ,1, € 0 ,,Albert Heijn
2024-01-01,2024-W01,2024-01-02,BEDRAG,Amount,Hogar,Otros,€0,1,€0, € 0 ,1, € 0 ,,Albert Heijn
2024-01-01,2024-W01,2024-01-02,KORTIJKE BROODJES,Broodjes AH,Panadería,Pan,€2,1,€2, € 2 ,1, € 2 ,,Albert Heijn
"""


def test_seed_skips_non_product_lines(tmp_path, db):
    """Non-product receipt lines must never be seeded as product labels."""
    csv = tmp_path / "old_with_nonproducts.csv"
    csv.write_text(NON_PRODUCT_CSV, encoding="utf-8")

    labels = {l["item_name"]: l for l in load_old_labels(str(csv))}

    # Only real products should be loaded
    assert set(labels) == {"AH YOGHURT", "KORTIJKE BROODJES"}
    # Non-products must not appear
    for non_product in ["KOOPZEGELS", "STATIEGELD", "CASHBACK", "KORTING", "BEDRAG"]:
        assert non_product not in labels

    # Seeding should also skip them
    assert seed_labels(db, str(csv)) == 2
    assert db.get_label("KOOPZEGELS") is None
    assert db.get_label("STATIEGELD") is None
    assert db.get_label("CASHBACK") is None
    assert db.get_label("KORTING") is None
    assert db.get_label("BEDRAG") is None
    assert db.get_label("AH YOGHURT") is not None
    assert db.get_label("KORTIJKE BROODJES") is not None


def test_rebuild_classified_joins_labels(db):
    from v2.stage1_extraction.store import ProcessedDataStore
    from v2.stage2_normalization.store import NormalizedDataStore

    ProcessedDataStore(db.db_path)
    norm = NormalizedDataStore(db.db_path)
    for name, total in [("AH EIEREN", 3.0), ("AH EIEREN", 3.5), ("MYSTERY", 1.0)]:
        norm.insert_normalized_item(
            source_id=None, receipt_id=f"r{total}", store="ah", date_of_purchase="2024-01-02",
            month_of_purchase="2024-01-01", item_name=name, measurement_type="discrete_units",
            measurement_quantity=1.0, price_per_measurement_unit=total,
            line_total_paid_amount=total, normalization_rules=[],
        )
    db.upsert_label("AH EIEREN", "Lácteos", "Huevos", source="old_data", producto_es="Huevos AH")

    assert db.get_unique_items() == [
        {"store": "ah", "item_name": "AH EIEREN", "n_rows": 2},
        {"store": "ah", "item_name": "MYSTERY", "n_rows": 1},
    ]
    assert db.rebuild_classified() == 3
    stats = db.get_classification_stats()
    assert stats["unlabelled_rows"] == 1
    assert stats["labels_by_source"] == {"old_data": 1}
