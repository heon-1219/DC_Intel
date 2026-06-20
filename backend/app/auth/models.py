"""Auth request/response models (backend-design AUTH §4, §6-7). The API field is `language`; the
DB column is `preferred_language` — serialize_user bridges the two. Register enforces the password
policy (-> 422 on violation); login does NOT (legacy passwords)."""
from pydantic import BaseModel, EmailStr, Field, field_validator

from app.auth.passwords import validate_password_policy


class RegisterRequest(BaseModel):
    email: EmailStr = Field(max_length=254)
    password: str
    language: str = "en"      # AUTH §4 request default (the table column default is 'ko')

    @field_validator("language")
    @classmethod
    def _lang(cls, v: str) -> str:
        if v not in ("ko", "en"):
            raise ValueError("language must be 'ko' or 'en'")
        return v

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        validate_password_policy(v)   # raises ValueError -> pydantic ValidationError -> 422
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)   # no policy re-check on login


def serialize_user(row) -> dict:
    """DB user row -> public user object (maps preferred_language->language; drops password_hash)."""
    return {
        "id": row["id"], "email": row["email"],
        "language": row["preferred_language"], "created_at": row["created_at"],
    }
