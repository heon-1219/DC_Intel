"""M7c grade one matured prediction (win-loss-tracking.md §4-§5.3, §7). Given a resolved exit price,
computes the outcome using the SNAPSHOTTED reasoning_json.neutral_band_pct (never the current
config — a band re-tune must not corrupt past grades) and the shared labels.derive_direction.
Strict 3-class: marked_correct=1 iff predicted == realized (a realized neutral is a LOSS for an
up/down call). abs(move) > 35% is a split-suspect -> park (manual backfill only)."""
import json

from app.db.repositories import economic_events as erepo
from app.tracking.labels import derive_direction

SPLIT_SUSPECT_PCT = 35.0
_RELEVANT = {"KRX": ["KR", "US"], "NASDAQ": ["US"], "NYSE": ["US"], "AMEX": ["US"], "OTC": ["US"]}


def relevant_countries(exchange: str) -> list[str]:
    """Countries whose high-impact events are relevant to a stock on this exchange (§7)."""
    return _RELEVANT.get(exchange, ["US"])


async def grade_prediction(con, ref, due_row: dict, exit_price: float, now_iso: str) -> dict:
    """Returns {'action':'grade','outcome':{...}} ready for record_outcome, or
    {'action':'park','reason':...} for split-suspect / missing entry price."""
    rj = json.loads(due_row["reasoning_json"])
    entry = rj.get("entry_price")
    band = rj.get("neutral_band_pct")
    if not entry or band is None:
        return {"action": "park", "reason": "no_entry_price"}

    move_pct = 100.0 * (exit_price - entry) / entry
    if abs(move_pct) > SPLIT_SUSPECT_PCT:
        return {"action": "park", "reason": "split_suspect"}

    actual = derive_direction(move_pct, band)
    marked = 1 if due_row["direction"] == actual else 0
    events = await erepo.list_in_range(con, due_row["created_at"], now_iso,
                                       impact=["high"], country=relevant_countries(ref.exchange))
    return {"action": "grade", "outcome": {
        "actual_direction": actual,
        "actual_price_change_percent": round(move_pct, 4),
        "marked_correct": marked,
        "exit_price": exit_price,
        "high_impact_event_overlap": 1 if events else 0,
    }}
