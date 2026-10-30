# Stage 3D Ingredient Labeling — Handoff

## Purpose

Give every product (`item_labels.item_name`, 1,067 products) one generic **ingredient**. A store
product that is the same food in AH and Jumbo should share a node in a future graph DB:
`JUMBO SPINAZIE GEWAS` (jumbo) and `AH SPINAZIE` (ah) → `espinaca`. Quantity, size and price
play no part.

We work **one category at a time**, a few subcategories per batch, with the user
reviewing every batch. A category is written to the db only once it is consistent. Then
we move on to the next category.

Read `README.md` in this folder for the code and file format. This file covers **how to
run it**.

> **Status (2026-10-30): done.** All 1,067 products are linked in the db to 372 active
> ingredient names (300 food, 72 non-food). 142 of those names have products from both
> stores. All review decisions are settled and applied.
>
> - **Next step:** graph export (not started).
> - **Archive:** the applied proposal files and the review (`reviews/DECISIONS.md`,
>   `corrections.json`, the category reports, `OPEN_DECISIONS.md`) were moved to
>   `processed/audits/stage3d_ingredients_2026-10/` (gitignored). Paths below that say
>   `proposals/` or `reviews/` refer to that archive now.
> - **db backups:** `processed/processed_data.before_ingredients_apply_*.db` and
>   `processed/processed_data.before_open_decisions_*.db`.
>
> The rest of this file is the history of how the work was run.

---

## Ground rules for the agent

1. **Never write the db unless the user explicitly says so.** `assign` only writes JSONL
   files in `proposals/`. `apply` is the only command that writes the db, and it needs
   the user's OK for each category.
2. **Never run a live `assign` without a selector.** Always pass `--category`, plus
   `--max-subcategories N` or `--subcategory`. Never use `--all`.
3. **Never `--redo` without asking.** A redo costs an LLM call and overwrites a file the
   user may have edited by hand. Check the file's modification time first.
4. **Don't edit the JSONL unless the user approves the specific edits.** Only change the
   `ingredient` and `is_food` fields. Never touch `llm_ingredient` or `inputs`, because
   apply uses them to detect edits and stale lines.
5. **Don't commit** unless asked. The `proposals/` folder is gitignored because it holds
   personal purchase data.
6. **Report the cost of every batch.** `status` prints the total spent under stage
   `ingredient_assign`.
7. **Use the project venv:** `.venv/bin/python`.

---

## Decisions already made (don't re-ask)

| Topic | Decision |
|---|---|
| Granularity | Generic food. Drop brand, bio/orgánico, size, pack, marketing variants, cuisine/style words, cooking method (para saltear/horno/wok), preparation (picada/rallada), add-ins and parentheses. At most 4 words. |
| Language | Spanish, lowercase, singular (`espagueti`, `lechuga iceberg`) |
| Non-food | Generic product name with `is_food=false` (`champú`, `bolsa de basura`) |
| Batching | **One LLM call per v2 subcategory**, with both stores in the same prompt. The prompt also lists the names already used in the category: from the db, from other proposal files, and from earlier chunks. |
| Model | Mistral Large (`INGREDIENT_MODEL=mistral-large-latest`). About $0.004 per subcategory, ~$0.22 for everything. |
| Kept apart on purpose | Pasta shapes (`espagueti`, `penne`, `fusilli`…), `verduras para sopa`, `hutspot`, `lechuga iceberg` vs `lechuga mantequilla`. A recipe asks for these by name. |
| Review | The JSONL file is the review. Applied links get `needs_review=0`. An edited `ingredient` becomes `source=manual`. |

---

## Layout

```
proposals/                        gitignored (personal purchase data)
  verduras/                       one folder per v2 category
    tomate.jsonl                  one file per subcategory, waiting for review
    applied/tomate.jsonl          moved here by `apply` once written to the db
  frutas/ ...
```

## Cost control

- Every live `assign` has `--budget` (default **$0.05**). It estimates each
  subcategory's call before making it, and stops before the one that would go over.
  The output then says `stopped by --budget … before <subcategory>`; run again to continue.
- Estimates have been accurate within about 20%. Batch 1 was estimated at $0.041 and cost $0.033.
- Check actual spend with `status`, or with the SQL at the bottom of this file.

## Batch plan

Running and reviewing are separate steps. A batch only writes JSONL; review happens
later, one category at a time (the loop below). Estimates are free with
`assign --dry-run --no-llm --category C`.

