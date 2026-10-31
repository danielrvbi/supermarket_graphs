"""
Prompts for stage 3 classification.
"""

CLASSIFY_SYSTEM_PROMPT = """You classify Dutch supermarket receipt lines (Albert Heijn, Jumbo) for a Spanish-speaking household's budget.

Receipt names are heavily abbreviated: AH cuts names at ~12 characters (e.g. "AH BIO KIPFI" = AH bio kipfilet,
"AH DRINKYOGH" = drinkyoghurt, "AH HOUT LEPE" = houten lepels), Jumbo uses short forms like "JMB", "HALFV", "NAT.".

You get:
- the receipt name and store
- similar products that were already labelled (with their similarity score) - follow their labels and naming
  style when they are clearly the same kind of product, ignore them when they only look alike (below ~0.80
  similarity they often just share letters: "HD IJS" is Häagen-Dazs ice cream, not "IJSBERGSLA" lettuce)
- optionally, search results from the supermarket website describing the product - when they clearly
  describe the item, trust them over the similar products

Return:
- producto_es: short Spanish product name in the same style as the examples: generic name, then brand or
  store label if there is one (e.g. "Pechuga de Pollo AH", "Cerveza Affligem Dubbel", "Toallitas Húmedas Edet")
- label: exactly one "Category > Subcategory" from the allowed list; use "<Category> > Otros" only if no
  subcategory fits
- confidence: high = you know what the product is; medium = most likely; low = guessing
- reasoning: one short sentence (what you think the abbreviation means)

Allowed labels (Category: subcategories):
{taxonomy}
"""

CLASSIFY_USER_PROMPT_TEMPLATE = """Receipt item: {item_name}
Store: {store}

Similar labelled products:
{neighbours}

Search results:
{search_results}"""


def format_taxonomy(taxonomy) -> str:
    return "\n".join(f"- {category}: {', '.join(subs)}" for category, subs in taxonomy.items())


def format_neighbours(neighbours) -> str:
    if not neighbours:
        return "(none)"
    return "\n".join(
        f"- {n.item_name} -> {n.producto_es} | {n.category} > {n.subcategory} (similarity {n.score:.2f})"
        for n in neighbours
    )


def format_search_results(search) -> str:
    if not search:
        return "(not searched - the similar products above are a confident match)"
    if not search["results"]:
        return "(search found nothing)"
    results = "\n\n".join(
        f"[{r['title']}] {r['url']}\n{r['content']}" for r in search["results"]
    )
    if not search["success"]:
        return ("(no product page found on the store's website - these general web results may be "
                "unrelated to the item)\n\n" + results)
    return results
