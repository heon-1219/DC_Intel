from datetime import datetime, time
from zoneinfo import ZoneInfo

_KST = ZoneInfo("Asia/Seoul")
_ET = ZoneInfo("America/New_York")
_JST = ZoneInfo("Asia/Tokyo")
_CET = ZoneInfo("Europe/Berlin")
_US = {"NASDAQ", "NYSE", "AMEX"}


def market_state(exchange: str, now_utc: datetime) -> str:
    """One of open|closed|pre|post. v1: regular weekly sessions only (no exchange
    holidays — documented limitation, data-sources.md). pre/post are US-only."""
    if exchange == "KRX":
        local = now_utc.astimezone(_KST)
        if local.weekday() >= 5:
            return "closed"
        return "open" if time(9, 0) <= local.time() <= time(15, 30) else "closed"
    if exchange in _US:
        local = now_utc.astimezone(_ET)
        if local.weekday() >= 5:
            return "closed"
        t = local.time()
        if time(9, 30) <= t <= time(16, 0):
            return "open"
        if time(4, 0) <= t < time(9, 30):
            return "pre"
        if time(16, 0) < t <= time(20, 0):
            return "post"
        return "closed"
    return "closed"  # INDEX/OTC: no live-session concept in v1


def _jp_state(now_utc: datetime) -> str:
    """Tokyo (JPX) regular session: 09:00-11:30 + 12:30-15:00 weekday; lunch break -> closed."""
    local = now_utc.astimezone(_JST)
    if local.weekday() >= 5:
        return "closed"
    t = local.time()
    if time(9, 0) <= t <= time(11, 30) or time(12, 30) <= t <= time(15, 0):
        return "open"
    return "closed"


def _de_state(now_utc: datetime) -> str:
    """Frankfurt (XETRA) regular session: 09:00-17:30 weekday."""
    local = now_utc.astimezone(_CET)
    if local.weekday() >= 5:
        return "closed"
    return "open" if time(9, 0) <= local.time() <= time(17, 30) else "closed"


def index_state(region: str, now_utc: datetime) -> str:
    """Open/closed (or pre/post for US) for an index tile, resolved by the index's home REGION —
    index rows carry exchange='INDEX', so map KR->KRX, US->US, JP->Tokyo, DE->Frankfurt sessions
    (weekly only; exchange holidays remain out of v1, data-sources.md)."""
    if region == "KR":
        return market_state("KRX", now_utc)
    if region == "US":
        return market_state("NASDAQ", now_utc)
    if region == "JP":
        return _jp_state(now_utc)
    if region == "DE":
        return _de_state(now_utc)
    return "closed"
