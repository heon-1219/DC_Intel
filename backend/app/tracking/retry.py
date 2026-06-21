"""M7d outcome-grading retry/park state in Redis (win-loss-tracking.md §5.5/§5.6). Transient
price-unavailability defers with exponential backoff; after 8 attempts (or a split-suspect) the
prediction is PARKED (excluded from grading + metrics until an operator backfills). FAIL-OPEN: a
Redis blip must never block grading or falsely park — on error, treat as due / not-parked."""
import logging
import time

_LOG = logging.getLogger("dcintel.outcome")
BACKOFF_MINUTES = [5, 10, 20, 40, 80, 160, 320, 640]
MAX_ATTEMPTS = 8
_PARKED_SET = "outcome:parked"


def _key(pid) -> str:
    return f"outcome:retry:{pid}"


def _now(now: float | None) -> float:
    return time.time() if now is None else now


async def attempts_for(redis, pid) -> int:
    try:
        v = await redis.hget(_key(pid), "count")
        return int(v) if v else 0
    except Exception:   # noqa: BLE001
        return 0


async def record_attempt(redis, pid, now: float | None = None) -> int:
    try:
        key = _key(pid)
        n = await redis.hincrby(key, "count", 1)
        await redis.hset(key, "last", str(_now(now)))
        await redis.expire(key, 7 * 24 * 3600)
        return n
    except Exception:   # noqa: BLE001
        return 0


async def due_for_retry(redis, pid, now: float | None = None) -> bool:
    try:
        key = _key(pid)
        count = int(await redis.hget(key, "count") or 0)
        if count == 0:
            return True
        last = float(await redis.hget(key, "last") or 0)
        wait = BACKOFF_MINUTES[min(count - 1, len(BACKOFF_MINUTES) - 1)] * 60
        return (_now(now) - last) >= wait
    except Exception:   # noqa: BLE001 - fail-open: allow the attempt
        return True


async def park(redis, pid, reason: str) -> None:
    try:
        await redis.sadd(_PARKED_SET, pid)
    except Exception:   # noqa: BLE001
        pass
    _LOG.warning("outcome park: prediction=%s reason=%s", pid, reason)


async def is_parked(redis, pid) -> bool:
    try:
        return bool(await redis.sismember(_PARKED_SET, pid))
    except Exception:   # noqa: BLE001
        return False


async def unpark(redis, pid) -> None:
    try:
        await redis.srem(_PARKED_SET, pid)
    except Exception:   # noqa: BLE001
        pass


async def clear_retry(redis, pid) -> None:
    try:
        await redis.delete(_key(pid))
    except Exception:   # noqa: BLE001
        pass
