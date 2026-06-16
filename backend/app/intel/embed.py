"""MiniLM embeddings + cosine + Redis vector cache (market-intel-pipeline.md §5.1).
sentence-transformers is lazy-imported so the offline suite (which injects fakes / uses
synthetic vectors) never loads model weights. Vectors are cached as a JSON float list (our
Redis client runs decode_responses=True, so raw-bytes storage isn't usable here)."""
import json
import math

from app.intel.config import EMBED_MODEL


def cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class MiniLMEmbedder:
    name = "minilm"

    def __init__(self, model_name: str = EMBED_MODEL):
        self.model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # lazy: heavy
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        vecs = self._load().encode(texts, normalize_embeddings=True)
        return [list(map(float, v)) for v in vecs]


async def cache_embedding(redis, intel_id: int, vec: list[float], ttl_h: int = 48) -> None:
    await redis.set(f"intel:emb:{intel_id}", json.dumps(vec), ex=ttl_h * 3600)


async def get_cached_embedding(redis, intel_id: int) -> list[float] | None:
    raw = await redis.get(f"intel:emb:{intel_id}")
    return json.loads(raw) if raw else None