| Batch | Categories | Subcats | Est. | Status |
|---|---|---|---|---|
| 1 | Verduras (rest) + Frutas | 10 + 6 | $0.041 | **done**, $0.033 |
| 2 | Despensa (rest) | 15 | $0.040 | **done**, $0.042 |
| 3 | Lácteos y Huevos + Carnes y Pescado | 13 + 9 | $0.059 | **done**, $0.058 |
| 4 | Panadería + Bebidas | 8 + 7 | $0.045 | **done** |
| 5 | Snacks + Dulces + Comida Preparada | 4 + 5 + 1 | $0.024 | **done** |
| 6 | Cuidado Personal y Salud + Limpieza y Lavandería + Hogar (non-food) | 10 + 4 + 8 | $0.053 | **done** (batches 4–6 together: $0.096) |

**Open decisions applied (2026-10-30).** All 47 groups are settled (see `reviews/DECISIONS.md`).
- The db now has **372 active names**: 300 food and 72 non-food. 142 of them are shared by both stores.
- There are 167 manual links.
- D8 was kept as it was.

**Applied (2026-10-29).** Every proposal file has been applied and moved to `proposals/<category>/applied/`.
- `product_ingredient` has **1,067 links**: 922 `llm` and 145 `manual`, none missing and none flagged.
- `ingredient` has **397 active names**: 326 food and 71 non-food. **139** of them are shared by AH and Jumbo.
- `classified_ingredients` gives an ingredient to all 3,751 purchase rows.
- db backup from before the apply: `processed/processed_data.before_ingredients_apply_20261029_235323.db`.
- Later fixes go through `set` / `merge` / `rename`, all of which are logged.

The open decision groups in `reviews/<category>.md` can still be settled that way.

**Review done (2026-10-29).** An OpenCode agent reviewed all 103 files and wrote 258 suggestions
to `reviews/corrections.json`. The user's decisions are in `reviews/DECISIONS.md`, and the
**142 approved changes have been written into the proposal JSONLs**. They will apply as manual
links. Still open: the decision groups in the category reports, `reviews/<category>.md`. Next step:
`apply --category <C> --dry-run`, then `apply`, one category at a time, with the user's OK.

**All 1,067 products in 103 subcategories are proposed.** No more LLM runs are needed
unless a fix needs a `--redo`. What remains is review and apply, one category at a time
(the loop below; skip its steps 1–2).

Run a batch one category at a time, with `--max-subcategories` covering the whole
category and a budget a little above its estimate:
```bash
.venv/bin/python -m v2.stage3d_ingredients.cli assign --category Despensa --max-subcategories 15 --budget 0.05
```
Keep the full output (e.g. `> batchN_<category>.log`), then report the following to the user:
- files written
- any `!` errors
- products left without an ingredient
- the spend

## Current state (2026-10-25)

- The db tables `ingredient` and `product_ingredient` exist and are **empty**. Nothing
  has been applied.
- LLM spend so far: 103 calls, 127,926 input + 34,029 output tokens, **$0.241**.
- The proposals hold **439 distinct names**. **144** of them have products from both stores.
- The 3 products the model left without an ingredient were filled in by hand in their
  JSONL. They will apply as manual links:
  - `K&M ANANAS` → `piña`
  - `GI BASILICO` → `salsa de albahaca`
  - `HERTOG JAN` → `cerveza pilsner`

| Category | Files | Notes |
|---|---|---|
| Verduras | 12/12 proposed | `lechuga_y_ensaladas` was edited by the user; the other 11 are unreviewed. 11 names are marked too specific (see below). |
| Frutas | 6/6 proposed | Unreviewed. `K&M ANANAS` got no ingredient (`duplicate_id`): set it to `piña`. |
| Despensa | 16/16 proposed | Unreviewed. `GI BASILICO` got no ingredient (`missing`). Notes below. |
| Lácteos y Huevos | 13/13 proposed | Unreviewed. 121 products, 45 new names. Notes below. |
| Carnes y Pescado | 9/9 proposed | Unreviewed. 117 products, 48 new names. Notes below. |
| Panadería | 8/8 proposed | Unreviewed. Notes below. |
| Bebidas | 7/7 proposed | Unreviewed. Notes below. |
| Snacks | 4/4 proposed | Unreviewed. Variants of `papa frita` and `totopo`. |
| Dulces | 5/5 proposed | Unreviewed. Notes below. |
| Comida Preparada | 1/1 proposed | Unreviewed. 4 products. |
| Cuidado Personal y Salud | 10/10 proposed | Unreviewed. Notes below. |
| Limpieza y Lavandería | 4/4 proposed | Unreviewed. Looks clean (21 generic names). |
| Hogar | 8/8 proposed | Unreviewed. Notes below. |

