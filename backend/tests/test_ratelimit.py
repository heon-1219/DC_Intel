"""M6k Redis fixed-window rate limiter (backend-design AUTH §5). Fail-open; respects
rate_limit_enabled. `now` is injected for deterministic window math."""
import fakeredis.aioredis
import pytest

from app.auth import ratelimit as rl


def _redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


class _BrokenRedis:
    async def incr(self, *a, **k):
        raise ConnectionError("down")

    async def get(self, *a, **k):
        raise ConnectionError("down")

    async def expire(self, *a, **k):
        raise ConnectionError("down")


@pytest.mark.asyncio
async def test_hit_allows_until_limit_then_blocks():
    r = _redis()
    for i in range(1, 4):     # limit 3
        allowed, remaining, _ = await rl.hit(r, "predict_user", "42", limit=3, window_sec=60, now=1000.0)
        assert allowed is True and remaining == 3 - i
    blocked, rem, retry = await rl.hit(r, "predict_user", "42", limit=3, window_sec=60, now=1000.0)
    assert blocked is False and rem == 0 and retry > 0


@pytest.mark.asyncio
async def test_hit_window_rolls_over():
    r = _redis()
    for _ in range(3):
        await rl.hit(r, "s", "id", limit=3, window_sec=60, now=1000.0)
    blocked, _, _ = await rl.hit(r, "s", "id", limit=3, window_sec=60, now=1000.0)
    assert blocked is False
    fresh, _, _ = await rl.hit(r, "s", "id", limit=3, window_sec=60, now=1075.0)   # next window
    assert fresh is True


@pytest.mark.asyncio
async def test_over_limit_after_recorded_failures():
    r = _redis()
    for _ in range(3):
        await rl.record_failure(r, "login_ip", "1.2.3.4", window_sec=900, now=1000.0)
    blocked, retry = await rl.over_limit(r, "login_ip", "1.2.3.4", limit=3, window_sec=900, now=1000.0)
    assert blocked is True and retry > 0
    ok, _ = await rl.over_limit(r, "login_ip", "9.9.9.9", limit=3, window_sec=900, now=1000.0)
    assert ok is False                # different identity unaffected


@pytest.mark.asyncio
async def test_fail_open_when_redis_down():
    allowed, _, _ = await rl.hit(_BrokenRedis(), "s", "id", limit=1, window_sec=60, now=1000.0)
    blocked, _ = await rl.over_limit(_BrokenRedis(), "s", "id", limit=1, window_sec=60, now=1000.0)
    assert allowed is True and blocked is False    # never block on Redis failure


@pytest.mark.asyncio
async def test_disabled_is_noop(monkeypatch):
    from app.config import get_settings
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    try:
        r = _redis()
        for _ in range(10):
            allowed, _, _ = await rl.hit(r, "s", "id", limit=1, window_sec=60, now=1000.0)
            assert allowed is True
    finally:
        get_settings.cache_clear()      # don't leak the disabled setting to other tests


def test_sha1_email_is_case_insensitive():
    assert rl.sha1_email("FOO@x.com") == rl.sha1_email("foo@x.com")
