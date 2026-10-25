# Taxonomy revamp: draft proposal

Draft for review. Numbers are **distinct products** (`item_labels`) from the real DB on
2026-10-25; `~` marks estimates for groups that don't exist yet. Guideline (not a hard rule):
**a subcategory should have about 3+ products**, unless purchases justify it (e.g. Frijoles:
3 products, 50 purchases). Otherwise it goes into a sibling or `Otros`.
Anything more specific than that (Naranja vs Mandarina, Gouda vs Edam) becomes the
**ingredient** in the next phase, not a subcategory.

Legend for how each line gets there:
- `=` unchanged · `mv` whole subcategory moves (automatic) · `merge` (automatic)
- `split` products must be assigned one by one (LLM limited to the new children, then review)

## Today: 1,067 products, 11 categories, 127 subcategories
- 27 subcategories have ≤2 products (Vino, Naranja, Algodón, Barritas, Frutos Secos, …).
- Some are overloaded: Queso 66, Pan 54, Cerveza 52, Salsas 39, Condimentos 31.
- About 120 food products sit in **Hogar** (Salsas, Condimentos, Cereal, Frijoles, …).
- Categories that mix things: Frutas & Verduras (fruit and veg are different recipe roles),
  Pasta/Sopas (really pantry).

## Proposed: 13 categories, about 95 subcategories

**Bebidas**: Cerveza 52 `=` · Refresco 27 `=` · Jugo 17 `=` · Agua 14 `=` ·
Té y Café 11 `merge` · Bebidas de Chocolate 7 `rename` · Vino y Cócteles 3 `merge` · Otros

**Carnes y Pescado** (`rename` Carnes): Pollo ~25 · Res ~16 · Carne Molida ~26
(`split` the molida items out of Res and Pollo) · Hamburguesas y Albóndigas ~10 `split` ·
Cerdo 11 · Jamón 18 · Embutidos 6 · Pescado y Mariscos 10 (Atún + Pescado `merge`) ·
Otros (Vegetariana 2 `merge`)

**Frutas** (new): Plátano 9 · Manzana 14 · Bayas ~10 (Fresa + Frambuesa + arándanos/zarzamoras) ·
Cítricos ~8 (Limón, Naranja, Mandarina, Pomelo) · Frutas Tropicales ~8 (Mango, Piña, Aguacate…) ·
Otras Frutas ~10 (Pera, Uvas, Sandía, Nectarina, fruit salad) · Fruta Seca 3

**Verduras** (new): Lechuga y Ensaladas ~30 (Lechuga + salad mixes + Espinaca) · Tomate 15 ·
Papas 15 · Zanahoria 9 · Cebolla y Ajo 8 · Mezclas para Saltear ~18 · Verduras Snack ~5 ·
Brócoli y Coliflor ~6 · Pepino y Calabacín 7 · Maíz 5 · Pimientos y Chiles ~4 ·
Otros (Champiñones, Brotes, Ejotes, Hierbas Frescas: 2 each)

**Lácteos y Huevos** (`rename`): Queso Madurado ~30 (Gouda, Old Amsterdam, Beemster, Manchego…) ·
Queso Rallado ~12 · Queso Fresco y Crema ~12 · Mozzarella ~8 · Queso Italiano y Feta ~10 ·
Leche 7 · Leche Deslactosada 6 · Leche Vegetal 10 · Yogur 11 · Crema 10 · Mantequilla 4 ·
Huevos 7 · Otros (leche condensada)

**Panadería**: Pan de Molde y Barra ~30 · Panecillos ~14 · Baguette ~5 (`split` of Pan) ·
Pan Dulce 14 · Focaccia 8 · Hotcakes y Repostería 6 · Tortilla 5 ·
Pan para Hamburguesa y Hotdog 3 `merge` · Otros

**Despensa** (new; takes Pasta/Sopas and the food from Hogar):
Pasta 24 · Arroz y Granos 13 · Fideos Instantáneos 5 · Sopas 6 · Cereales y Avena 15 ·
Salsas para Pasta ~22 · Aderezos ~8 (ketchup, mayo, mostaza) · Salsas del Mundo ~9 (soya,
worcestershire, mexicanas) · Especias y Hierbas Secas ~15 · Caldos y Sazonadores ~10 · Sal 4 ·
Harina y Repostería ~7 (harina, azúcar, vainilla, bicarbonato) · Aceite y Vinagre 5 ·
Conservas y Legumbres ~11 (Frijoles + both Conservas `merge`) · Mermeladas y Untables ~9 · Otros

**Dulces**: Chocolate 10 · Postres 7 · Helado 6 · Galletas y Pasteles 5 `merge` · Golosinas 4 · Otros

