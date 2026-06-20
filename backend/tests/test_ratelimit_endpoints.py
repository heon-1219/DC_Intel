"""M6k throttles wired into the routers (backend-design AUTH §5): login brute-force + register abuse."""
import pytest


@pytest.mark.asyncio
async def test_login_brute_force_429_after_10_failures(app_client):
    async with app_client as c:
        await c.post("/auth/register", json={"email": "u@x.com", "password": "Tr0ubadour9x"})
        for _ in range(10):
            r = await c.post("/auth/login", json={"email": "u@x.com", "password": "WrongPass9"})
            assert r.status_code == 401
        blocked = await c.post("/auth/login", json={"email": "u@x.com", "password": "WrongPass9"})
    assert blocked.status_code == 429 and blocked.json()["error"]["code"] == "RATE_LIMITED"
    assert blocked.headers.get("Retry-After")


@pytest.mark.asyncio
async def test_register_abuse_429_after_5(app_client):
    async with app_client as c:
        for i in range(5):
            r = await c.post("/auth/register", json={"email": f"u{i}@x.com", "password": "Tr0ubadour9x"})
            assert r.status_code == 201
        blocked = await c.post("/auth/register", json={"email": "u6@x.com", "password": "Tr0ubadour9x"})
    assert blocked.status_code == 429 and blocked.json()["error"]["code"] == "RATE_LIMITED"
