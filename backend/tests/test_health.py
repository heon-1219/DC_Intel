import pytest


@pytest.mark.asyncio
async def test_healthz_ok(app_client):
    async with app_client as c:
        r = await c.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["checks"]["sqlite"] is True
    assert body["checks"]["redis"] is True


@pytest.mark.asyncio
async def test_healthz_degraded_when_redis_down(app_client, monkeypatch):
    import app.cache.redis as cache_redis

    class Broken:
        async def ping(self):
            raise ConnectionError("down")

    monkeypatch.setattr(cache_redis, "get_client", lambda: Broken())
    async with app_client as c:
        r = await c.get("/healthz")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert body["checks"]["redis"] is False
    assert body["checks"]["sqlite"] is True
