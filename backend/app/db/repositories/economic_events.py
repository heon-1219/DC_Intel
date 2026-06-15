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
                "provider", "provider_event_id", "event_type", "title_ko", "country",
                "impact_source", "status", "updated_at"]
_UPDATE_COLS = ["event_name", "impact_level", "affected_stocks_json", "event_type",
                "title_ko", "country", "impact_source", "updated_at"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


async def upsert_event(con, canon: CanonEvent) -> None:
    vals = [canon.event_name, canon.event_time, canon.impact_level,
            json.dumps(canon.affected_json), canon.provider, canon.provider_event_id,
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


async def mark_cancelled(con, ids: list[int]) -> None:
    if not ids:
        return
    await con.execute(
        f"UPDATE economic_events SET status='cancelled', updated_at=? "
        f"WHERE id IN ({','.join('?' * len(ids))})",
        [_now_iso(), *ids])
    await con.commit()
