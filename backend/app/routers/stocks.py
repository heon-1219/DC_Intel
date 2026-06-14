from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.cache import redis as cache_redis
from app.config import get_settings
from app.core.instrument import InvalidInstrument, parse_instrument
from app.db.connection import connect
from app.db.repositories import stocks as repo
from app.market.hours import market_state
from app.providers.fx_provider import FxProvider
from app.services import price as svc
from app.services.fx import get_usdkrw
from app.services.xmkt import build_cross_market

router = APIRouter()


def _err(status: int, code: str, en: str, ko: str, request_id: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {
        "code": code, "message_en": en, "message_ko": ko, "request_id": request_id}})


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
