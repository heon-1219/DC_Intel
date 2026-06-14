from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.cache import redis as cache_redis
from app.config import get_settings
from app.db.connection import connect

router = APIRouter()

HEARTBEAT_MAX_AGE_S = 180


@router.get("/healthz")
async def healthz():
    """200 only if SQLite + Redis answer and (if a scheduler heartbeat exists) it's fresh."""
    checks = {"sqlite": False, "redis": False, "scheduler": True}
    try:
        async with connect(get_settings().sqlite_path) as con:
            await (await con.execute("SELECT 1")).fetchone()
        checks["sqlite"] = True
    except Exception:
        pass

    client = cache_redis.get_client()
    checks["redis"] = await cache_redis.ping(client)

    # Scheduler heartbeat: only enforced when the key exists (absent in tests / before the
    # first beat). Redis failures are already captured by the redis check above.
    try:
        hb = await client.get("ops:heartbeat")
        if hb:
            age = (datetime.now(timezone.utc)
                   - datetime.fromisoformat(hb.replace("Z", "+00:00"))).total_seconds()
            checks["scheduler"] = age < HEARTBEAT_MAX_AGE_S
    except Exception:
        pass

    ok = all(checks.values())
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"status": "ok" if ok else "degraded", "checks": checks},
    )
