"""M8a — centralized error catalog + global handlers (backend-design §2.4)."""
import pytest
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request

from app.core import errors
from app.main import create_app


def _req(headers=None):
    return Request({"type": "http", "headers": headers or [], "state": {}})


def test_catalog_covers_the_full_2_4_set():
    assert errors.STATUS["INVALID_PARAM"] == 400
    assert errors.STATUS["UNAUTHORIZED"] == 401 and errors.STATUS["INVALID_CREDENTIALS"] == 401
    assert errors.STATUS["SYMBOL_NOT_FOUND"] == 404 and errors.STATUS["NOT_FOUND"] == 404
    assert errors.STATUS["EMAIL_TAKEN"] == 409 and errors.STATUS["VALIDATION_ERROR"] == 422
    assert errors.STATUS["RATE_LIMITED"] == 429 and errors.STATUS["INTERNAL"] == 500
    assert errors.STATUS["SOURCE_DEGRADED"] == 503 and errors.STATUS["MODEL_UNAVAILABLE"] == 503


def test_error_content_always_carries_details_key():
    body = errors.error_content("NOT_FOUND", "x", "y", "req_1")
    assert body == {"error": {"code": "NOT_FOUND", "message_en": "x", "message_ko": "y",
                              "details": None, "request_id": "req_1"}}


def test_err_uses_canonical_messages_and_status():
    resp = errors.err("UNAUTHORIZED", "req_2")
    assert resp.status_code == 401
    import json
    body = json.loads(resp.body)
    assert body["error"]["code"] == "UNAUTHORIZED"
    assert body["error"]["message_en"] and body["error"]["message_ko"]
    assert body["error"]["details"] is None and body["error"]["request_id"] == "req_2"


def test_err_message_override():
    import json
    resp = errors.err("INVALID_PARAM", "r", message_en="bad q", message_ko="잘못")
    body = json.loads(resp.body)
    assert resp.status_code == 400 and body["error"]["message_en"] == "bad q"


def test_invalid_param_helper():
    resp = errors.invalid_param("r", "bad", "나쁨")
    assert resp.status_code == 400


def test_request_id_prefers_state_then_header():
    r = _req(headers=[(b"x-request-id", b"req_hdr")])
    assert errors.request_id(r) == "req_hdr"
    r2 = _req()
    r2.state.request_id = "req_state"
    assert errors.request_id(r2) == "req_state"
    assert errors.request_id(_req()) == "req_local"   # neither set -> default


@pytest.mark.asyncio
async def test_validation_handler_reshapes_to_422_fields():
    import json
    exc = RequestValidationError([
        {"loc": ("body", "email"), "msg": "field required", "type": "missing"},
        {"loc": ("body", "password"), "msg": "too short", "type": "value_error"},
    ])
    resp = await errors.validation_exception_handler(_req(), exc)
    assert resp.status_code == 422
    body = json.loads(resp.body)
    assert body["error"]["code"] == "VALIDATION_ERROR"
    fields = body["error"]["details"]["fields"]
    assert {"field": "email", "problem": "field required"} in fields
    assert {"field": "password", "problem": "too short"} in fields


@pytest.mark.asyncio
async def test_unhandled_handler_hides_internals():
    import json
    resp = await errors.unhandled_exception_handler(_req(), ValueError("secret stack detail"))
    assert resp.status_code == 500
    body = json.loads(resp.body)
    assert body["error"]["code"] == "INTERNAL"
    assert "secret stack detail" not in resp.body.decode()   # never leak the message
    assert body["error"]["details"] is None


def test_create_app_registers_global_handlers():
    app = create_app()
    assert RequestValidationError in app.exception_handlers
    assert Exception in app.exception_handlers
