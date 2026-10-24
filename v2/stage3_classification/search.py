"""
Tavily product search with a permanent SQLite cache.

Every (store, item_name) is searched at most once: results - including failures -
are stored in search_cache and returned from there on later runs. Pass
retry_failed=True to re-query items whose earlier search errored or found nothing.

A search succeeds only if the store's site returns a product page. Otherwise the
whole web is searched once; those results are passed to the LLM as unverified
context and the item is flagged for review.
"""

from typing import Dict, List

from v2.common.settings import settings
from v2.stage3_classification.matcher import strip_prefixes
from v2.stage3_classification.store import ClassificationStore


# store -> (name used in the query, supermarket website)
STORE_SITES = {
    "ah": ("Albert Heijn", "ah.nl"),
    "jumbo": ("Jumbo", "jumbo.com"),
}
MAX_RESULTS = 3
MAX_CONTENT_CHARS = 500


def is_product_page(url: str) -> bool:
    """ah.nl/producten/... and jumbo.com/producten/... (product or product-category pages)."""
    url = (url or "").lower()
    return any(f"{domain}/producten/" in url for _, domain in STORE_SITES.values())


class ProductSearch:
    """Look up what a receipt abbreviation is on the supermarket's own website."""

    def __init__(self, db: ClassificationStore, client=None):
        self.db = db
        self._client = client
        self.api_calls = 0
        self.cache_hits = 0

    @property
    def client(self):
        if self._client is None:
            from tavily import TavilyClient

            if not settings.TAVILY_KEY:
                raise ValueError(
                    "Tavily key not set. Add TAVILY_API_KEY (or TAVILY_KEY) to your .env file,\n"
                    "or run with --no-search."
                )
            self._client = TavilyClient(api_key=settings.TAVILY_KEY)
        return self._client

    def search(self, store: str, item_name: str, retry_failed: bool = False) -> Dict:
        """
        Search for a product, using the cache when possible.

        Returns:
            {"query", "success", "results": [{url, title, content}], "cached": bool}
        """
        cached = self.db.get_search(store, item_name)
        if cached and (cached["success"] or not retry_failed):
            self.cache_hits += 1
            return {
                "query": cached["query"],
                "success": cached["success"],
                "results": cached["results"],
                "cached": True,
            }

        store_name, domain = STORE_SITES.get(store, (store, None))
        query = f"{store_name} {strip_prefixes(item_name)}"

        try:
            # Only the store's product pages count as a hit; its other pages (about us,
            # offers, recipes) come back for nonsense queries and say nothing about the item.
            results = [r for r in self._search(query, [domain] if domain else None)
                       if is_product_page(r["url"])]
            success, error = bool(results), None
            if not results:
                # Widen to the whole web once; shown to the LLM but not trusted
                results = self._search(query, None)
                error = "no product page on store site"
        except Exception as e:  # network/quota errors are cached too, retry with --retry-failed-search
            results, success, error = [], False, str(e)[:500]

        self.db.save_search(store, item_name, query, success, results, error)
        return {"query": query, "success": success, "results": results, "cached": False}

    def _search(self, query: str, include_domains) -> List[Dict]:
        self.api_calls += 1
        response = self.client.search(
            query=query,
            search_depth="basic",
            max_results=MAX_RESULTS,
            include_domains=include_domains,
            include_answer=False,
        )
        return [
            {
                "url": r.get("url"),
                "title": r.get("title"),
                "content": (r.get("content") or "")[:MAX_CONTENT_CHARS],
            }
            for r in response.get("results", [])
        ]