**Verduras, to review** (from `review --category Verduras`):
- **Too specific:**
  - Mezclas de Verduras (old prompt). Suggested:
    - `ROERBAK *`, `BASISMIX ITA`, `GROENTEMIX`, `WOKGROENTE`, `OVENGRO COURG PAPRIK` and `AH OVENGROEN` → `mezcla de verduras`
    - `HUTSPOT` products → `hutspot`
    - keep `verduras para sopa`
  - Papas: `papa con mantequilla de hierbas`, `papa con tocino y cebolla`,
    `papa congelada en rodajas`, `papa preparada`. Decide between plain `papa` and one
    prepared-potato name.
  - `mezcla de brócoli y coliflor`: marked only because it has 5 words. Decide whether to keep it.
- **Variants to settle:**
  - `tomate` vs `tomate cherry` / `tomate en rama` / `tomate roma` / `tomate snack`
  - `maíz en grano` vs `mazorca de maíz`
  - `pimiento rojo` / `pimiento amarillo` / `pimiento verde` vs a single `pimiento`
- **Frutas** looks clean: 18 generic names, one per fruit. The only gap is pineapple.

**Despensa, to review** (from `review --category Despensa`):
- **Too specific:**
  - `aceite de oliva en spray` → `aceite de oliva`
  - `crema de cacao y avellanas` → `crema de avellanas` (they duplicate each other; Nutella)
  - `salsa para horno`
  - `sopa de tomate con albóndigas` → `sopa de tomate`
- **Variants to settle:**
  - `arroz` vs `arroz para risotto` / `arroz para sushi` / `arroz precocido`
  - `cuscús` vs `cuscús perlado`
  - `mayonesa` vs `mayonesa con trufa`
  - `mostaza` vs `mostaza verde`
  - `ravioli` vs `ravioli de champiñones`
  - `cilantro molido` vs `cilantro seco`
  - `frijol negro` vs `frijol negro untable`
- **Vague names:**
  - `salsa casera`
  - `condimento líquido` (probably Maggi)
  - `base para sopa`
  - `especias`
  - `sazonador`
- **Suspicious:** `pasta con trufa` sits in Salsas para Pasta, so it is probably a truffle sauce or paste.
- **Cross-category:** `queso parmesano` (Salsas para Pasta) and `ajo` (Sal y Especias)
  should match the Lácteos and Verduras names. Exact-key matches link globally, but the
  prompt only shows names from its own category, so check Lácteos for `parmesano` vs
  `queso parmesano`.

**Lácteos y Huevos, to review:**
- **Too specific:**
  - `leche de avena con cacao`
  - `queso crema con ajo y hierbas` → `queso crema`
  - `mantequilla con hierbas`
  - `yogur de fresa`
- **Cheese granularity:**
  - Gouda has `queso gouda` / `joven` / `maduro` / `rallado`.
  - Also: `queso jersey maduro`, `queso old amsterdam`, `queso polderkaasje`, `queso con especias`.

  Decide on one rule, e.g. `queso gouda` for every Dutch matured cheese and `queso rallado` for grated.
- **Grated forms** (`mozzarella rallada`, `grana padano rallado`, `queso gouda rallado`):
  the prompt says to drop preparation words, but these slipped through.
- **Translation errors:**
  - `JUMBO WITTE KAAS PL` → `queso blanco vegetal`. It is white (young) cheese slices, not vegan.
  - `BEEMSTER PUMPKIN SPI` → `queso con especias`.
- **Cross-category mismatch:** Lácteos has `parmesano`, Despensa has `queso parmesano`.
  Pick one. The two spellings have different keys, so they would not link.
- Milk: `leche semidesnatada sin lactosa` vs `leche sin lactosa`, and `leche para café`.

**Carnes y Pescado, to review:**
- **Too specific:**
  - `carne de cerdo en cubos`
  - `carne de res en cubos`
  - `pechuga de pollo en cubos`
  - `tocino en cubos`
  - `jamón cocido en bloque` / `en cubos`
  - `albóndiga para sopa`
- **Translation error:** `JOHN W TONIJNST WTR` → `agua con sabor a atún`. It is John West tuna
  chunks in water, so it should be `atún en conserva`. Also merge `atún en aceite` into it.
- **Ground meat:** `carne molida` vs `de res` / `de pollo` / `mixta`. Keep the meat type
  (a recipe asks for it), and decide what plain `carne molida` means.
