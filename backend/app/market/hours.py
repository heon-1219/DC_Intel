from datetime import datetime, time
from zoneinfo import ZoneInfo

_KST = ZoneInfo("Asia/Seoul")
_ET = ZoneInfo("America/New_York")
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
