"""Canonicalize a RawEvent into a CanonEvent ready to upsert (economic-calendar.md §3-§6)."""
from datetime import timezone

from app.calendar.actuals import build_avf
from app.calendar.affected import build_affected_json
from app.calendar.impact import assign_impact
from app.calendar.models import CanonEvent, RawEvent
from app.calendar.registry import auto_slug, match_event_type


def _iso(dt) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def canonicalize(raw: RawEvent, registry: dict, sectors: dict,
                 mega_caps: list[str]) -> CanonEvent:
    # Earnings: composite slug earnings:{symbol}:{exchange}; mega-caps high, else medium (§5.1).
    if raw.extra.get("kind") == "earnings":
        sym = raw.extra["symbol"]
        exch = raw.extra.get("exchange", "NASDAQ")
        etype = f"earnings:{sym}:{exch}"
        impact = "high" if sym in mega_caps else "medium"
        return CanonEvent(
            event_type=etype, event_name=f"{sym} Earnings", title_ko=f"{sym} 실적 발표",
            country=raw.country, event_time=_iso(raw.scheduled_utc),
            impact_level=impact, impact_source="override", provider=raw.provider,
            provider_event_id=raw.provider_event_id,
            affected_json=build_affected_json(None, sectors, earnings_stock=(sym, exch)),
            raw=raw, actual_vs_forecast=build_avf(raw, None, raw.provider))

    # Seeds carry their event_type directly; providers match by name.
    etype = raw.extra.get("event_type") or match_event_type(registry, raw.provider, raw.raw_name)
    entry = registry.get(etype) if etype else None
    # Country cross-check: a name-matched entry must agree on country, so an over-generic
    # alias (e.g. "Interest Rate Decision") can't mislabel another country's event. Seeds
    # (explicit event_type) bypass this guard.
    if (entry and not raw.extra.get("event_type")
            and entry.get("country") and entry["country"] != raw.country):
        etype, entry = None, None
    if not etype:
        etype = auto_slug(raw.country, raw.raw_name)
    impact, impact_src = assign_impact(entry, raw.importance)
    name = entry["titles"]["en"] if entry else raw.raw_name
    name_ko = entry["titles"]["ko"] if entry else None
    return CanonEvent(
        event_type=etype, event_name=name, title_ko=name_ko, country=raw.country,
        event_time=_iso(raw.scheduled_utc), impact_level=impact, impact_source=impact_src,
        provider=raw.provider, provider_event_id=raw.provider_event_id,
        affected_json=build_affected_json(entry, sectors), raw=raw,
        actual_vs_forecast=build_avf(raw, entry, raw.provider))
