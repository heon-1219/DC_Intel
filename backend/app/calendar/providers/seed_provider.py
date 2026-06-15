"""Static central-bank seed events (economic-calendar.md §2 fallback piece 3). Guarantees
the highest-impact events exist even if the scraper and all API pieces are down."""
import json
from datetime import datetime
from pathlib import Path

from app.calendar.models import RawEvent

_SEED_FILES = ["fomc_2026.json", "bok_2026.json", "boj_2026.json"]
_NAMES = {
    "us_fomc_rate_decision": "Fed Interest Rate Decision",
    "kr_bok_rate_decision": "BoK Interest Rate Decision",
    "jp_boj_rate_decision": "BoJ Interest Rate Decision",
}


class SeedProvider:
    name = "seed"

    def __init__(self, config_dir: str):
        self.config_dir = config_dir

    async def fetch_scheduled(self, start_utc: datetime, end_utc: datetime) -> list[RawEvent]:
        out: list[RawEvent] = []
        for fn in _SEED_FILES:
            p = Path(self.config_dir) / fn
            if not p.exists():
                continue
            doc = json.loads(p.read_text(encoding="utf-8"))
            etype = doc["event_type"]
            country = doc["country"]
            estimated = bool(doc.get("time_estimated", False))
            for ev in doc.get("events", []):
                ts = datetime.fromisoformat(ev["event_time"].replace("Z", "+00:00"))
                if start_utc <= ts <= end_utc:
                    out.append(RawEvent(
                        provider="seed", provider_event_id=ev.get("provider_event_id"),
                        raw_name=_NAMES.get(etype, etype), country=country,
                        scheduled_utc=ts, time_estimated=estimated,
                        extra={"event_type": etype}))
        return out
