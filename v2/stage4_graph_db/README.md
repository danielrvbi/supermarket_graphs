# Stage 4 — graph db

A small, clean db for graph ingestion, built from the processing db:

```
processed/processed_data.db   processing db: every stage's tables, caches, reviews, logs
        │  python -m v2.main graph-db   (read-only on the processing db)
        ▼
processed/graph.db            only the final, corrected data
```

`graph.db` is **rebuilt from scratch** every time and never edited by hand. To fix
something, fix it in the processing db (e.g. with the stage 3C / 3D CLIs) and rebuild.
The build writes `graph.db.building` and only replaces `graph.db` once every check
passes, so a failed build leaves the old file as it was.

## Tables

| Table | Rows (2026-10-31) | Content |
|---|---|---|
| `store` | 2 | `ah` Albert Heijn, `jumbo` Jumbo |
| `category` | 13 | v2 categories (3C) |
| `subcategory` | 110 | active v2 subcategories (3C) |
| `ingredient` | 372 | active ingredients (3D) that at least one bought product uses; `is_food` |
| `product` | 1,041 | one per (store, receipt name) that was bought: `item_name`, `name_es`, `subcategory_id`, `ingredient_id` |
| `receipt` | 722 | `id` (receipt id), store, `date`, `month`, `item_count`, `total` |
| `purchase` | 3,751 | one per receipt line: `product_id`, `quantity`, `unit` (`unit` or `kg`), `unit_price`, `total` |
| `build_info` | — | `built_at`, `source_db`, `git_commit`, `spend_total`, `count_<table>` |
| view `purchase_detail` | — | purchase joined with receipt, store, product, ingredient, subcategory, category |

- **Products are per store.** A receipt name bought in both stores becomes two
  products. AH and Jumbo meet at the shared `ingredient`.
- **Ids are kept from the processing db** for `category`, `subcategory` and `ingredient`.
  `purchase.id` is the `classified_data` id.
- **Weights are in kg.** The processing db labels them `weight_in_grams`, but the values
  are kilograms, so they are stored with `unit = 'kg'`.

**Left out:**
- the intermediate tables: `processed_data`, `normalized_data`, `classified_data`
- the v1 labels and `v1_map`
- the caches and the review tables
- the change logs, plus every evidence, confidence, source and needs-review column
- receipt file paths
- retired names
- products that were never bought

## Checks

The build stops, and leaves `graph.db` unchanged, if any of these fail:
- every purchase line has a v2 subcategory and an ingredient, both active
- every line has a known unit, a date and a total
- every receipt has one store and one date
- the purchase count, receipt count and total spend equal the processing db's
- every receipt total equals the sum of its lines

## Usage

```bash
python -m v2.main graph-db                          # processed/processed_data.db -> processed/graph.db
python -m v2.main graph-db --out /tmp/graph.db
python -m pytest v2/stage4_graph_db/tests -q        # no API calls
```

```sql
-- what each ingredient costs per store
SELECT ingredient, store, COUNT(*) AS purchases, ROUND(SUM(total), 2) AS spend
FROM purchase_detail WHERE is_food = 1
GROUP BY ingredient, store ORDER BY spend DESC LIMIT 20;
```
