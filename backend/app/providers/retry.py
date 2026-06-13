import asyncio
import random
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")


class ProviderError(Exception):
    """Retryable upstream failure (timeout / 5xx / 429)."""


async def with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    attempts: int = 4,
    base: float = 0.5,
    cap: float = 8.0,
    retry_on: tuple[type[BaseException], ...] = (ProviderError, TimeoutError),
    sleep: Callable[[float], Awaitable] = asyncio.sleep,
    rng: Callable[[], float] = random.random,
) -> T:
    """Exponential backoff with full jitter. Retries only `retry_on`; re-raises the last."""
    last: BaseException | None = None
    for i in range(attempts):
        try:
            return await fn()
        except retry_on as e:  # type: ignore[misc]
            last = e
            if i == attempts - 1:
                break
            delay = min(cap, base * (2 ** i)) * rng()
            await sleep(delay)
    assert last is not None
    raise last
