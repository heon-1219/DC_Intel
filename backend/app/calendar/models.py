"""Calendar ingestion dataclasses. RawEvent = provider output; CanonEvent = after the
registry canonicalizes it (ready to upsert into economic_events)."""
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class RawEvent:
    provider: str                       # 'investing_com'|'fred'|'finnhub'|'seed'
    provider_event_id: str | None
    raw_name: str                       # provider's event name (for registry match)
    country: str                        # ISO-2 ('US','KR','JP','DE') or 'GLOBAL'
    scheduled_utc: datetime             # tz-aware UTC
    importance: int | None = None       # provider scale 1..3 (Investing.com bulls); else None
    forecast: float | None = None
    previous: float | None = None
    actual: float | None = None
    unit: str | None = None
    time_estimated: bool = False        # seeds whose intraday time is unpublished
    extra: dict = field(default_factory=dict)   # earnings symbol/exchange/eps, etc.


@dataclass(frozen=True)
class CanonEvent:
    event_type: str
    event_name: str                     # English display title
    title_ko: str | None
    country: str
    event_time: str                     # ISO-8601 UTC with trailing 'Z'
    impact_level: str                   # 'high'|'medium'|'low'
    impact_source: str                  # 'override'|'provider'|'default'
    provider: str
    provider_event_id: str | None
    affected_json: dict
    raw: RawEvent
