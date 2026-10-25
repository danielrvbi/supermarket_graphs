# Stage 3D — ingredients

Maps every product (`item_labels.item_name`) to a generic **ingredient**, so that store
products that are the same thing share one node: `JUMBO SPINAZIE GEWAS` (jumbo) and
`BIO SPINAZIE` → `espinaca`. Quantity, size and price play no part. Names are Spanish,
lowercase, singular, with no brand, bio, size or packaging. Non-food products get a
generic product name (`champú`) with `is_food=0`.

| Table | Purpose |
|-------|---------|
| `ingredient` | canonical names; `active=0` + `merged_into` once merged away |
| `product_ingredient` | one ingredient per product: `source` (`llm` · `manual` · `pending`), `needs_review`, `evidence` |
| `ingredient_change_log` | every manual operation (set, approve, rename, merge) |
| view `classified_ingredients` | `classified_v2` + `ingredient` / `is_food` |

Reads `item_labels` and the 3C tables (`product_category`, `subcategory`, `category`) and
changes neither.

## How assignment works

- **One LLM call per v2 subcategory.** All of the subcategory's products from both stores
  go in one prompt, in chunks of 60 if it is bigger. The model sees every variant together
  and groups them, so one food gets one name.
- Each prompt lists the ingredients already used in that category, and the model must
  reuse them.
- Names are matched to existing ingredients ignoring accents, case and plural endings
  (`Espinacas` = `espinaca`).
- Any other name creates a new ingredient. Its products are flagged `new_ingredient`.
  Medium or low confidence adds the flag `confidence`.
- Products the model leaves out, numbers it repeats, and failed calls all stay `pending`.
  They are retried on the next run.
- A run skips manual links and LLM links whose inputs are unchanged. The inputs are
  `producto_es`, store and v2 subcategory.
- The model is Mistral Large (`INGREDIENT_MODEL`, default `mistral-large-latest`). Tokens
  are tracked under the stage `ingredient_assign`.

A full run is about 103 calls, ~90k input + ~36k output tokens, roughly $0.30 on Large.

```bash
python -m v2.stage3d_ingredients.cli init                                   # tables + OVERRIDES
python -m v2.stage3d_ingredients.cli assign --dry-run --no-llm              # batches + estimate, no API
python -m v2.stage3d_ingredients.cli assign --dry-run --no-llm --max-subcategories 3 --show-prompt
python -m v2.stage3d_ingredients.cli assign --subcategory "Verduras > Lechuga y Ensaladas" --dry-run   # LLM, no writes
python -m v2.stage3d_ingredients.cli assign --subcategory "Verduras > Lechuga y Ensaladas"
python -m v2.stage3d_ingredients.cli assign --max-subcategories 5
python -m v2.stage3d_ingredients.cli status                                 # progress + tokens spent
python -m v2.stage3d_ingredients.cli show --subcategory "Verduras > Lechuga y Ensaladas"
python -m v2.stage3d_ingredients.cli show --shared                          # ingredients in both stores
python -m v2.stage3d_ingredients.cli list
python -m v2.stage3d_ingredients.cli set "OATLY" "leche de avena"
python -m v2.stage3d_ingredients.cli approve --subcategory "Verduras > Lechuga y Ensaladas"
python -m v2.stage3d_ingredients.cli merge "espinaca baby" espinaca --dry-run
python -m v2.stage3d_ingredients.cli rename "papa" "patata"
```

A live `assign` needs `--subcategory`, `--category`, `--max-subcategories N` or `--all`.
`--dry-run` calls the LLM but rolls everything back. Adding `--no-llm` skips the LLM as well.
