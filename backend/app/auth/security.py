"""Auth primitives (backend-design AUTH §1-2): bcrypt password hashing + HS256 JWT.
Pure — no FastAPI. Secret/cost/expiry come from config. JWT claims are exactly {sub, iat, exp}
(no email — keep PII out of the token). `now` is injected so token timing is testable/deterministic."""
from datetime import datetime, timedelta

import bcrypt
import jwt

from app.config import get_settings

_ALG = "HS256"


def hash_password(plain: str) -> str:
    rounds = get_settings().bcrypt_rounds
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):   # malformed hash / non-utf8 -> not a match
        return False


def encode_token(user_id: int, now: datetime) -> str:
    s = get_settings()
    return jwt.encode(
        {"sub": str(user_id), "iat": int(now.timestamp()),
         "exp": int((now + timedelta(minutes=s.jwt_expiry_min)).timestamp())},
        s.jwt_secret, algorithm=_ALG)


def decode_token(token: str) -> dict | None:
    """Validated claims, or None for any invalid/expired/forged/garbage token."""
    try:
        return jwt.decode(token, get_settings().jwt_secret, algorithms=[_ALG])
    except jwt.PyJWTError:
        return None
