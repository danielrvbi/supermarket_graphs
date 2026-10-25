# Stage 3C — v2 taxonomy

A redesigned category/subcategory taxonomy (see `PROPOSAL.md`) kept in **new tables**
next to the v1 labels. `item_labels` and `classified_data` are never modified; v2 labels
reference products by `item_name` and are filled by a re-runnable sync.

| Table | Purpose |
|-------|---------|
| `category`, `subcategory` | v2 taxonomy (`subcategory.active=0` once merged away) |
| `product_category` | one v2 label per product: `subcategory_id`, `source`, `needs_review`, `synced_from` |
| `v1_map` | v1 (category, subcategory) → v2 subcategory; several rows = split |
| `taxonomy_change_log` | every taxonomy operation and how many products it touched |
| view `classified_v2` | `classified_data` + `category_v2` / `subcategory_v2` |

`source`: `map` (1:1 from v1) · `split_llm` (LLM picked among the split candidates) ·
`pending_split` (no subcategory yet) · `manual` (set by hand, never overwritten by sync).

```bash
python -m v2.stage3c_taxonomy.cli init                 # once: tables from seed_v2.py
python -m v2.stage3c_taxonomy.cli sync --dry-run       # what would be mapped / split
python -m v2.stage3c_taxonomy.cli sync --no-llm        # map 1:1, store splits as pending
python -m v2.stage3c_taxonomy.cli sync                 # map 1:1, LLM resolves splits
python -m v2.stage3c_taxonomy.cli show --counts
python -m v2.stage3c_taxonomy.cli list                 # flagged v2 labels
python -m v2.stage3c_taxonomy.cli set "KIK SOY SAUC" Despensa "Salsas del Mundo"
python -m v2.stage3c_taxonomy.cli approve "KIK SOY SAUC"
python -m v2.stage3c_taxonomy.cli rename Frutas Bayas "Frutos Rojos" --dry-run
```

Sync skips manual labels and labels whose `synced_from` still equals the product's v1
label, so re-running only handles new products and changed v1 labels. Splits are sent
to Mistral in batches of 25 per v1 label; the model can only choose among that label's
candidates. Low or medium confidence, or a v1 review flag, sets `needs_review`.

Labels point to subcategory ids: `rename` and `move` change one row, `merge` repoints
products and `v1_map`, `split` adds subcategories and flags the products in the source.
