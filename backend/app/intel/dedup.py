"""Exact-duplicate detection via a Redis hash set (market-intel-pipeline.md §4.3). The
embedding-based near-dup (cosine >= 0.97) lives in M4b's cluster step."""
from app.intel.config import INTEL_HASH_TTL_H
from app.intel.normalize import text_hash


async def is_exact_duplicate(redis, text: str, ttl_h: int = INTEL_HASH_TTL_H) -> bool:
    """True if this exact text was seen within the TTL window; records it otherwise."""
    key = f"intel:hash:{text_hash(text)}"
    if await redis.exists(key):
        return True
    await redis.set(key, "1", ex=ttl_h * 3600)
    return False
