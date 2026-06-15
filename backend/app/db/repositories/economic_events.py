"""economic_events repository (economic-calendar.md §3). Upsert by (provider,
provider_event_id) when a stable id exists, else (event_type, event_time). Never deletes —
provider-removed events are marked 'cancelled'. event_time/status/actual_vs_forecast_json are
NOT overwritten on conflict (status + actuals are owned by the M3b actual-fetch job)."""
import json
from datetime import datetime, timezone

from app.calendar.models import CanonEvent

_COLS = ("id, event_name, event_time, impact_level, affected_stocks_json, "
         "actual_vs_forecast_json, provider, provider_event_id, event_type, title_ko, "
         "country, impact_source, status, created_at, updated_at")

_INSERT_COLS = ["event_name", "event_time", "impact_level", "affected_stocks_json",
                "actual_vs_forecast_json", "provider", "provider_event_id", "event_type",
                "title_ko", "country", "impact_source", "status", "updated_at"]
# event_time/status/actual_vs_forecast_json are NOT overwritten on conflict — a released
# actual (set by fetch_actual) must survive later scheduled-only syncs (§11.3).
_UPDATE_COLS = ["event_name", "impact_level", "affected_stocks_json", "event_type",
                "title_ko", "country", "impact_source", "updated_at"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


async def upsert_event(con, canon: CanonEvent) -> None:
    avf = json.dumps(canon.actual_vs_forecast) if canon.actual_vs_forecast else None
    vals = [canon.event_name, canon.event_time, canon.impact_level,
            json.dumps(canon.affected_json), avf, canon.provider, canon.provider_event_id,
            canon.event_type, canon.title_ko, canon.country, canon.impact_source,
            "scheduled", _now_iso()]
    placeholders = ",".join("?" * len(_INSERT_COLS))
    updates = ",".join(f"{c}=excluded.{c}" for c in _UPDATE_COLS)
    conflict = "(provider, provider_event_id)" if canon.provider_event_id else "(event_type, event_time)"
    await con.execute(
        f"INSERT INTO economic_events ({','.join(_INSERT_COLS)}) VALUES ({placeholders}) "
        f"ON CONFLICT {conflict} DO UPDATE SET {updates}",
        vals)
    await con.commit()


async def list_in_range(con, from_utc: str, to_utc: str, impact: list[str] | None = None,
                        country: list[str] | None = None) -> list[dict]:
    q = (f"SELECT {_COLS} FROM economic_events "
         "WHERE event_time >= ? AND event_time <= ? AND status != 'cancelled'")
    args: list = [from_utc, to_utc]
    if impact:
        q += f" AND impact_level IN ({','.join('?' * len(impact))})"
        args += impact
    if country:
        q += f" AND country IN ({','.join('?' * len(country))})"
        args += country
    q += " ORDER BY event_time ASC"
    cur = await con.execute(q, args)
    return [dict(r) for r in await cur.fetchall()]


async def set_actual(con, event_id: int, avf: dict, status: str = "released") -> None:
    """Targeted update when an actual is fetched/revised (§11.3)."""
    await con.execute(
        "UPDATE economic_events SET actual_vs_forecast_json=?, status=?, updated_at=? WHERE id=?",
        [json.dumps(avf), status, _now_iso(), event_id])
    await con.commit()


async def list_pending_actuals(con, before_utc: str) -> list[dict]:
    """High/medium events past their time whose actual value is still null (for backfill,
    §11.3). The stored JSON always carries the 'actual' key, so pending = json is NULL or
    its actual is null (LIKE '%\"actual\": null%')."""
    cur = await con.execute(
        f"SELECT {_COLS} FROM economic_events WHERE status='scheduled' "
        "AND impact_level IN ('high','medium') AND event_time <= ? "
        "AND (actual_vs_forecast_json IS NULL "
        "     OR actual_vs_forecast_json LIKE '%\"actual\": null%') "
        "ORDER BY event_time DESC",
        [before_utc])
    return [dict(r) for r in await cur.fetchall()]


async def list_released_occurrences(con, event_type: str, since_utc: str) -> list[dict]:
    """Past released occurrences of an event_type within the lookback (event-study, §8)."""
    cur = await con.execute(
        f"SELECT {_COLS} FROM economic_events WHERE event_type=? AND status='released' "
        "AND event_time >= ? ORDER BY event_time ASC",
        [event_type, since_utc])
    return [dict(r) for r in await cur.fetchall()]


async def update_history(con, event_id: int, affected_json: dict) -> None:
    """Write the event-study history back into affected_stocks_json (§8.6)."""
    await con.execute(
        "UPDATE economic_events SET affected_stocks_json=?, updated_at=? WHERE id=?",
        [json.dumps(affected_json), _now_iso(), event_id])
    await con.commit()


async def mark_cancelled(con, ids: list[int]) -> None:
    if not ids:
        return
    await con.execute(
        f"UPDATE economic_events SET status='cancelled', updated_at=? "
        f"WHERE id IN ({','.join('?' * len(ids))})",
        [_now_iso(), *ids])
    await con.commit()
