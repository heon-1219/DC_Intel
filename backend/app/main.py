from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI

from app.cache import redis as cache_redis
from app.config import get_settings
from app.jobs.price_poller import poll_indexes, poll_region
from app.providers.breaker import CircuitBreaker
from app.providers.finnhub_provider import FinnhubProvider
from app.providers.pykrx_provider import PykrxProvider
from app.providers.yfinance_provider import YFinanceProvider
from app.routers import health, stocks
from app.scheduler import build_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the price-poller scheduler with real providers/redis. Not run by the test
    ASGI transport, so unit tests never start real jobs."""
    settings = get_settings()
    redis = cache_redis.get_client()
    breaker = CircuitBreaker(redis)
    yf = YFinanceProvider()
    fh = FinnhubProvider(settings.finnhub_api_key)
    pk = PykrxProvider()

    async def _krx():
        await poll_region(settings.sqlite_path, "KR", redis, breaker, yfinance=yf, finnhub=fh, pykrx=pk)

    async def _us():
        await poll_region(settings.sqlite_path, "US", redis, breaker, yfinance=yf, finnhub=fh, pykrx=pk)

    async def _idx():
        await poll_indexes(settings.sqlite_path, redis, breaker, yfinance=yf, finnhub=fh, pykrx=pk)

    async def _hb():
        await redis.set("ops:heartbeat",
                        datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))

    sched = build_scheduler(run=True, jobs={
        "poll_prices_krx": _krx, "poll_prices_us": _us, "poll_indexes": _idx, "heartbeat": _hb})
    try:
        yield
    finally:
        sched.shutdown(wait=False)
        await redis.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="DC Intel API", version="0.1.0", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(stocks.router)
    return app


app = create_app()