- `chorizo` appears in both Cerdo and Embutidos, which is fine (same name).
- `rosbif` sits under Embutidos y Fiambres.

**Panadería:**
- `focaccia con ajo` / `con mozzarella` / `con pimiento` / `con romero` → `focaccia`
- `baguette con cebolla` → `baguette`
- `pan duro` vs `pan de ayer`
- `hotcake` vs `mezcla para hotcakes`
- `mezcla para poffertjes` appears in both Despensa and Panadería (same name, fine)

**Bebidas:**
- **Too specific:**
  - `refresco de cola sin azúcar` → `refresco de cola`
  - `refresco de cítricos sin azúcar`
  - `refresco de sandía y lima`
  - `refresco de mojito sin alcohol` and `mojito sin alcohol` (one name for both)
  - `jugo de naranja y mango`
  - `jugo de frutas recién exprimido`
  - `café molido o en grano` → `café`
- **Beer:** 10 names
  - `cerveza rubia` / `rubia fuerte` / `pilsner` / `ipa` / `de trigo` / `negra` / `artesanal` / `rosada` / `con cereza` / `con limón`
  - Decide whether to keep beer styles or use one `cerveza`.
- `té orgánico` breaks the no-bio rule.

**Dulces:**
- `barrita de chocolate con galleta`, `barrita de galleta con crema de avellanas` and
  `chocolate con almendras y miel` are too specific
- `chocolate` vs `tableta de chocolate` vs `chocolate con avellanas`
- `sorbete` vs `sorbete de limón`

**Cuidado Personal y Salud:**
- `AH POEDER` → `proteína en polvo` and `LUCOVITAAL` → `suplemento vitamínico` have
  `is_food=true`. Decide whether supplements count as food.
- `analgésico naproxeno` → `naproxeno`
- `champú y acondicionador`
- `toallitas húmedas` vs `toallitas húmedas para bebé`

**Hogar:**
- `alimento para gatos` / `alimento para perros` have `is_food=true`. Pet food should
  probably be `false` (not human food).
- `bolsa de basura grande` / `mediana` / `pequeña` / `orgánica` / `sanitaria` / `para reciclaje`:
  the size words break the "no size" rule, so use `bolsa de basura` (perhaps keeping `orgánica`)
- `pila aa` / `pila aaa` / `pila cr2032`: decide whether to keep the battery sizes
- `bandeja para horno` was marked too specific only by the "para horno" pattern. It is fine.

**Across categories:** the prompt only shows names from the same category, so the same
food can get different names in different categories. Known case: `parmesano` (Lácteos) vs
`queso parmesano` (Despensa). Before applying, scan `review --category` for each category
alongside the others. Overlaps found so far: `ajo`, `mezcla para poffertjes`.

**Pasta, open questions:**
- `STM PASTA` → tagliatelle is based only on the Spanish name. Check it.
- Pasta stays at shape level, and spelling is mixed (Spanish `espagueti`, Italian `penne`).

### Categories

| # | Category | Subcats | Products |
|---|---|---|---|
| 1 | Verduras | 12 | 131 |
| 2 | Frutas | 6 | 60 |
| 3 | Despensa | 16 | 172 |
| 4 | Lácteos y Huevos | 13 | 121 |
| 5 | Carnes y Pescado | 9 | 117 |
| 6 | Panadería | 8 | 93 |
| 7 | Bebidas | 7 | 131 (Cerveza = 52, the biggest subcategory) |
| 8 | Snacks | 4 | 45 |
| 9 | Dulces | 5 | 29 |
| 10 | Comida Preparada | 1 | 4 |
| 11 | Cuidado Personal y Salud | 10 | 63 (non-food) |
| 12 | Limpieza y Lavandería | 4 | 39 (non-food) |
| 13 | Hogar | 8 | 62 (non-food) |

Run `status` for the live numbers. In its output, `prop` counts products in proposal
files and `todo` counts products not proposed yet.

---

## The loop: one category

All commands start with `.venv/bin/python -m v2.stage3d_ingredients.cli`.

### 1. Preview the category (free, no API call)
```bash
.venv/bin/python -m v2.stage3d_ingredients.cli assign --dry-run --no-llm --category Verduras
```
This shows the subcategories still to do, their sizes, the names already known, and the
estimated cost. Tell the user how many batches are left.

### 2. Run a batch of 2–3 subcategories (writes JSONL only)
```bash
.venv/bin/python -m v2.stage3d_ingredients.cli assign --category Verduras --max-subcategories 3 --budget 0.02
```
This picks the next 3 subcategories of the category that don't have a proposal file yet,
makes one LLM call each, and writes one JSONL each to `proposals/verduras/`. Use `--subcategory "C > S"` to run
one specific subcategory.

