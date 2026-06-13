import pytest
from app.config import Settings


def test_settings_load_with_required_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    s = Settings()
    assert s.env == "dev"
    assert s.database_url.startswith("sqlite")
    assert s.jwt_expiry_min == 1440
    assert s.bcrypt_rounds == 12


def test_sqlite_path_strips_sqlalchemy_prefix(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./data/dcintel.db")
    assert Settings().sqlite_path == "./data/dcintel.db"


def test_sqlite_path_absolute_four_slashes(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:////data/dcintel.db")
    assert Settings().sqlite_path == "/data/dcintel.db"


def test_jwt_secret_too_short_is_rejected(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "short")
    with pytest.raises(ValueError):
        Settings()
