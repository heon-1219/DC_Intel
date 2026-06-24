import json
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.auth import ratelimit as rl
from app.cache import redis as cache_redis
from app.cache.redis import make_envelope
from app.config import get_settings
from app.core import errors
from app.core.instrument import InvalidInstrument, parse_instrument
from app.db.connection import connect
from app.db.repositories import accuracy as accrepo
from app.db.repositories import stocks as repo
from app.db.repositories import whisper as wrepo
from app.market.hours import market_state
from app.ml.config import TIMEFRAMES
from app.providers.fx_provider import FxProvider
from app.services import price as svc
from app.services.fx import get_cached_usdkrw, get_usdkrw
from app.services.xmkt import _norm_usd, build_cross_market

router = APIRouter()


def _err(status: int, code: str, en: str, ko: str, request_id: str) -> JSONResponse:
    return errors.error_json(status, code, en, ko, request_id)


def _iso(now: datetime) -> str:
    return now.isoformat().replace("+00:00", "Z")


@router.get("/stocks/{instrument}/price")
async def get_price(instrument: str, request: Request):
    rid = errors.request_id(request)
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
    rid = errors.request_id(request)
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
    rid = errors.request_id(request)
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


@router.get("/stocks/{instrument}/whisper")
async def get_whisper(instrument: str, request: Request):
    """Public (no auth) latest AIWCE whisper-EPS corroboration for a stock — the corroborated/
    tentative badge + value vs consensus, OR an honest abstention (status no_reliable_whisper +
    abstain_reason). A stock with no row yet returns 200 with status=None ("not computed"), never a
    404 — only an unknown symbol 404s."""
    rid = errors.request_id(request)
    try:
        symbol, exchange = parse_instrument(instrument)
    except InvalidInstrument:
        return _err(400, "INVALID_PARAM", "Malformed instrument.", "잘못된 종목 형식이에요.", rid)

    async with connect(get_settings().sqlite_path) as con:
        ref = await repo.get_stock(con, symbol, exchange)
        if ref is None:
            return _err(404, "SYMBOL_NOT_FOUND", "Unknown stock.", "알 수 없는 종목이에요.", rid)
        row = await wrepo.get_latest_for_stock(con, ref.id)

    inst = f"{symbol}:{exchange}"
    if row is None:
        data = {
            "instrument": inst, "status": None, "whisper_value": None, "confidence": None,
            "anchor": None, "surprise_vs_anchor": None, "earnings_date": None,
            "n_inliers": 0, "n_outliers_rejected": 0, "n_distinct_families": 0,
            "contributing_families": [], "inlier_dispersion": None, "factors": {},
            "abstain_reason": None, "rounds_used": 0, "computed_at": None,
        }
        as_of = _iso(datetime.now(timezone.utc))
    else:
        data = {
            "instrument": inst, "status": row["status"], "whisper_value": row["whisper_value"],
            "confidence": row["confidence"], "anchor": row["anchor"],
            "surprise_vs_anchor": row["surprise_vs_anchor"], "earnings_date": row["earnings_date"],
            "n_inliers": row["n_inliers"], "n_outliers_rejected": row["n_outliers_rejected"],
            "n_distinct_families": row["n_distinct_families"],
            "contributing_families": row["contributing_families"],
            "inlier_dispersion": row["inlier_dispersion"], "factors": row["factors"],
            "abstain_reason": row["abstain_reason"], "rounds_used": row["rounds_used"],
            "computed_at": row["computed_at"],
        }
        as_of = row["computed_at"]
    return JSONResponse(content=make_envelope(
        data, source="internal", data_as_of=as_of, is_stale=False,
        cache="miss", request_id=rid))


SEARCH_LIMIT_PER_MIN = 60   # §4.2 per-endpoint override (module-level so tests can dial it down)
_SEARCH_TTL = 6 * 3600      # metadata blob TTL (prices are merged live, never cached)


