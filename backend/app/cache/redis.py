from typing import Any

import redis.asyncio as aioredis

from app.config import get_settings


def get_client() -> aioredis.Redis:
    return aioredis.from_url(get_settings().redis_url, decode_responses=True)


async def ping(client) -> bool:
    try:
        return bool(await client.ping())
    except Exception:
        return False


def make_envelope(data: Any, *, source: str, data_as_of: str, is_stale: bool,
                  cache: str, request_id: str) -> dict:
    """The canonical {data, meta} response envelope (backend-design.md §12)."""
    return {
        "data": data,
        "meta": {"source": source, "data_as_of": data_as_of, "is_stale": is_stale,
                 "cache": cache, "request_id": request_id},
    }
