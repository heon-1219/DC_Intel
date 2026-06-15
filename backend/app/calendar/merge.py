"""Dedup canonical events that describe the same occurrence (economic-calendar.md §11.2, §15).
Same (event_type, calendar-date) collapses to one row; the authoritative source wins on
time/title (seed > investing_com > fred > finnhub), and forecast/previous/actual/importance
are merged from whichever source supplies them."""
from dataclasses import replace

from app.calendar.models import CanonEvent

_PRIORITY = {"seed": 0, "investing_com": 1, "fred": 2, "finnhub": 3}


def dedup(events: list[CanonEvent]) -> list[CanonEvent]:
    groups: dict[tuple, list[CanonEvent]] = {}
    for e in events:
        groups.setdefault((e.event_type, e.event_time[:10]), []).append(e)

    out: list[CanonEvent] = []
    for grp in groups.values():
        grp.sort(key=lambda e: _PRIORITY.get(e.provider, 9))
        winner = grp[0]

        def pick(attr):
            for e in grp:
                v = getattr(e.raw, attr)
                if v is not None:
                    return v
            return None

        merged_raw = replace(
            winner.raw,
            forecast=pick("forecast"), previous=pick("previous"),
            actual=pick("actual"),
            importance=winner.raw.importance if winner.raw.importance is not None
            else pick("importance"))
        # keep the most-complete actual_vs_forecast across the group (actual > forecast > none)
        best = max(grp, key=_avf_score)
        out.append(replace(winner, raw=merged_raw, actual_vs_forecast=best.actual_vs_forecast))
    return out


def _avf_score(e: CanonEvent) -> int:
    a = e.actual_vs_forecast
    if not a or not a.get("metrics"):
        return -1
    m = a["metrics"][0]
    return (2 if m.get("actual") is not None else 0) + (1 if m.get("forecast") is not None else 0)
