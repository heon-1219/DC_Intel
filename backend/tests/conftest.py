import os
from pathlib import Path

import fakeredis.aioredis
import pytest

# Default env so get_settings() validates in plain unit tests (auth/security etc.). Set BEFORE any
# app import / first get_settings() call. The app_client fixture overrides these per-test + cache_clears.
os.environ.setdefault("JWT_SECRET", "x" * 32)
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_unit.db")

MIG_DIR = str(Path(__file__).resolve().parents[1] / "migrations")
SEED_CSV = str(Path(__file__).resolve().parents[2] / "config" / "seed_stocks.csv")


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    """An httpx AsyncClient bound to the app, backed by a migrated temp SQLite DB
    and a fake Redis. Returns an unopened client — use `async with app_client as c`."""
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 't.db'}")

    from app.config import get_settings
    get_settings.cache_clear()

    from app.db.migrate import migrate
    migrate(get_settings().sqlite_path, MIG_DIR)
    from app.db.seed import seed_stocks
    seed_stocks(get_settings().sqlite_path, SEED_CSV)

    # Patch the module attribute so handlers that call cache_redis.get_client() see the fake.
    import app.cache.redis as cache_redis
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(cache_redis, "get_client", lambda: fake)

    import httpx
    from app.main import create_app
    transport = httpx.ASGITransport(app=create_app())
    return httpx.AsyncClient(transport=transport, base_url="http://test")
