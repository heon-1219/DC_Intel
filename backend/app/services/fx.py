_KEY = "px:fx:USDKRW"
_TTL_S = 300


async def get_usdkrw(redis, fx_provider) -> float | None:
    """USD->KRW rate from cache, or fetch + cache (5-min TTL). None if unavailable."""
    raw = await redis.get(_KEY)
    if raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    try:
        rate = await fx_provider.fetch_usdkrw()
    except Exception:  # noqa: BLE001 - FX is best-effort; callers handle None
        return None
    await redis.set(_KEY, str(rate), ex=_TTL_S)
    return rate
