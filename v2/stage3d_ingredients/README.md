# Stage 3D — ingredients

Maps every product (`item_labels.item_name`) to a generic **ingredient**, so that store
products that are the same thing share one node: `JUMBO SPINAZIE GEWAS` (jumbo) and
`BIO SPINAZIE` → `espinaca`. Quantity, size and price play no part. Names are Spanish,
lowercase, singular, with no brand, bio, size or packaging. Non-food products get a
generic product name (`champú`) with `is_food=0`.

**`assign` never writes the db.** Each category gets a folder in `proposals/`
(gitignored, like `processed/`), and each subcategory becomes one JSONL file in it.
Once you have checked a file, `apply` writes it to the db and moves it to
`proposals/<category>/applied/`.

```
assign  ->  proposals/verduras/lechuga_y_ensaladas.jsonl  ->  (you check / edit)  ->  apply  ->  db
```

A live `assign` stops before going over `--budget`: $0.05 by default, estimated for each
subcategory before its call. See `HANDOFF.md` for the batch plan.

Each proposal line is one product, with these keys:
- `item_name`, `store`, `producto_es`, `category`, `subcategory`
- `ingredient`: editable. Set it to `null` to leave the product unassigned.
- `is_food`: editable.
- `llm_ingredient`: what the model said. Don't edit this one.
- `new`: whether the name didn't exist when it was proposed.
- `confidence`, `reasoning`, `model`, `pending`
- `inputs`: producto_es, store and v2 subcategory id at proposal time.

When `apply` reads a line:
- An unchanged line becomes `source=llm`.
- A line whose `ingredient` you edited becomes `source=manual`. Manual links are never
  overwritten.
- A line with `ingredient: null` is skipped and proposed again on the next `assign`.
- A product whose inputs changed since the proposal is skipped as stale.
- An invalid name aborts the whole file.

| Table | Purpose |
|-------|---------|
| `ingredient` | canonical names; `active=0` + `merged_into` once merged away |
| `product_ingredient` | one ingredient per product: `source` (`llm` · `manual`), `evidence` (inputs, model answer, proposal file) |
| `ingredient_change_log` | every apply / set / rename / merge |
| view `classified_ingredients` | `classified_v2` + `ingredient` / `is_food` |

Reads `item_labels` and the 3C tables (`product_category`, `subcategory`, `category`) and
changes neither.

## How proposals are made

- **One LLM call per v2 subcategory.** All of the subcategory's products from both stores
  go in one prompt, in chunks of 60 if it is bigger. The model sees every variant together
  and groups them, so one food gets one name.
- Each prompt lists the ingredients already known in that category, from the db, from
  other proposal files, and from earlier chunks. The model must reuse them.
- Names are matched ignoring accents, case and plural endings (`Espinacas` = `espinaca`).
- Products the model leaves out or lists twice get `ingredient: null` with a `pending`
  reason.
- If a call fails, no file is written, so the subcategory is retried on the next run.
- A run skips subcategories that already have a proposal file (unless `--redo`), manual
  links, and applied links whose inputs are unchanged.
- The model is Mistral Large (`INGREDIENT_MODEL`, default `mistral-large-latest`). Tokens
  are tracked under the stage `ingredient_assign`.

A full run is about 103 calls, roughly $0.20–0.30 on Large. The first live call, on
Lechuga y Ensaladas, cost $0.0039.

```bash
python -m v2.stage3d_ingredients.cli init                                   # tables + OVERRIDES
python -m v2.stage3d_ingredients.cli assign --dry-run --no-llm              # batches + estimate, no API
python -m v2.stage3d_ingredients.cli assign --dry-run --no-llm --max-subcategories 3 --show-prompt
python -m v2.stage3d_ingredients.cli assign --subcategory "Verduras > Lechuga y Ensaladas"   # -> JSONL
python -m v2.stage3d_ingredients.cli assign --subcategory "Verduras > Lechuga y Ensaladas" --redo
python -m v2.stage3d_ingredients.cli assign --max-subcategories 5
python -m v2.stage3d_ingredients.cli proposals                              # files waiting for review
python -m v2.stage3d_ingredients.cli review --subcategory "Verduras > Lechuga y Ensaladas"
python -m v2.stage3d_ingredients.cli apply --subcategory "Verduras > Lechuga y Ensaladas" --dry-run
python -m v2.stage3d_ingredients.cli apply --subcategory "Verduras > Lechuga y Ensaladas"
python -m v2.stage3d_ingredients.cli status                                 # db / proposed / todo + tokens spent
python -m v2.stage3d_ingredients.cli show --shared                          # ingredients in both stores (db)
python -m v2.stage3d_ingredients.cli set "OATLY" "leche de avena"
python -m v2.stage3d_ingredients.cli merge "espinaca baby" espinaca --dry-run
python -m v2.stage3d_ingredients.cli rename "papa" "patata"
```

A live `assign` needs `--subcategory`, `--category`, `--max-subcategories N` or `--all`.
`--dry-run` calls the LLM but writes no file. Adding `--no-llm` skips the LLM as well.
