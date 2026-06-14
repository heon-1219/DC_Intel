import fakeredis.aioredis
import pytest

from app.providers.retry import ProviderError
from app.services.fx import get_usdkrw


class FakeFx:
    def __init__(self, rate=None, error=None):
        self.rate = rate
        self.error = error
        self.calls = 0

    async def fetch_usdkrw(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.rate


@pytest.mark.asyncio
async def test_get_usdkrw_fetches_and_caches():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    fx = FakeFx(rate=1378.2)
    assert await get_usdkrw(r, fx) == 1378.2
    assert await r.get("px:fx:USDKRW") == "1378.2"
    assert await get_usdkrw(r, fx) == 1378.2 and fx.calls == 1  # 2nd call hits cache


@pytest.mark.asyncio
async def test_get_usdkrw_none_on_failure():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    fx = FakeFx(error=ProviderError("down"))
    assert await get_usdkrw(r, fx) is None
