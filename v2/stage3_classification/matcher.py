"""
Embedding similarity between receipt item names and already-labelled products.

Receipt names are abbreviations (AH truncates at ~12 chars), so similarity is used
to retrieve few-shot neighbours and to decide whether a web search is needed - not
as the final label. Store/brand prefixes are stripped before embedding because they
dominate short names without saying anything about the product type.

Measured on old_data (leave-one-out): top1 >= 0.80 with the top-3 neighbours agreeing
on category gives ~97% category accuracy; below that, ~63%.
"""

import re
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

import numpy as np

from v2.common.settings import settings
from v2.stage3_classification.store import ClassificationStore


PREFIX_RE = re.compile(r"\b(?:AH|ALBERT HEIJN|JUMBO|JUMBOS|JMB|BIO)\b")
EMBED_BATCH_SIZE = 128


def strip_prefixes(name: str) -> str:
    """'AH BIO KIPFI' -> 'KIPFI'. Returns the original name if nothing is left."""
    stripped = re.sub(r"\s+", " ", PREFIX_RE.sub("", name.upper())).strip()
    return stripped or name.upper().strip()


@dataclass
class Neighbour:
    """A labelled product similar to the item being classified."""
    item_name: str
    producto_es: Optional[str]
    category: str
    subcategory: str
    score: float

    def to_dict(self) -> Dict:
        return {**asdict(self), "score": round(self.score, 3)}


def passes_gate(neighbours: List[Neighbour], min_score: float = None) -> bool:
    """Confident match: best score >= min_score and the top-3 agree on category."""
    if min_score is None:
        min_score = settings.MATCH_GATE_SCORE
    if not neighbours or neighbours[0].score < min_score:
        return False
    return len({n.category for n in neighbours[:3]}) == 1


class Embedder:
    """Mistral embeddings with a SQLite cache (each text is embedded once per model)."""

    def __init__(self, db: ClassificationStore, model: str = None, client=None):
        self.db = db
        self.model = model or settings.EMBED_MODEL
        self._client = client
        self.api_calls = 0

    @property
    def client(self):
        if self._client is None:
            from langchain_mistralai import MistralAIEmbeddings

            if not settings.MISTRAL_KEY:
                raise ValueError("MISTRAL_KEY not set. Please add it to your .env file.")
            self._client = MistralAIEmbeddings(model=self.model, api_key=settings.MISTRAL_KEY)
        return self._client

    def embed(self, texts: List[str]) -> np.ndarray:
        """Return L2-normalised vectors, one row per text."""
        unique = list(dict.fromkeys(texts))
        vectors = self.db.get_embeddings(self.model, unique)

        missing = [t for t in unique if t not in vectors]
        for i in range(0, len(missing), EMBED_BATCH_SIZE):
            batch = missing[i:i + EMBED_BATCH_SIZE]
            new = dict(zip(batch, (np.asarray(v, dtype=np.float32)
                                   for v in self.client.embed_documents(batch))))
            self.api_calls += 1
            self.db.save_embeddings(self.model, new)
            vectors.update(new)

        matrix = np.stack([vectors[t] for t in texts]) if texts else np.zeros((0, 1))
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        return matrix / np.where(norms == 0, 1, norms)


class Matcher:
    """Nearest labelled products for new item names."""

    def __init__(self, labels: List[Dict], embedder: Embedder):
        self.labels = labels
        self.embedder = embedder
        self._index = embedder.embed([strip_prefixes(l["item_name"]) for l in labels])

    def neighbours(self, item_names: List[str], k: int = 5) -> List[List[Neighbour]]:
        """Top-k labelled neighbours for each item name, best first."""
        if not item_names or not self.labels:
            return [[] for _ in item_names]

        queries = self.embedder.embed([strip_prefixes(n) for n in item_names])
        scores = queries @ self._index.T

        results = []
        for name, row in zip(item_names, scores):
            top = np.argsort(-row)[: k + 1]
            hits = []
            for j in top:
                label = self.labels[j]
                if label["item_name"] == name:  # never match an item to itself
                    continue
                hits.append(Neighbour(
                    item_name=label["item_name"],
                    producto_es=label.get("producto_es"),
                    category=label["category"],
                    subcategory=label["subcategory"],
                    score=float(row[j]),
                ))
            results.append(hits[:k])
        return results
