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

Sync skips manual labels and automatic labels whose recorded inputs are unchanged.
Evidence contains a versioned `sync_inputs` snapshot of the v1 category, subcategory,
Spanish product name, store, and review flag; `synced_from` remains available. Correcting
an identity input refreshes the assignment, including a corrected Spanish name within
the same v1 category. Splits are sent to Mistral in batches of 25 per v1 label, constrained
to that label's candidates. Missing picks stay pending and are retried on later syncs.

Review-flag-only changes update metadata without LLM calls. `review_reasons` records
upstream review flags, low/medium model confidence, pending splits, and taxonomy splits,
so clearing one reason cannot clear another. `approve` records approval of the current
identity and assignment in evidence. That approval survives upstream review-flag changes;
identity changes or a taxonomy split invalidate it. Manual labels remain protected.

There is no schema migration. Existing automatic labels without input snapshots are
refreshed once by the next sync (split labels may require LLM calls, or become pending
with `--no-llm`). Historical approvals without evidence cannot be reconstructed; manually
set labels are preserved. A new explicit approval also establishes the input snapshot.
Metadata-only updates contribute to the existing rows-written count.

Labels point to subcategory ids: `rename` and `move` change one row, `merge` repoints
products and `v1_map`, `split` adds subcategories and flags the products in the source.