### 3. Review the batch with the user
Show the grouped output from the assign run, or run
`review --subcategory "C > S"`. Check each file against this list:

- **Cross-store sharing:** the same food from AH and Jumbo has one name.
- **Too specific:** lines marked `[TOO SPECIFIC]` (parentheses, "para saltear/horno/wok…",
  more than 4 words), cuisine or flavour words, single-product names that are really a
  variant of a bigger group.
- **Too broad:** different foods merged under one name, e.g. `queso` for both mozzarella
  and gouda.
- **Translation errors:** `producto_es` is wrong, but the Dutch receipt name says
  otherwise (e.g. `AH KOOL PEEN` is cabbage and carrot, not "col rallada").
- **Reuse:** a name that already exists in another file of the category was not reused
  (`new: true` when it shouldn't be).
- **Non-food:** `is_food` is correct.
- **Products with no ingredient** (`pending: missing / duplicate_id`): propose a name.

Give the user a **table of suggested corrections** (products → current → suggested). Apply
only the edits they approve, editing the `ingredient` field in the JSONL.

If the **same problem shows up in two or more subcategories**, propose a rule change to
`prompts.py` (`INGREDIENT_SYSTEM_PROMPT`: a rule or a wrong → right example). Once the user
agrees, change it, and `--redo` a subcategory only if the user asks.

### 4. Repeat steps 2–3 until the category has `todo = 0`
```bash
.venv/bin/python -m v2.stage3d_ingredients.cli status
```

### 5. Consistency pass over the whole category
```bash
.venv/bin/python -m v2.stage3d_ingredients.cli review --category Verduras
```
This prints every file of the category, then **names across files** (which subcategories
use each name), then **possible duplicates**, where one name is contained in another
(`'lechuga iceberg' < 'lechuga iceberg con maíz y rábanos'`). Settle each duplicate with
the user: rename or merge by editing the JSONL lines.

### 6. Apply the category (only with the user's explicit OK)
```bash
.venv/bin/python -m v2.stage3d_ingredients.cli apply --category Verduras --dry-run
.venv/bin/python -m v2.stage3d_ingredients.cli apply --category Verduras
.venv/bin/python -m v2.stage3d_ingredients.cli show --shared
```
Applied files move to `proposals/<category>/applied/`. Report what apply printed:
- lines applied as llm
- edited lines, which become manual
- unassigned lines
- stale lines, which mean the product changed since it was proposed and will be proposed again

Note: applied names become the vocabulary for the next categories. That is one reason
to apply a category before starting the next.

### 7. Next category
Update the **Current state** table in this file (category status, spend), then go back
to step 1.

---

## Fixing things after apply

Use these only when the user asks. Each is logged in `ingredient_change_log`.
```bash
.venv/bin/python -m v2.stage3d_ingredients.cli set "AH KOOL PEEN" "mezcla de col y zanahoria"   # manual link
.venv/bin/python -m v2.stage3d_ingredients.cli merge "mezcla de lechugas" "ensalada mixta" --dry-run
.venv/bin/python -m v2.stage3d_ingredients.cli rename "papa" "patata" --dry-run
.venv/bin/python -m v2.stage3d_ingredients.cli list                  # every link in the db
.venv/bin/python -m v2.stage3d_ingredients.cli log
```

## Useful checks
```bash
.venv/bin/python -m v2.stage3d_ingredients.cli proposals             # files waiting for review
.venv/bin/python -m pytest v2/stage3d_ingredients/tests -q            # 21 tests, no API
sqlite3 -readonly processed/processed_data.db "SELECT COUNT(*) FROM product_ingredient"
sqlite3 -readonly v2/checkpoints/token_usage.db \
  "SELECT file_path, input_tokens, output_tokens, total_cost_usd FROM token_usage WHERE stage='ingredient_assign'"
```

## Pitfalls seen so far

- **The model reports "high" confidence for almost everything.** Don't rely on
  confidence; read the groups.
- **Mixes and dish products drift into flavour or method names.** The prompt now forbids
  this and the `too_specific` marker catches what slips through, but check them anyway.
- **The model trusts `producto_es` too much.** Check against the Dutch receipt name.
- **Names come from unapplied files too.** A bad name in an unreviewed file can be
  offered to the next prompt. Names marked too specific are filtered out, other bad
  names are not. This is another reason to fix files before running more of the same
  category.
