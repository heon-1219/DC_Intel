"""FRED releases/dates — official US macro release schedule (economic-calendar.md §2 piece 1).
Dates only (no forecast); cross-checks the scrape's US dates and backstops it."""
from datetime import datetime

import httpx

from app.calendar.models import RawEvent
from app.providers.retry import ProviderError

_URL = "https://api.stlouisfed.org/fred/releases/dates"


def parse_fred(data: dict, start_utc: datetime, end_utc: datetime) -> list[RawEvent]:
    out: list[RawEvent] = []
    for row in data.get("release_dates", []) or []:
        d, name = row.get("date"), row.get("release_name")
        if not d or not name:
            continue
        # FRED returns a calendar date only; most US macro drops 08:30 ET ~= 12:30Z
        # (documented placeholder, refined by the Investing.com scrape / actual-fetch job).
        ts = datetime.fromisoformat(d + "T12:30:00+00:00")
        if start_utc <= ts <= end_utc:
            out.append(RawEvent(
                provider="fred", provider_event_id=f"{row.get('release_id')}:{d}",
                raw_name=name, country="US", scheduled_utc=ts))
    return out


class FredProvider:
    name = "fred"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def fetch_scheduled(self, start_utc: datetime, end_utc: datetime) -> list[RawEvent]:
        if not self.api_key:
            return []
        params = {
            "api_key": self.api_key, "file_type": "json",
            "include_release_dates_with_no_data": "true",
            "realtime_start": start_utc.date().isoformat(),
            "order_by": "release_date", "sort_order": "asc", "limit": 1000,
        }
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.get(_URL, params=params)
            if r.status_code >= 400:
                raise ProviderError(f"fred {r.status_code}")
            data = r.json()
        except ProviderError:
            raise
        except Exception as e:  # noqa: BLE001 - normalize to retryable
            raise ProviderError(f"fred: {e}") from e
        return parse_fred(data, start_utc, end_utc)
