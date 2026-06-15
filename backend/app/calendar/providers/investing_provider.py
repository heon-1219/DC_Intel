"""Investing.com economic-calendar scraper (economic-calendar.md §2 primary). Our own
low-frequency scraper of the public AJAX endpoint — realistic headers, NO detection-evasion.
Verified live 2026-06-16: needs X-Requested-With + a real UA; returns JSON whose 'data' is
an HTML <tr> fragment parsed by id attributes (brittle by design — alert on shape changes)."""
from datetime import datetime, timedelta, timezone

import httpx
from bs4 import BeautifulSoup

from app.calendar.models import RawEvent
from app.providers.retry import ProviderError

_URL = "https://www.investing.com/economic-calendar/Service/getCalendarFilteredData"
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "X-Requested-With": "XMLHttpRequest",   # MANDATORY — without it the endpoint 301s empty
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.investing.com/economic-calendar/",
    # Content-Type is set automatically by httpx for dict form data.
}
_TZ_SEOUL = 55   # Asia/Seoul = UTC+9 year-round (no DST) -> offsetSec is constant, DST-proof
_COUNTRY_ISO2 = {
    "United States": "US", "South Korea": "KR", "Japan": "JP", "Germany": "DE",
    "Euro Zone": "EU", "United Kingdom": "GB", "China": "CN", "Canada": "CA",
    "France": "FR", "Italy": "IT", "Spain": "ES", "Australia": "AU",
}


def _iso2(country_name: str) -> str:
    return _COUNTRY_ISO2.get(country_name.strip(), "GLOBAL")


def _num(tr, css: str) -> float | None:
    el = tr.select_one(css)
    if el is None:
        return None
    t = el.get_text(strip=True).replace("%", "").replace(",", "").replace("K", "").replace("B", "")
    try:
        return float(t)
    except ValueError:
        return None


def parse_rows(html: str, offset_sec: int) -> list[RawEvent]:
    """offset_sec = params.offsetSec from the response (local tz offset from UTC)."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[RawEvent] = []
    for tr in soup.select("tr.js-event-item"):
        rid = (tr.get("id") or "").replace("eventRowId_", "")
        dt_local = tr.get("data-event-datetime")          # 'YYYY/MM/DD HH:MM:SS' in requested tz
        if not dt_local:
            continue
        try:
            naive = datetime.strptime(dt_local, "%Y/%m/%d %H:%M:%S")
        except ValueError:
            continue
        scheduled_utc = (naive - timedelta(seconds=offset_sec)).replace(tzinfo=timezone.utc)
        flag = tr.select_one("td.flagCur span")
        country = _iso2(flag.get("title") if flag and flag.get("title") else "")
        imp_cell = tr.select_one("td.sentiment")
        img = (imp_cell.get("data-img_key") if imp_cell else "") or ""
        importance = int(img[-1]) if img.startswith("bull") and img[-1].isdigit() else None
        a = tr.select_one("td.event a")
        ev = tr.select_one("td.event")
        name = (a.get_text(strip=True) if a else (ev.get_text(strip=True) if ev else "")).strip()
        if not name:
            continue
        out.append(RawEvent(
            provider="investing_com", provider_event_id=rid or None, raw_name=name,
            country=country, scheduled_utc=scheduled_utc, importance=importance,
            actual=_num(tr, f"#eventActual_{rid}"), forecast=_num(tr, f"#eventForecast_{rid}"),
            previous=_num(tr, f"#eventPrevious_{rid}")))
    return out


class InvestingProvider:
    name = "investing_calendar"

    async def fetch_scheduled(self, start_utc: datetime, end_utc: datetime) -> list[RawEvent]:
        body = {
            "currentTab": "custom",
            "dateFrom": start_utc.date().isoformat(),
            "dateTo": end_utc.date().isoformat(),
            "timeZone": str(_TZ_SEOUL),
            "timeFilter": "timeOnly",
            "submitFilters": "1",
            "limit_from": "0",
        }
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as c:
                r = await c.post(_URL, headers=_HEADERS, data=body)
            if r.status_code != 200:
                raise ProviderError(f"investing {r.status_code}")
            payload = r.json()
        except ProviderError:
            raise
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"investing: {e}") from e
        offset_sec = int((payload.get("params") or {}).get("offsetSec", 32400))
        return parse_rows(payload.get("data", "") or "", offset_sec)
