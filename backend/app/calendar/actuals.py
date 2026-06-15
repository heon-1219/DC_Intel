"""Realized-vs-expected derivation (economic-calendar.md §7). Pure: builds the
actual_vs_forecast_json payload + market_read from the primary metric and the registry's
surprise_polarity / neutral_band_abs."""


def compute_surprise(actual, forecast, neutral_band: float, polarity: int):
    """Returns (surprise_abs, surprise_direction, market_read). market_read is None when
    actual is unknown; 'neutral' for in-line / unknown polarity."""
    if actual is None or forecast is None:
        return None, None, None
    s = round(actual - forecast, 6)
    if abs(s) <= (neutral_band or 0):
        direction = "in_line"
    else:
        direction = "above_forecast" if s > 0 else "below_forecast"
    if direction == "in_line" or not polarity:
        read = "neutral"
    else:
        read = "bullish" if (1 if s > 0 else -1) * polarity > 0 else "bearish"
    return s, direction, read


def _metric_meta(raw, entry: dict | None):
    if raw.extra.get("kind") == "earnings":
        return "eps", "Earnings per share", "주당순이익", "USD"
    if entry:
        key = entry.get("metric_key") or "value"
        return key, entry["titles"]["en"], entry["titles"]["ko"], (raw.unit or "%")
    return "value", raw.raw_name, None, (raw.unit or "%")


def build_avf(raw, entry: dict | None, source: str, released_at: str | None = None) -> dict | None:
    """None when the event carries no numeric data (e.g. a speech)."""
    is_earnings = raw.extra.get("kind") == "earnings"
    if not (entry or is_earnings or raw.forecast is not None or raw.actual is not None):
        return None
    polarity = int((entry or {}).get("surprise_polarity", 0) or 0)
    band = float((entry or {}).get("neutral_band_abs", 0) or 0)
    if is_earnings:                       # earnings beats are bullish regardless of registry
        polarity = 1
    key, label_en, label_ko, unit = _metric_meta(raw, entry)
    surprise_abs, direction, read = compute_surprise(raw.actual, raw.forecast, band, polarity)
    metric = {
        "key": key, "label_en": label_en, "label_ko": label_ko, "unit": unit, "primary": True,
        "forecast": raw.forecast, "previous": raw.previous, "revised_previous": None,
        "actual": raw.actual, "surprise_abs": surprise_abs, "surprise_direction": direction,
    }
    return {
        "metrics": [metric],
        "released_at_utc": released_at if raw.actual is not None else None,
        "source": source, "surprise_polarity": polarity,
        "market_read": read if raw.actual is not None else None,
    }
