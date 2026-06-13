import pytest

from app.providers.retry import ProviderError, with_retry


@pytest.mark.asyncio
async def test_retries_then_succeeds():
    slept = []
    calls = {"n": 0}

    async def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ProviderError("flaky")
        return "ok"

    async def fake_sleep(d):
        slept.append(d)

    out = await with_retry(fn, sleep=fake_sleep, rng=lambda: 1.0)
    assert out == "ok"
    assert calls["n"] == 3
    assert slept == [0.5, 1.0]  # base*2^0, base*2^1 with full jitter rng=1.0


@pytest.mark.asyncio
async def test_exhausts_and_raises():
    async def fn():
        raise ProviderError("always")

    async def fake_sleep(d):
        return None

    with pytest.raises(ProviderError):
        await with_retry(fn, attempts=2, sleep=fake_sleep, rng=lambda: 0.0)


@pytest.mark.asyncio
async def test_non_retryable_propagates_immediately():
    calls = {"n": 0}

    async def fn():
        calls["n"] += 1
        raise ValueError("boom")

    async def fake_sleep(d):
        return None

    with pytest.raises(ValueError):
        await with_retry(fn, retry_on=(ProviderError,), sleep=fake_sleep)
    assert calls["n"] == 1
