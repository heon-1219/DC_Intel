import fakeredis.aioredis
import pytest

from app.intel.dedup import is_exact_duplicate


@pytest.mark.asyncio
async def test_exact_duplicate_detection():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    assert await is_exact_duplicate(r, "To the moon $AAPL") is False   # first sighting
    assert await is_exact_duplicate(r, "to  the  moon  $aapl!!!") is True  # same after norm
    assert await is_exact_duplicate(r, "totally different post") is False