async def _price_overlay(redis, lst: dict, usdkrw, now: datetime):
    """(last_price, price_as_of, fx_rate, norm_usd_or_None_when_stale) for a search listing."""
    cached = await svc.read_cached(redis, lst["symbol"], lst["exchange"])
    fx_rate = 1.0 if lst["currency"] == "USD" else (round(1 / usdkrw, 8) if usdkrw else None)
    if cached is None:
        return None, None, fx_rate, None
    as_of = cached["as_of"]
    state = market_state(lst["exchange"], now)
    fresh = not svc.is_stale(datetime.fromisoformat(as_of.replace("Z", "+00:00")), state, now)
    norm = _norm_usd(cached["price"], lst["currency"], lst["adr_ratio"], usdkrw) if fresh else None
    return cached["price"], as_of, fx_rate, norm


@router.get("/stocks/search")
async def search_stocks(request: Request):
    """Public stock search (backend-design §6.3). 6h metadata blob + live per-request price overlay
    (last_price/price_as_of/fx_rate/diff_vs_primary_pct); 60/min/IP."""
    rid = errors.request_id(request)
    redis = cache_redis.get_client()
    allowed, _, retry = await rl.hit(redis, "search_ip", rl.client_ip(request),
                                     limit=SEARCH_LIMIT_PER_MIN, window_sec=60)
    if not allowed:
        return rl.rate_limited(rid, retry, SEARCH_LIMIT_PER_MIN)

    qp = request.query_params
    q = (qp.get("q") or "").strip()
    if not (1 <= len(q) <= 50):
        return _err(400, "INVALID_PARAM", "q must be 1-50 characters.",
                    "검색어는 1-50자여야 해요.", rid)
    try:
        limit = int(qp.get("limit", 10))
    except ValueError:
        return _err(400, "INVALID_PARAM", "Bad limit.", "limit 형식 오류예요.", rid)
    if not (1 <= limit <= 20):
        return _err(400, "INVALID_PARAM", "limit must be 1-20.", "limit는 1-20이어야 해요.", rid)

    norm_q = q.lower()
    meta_key = f"stocks:search:{norm_q}:{limit}"
    groups, cache_status = None, "miss"
    try:
        raw = await redis.get(meta_key)
        if raw:
            groups, cache_status = json.loads(raw), "metadata-hit"
    except Exception:  # noqa: BLE001 - fail-open: query live
        pass
    if groups is None:
        async with connect(get_settings().sqlite_path) as con:
            groups = await repo.search_listings(con, norm_q, limit=limit)
        try:
            await redis.set(meta_key, json.dumps(groups), ex=_SEARCH_TTL)
        except Exception:  # noqa: BLE001
            pass

    usdkrw = await get_cached_usdkrw(redis)   # cache-only: the request path makes no external calls
    now = datetime.now(timezone.utc)
    results = []
    for g in groups:
        overlays = [await _price_overlay(redis, lst, usdkrw, now) for lst in g["listings"]]
        primary_norm = next((o[3] for lst, o in zip(g["listings"], overlays)
                             if lst["is_primary"]), None)
        listings = []
        for lst, (price, as_of, fx_rate, norm) in zip(g["listings"], overlays):
            diff = (None if lst["is_primary"] or primary_norm is None or norm is None
                    else round((norm - primary_norm) / primary_norm * 100, 2))
            listings.append({
                "instrument": lst["instrument"], "symbol": lst["symbol"],
                "exchange": lst["exchange"], "board": lst["board"], "currency": lst["currency"],
                "is_primary": lst["is_primary"], "kind": lst["kind"],
                "last_price": price, "price_as_of": as_of, "fx_rate": fx_rate,
                "diff_vs_primary_pct": diff,
            })
        results.append({"company_name_en": g["company_name_en"],
                        "company_name_ko": g["company_name_ko"], "listings": listings})

    return JSONResponse(content=make_envelope(
        {"query": q, "results": results}, source="internal", data_as_of=_iso(now),
        is_stale=False, cache=cache_status, request_id=rid))
