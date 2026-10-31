# Prompt: review the stage 3D ingredient proposals (OpenCode + explore subagents)

Copy everything below the line into a new OpenCode session started in the repo root
(`supermkt/`).

---

You are reviewing **ingredient proposals** for a supermarket-receipt pipeline. Every
product bought at Albert Heijn (`ah`) or Jumbo (`jumbo`) has been given one generic
Spanish **ingredient** name by Mistral Large, so that the same food from both stores
becomes one node in a future graph DB. Example: `JUMBO SPINAZIE GEWAS` (jumbo) and
`AH SPINAZIE` (ah) → `espinaca`.

Your job is to **find wrong or inconsistent names and propose corrections.** You are a
reviewer, not an editor. The user decides, and a later session applies the decisions.

## Read first (main agent, yourself)

1. `v2/stage3d_ingredients/HANDOFF.md`: the decisions already made, plus per-category
   notes from a first quick look. Those notes are a starting point, not the full review.
2. `v2/stage3d_ingredients/prompts.py`: the exact naming rules the model was given.
   These are the standard to check against.
3. `v2/stage3d_ingredients/README.md`: the JSONL line format (skim it).

## Hard rules

- **Read-only on the data.**
  - Do not edit, move or delete anything in `v2/stage3d_ingredients/proposals/`.
  - Do not touch `processed/processed_data.db` (read-only queries only, e.g. `sqlite3 -readonly`).
- **Don't run these:**
  - no `assign` (it calls a paid API)
  - no `apply`, `set`, `merge` or `rename` (they write the db)
  - no `git commit`
- **Write only inside `v2/stage3d_ingredients/reviews/`.** This folder is gitignored
  because it holds personal purchase data.
- **Don't decide taste questions.** Where the naming rules don't settle a case, list it
  under "Decisions needed" with the options and your recommendation. Examples: beer
  styles vs a single `cerveza`, or `queso gouda joven` vs `queso gouda`. Don't put those
  in the corrections file.
- Use the project interpreter, `.venv/bin/python`, if you run Python.

## The data

- `v2/stage3d_ingredients/proposals/<category>/<subcategory>.jsonl`: 13 category
  folders, 103 files, 1,067 lines in total. Each line is one product.
- The fields that matter for review:

| Field | Meaning |
|---|---|
| `item_name` | the Dutch receipt text, abbreviated; often the most reliable clue |
| `producto_es` | the Spanish product name from an earlier stage; **sometimes a bad translation** |
| `store` | `ah` or `jumbo` |
| `category`, `subcategory` | the product's v2 category and subcategory |
| `ingredient` | the proposed name; this is what you review |
| `llm_ingredient` | what the model said. If it differs from `ingredient`, the user already edited the line, so treat that line as decided. |
| `is_food` | `true`/`false`. The 3 non-food categories should be `false`. |
| `new`, `confidence`, `reasoning`, `too_specific` | hints. `confidence` is almost always "high", so don't trust it. `too_specific: true` means a regex flagged the name. |

Readable overview of one category (grouped by ingredient, with a cross-file name list
and possible duplicates at the end):
```bash
.venv/bin/python -m v2.stage3d_ingredients.cli review --category "Verduras"
```

Category names, as used by `--category`, with folder and size:

| `--category` | Folder | Files | Products |
|---|---|---|---|
| Verduras | verduras | 12 | 131 |
| Frutas | frutas | 6 | 60 |
| Despensa | despensa | 16 | 172 |
| Lácteos y Huevos | lacteos_y_huevos | 13 | 121 |
| Carnes y Pescado | carnes_y_pescado | 9 | 117 |
| Panadería | panaderia | 8 | 93 |
| Bebidas | bebidas | 7 | 131 |
| Snacks | snacks | 4 | 45 |
| Dulces | dulces | 5 | 29 |
| Comida Preparada | comida_preparada | 1 | 4 |
| Cuidado Personal y Salud | cuidado_personal_y_salud | 10 | 63 (non-food) |
| Limpieza y Lavandería | limpieza_y_lavanderia | 4 | 39 (non-food) |
| Hogar | hogar | 8 | 62 (non-food) |

## Review checklist

Check every line against these.

1. **Wrong food.** The ingredient doesn't match the product. Check `item_name` (Dutch)
   against `producto_es` (Spanish). Known example: `JOHN W TONIJNST WTR` (John West tuna
   chunks in water) became `agua con sabor a atún`, but it should be `atún en conserva`.
   Useful Dutch: *tonijn* tuna, *kaas* cheese, *witte kaas* young white cheese,
   *kip* chicken, *rund* beef, *varken* pork, *gehakt* minced meat, *sla* lettuce,
   *kool* cabbage, *peen/wortel* carrot, *ui* onion, *aardappel* potato, *zuivel* dairy,
   *roerbak* stir-fry, *soep* soup, *saus* sauce, *ontbijt* breakfast, *volkoren*
   wholemeal, *pils* lager.
2. **Too specific** (breaks the rules in `prompts.py`). Look for:
   - brand, bio/orgánico, size or pack
   - cuisine or flavour words
   - cooking use (`para saltear/horno/wok`)
   - cut or preparation (`en cubos`, `rallado`, `en tiras`, `en bloque`, `en spray`)
   - add-ins (`con …`)
   - parentheses, or more than 4 words

   Suggest the broader name.
