# Stage 3 — Classification

**Input:** `normalized_data` table + `old_data.csv` (hand-labelled products)
**Output:** `item_labels` (product dictionary) and `classified_data` tables

Assigns every item a Spanish name (`producto_es`), category and subcategory from a frozen taxonomy.

## How it works

Classification runs once per unique item name, not per row:

```
Tier 0  exact match in item_labels ─────────────────────────────────────────► done
        (seeded from old_data.csv + every earlier result)
Tier 1  Mistral embeddings: 5 nearest labelled products (AH/JUMBO/JMB/BIO stripped)
        gate = top1 similarity ≥ 0.80 AND top-3 agree on category
Tier 2  gate failed → Tavily search on ah.nl / jumbo.com (cached per item, forever)
Tier 3  Mistral picks producto_es + "Category > Subcategory" (enum of the taxonomy),
        using the neighbours as examples and the search results as evidence
        ─► saved to item_labels, so the next run treats it as Tier 0
```

**Why embeddings are not enough on their own:** receipt names are abbreviations (AH cuts at ~12 chars:
`AH BIO KIPFI`, `AH DRINKYOGH`). Embeddings handle partial words well (`KIPFI` ≈ kip), but fail when
truncation destroys the word (`AH SCHEPIJS` ≈ Schweppes) or the name is just a brand (`DUMIL`, `EDET`).
On old_data (leave-one-out) the nearest neighbour gets the category right 76% of the time overall, but
**97% when the gate passes** — so the gate decides when a web search is needed.

**Tavily is called at most once per (store, item_name).** Results, including failures, are stored in
`search_cache`; a search only counts as successful if the store's site returned a product page
(`/producten/`). Otherwise the whole web is searched once, shown to the LLM as unverified, and the item is
flagged for review.

## Usage

```bash
python -m v2.main classify --dry-run     # tier counts + how many Tavily/LLM calls would happen
python -m v2.main classify --limit 20    # try on 20 new items
python -m v2.main classify               # classify everything new
python -m v2.main classify --no-search   # never call Tavily (weak matches get flagged)
python -m v2.main classify --rebuild     # redo LLM labels (keeps old_data/manual labels, reuses caches)
python -m v2.main classify --retry-failed-search
```

Requires `MISTRAL_KEY` and `TAVILY_API_KEY` (or `TAVILY_KEY`) in `.env`.

### Review

Items are flagged (`needs_review = 1`) when the LLM is not confident, when it disagrees with confident
neighbours, or when a weak match had no usable search result.

```bash
python -m v2.main review-labels list                 # flagged items
python -m v2.main review-labels list --all           # all LLM labels
python -m v2.main review-labels show "AH GEGRILDE"   # neighbours, search results, reasoning
python -m v2.main review-labels approve "AH GEGRILDE"
python -m v2.main review-labels set "AH GEGRILDE" Carnes Jamón --producto "Jamón York a la Parrilla AH"
python -m v2.main review-labels taxonomy
```

`set` saves a `manual` label: it is never overwritten (not even by re-seeding) and becomes a neighbour
for future items.

### Evaluation

```bash
python -m v2.stage3_classification.eval --n 100          # held-out old_data products, no Tavily
python -m v2.stage3_classification.eval --n 40 --search  # weak matches use Tavily (spends credits)
```

Measured: confident matches ~92–97% category / ~85–88% subcategory; weak matches ~78% category with
Tavily (several "misses" are wrong old labels, e.g. `AH BRAMEN` = blackberries, labelled Zanahoria).

## Taxonomy

`taxonomy.py` holds the frozen `TAXONOMY` (11 categories, 127 subcategories, each with `Otros`) and
`SUBCATEGORY_ALIASES`, which maps the 174 (category, subcategory) pairs found in old_data.csv onto it —
e.g. Yogurt → Yogur, Fresas → Fresa, Hogar > Huevos → Lácteos > Huevos, Hogar > Arroz → Pasta/Sopas > Arroz.
Seeding fails loudly if old_data contains a pair that has no alias.

## Tables

| Table | Key | Contents |
|-------|-----|----------|
| `item_labels` | item_name | producto_es, category, subcategory, source (`old_data`/`embed_llm`/`search_llm`/`manual`), confidence, needs_review, evidence JSON |
| `search_cache` | (store, item_name) | Tavily query, results, success, error |
| `embedding_cache` | (model, text) | float32 vector |
| `classified_data` | id | normalized_data columns + labels (rebuilt from a join every run) |

## Files

```
stage3_classification/
├── run.py          # CLI, wired into `python -m v2.main classify`
├── store.py        # ClassificationStore: the four tables above
├── taxonomy.py     # frozen taxonomy + old_data alias map
├── seed.py         # old_data.csv → item_labels
├── matcher.py      # prefix stripping, cached embeddings, neighbours, gate
├── search.py       # Tavily + cache
├── prompts.py      # LLM prompts
├── classifier.py   # structured Mistral call + review rules
├── eval.py         # held-out accuracy check
├── review/cli.py   # list / show / approve / set
└── tests/          # deterministic tests (fake embedding + Tavily clients)
```
