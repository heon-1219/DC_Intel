import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.cache import redis as cache_redis
from app.calendar.registry import load_registry
from app.config import get_settings
from app.db.connection import connect
from app.db.repositories import economic_events as repo

router = APIRouter()

_CONFIG = Path(__file__).resolve().parents[3] / "config"
_REG_PATH = str(_CONFIG / "economic_events.yaml")
_VALID_IMPACT = {"high", "medium", "low"}
_STALE_AFTER_H = 48


def _err(status, code, en, ko, rid):
    return JSONResponse(status_code=status, content={"error": {
        "code": code, "message_en": en, "message_ko": ko, "request_id": rid}})


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


@router.get("/dashboard/economic-calendar")
async def economic_calendar(request: Request):
    rid = request.headers.get("x-request-id", "req_local")
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

    events = []
    for e in events_base:
        sched = datetime.fromisoformat(e["scheduled_at_utc"].replace("Z", "+00:00"))
        countdown = (int((sched - now).total_seconds())
                     if e["status"] not in ("released", "cancelled") else None)
        events.append({**e, "countdown_seconds": countdown,
                       "affects_your_stocks": None, "match_level": None,
                       "matched_symbols": []})   # auth overlay lands in M6

    last_synced = await redis.get("cal:last_synced_at")
    data_stale = True
    if last_synced:
        synced = datetime.fromisoformat(last_synced.replace("Z", "+00:00"))
        data_stale = (now - synced) > timedelta(hours=_STALE_AFTER_H)

    return JSONResponse(content={
        "data": {
            "server_time_utc": _iso(now),
            "range": {"from_utc": from_utc, "to_utc": to_utc},
            "last_synced_at_utc": last_synced, "data_stale": data_stale,
            "events": events,
        },
        "meta": {"source": "composite", "cache": "hit" if cached else "miss",
                 "request_id": rid},
    })
