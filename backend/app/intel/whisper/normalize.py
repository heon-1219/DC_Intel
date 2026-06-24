"""Parse a free-text EPS mention into a float in dollars. Handles the messy forms scraped from the
wild: '$1.51', '($0.12)' / 'loss of 12c' (accounting-negative), '12c' / '12 cents' (cents), '0.34 EPS'.
Returns None for non-numeric, percentages, or implausibly large magnitudes (a price/market-cap caught
by mistake). Pure + table-tested."""
import re

from app.intel import whisper_config as cfg

_CENTS = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:¢|cents?\b|c\b)")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def parse_eps(raw: str | None) -> float | None:
    if not raw:
        return None
    s = str(raw).strip().lower()
    if not s or "%" in s:  # percentages ("beat by 5%") are not EPS values
        return None

    cents = _CENTS.search(s)
    if cents:
        num = float(cents.group(1))
        magnitude = abs(num) / 100.0
        explicit_neg = num < 0
    else:
        m = _NUMBER.search(s.replace("$", ""))
        if not m:
            return None
        num = float(m.group(0))
        magnitude = abs(num)
        explicit_neg = num < 0

    negative = explicit_neg or ("(" in s and ")" in s) or "loss" in s
    value = -magnitude if negative else magnitude
    if abs(value) > cfg.PLAUSIBLE_ABS_CAP:  # not a quarterly EPS — likely a price/units error
        return None
    return value
