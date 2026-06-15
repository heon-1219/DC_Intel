"""Finnhub earnings calendar (economic-calendar.md §2 piece 2). Free tier, US tickers.
EPS estimate/actual carried for the M3b actual_vs_forecast derivation."""
from datetime import datetime

import httpx

from app.calendar.models import RawEvent
from app.providers.retry import ProviderError

_BASE = "https://finnhub.io/api/v1"
# 'hour' (bmo/amc/dmh) -> a coarse UTC time placeholder (refined later); amc/unknown -> after close.
_HOUR_UTC = {"bmo": "13:00:00", "amc": "21:00:00", "dmh": "16:00:00", "": "21:00:00"}


def parse_earnings(data: dict, start_utc: datetime, end_utc: datetime) -> list[RawEvent]:
    out: list[RawEvent] = []
    for row in data.get("earningsCalendar", []) or []:
        sym, d = row.get("symbol"), row.get("date")
        if not sym or not d:
            continue
        hour = (row.get("hour") or "").lower()
        ts = datetime.fromisoformat(d + "T" + _HOUR_UTC.get(hour, "21:00:00") + "+00:00")
        if not (start_utc <= ts <= end_utc):
            continue
        out.append(RawEvent(
            provider="finnhub", provider_event_id=f"earnings:{sym}:{d}",
            raw_name=f"{sym} earnings", country="US", scheduled_utc=ts,
            forecast=row.get("epsEstimate"), actual=row.get("epsActual"),
            extra={"kind": "earnings", "symbol": sym, "exchange": "NASDAQ",
                   "eps_estimate": row.get("epsEstimate"), "eps_actual": row.get("epsActual"),
                   "revenue_estimate": row.get("revenueEstimate"),
                   "revenue_actual": row.get("revenueActual")}))
    return out


class FinnhubCalendarProvider:
    name = "finnhub"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def fetch_scheduled(self, start_utc: datetime, end_utc: datetime) -> list[RawEvent]:
        if not self.api_key:
            return []
        params = {"from": start_utc.date().isoformat(), "to": end_utc.date().isoformat(),
                  "token": self.api_key}
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.get(f"{_BASE}/calendar/earnings", params=params)
            if r.status_code >= 400:
                raise ProviderError(f"finnhub {r.status_code}")
            data = r.json()
        except ProviderError:
            raise
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"finnhub: {e}") from e
        return parse_earnings(data, start_utc, end_utc)