**Snacks**: Papas Fritas 19 · Totopos 11 · Dips 9 · Botanas y Palomitas 7 `merge` · Otros

**Comida Preparada** (new): pizza, sándwiches, pollo asado, rollitos (~5).

**Cuidado Personal y Salud** (Higiene + Salud `merge`): Pañuelos 14 · Papel Higiénico 10 ·
Higiene Femenina 6 · Toallitas 6 · Cabello 5 · Jabón 5 · Dental 4 · Afeitado 4 ·
Medicamentos 7 · Otros (Suplementos 2)

**Limpieza y Lavandería** (new, out of Hogar): Lavavajillas y Platos ~9 · Limpiadores ~15 ·
Lavandería 12 · Ambientador 3

**Hogar** (non-food only): Bolsas de Basura ~20 · Bolsas Reutilizables ~7 ·
Desechables de Cocina 10 · Utensilios de Cocina 8 · Baterías 6 · Mascotas 3 · Papelería 3 ·
Otros (velas, plantas, ropa)

## Mislabels found while exploring (fix during the splits)
- About 8 ground-beef items are labelled Carnes > Res and 2 ground-chicken items Carnes > Pollo.
- Hogar > Salsas has "Pasta Italiana con Salsa Boloñesa"-style names: these are probably jars
  of pasta sauce (Dutch *pastasaus* mistranslated), so the label is right but the name is wrong.
- "Semillas de Sésamo" is in Fruta Seca; "Mezcla de Semillas" is in Condimentos.
- "Untable de frijoles negros" appears in both Hogar > Frijoles and Snacks > Dips.
- "Sirope de Caramelo" is in Dulces > Untables.

## Decisions (2026-10-25)
- The ≥3 products guideline is a judgement call, not a hard rule.
- Frutas and Verduras become separate categories.
- Comida Preparada and Limpieza y Lavandería become separate categories.
- The new taxonomy goes in **new tables**, alongside the old labels. `item_labels.category /
  subcategory` stays untouched as the v1 history; new labels reference products by
  `item_name` and are re-synced, never replacing what exists.

## Implementation plan

### Data model (new tables in processed_data.db)
```
category(id, name, position)
subcategory(id, category_id, name, position, active)
product_category(item_name PK -> item_labels, subcategory_id -> subcategory,
                 source, confidence, needs_review, evidence, synced_from, updated_at)
v1_map(old_category, old_subcategory, subcategory_id NULL, split_into JSON NULL)
taxonomy_change_log(op, payload, items_affected, applied_at)
view classified_v2: classified_data + new category/subcategory through product_category
```
- Labels point to `subcategory_id`, so renames and moves change one row and no labels.
  A merge repoints `subcategory_id`; a split flags the affected products.
- `synced_from` stores the v1 pair the label was derived from, so a later sync can tell
  "old label changed, re-map" apart from "already done".
- `source`: `map` (1:1 from v1), `split_llm`, `manual`. A sync never overwrites `manual`.

### Steps
1. **Rework stage 3c onto the new tables.** The `taxonomy_*` tables built earlier were never
   created in the real DB. Replace them with the tables above, make the ops write
   `product_category` instead of relabelling `item_labels`, and drop the alias table (IDs
   make it unnecessary). `taxonomy.py` goes back to the v1 seed so the classifier keeps
   producing v1 labels for now.
2. **Write the new tree as a seed file** (`v2/stage3c_taxonomy/seed_v2.py`, built from this
   proposal) plus the `v1_map`: for each of the 127 old pairs, either one new subcategory
   (move/merge/rename) or a list of candidate children (split).
3. **`sync` command:** for each product in `item_labels`, look up its v1 pair in `v1_map`.
   - 1:1 → write `product_category` (source=map).
   - split → the LLM picks among only the candidate children (existing Mistral client,
     cached), source=split_llm, needs_review below the confidence threshold.
   - Skip products whose label is manual or whose `synced_from` matches the current v1 label.
   Idempotent, with `--dry-run` and `--no-llm` (flags splits instead of calling the LLM).
4. **Review:** `list` / `set` / `approve` commands for `product_category`, same style as
   stage 3b. Fix the mislabels listed above here.
5. **Hook into the pipeline:** run `sync` after `classify`, so new receipts get v2 labels.
   Later (separate step), switch the classifier to output v2 directly and freeze v1.

### Verification
- After sync: every `item_labels` row has a `product_category` row; no active subcategory is
  empty unless intended; `item_labels` and `classified_data` are byte-for-byte unchanged.
- Spend per new category from `classified_v2` adds up to the same total as `classified_data`.
- Unit tests on a temp DB: map, split, manual not overwritten, re-sync after a v1 label
  change, rename/merge through IDs.
- Run the first sync on a copy of the DB, review the split results, then on the real DB.