3. **Too broad.** Different foods merged under one name, e.g. mozzarella and gouda both
   under `queso`.
4. **Same food, different names.** Within a category, and **across categories**: the model
   only saw names from the current category. Known example: `parmesano` (Lácteos y Huevos)
   vs `queso parmesano` (Despensa). Also check spelling and singular/plural variants.
5. **Cross-store sharing missed.** An AH product and a Jumbo product that are the same
   food but got different names.
6. **`is_food` wrong.**
   - Food categories should be `true`.
   - Cleaning, personal care and household items should be `false`.
   - Pet food and supplements are a decision for the user. List them under "Decisions needed".
7. **Format.** Not Spanish, not lowercase, plural where singular is expected, or a typo.

Don't report lines that are fine. Don't re-report edited lines
(`ingredient != llm_ingredient`) unless they are clearly wrong.

## How to split the work (explore subagents)

Use OpenCode's **explore** subagent (Task tool, `subagent_type: explore`) for the
per-category reading. Run them **at most 3 at a time**. Explore agents are read-only, so
**they report back to you and you write the files.**

| Agent | Scope |
|---|---|
| 1 | Verduras |
| 2 | Frutas + Comida Preparada |
| 3 | Despensa: the first 9 files alphabetically (`aceite_y_vinagre` … `harina_y_reposteria`) |
| 4 | Despensa: the last 7 files (`mermeladas_y_untables` … `sopas`) |
| 5 | Lácteos y Huevos |
| 6 | Carnes y Pescado |
| 7 | Panadería + Snacks + Dulces |
| 8 | Bebidas |
| 9 | Cuidado Personal y Salud + Limpieza y Lavandería + Hogar |

Prompt for each subagent (fill in the scope):

```text
Read-only review task. Do not modify any file.
Repo: the current directory. Read these files completely:
  v2/stage3d_ingredients/prompts.py  (the naming rules; the standard to check against)
  v2/stage3d_ingredients/proposals/<folder>/<file>.jsonl  for: <SCOPE>
Each JSONL line is one supermarket product with fields item_name (Dutch receipt text),
producto_es (Spanish name, sometimes mistranslated), store, subcategory, ingredient
(proposed generic Spanish name — what you review), llm_ingredient, is_food.
Check every line for: wrong food (compare the Dutch item_name with producto_es), too specific
(brand, bio, size, flavour, cuisine, cooking use, cut/preparation such as "en cubos"/"rallado",
"con ...", parentheses, >4 words), too broad, the same food under different names (also AH vs
Jumbo), wrong is_food, non-Spanish/plural/typos. Skip lines where ingredient != llm_ingredient
(already edited by the user) unless clearly wrong. Do not report lines that are fine.
Return ONLY:
1. CORRECTIONS: one per line, pipe-separated:
   file | item_name | store | producto_es | current ingredient | suggested ingredient | is_food (true/false) | kind | certainty (high/medium) | reason (short)
   kind is one of: wrong_food, too_specific, too_broad, duplicate_name, missed_share, is_food, format
2. DECISIONS NEEDED: granularity questions the rules don't settle (e.g. beer styles, cheese
   ages): the question, the names and item_names involved, options, your recommendation.
3. ALL NAMES: every distinct ingredient name in your scope with its product count.
```

## Your own work after the subagents return

1. Go through each subagent's corrections. Spot-check anything surprising by reading the
   line yourself, and drop corrections you don't agree with.
2. **Cross-category pass (yourself):** merge the "ALL NAMES" lists and look for the same
   food under different names in different categories (`parmesano` / `queso parmesano`,
   `ajo` in Verduras and Despensa is fine). For each pair, pick one canonical spelling and
   suggest corrections for the other side. This is the check no subagent can do.
3. Write the outputs below.

## Output (where the review goes)

Write everything in **`v2/stage3d_ingredients/reviews/`**:

| File | Content |
|---|---|
| `SUMMARY.md` | Totals: lines reviewed, corrections by kind and by category, decisions needed. List the top 10 most important fixes, and give your view of overall quality. |
| `<folder>.md` (one per category, e.g. `verduras.md`) | Three parts. **Decisions needed:** each with options and a recommendation. **Corrections:** a table with columns subcategory, item_name, store, producto_es, current, suggested, kind, certainty, reason. **Notes.** |
| `cross_category.md` | Names that differ across categories for the same food, the canonical spelling chosen, and the lines affected. |
| `corrections.json` | **Every** correction, machine-readable, so a later session can apply the approved ones. See the format below. |

`corrections.json` format, a JSON array:
```json
[
  {
    "file": "carnes_y_pescado/pescado_y_mariscos.jsonl",
    "item_name": "JOHN W TONIJNST WTR",
    "store": "jumbo",
    "current": "agua con sabor a atún",
    "suggested": "atún en conserva",
    "is_food": true,
    "kind": "wrong_food",
    "certainty": "high",
    "reason": "John West tuna chunks in water (tonijnstukken in water), not flavoured water"
  }
]
```
`file` is relative to `v2/stage3d_ingredients/proposals/`. `item_name` must match the
JSONL exactly, because it identifies the line. Only include corrections that follow from
the rules. Granularity choices go in the "Decisions needed" sections, not here.

## When you're done

Reply with a short summary:
- the number of corrections, by kind
- the decisions needed
- the paths of the files you wrote
- anything you were unsure about

Don't apply anything.
