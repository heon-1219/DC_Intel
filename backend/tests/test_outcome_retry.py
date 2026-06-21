"""M7d Redis retry/park state (win-loss §5.5/§5.6): exponential backoff, park after 8, fail-open."""
import fakeredis.aioredis
import pytest

from app.tracking import retry as rt


def _r():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


class _Broken:
    async def hget(self, *a, **k):
        raise ConnectionError("down")

    async def sismember(self, *a, **k):
        raise ConnectionError("down")


@pytest.mark.asyncio
async def test_first_attempt_is_due():
    assert await rt.due_for_retry(_r(), 1, now=1000.0) is True


@pytest.mark.asyncio
async def test_backoff_schedule():
    r = _r()
    await rt.record_attempt(r, 1, now=1000.0)                       # count 1 -> wait 5 min
    assert await rt.due_for_retry(r, 1, now=1000.0 + 299) is False
    assert await rt.due_for_retry(r, 1, now=1000.0 + 300) is True
    await rt.record_attempt(r, 1, now=1300.0)                       # count 2 -> wait 10 min
    assert await rt.due_for_retry(r, 1, now=1300.0 + 599) is False
    assert await rt.due_for_retry(r, 1, now=1300.0 + 600) is True


@pytest.mark.asyncio
async def test_attempts_count_and_park():
    r = _r()
    for i in range(8):
        await rt.record_attempt(r, 5, now=1000.0 + i)
    assert await rt.attempts_for(r, 5) == 8
    await rt.park(r, 5, "max_retries")
    assert await rt.is_parked(r, 5) is True
    assert await rt.is_parked(r, 6) is False


@pytest.mark.asyncio
async def test_clear_retry_resets():
    r = _r()
    await rt.record_attempt(r, 9, now=1.0)
    await rt.clear_retry(r, 9)
    assert await rt.attempts_for(r, 9) == 0


@pytest.mark.asyncio
async def test_fail_open_on_redis_error():
    b = _Broken()
    assert await rt.due_for_retry(b, 1) is True      # never block grading on a Redis blip
    assert await rt.is_parked(b, 1) is False
