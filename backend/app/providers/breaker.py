class CircuitBreaker:
    """Minimal Redis circuit breaker. Opens after `threshold` failures within the
    cooldown window; auto half-opens when the open key expires (cooldown_s)."""

    def __init__(self, redis, *, threshold: int = 5, cooldown_s: int = 60):
        self.redis = redis
        self.threshold = threshold
        self.cooldown_s = cooldown_s

    async def is_open(self, source: str) -> bool:
        return bool(await self.redis.exists(f"cb:{source}:open"))

    async def record_failure(self, source: str) -> None:
        fails = await self.redis.incr(f"cb:{source}:fails")
        await self.redis.expire(f"cb:{source}:fails", self.cooldown_s)
        if fails >= self.threshold:
            await self.redis.set(f"cb:{source}:open", "1", ex=self.cooldown_s)

    async def record_success(self, source: str) -> None:
        await self.redis.delete(f"cb:{source}:fails", f"cb:{source}:open")
