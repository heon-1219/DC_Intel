"""M6d auth router (backend-design AUTH §4) — register (auto-login) + login, via the real app."""
import pytest

from app.auth.security import decode_token


@pytest.mark.asyncio
async def test_register_happy_path(app_client):
    async with app_client as c:
        r = await c.post("/auth/register",
                         json={"email": "New@X.com", "password": "Tr0ubadour9x", "language": "ko"})
    assert r.status_code == 201
    d = r.json()["data"]
    assert d["token_type"] == "bearer" and d["expires_in"] == 86400
    assert d["user"]["email"] == "new@x.com" and d["user"]["language"] == "ko"
    assert "password_hash" not in d["user"]
    assert decode_token(d["access_token"])["sub"] == str(d["user"]["id"])   # auto-login token valid


@pytest.mark.asyncio
async def test_register_duplicate_409(app_client):
    async with app_client as c:
        await c.post("/auth/register", json={"email": "d@x.com", "password": "Tr0ubadour9x"})
        r = await c.post("/auth/register", json={"email": "D@x.com", "password": "Another9pass"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "EMAIL_TAKEN"


@pytest.mark.asyncio
async def test_register_bad_password_422(app_client):
    async with app_client as c:
        r = await c.post("/auth/register", json={"email": "b@x.com", "password": "password1"})
    body = r.json()
    assert r.status_code == 422 and body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["details"]["fields"]                  # carries which field failed


@pytest.mark.asyncio
async def test_login_success(app_client):
    async with app_client as c:
        await c.post("/auth/register", json={"email": "l@x.com", "password": "Tr0ubadour9x"})
        r = await c.post("/auth/login", json={"email": "L@x.com", "password": "Tr0ubadour9x"})
    assert r.status_code == 200 and r.json()["data"]["access_token"]


@pytest.mark.asyncio
async def test_login_wrong_password_and_unknown_email_same_401(app_client):
    async with app_client as c:
        await c.post("/auth/register", json={"email": "w@x.com", "password": "Tr0ubadour9x"})
        wrong = await c.post("/auth/login", json={"email": "w@x.com", "password": "WrongPass9"})
        unknown = await c.post("/auth/login", json={"email": "nobody@x.com", "password": "Whatever9x"})
    assert wrong.status_code == 401 and wrong.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert unknown.status_code == 401 and unknown.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert wrong.json()["error"]["message_en"] == unknown.json()["error"]["message_en"]


@pytest.mark.asyncio
async def test_login_unknown_email_still_runs_bcrypt(app_client, monkeypatch):
    # timing-attack defense: bcrypt verify must run even when the email is unknown.
    import app.routers.auth as authmod
    calls = {"n": 0}
    real = authmod.verify_password

    def spy(plain, hashed):
        calls["n"] += 1
        return real(plain, hashed)

    monkeypatch.setattr(authmod, "verify_password", spy)
    async with app_client as c:
        await c.post("/auth/login", json={"email": "ghost@x.com", "password": "Whatever9x"})
    assert calls["n"] == 1                                     # verified against the dummy hash
