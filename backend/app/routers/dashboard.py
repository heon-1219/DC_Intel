import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.auth.deps import get_current_user_optional
from app.cache import redis as cache_redis
from app.cache.redis import make_envelope
from app.calendar.affects import compute_event_affects
from app.calendar.registry import load_registry, load_sectors
from app.config import get_settings
from app.core import errors
from app.core.instrument import InvalidInstrument, parse_instrument
from app.db.connection import connect
from app.db.repositories import economic_events as repo
from app.db.repositories import market_intel as mi_repo
from app.db.repositories import predictions as pred_repo
from app.db.repositories import stocks as srepo
from app.intel.config import INTEL_MIN_CREDIBILITY_DEFAULT
from app.intel.feed import build_clusters

router = APIRouter()

_INTEL_LOOKBACK_H = 72
_HOLDINGS_LOOKBACK_D = 14

_CONFIG = Path(__file__).resolve().parents[3] / "config"
_REG_PATH = str(_CONFIG / "economic_events.yaml")
_SEC_PATH = str(_CONFIG / "sectors.yaml")
_VALID_IMPACT = {"high", "medium", "low"}
_STALE_AFTER_H = 48


def _err(status, code, en, ko, rid):
    return errors.error_json(status, code, en, ko, rid)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _event_base(row: dict, registry: dict) -> dict:
    """DB row -> per-event response fields EXCEPT the per-request countdown + affects overlay."""
    entry = registry.get(row["event_type"]) or {}
    summ = entry.get("plain_summary") or {}
    return {
        "id": row["id"], "event_type": row["event_type"],
        "title_en": row["event_name"], "title_ko": row["title_ko"],
        "plain_summary_en": summ.get("en"), "plain_summary_ko": summ.get("ko"),
        "country": row["country"], "impact_level": row["impact_level"],
        "impact_source": row["impact_source"], "scheduled_at_utc": row["event_time"],
        "status": row["status"],
        "actual_vs_forecast": json.loads(row["actual_vs_forecast_json"])
        if row.get("actual_vs_forecast_json") else None,
        "affected": json.loads(row["affected_stocks_json"])
        if row.get("affected_stocks_json") else None,
    }


async def _holdings_instruments(con, user_id: int, now: datetime) -> list[tuple[str, str]]:
    """The (symbol, exchange) of stocks the user has predicted on in the last 14 days."""
    since = _iso(now - timedelta(days=_HOLDINGS_LOOKBACK_D))
    ids = await pred_repo.distinct_recent_stock_ids(con, user_id, since)
    if not ids:
        return []
    qs = ",".join("?" * len(ids))
    cur = await con.execute(f"SELECT symbol, exchange FROM stocks WHERE id IN ({qs})", ids)
    return [(r["symbol"], r["exchange"]) for r in await cur.fetchall()]


@router.get("/dashboard/economic-calendar")
async def economic_calendar(request: Request):
    rid = errors.request_id(request)
    user = await get_current_user_optional(request)   # anon -> None; present-but-invalid -> 401
    qp = request.query_params
    try:
        days = int(qp.get("days", 7))
        include_past_hours = int(qp.get("include_past_hours", 24))
    except ValueError:
        return _err(400, "INVALID_PARAM", "Bad numeric parameter.", "숫자 형식 오류예요.", rid)
    if not (1 <= days <= 14) or not (0 <= include_past_hours <= 48):
        return _err(400, "INVALID_PARAM", "days 1-14, include_past_hours 0-48.",
                    "days는 1-14, include_past_hours는 0-48이어야 해요.", rid)
    impact = [s for s in (qp.get("impact", "").split(",")) if s]
    if any(i not in _VALID_IMPACT for i in impact):
        return _err(400, "INVALID_PARAM", "Bad impact filter.", "잘못된 영향도 필터예요.", rid)
    country = [s.upper() for s in (qp.get("country", "").split(",")) if s]

    now = datetime.now(timezone.utc)
    from_utc = _iso(now - timedelta(hours=include_past_hours))
    to_utc = _iso(now + timedelta(days=days))
    redis = cache_redis.get_client()

    cache_key = f"cal:list:{days}:{','.join(impact)}:{','.join(country)}:{include_past_hours}"
    cached = await redis.get(cache_key)
    if cached:
        events_base = json.loads(cached)
    else:
        registry = load_registry(_REG_PATH)
        async with connect(get_settings().sqlite_path) as con:
            rows = await repo.list_in_range(con, from_utc, to_utc,
                                            impact=impact or None, country=country or None)
        events_base = [_event_base(r, registry) for r in rows]
        await redis.set(cache_key, json.dumps(events_base), ex=600)

    holdings, sectors = [], {}
    if user:
        async with connect(get_settings().sqlite_path) as con:
            holdings = await _holdings_instruments(con, user["id"], now)
        sectors = load_sectors(_SEC_PATH)

    events = []
    for e in events_base:
        sched = datetime.fromisoformat(e["scheduled_at_utc"].replace("Z", "+00:00"))
        countdown = (int((sched - now).total_seconds())
                     if e["status"] not in ("released", "cancelled") else None)
        overlay = (compute_event_affects(holdings, e["affected"], sectors) if user else
                   {"affects_your_stocks": None, "match_level": None, "matched_symbols": []})
        events.append({**e, "countdown_seconds": countdown, **overlay})

    last_synced = await redis.get("cal:last_synced_at")
    data_stale = True
    if last_synced:
        synced = datetime.fromisoformat(last_synced.replace("Z", "+00:00"))
        data_stale = (now - synced) > timedelta(hours=_STALE_AFTER_H)

    return JSONResponse(content=make_envelope(
        {
            "server_time_utc": _iso(now),
            "range": {"from_utc": from_utc, "to_utc": to_utc},
            "last_synced_at_utc": last_synced, "data_stale": data_stale,
            "events": events,
        },
        source="composite", data_as_of=last_synced or _iso(now), is_stale=data_stale,
        cache="hit" if cached else "miss", request_id=rid))


