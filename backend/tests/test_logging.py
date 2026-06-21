"""M8b — structured logging redaction (§10.3) + request_id middleware (§10.1)."""
import pytest

from app.core.logging import redact


def _redact(event_dict):
    return redact(None, "info", event_dict)


def test_redacts_secret_keys():
    out = _redact({"event": "x", "password": "hunter2", "authorization": "Bearer abc",
                   "api_key": "k", "access_token": "t", "jwt": "j"})
    assert out["password"] == "***" and out["authorization"] == "***"
    assert out["api_key"] == "***" and out["access_token"] == "***" and out["jwt"] == "***"


def test_token_type_is_not_redacted_but_token_is():
    out = _redact({"event": "x", "token": "secret", "token_type": "bearer"})
    assert out["token"] == "***" and out["token_type"] == "bearer"


def test_masks_email_outside_auth_events():
    out = _redact({"event": "prediction.created", "note": "user a@b.com asked"})
    assert "a@b.com" not in out["note"] and "***@***" in out["note"]


def test_keeps_email_in_auth_events():
    out = _redact({"event": "auth.register", "email": "a@b.com", "user_id": 7})
    assert out["email"] == "a@b.com"


def test_new_request_id_shape():
    from app.core.middleware import new_request_id
    rid = new_request_id()
    assert rid.startswith("req_") and len(rid) == 12   # req_ + 8 hex


@pytest.mark.asyncio
async def test_middleware_mints_and_echoes_request_id(app_client):
    async with app_client as c:
        r = await c.get("/healthz")
    rid = r.headers.get("x-request-id")
    assert rid and rid.startswith("req_")


@pytest.mark.asyncio
async def test_middleware_honors_inbound_request_id(app_client):
    async with app_client as c:
        r = await c.get("/healthz", headers={"X-Request-ID": "req_caller123"})
    assert r.headers.get("x-request-id") == "req_caller123"
