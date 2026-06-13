import pytest
import fakeredis.aioredis

from app.cache.redis import make_envelope, ping


@pytest.mark.asyncio
async def test_ping_ok():
    r = fakeredis.aioredis.FakeRedis()
    assert await ping(r) is True


@pytest.mark.asyncio
async def test_ping_false_on_error():
    class Broken:
        async def ping(self):
            raise ConnectionError("down")
    assert await ping(Broken()) is False


def test_envelope_shape():
    env = make_envelope({"price": 100}, source="yfinance",
                        data_as_of="2026-06-13T00:00:00Z", is_stale=False,
                        cache="hit", request_id="req_1")
    assert env["data"] == {"price": 100}
    assert env["meta"] == {"source": "yfinance", "data_as_of": "2026-06-13T00:00:00Z",
                           "is_stale": False, "cache": "hit", "request_id": "req_1"}
