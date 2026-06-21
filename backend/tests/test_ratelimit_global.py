"""M8c — global per-IP / per-user rate-limit middleware (backend-design §4.1/§4.3)."""
import pytest

_PATH = "/dashboard/market-intel"   # non-exempt, optional-auth, returns 200 with empty data


@pytest.mark.asyncio
async def test_allowed_response_carries_ratelimit_headers(app_client):
    async with app_client as c:
        r = await c.get(_PATH)
    assert r.status_code == 200
    assert r.headers["x-ratelimit-limit"] == "100"
    assert int(r.headers["x-ratelimit-remaining"]) == 99


@pytest.mark.asyncio
async def test_ip_limit_trips_429(app_client, monkeypatch):
    monkeypatch.setattr("app.core.middleware.GLOBAL_IP_PER_MIN", 2)
    async with app_client as c:
        s1 = await c.get(_PATH)
        s2 = await c.get(_PATH)
        s3 = await c.get(_PATH)
    assert s1.status_code == 200 and s2.status_code == 200
    assert s3.status_code == 429
    assert s3.json()["error"]["code"] == "RATE_LIMITED"
    assert "retry-after" in {k.lower() for k in s3.headers}


@pytest.mark.asyncio
async def test_healthz_is_exempt(app_client, monkeypatch):
    monkeypatch.setattr("app.core.middleware.GLOBAL_IP_PER_MIN", 1)
    async with app_client as c:
        a = await c.get("/healthz")
        b = await c.get("/healthz")
    assert a.status_code != 429 and b.status_code != 429
    assert "x-ratelimit-limit" not in a.headers   # exempt paths carry no limiter headers


@pytest.mark.asyncio
async def test_disabled_bypasses(app_client, monkeypatch):
    monkeypatch.setattr("app.core.middleware.GLOBAL_IP_PER_MIN", 1)
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    from app.config import get_settings
    get_settings.cache_clear()
    try:
        async with app_client as c:
            r1 = await c.get(_PATH)
            r2 = await c.get(_PATH)
            r3 = await c.get(_PATH)
        assert r1.status_code == 200 and r2.status_code == 200 and r3.status_code == 200
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_user_limit_trips_with_valid_token(app_client, monkeypatch):
    monkeypatch.setattr("app.core.middleware.GLOBAL_USER_PER_MIN", 1)
    async with app_client as c:
        reg = await c.post("/auth/register",
                           json={"email": "rl@x.com", "password": "Tr0ubadour9x"})
        token = reg.json()["data"]["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        u1 = await c.get(_PATH, headers=h)
        u2 = await c.get(_PATH, headers=h)
    assert reg.status_code == 201
    assert u1.status_code == 200 and u2.status_code == 429
    assert u2.json()["error"]["code"] == "RATE_LIMITED"
