from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.cache import redis as cache_redis
from app.core import errors
from app.core import logging as applog
from app.core.middleware import MetricsMiddleware, RateLimitMiddleware, RequestIdMiddleware
from app.calendar.providers.finnhub_calendar_provider import FinnhubCalendarProvider
from app.calendar.providers.fred_provider import FredProvider
from app.calendar.providers.investing_provider import InvestingProvider
from app.calendar.providers.seed_provider import SeedProvider
from app.config import get_settings
from app.intel.fetchers.kr_communities import DcInsideFetcher, NaverFetcher
from app.intel.fetchers.reddit_fetcher import RedditFetcher
from app.intel.fetchers.stocktwits_fetcher import StockTwitsFetcher
from app.intel.fetchers.twitter_fetcher import TwitterFetcher
from app.intel.anomaly import scan_anomalies
from app.intel.confirm import match_confirmations
from app.intel.embed import MiniLMEmbedder
from app.intel.maintenance import purge_old_intel, recompute_author_stats
from app.intel.scraper import ingest as intel_ingest
from app.sentiment.fetchers.finnhub_news import FinnhubNewsFetcher
from app.sentiment.fetchers.newsapi import NewsApiFetcher
from app.jobs.calendar_sync import sync_calendar
from app.jobs.dashboard_builder import build_dashboard_blobs
from app.jobs.db_backup import run_db_backup
from app.jobs.metrics_rollup import run_metrics_rollup
from app.jobs.model_retrain import run_model_retrain
from app.jobs.win_rate_monitor import run_win_rate_monitor
from app.jobs.event_study import econ_event_study
from app.jobs.indicator_calculator import recompute_indicators
from app.jobs.outcome_checker import run_outcome_checker
from app.jobs.price_poller import poll_indexes, poll_region
from app.providers.breaker import CircuitBreaker
from app.sentiment.classify import ZeroShotClassifier
from app.sentiment.pipeline import aggregate_sentiment
from app.providers.finnhub_provider import FinnhubProvider
from app.providers.pykrx_provider import PykrxProvider
from app.providers.yfinance_bars import YFinanceBarProvider
from app.providers.yfinance_provider import YFinanceProvider
from app.jobs.fetch_actual import backfill_actuals
from app.auth.deps import AuthError, auth_error_handler
from app.routers import auth, dashboard, health, predictions, stocks
from app.scheduler import build_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the price-poller scheduler with real providers/redis. Not run by the test
    ASGI transport, so unit tests never start real jobs."""
    settings = get_settings()
    applog.configure_logging(settings.log_level)
    log = applog.get_logger()
    log.info("app.start", env=settings.env)
    redis = cache_redis.get_client()
    breaker = CircuitBreaker(redis)
    yf = YFinanceProvider()
    fh = FinnhubProvider(settings.finnhub_api_key)
    pk = PykrxProvider()
    bars = YFinanceBarProvider()

    async def _krx():
        await poll_region(settings.sqlite_path, "KR", redis, breaker, yfinance=yf, finnhub=fh, pykrx=pk)

    async def _us():
        await poll_region(settings.sqlite_path, "US", redis, breaker, yfinance=yf, finnhub=fh, pykrx=pk)

    async def _idx():
        await poll_indexes(settings.sqlite_path, redis, breaker, yfinance=yf, finnhub=fh, pykrx=pk)

    async def _hb():
        await redis.set("ops:heartbeat",
                        datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))

    async def _ind():
        await recompute_indicators(settings.sqlite_path, redis, breaker, bars_provider=bars)

    async def _dash():
        await build_dashboard_blobs(settings.sqlite_path, redis, bars)

    config_dir = str(Path(__file__).resolve().parents[2] / "config")
    reg_path = str(Path(config_dir) / "economic_events.yaml")
    sec_path = str(Path(config_dir) / "sectors.yaml")
    cal_providers = [InvestingProvider(), SeedProvider(config_dir),
                     FredProvider(settings.fred_api_key),
                     FinnhubCalendarProvider(settings.finnhub_api_key)]

    async def _cal():
        await sync_calendar(settings.sqlite_path, redis, breaker, providers=cal_providers,
                            registry_path=reg_path, sectors_path=sec_path)
        await backfill_actuals(settings.sqlite_path, redis, breaker, providers=cal_providers,
                               registry_path=reg_path, sectors_path=sec_path)

    async def _study():
        await econ_event_study(settings.sqlite_path, bars, registry_path=reg_path)

    intel_fetchers = [
        StockTwitsFetcher(settings.stocktwits_access_token),
        RedditFetcher(settings.reddit_client_id, settings.reddit_client_secret,
                      settings.reddit_user_agent),
        TwitterFetcher(settings.twitter_auth_token, settings.twitter_ct0,
                       settings.twitter_cookies_file, enabled_flag=settings.twitter_enabled),
        DcInsideFetcher(), NaverFetcher(),
        FinnhubNewsFetcher(settings.finnhub_api_key), NewsApiFetcher(settings.newsapi_api_key),
    ]
    classifier = ZeroShotClassifier()   # lazy: weights load on first classify
    embedder = MiniLMEmbedder()         # lazy: MiniLM loads on first embed

    async def _intel_scrape():
        await intel_ingest(settings.sqlite_path, redis, intel_fetchers, embedder=embedder)

    async def _agg_sentiment():
        await aggregate_sentiment(settings.sqlite_path, redis, classifier)

    async def _anomaly():
        await scan_anomalies(settings.sqlite_path, redis, bars)

    async def _confirm():
        await match_confirmations(settings.sqlite_path, redis)

    async def _author_stats():
        await recompute_author_stats(settings.sqlite_path, redis)

    async def _retention():
        await purge_old_intel(settings.sqlite_path)

    async def _outcome():
        await run_outcome_checker(settings.sqlite_path, redis)

    async def _winrate():
        await run_win_rate_monitor(settings.sqlite_path)

    async def _backup():
        await run_db_backup(settings.sqlite_path, settings.backup_dir)

    async def _metrics():
        await run_metrics_rollup()

    async def _retrain():
        await run_model_retrain(settings.sqlite_path, settings.model_dir)

    sched = build_scheduler(run=True, jobs={
        "poll_prices_krx": _krx, "poll_prices_us": _us, "poll_indexes": _idx,
        "heartbeat": _hb, "recompute_indicators": _ind, "build_dashboard": _dash,
        "sync_calendar": _cal,
        "econ_event_study": _study, "intel_scrape": _intel_scrape,
        "aggregate_sentiment": _agg_sentiment, "intel_anomaly_scan": _anomaly,
        "intel_confirmation_match": _confirm, "outcome_checker": _outcome,
        "intel_author_stats": _author_stats, "intel_retention": _retention,
        "win_rate_monitor": _winrate, "db_backup": _backup,
        "metrics_rollup": _metrics, "model_retrain": _retrain})
    try:
        yield
    finally:
        log.info("app.stop")
        sched.shutdown(wait=False)
        await redis.aclose()


def create_app() -> FastAPI:
    applog.configure_logging(get_settings().log_level)
    app = FastAPI(title="DC Intel API", version="0.1.0", lifespan=lifespan)
    # Order: RateLimit added first (inner), RequestId last (outer) — so request_id is set before the
    # limiter runs and is present on the 429 body + X-Request-ID header.
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(MetricsMiddleware)  # outermost: measures total request time incl. other mw
    app.add_exception_handler(AuthError, auth_error_handler)
    app.add_exception_handler(RequestValidationError, errors.validation_exception_handler)
    app.add_exception_handler(Exception, errors.unhandled_exception_handler)
    app.include_router(health.router)
    app.include_router(stocks.router)
    app.include_router(dashboard.router)
    app.include_router(auth.router)
    app.include_router(predictions.router)
    return app


app = create_app()
