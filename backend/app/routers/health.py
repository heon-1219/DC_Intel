from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.cache import redis as cache_redis
from app.config import get_settings
from app.db.connection import connect

router = APIRouter()


@router.get("/healthz")
async def healthz():
    """Liveness/readiness: 200 only if SQLite and Redis both answer."""
    checks = {"sqlite": False, "redis": False}
    try:
        async with connect(get_settings().sqlite_path) as con:
            await (await con.execute("SELECT 1")).fetchone()
        checks["sqlite"] = True
    except Exception:
        pass
    # Looked up via the module so tests can monkeypatch cache_redis.get_client.
    checks["redis"] = await cache_redis.ping(cache_redis.get_client())
    ok = all(checks.values())
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"status": "ok" if ok else "degraded", "checks": checks},
    )
