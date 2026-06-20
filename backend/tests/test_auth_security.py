"""M6a auth core — bcrypt hashing + HS256 JWT (backend-design AUTH §1-3)."""
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest

from app.auth.security import decode_token, encode_token, hash_password, verify_password
from app.config import get_settings


def test_hash_verify_roundtrip():
    h = hash_password("Tr0ubadour9x")
    assert h != "Tr0ubadour9x"            # hashed, not plaintext
    assert verify_password("Tr0ubadour9x", h) is True
    assert verify_password("wrongpass1", h) is False


def test_encode_decode_roundtrip_claims():
    now = datetime.now(timezone.utc)
    claims = decode_token(encode_token(42, now))
    assert claims is not None
    assert claims["sub"] == "42"                                  # user id as string
    assert "email" not in claims                                  # email deliberately excluded
    assert claims["exp"] - claims["iat"] == get_settings().jwt_expiry_min * 60


def test_expired_token_returns_none():
    past = datetime.now(timezone.utc) - timedelta(days=2)         # exp already in the past
    assert decode_token(encode_token(42, past)) is None


@pytest.mark.parametrize("bad", ["", "not.a.jwt", "a.b.c", "garbage"])
def test_garbage_token_returns_none(bad):
    assert decode_token(bad) is None


def test_wrong_secret_returns_none():
    now = datetime.now(timezone.utc)
    payload = {"sub": "42", "iat": int(now.timestamp()),
               "exp": int((now + timedelta(hours=1)).timestamp())}
    forged = pyjwt.encode(payload, "a-totally-different-secret-key-000000", algorithm="HS256")
    assert decode_token(forged) is None                          # signature mismatch
