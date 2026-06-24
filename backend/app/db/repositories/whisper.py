"""whisper_numbers repository (AIWCE; migration 003). The scheduled whisper_corroborator job
upserts the latest WhisperResult OR abstention here (one current row per stock × report date), and
the read API serves the newest row per stock. Mirrors the economic_events / market_intel repo style:
explicit commit, JSON columns dumped/loaded at the boundary. Abstentions are first-class rows
(whisper_value NULL, abstain_reason set) — honesty is recorded, never discarded."""
import json
from datetime import date, datetime, timezone

from app.intel.whisper.models import WhisperResult

_COLS = ("id, stock_id, earnings_event_id, earnings_date, status, whisper_value, confidence, "
         "anchor, surprise_vs_anchor, inlier_dispersion, n_inliers, n_outliers_rejected, "
         "n_distinct_families, contributing_families_json, factors_json, rounds_used, "
         "abstain_reason, computed_at, created_at, updated_at")

_INSERT_COLS = ["stock_id", "earnings_event_id", "earnings_date", "status", "whisper_value",
                "confidence", "anchor", "surprise_vs_anchor", "inlier_dispersion", "n_inliers",
                "n_outliers_rejected", "n_distinct_families", "contributing_families_json",
                "factors_json", "rounds_used", "abstain_reason", "computed_at", "updated_at"]
# stock_id/earnings_date/created_at are the identity / immutable; everything else is overwritten on rerun.
_UPDATE_COLS = [c for c in _INSERT_COLS if c not in ("stock_id", "earnings_date")]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _iso(dt: datetime | None) -> str:
    return (dt or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace(
        "+00:00", "Z")


def _hydrate(row: dict | None) -> dict | None:
    """Row -> dict with the two JSON columns parsed back into list/dict under stable key names."""
    if row is None:
        return None
    d = dict(row)
    d["contributing_families"] = json.loads(d.pop("contributing_families_json") or "[]")
    d["factors"] = json.loads(d.pop("factors_json") or "{}")
    return d


async def upsert_result(con, *, stock_id: int, earnings_event_id: int | None,
                        earnings_date: date | str, result: WhisperResult) -> None:
    ed = earnings_date.isoformat() if isinstance(earnings_date, date) else earnings_date
    vals = [stock_id, earnings_event_id, ed, result.status, result.whisper_value,
            result.confidence, result.anchor, result.surprise_vs_anchor, result.inlier_dispersion,
            result.n_inliers, result.n_outliers_rejected, result.n_distinct_families,
            json.dumps(list(result.contributing_families)), json.dumps(result.factors or {}),
            result.rounds_used, result.abstain_reason, _iso(result.computed_at), _now_iso()]
    placeholders = ",".join("?" * len(_INSERT_COLS))
    updates = ",".join(f"{c}=excluded.{c}" for c in _UPDATE_COLS)
    await con.execute(
        f"INSERT INTO whisper_numbers ({','.join(_INSERT_COLS)}) VALUES ({placeholders}) "
        f"ON CONFLICT (stock_id, earnings_date) DO UPDATE SET {updates}",
        vals)
    await con.commit()


async def get_latest_for_stock(con, stock_id: int) -> dict | None:
    """The most-recently-computed whisper row (result OR abstention) for a stock — what the API serves."""
    cur = await con.execute(
        f"SELECT {_COLS} FROM whisper_numbers WHERE stock_id=? "
        "ORDER BY computed_at DESC, id DESC LIMIT 1", (stock_id,))
    return _hydrate(await cur.fetchone())


async def list_for_stock(con, stock_id: int, limit: int = 50) -> list[dict]:
    cur = await con.execute(
        f"SELECT {_COLS} FROM whisper_numbers WHERE stock_id=? "
        "ORDER BY computed_at DESC, id DESC LIMIT ?", (stock_id, limit))
    return [_hydrate(dict(r)) for r in await cur.fetchall()]
