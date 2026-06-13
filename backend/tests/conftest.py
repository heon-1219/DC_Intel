from pathlib import Path

import fakeredis.aioredis
import pytest

MIG_DIR = str(Path(__file__).resolve().parents[1] / "migrations")


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

    # Patch the module attribute so handlers that call cache_redis.get_client() see the fake.
    import app.cache.redis as cache_redis
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(cache_redis, "get_client", lambda: fake)

    import httpx
    from app.main import create_app
    transport = httpx.ASGITransport(app=create_app())
    return httpx.AsyncClient(transport=transport, base_url="http://test")
