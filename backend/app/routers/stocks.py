import json
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.cache import redis as cache_redis
from app.cache.redis import make_envelope
from app.config import get_settings
from app.core import errors
from app.core.instrument import InvalidInstrument, parse_instrument
from app.db.connection import connect
from app.db.repositories import accuracy as accrepo
from app.db.repositories import stocks as repo
from app.market.hours import market_state
from app.ml.config import TIMEFRAMES
from app.providers.fx_provider import FxProvider
from app.services import price as svc
from app.services.fx import get_usdkrw
from app.services.xmkt import build_cross_market

router = APIRouter()


def _err(status: int, code: str, en: str, ko: str, request_id: str) -> JSONResponse:
    return errors.error_json(status, code, en, ko, request_id)


def _iso(now: datetime) -> str:
    return now.isoformat().replace("+00:00", "Z")


@router.get("/stocks/{instrument}/price")
async def get_price(instrument: str, request: Request):
    rid = request.headers.get("x-request-id", "req_local")
    try:
        symbol, exchange = parse_instrument(instrument)
    except InvalidInstrument:
        return _err(400, "INVALID_PARAM", "Malformed instrument.", "잘못된 종목 형식이에요.", rid)

    async with connect(get_settings().sqlite_path) as con:
        ref = await repo.get_stock(con, symbol, exchange)
    if ref is None:
        return _err(404, "SYMBOL_NOT_FOUND", "Unknown stock.", "알 수 없는 종목이에요.", rid)

    cached = await svc.read_cached(cache_redis.get_client(), symbol, exchange)
    if cached is None:
        return _err(404, "NOT_FOUND", "We're still preparing data for this stock.",
                    "이 종목의 데이터가 아직 준비 중이에요.", rid)

    now = datetime.now(timezone.utc)
    state = market_state(exchange, now)
    as_of = datetime.fromisoformat(cached["as_of"].replace("Z", "+00:00"))
    stale = svc.is_stale(as_of, state, now)
    pc = cached.get("previous_close")
    price = cached["price"]
    change = round(price - pc, 4) if pc else None
    change_pct = round((price - pc) / pc * 100, 4) if pc else None
    return JSONResponse(content={
        "data": {
            "instrument": f"{symbol}:{exchange}",
            "name_en": ref.company_name or ref.symbol,
            "name_ko": ref.company_name_ko or ref.company_name or ref.symbol,
            "price": price, "currency": cached.get("currency", ref.currency),
            "change": change, "change_pct": change_pct,
            "previous_close": pc, "volume": cached.get("volume"),
            "day_high": cached.get("day_high"), "day_low": cached.get("day_low"),
            "market_state": state,
        },
        "meta": {"source": cached.get("source", "yfinance"), "data_as_of": cached["as_of"],
                 "is_stale": stale, "cache": "hit", "request_id": rid},
    })


@router.get("/stocks/{instrument}/prices-across-markets")
async def get_prices_across_markets(instrument: str, request: Request):
    rid = request.headers.get("x-request-id", "req_local")
    try:
        symbol, exchange = parse_instrument(instrument)
    except InvalidInstrument:
        return _err(400, "INVALID_PARAM", "Malformed instrument.", "잘못된 종목 형식이에요.", rid)

    async with connect(get_settings().sqlite_path) as con:
        res = await repo.get_company_listings(con, symbol, exchange)
    if res is None:
        return _err(404, "SYMBOL_NOT_FOUND", "Unknown stock.", "알 수 없는 종목이에요.", rid)

    names, listings = res
    redis = cache_redis.get_client()
    usdkrw = await get_usdkrw(redis, FxProvider())
    now = datetime.now(timezone.utc)
    data = await build_cross_market(symbol, exchange, names, listings, redis, usdkrw, now)
    return JSONResponse(content={
        "data": data,
        "meta": {"source": "composite", "data_as_of": _iso(now),
                 "is_stale": False, "cache": "miss", "request_id": rid},
    })


_ACC_TTL = 300   # accuracy stats cache TTL (sec); busted eagerly by the outcome_checker on each grade


@router.get("/stocks/{instrument}/accuracy")
async def get_accuracy(instrument: str, request: Request):
    """Public (no auth) win-rate stats for a stock — the trust anchor (win-loss §8.2)."""
    rid = request.headers.get("x-request-id", "req_local")
    qp = request.query_params
    tf = qp.get("timeframe")
    if tf is not None and tf not in TIMEFRAMES:
        return _err(400, "INVALID_PARAM", "Bad timeframe.", "잘못된 기간이에요.", rid)
    window = qp.get("window", "all")
    if window not in ("30d", "90d", "all"):
        return _err(400, "INVALID_PARAM", "window must be 30d, 90d, or all.",
                    "window는 30d, 90d, all 중 하나여야 해요.", rid)
    include_mv = qp.get("include_model_versions", "false").lower() == "true"
    try:
        symbol, exchange = parse_instrument(instrument)
    except InvalidInstrument:
        return _err(400, "INVALID_PARAM", "Malformed instrument.", "잘못된 종목 형식이에요.", rid)

    redis = cache_redis.get_client()
    now_iso = _iso(datetime.now(timezone.utc))
    key = f"acc:{symbol}:{exchange}:{tf or 'all'}:{window}" + (":mv" if include_mv else "")

    data, cache_status = None, "miss"
    try:
        raw = await redis.get(key)
        if raw:
            data, cache_status = json.loads(raw), "hit"
    except Exception:  # noqa: BLE001 - fail-open: compute live
        pass

    if data is None:
        async with connect(get_settings().sqlite_path) as con:
            ref = await repo.get_stock(con, symbol, exchange)
            if ref is None:
                return _err(404, "SYMBOL_NOT_FOUND", "Unknown stock.", "알 수 없는 종목이에요.", rid)
            stats = await accrepo.accuracy_stats(con, ref.id, window=window, now_iso=now_iso,
                                                 include_model_versions=include_mv, timeframe=tf)
        data = {"instrument": f"{symbol}:{exchange}", "window": window, **stats}
        try:
            await redis.set(key, json.dumps(data), ex=_ACC_TTL)
        except Exception:  # noqa: BLE001
            pass

    return JSONResponse(content=make_envelope(
        data, source="internal", data_as_of=now_iso, is_stale=False,
        cache=cache_status, request_id=rid))
