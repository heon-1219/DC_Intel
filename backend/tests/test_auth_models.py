"""M6b auth request/response models (backend-design AUTH §4, §6-7)."""
import pytest
from pydantic import ValidationError

from app.auth.models import LoginRequest, RegisterRequest, serialize_user


def test_register_defaults_language_en():
    r = RegisterRequest(email="a@b.com", password="Tr0ubadour9x")
    assert r.language == "en"           # AUTH §4 request default (table default is 'ko')


def test_register_accepts_explicit_ko():
    assert RegisterRequest(email="a@b.com", password="Tr0ubadour9x", language="ko").language == "ko"


def test_register_rejects_bad_password():
    with pytest.raises(ValidationError):
        RegisterRequest(email="a@b.com", password="password1")   # common -> policy rejects


def test_register_rejects_overlong_email():
    long = ("x" * 250) + "@b.com"        # > 254 chars
    with pytest.raises(ValidationError):
        RegisterRequest(email=long, password="Tr0ubadour9x")


def test_register_rejects_bad_language():
    with pytest.raises(ValidationError):
        RegisterRequest(email="a@b.com", password="Tr0ubadour9x", language="jp")


def test_login_accepts_short_password_no_policy():
    # login must accept legacy/short passwords (no policy re-check)
    assert LoginRequest(email="a@b.com", password="x").password == "x"


def test_serialize_user_maps_language_field():
    row = {"id": 7, "email": "a@b.com", "preferred_language": "ko",
           "created_at": "2026-06-21T00:00:00.000Z", "password_hash": "secret"}
    out = serialize_user(row)
    assert out == {"id": 7, "email": "a@b.com", "language": "ko",
                   "created_at": "2026-06-21T00:00:00.000Z"}
    assert "password_hash" not in out      # never leak the hash