async def _read_anomalies(redis) -> list[dict]:
    try:
        keys = [k async for k in redis.scan_iter("intel:anomaly:*")]
    except Exception:  # noqa: BLE001 - scan unsupported / none
        return []
    out = []
    for k in keys:
        raw = await redis.get(k)
        if raw:
            out.append(json.loads(raw))
    return out


@router.get("/dashboard/market-intel")
async def market_intel(request: Request):
    rid = errors.request_id(request)
    qp = request.query_params
    lang = "ko" if qp.get("lang") == "ko" else "en"
    try:
        limit = int(qp.get("limit", 20))
        min_cred = int(qp.get("min_credibility", INTEL_MIN_CREDIBILITY_DEFAULT))
    except ValueError:
        return _err(400, "INVALID_PARAM", "Bad numeric parameter.", "숫자 형식 오류예요.", rid)
    if not (1 <= limit <= 50) or not (0 <= min_cred <= 100):
        return _err(400, "INVALID_PARAM", "limit 1-50, min_credibility 0-100.",
                    "limit는 1-50, min_credibility는 0-100이어야 해요.", rid)
    only_anom = qp.get("only_anomalies", "false").lower() == "true"
    stock_param = qp.get("stock")

    now = datetime.now(timezone.utc)
    since = _iso(now - timedelta(hours=_INTEL_LOOKBACK_H))
    stock_id = None
    async with connect(get_settings().sqlite_path) as con:
        stocks = await srepo.list_active_all(con)
        if stock_param:
            try:
                sym, exch = parse_instrument(stock_param)
            except InvalidInstrument:
                return _err(400, "INVALID_PARAM", "Malformed instrument.",
                            "잘못된 종목 형식이에요.", rid)
            ref = await srepo.get_stock(con, sym, exch)
            if ref is None:
                return _err(404, "SYMBOL_NOT_FOUND", "Unknown stock.", "알 수 없는 종목이에요.", rid)
            stock_id = ref.id
        rows = await mi_repo.list_recent(con, since, stock_id=stock_id)

    stock_map = {s.id: {"symbol": s.symbol, "exchange": s.exchange,
                        "name_en": s.company_name or s.symbol,
                        "name_ko": s.company_name_ko or s.company_name or s.symbol}
                 for s in stocks}
    clusters = build_clusters(rows, lang=lang, min_credibility=min_cred, limit=limit)
    for c in clusters:
        sid = c.pop("_stock_id")
        c["stock"] = stock_map.get(sid) if sid else None

    anomalies = await _read_anomalies(cache_redis.get_client())
    if only_anom:
        pinned = {cid for a in anomalies for cid in a.get("top_cluster_ids", [])}
        clusters = [c for c in clusters if c["cluster_id"] in pinned]

    return JSONResponse(content=make_envelope(
        {"as_of": _iso(now), "lang": lang, "anomalies": anomalies, "clusters": clusters},
        source="composite", data_as_of=_iso(now), is_stale=False, cache="miss", request_id=rid))
