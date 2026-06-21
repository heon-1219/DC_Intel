"""Intraday sparkline series for trending cards + index tiles (backend-design §6.7, ui-ux §7.2.1).
Owner decision (M8): fetch 5m bars on demand via YFinanceBarProvider and take the most-recent
session's closes (most-recent last, capped). No new bar store. Any fetch error -> [] (the UI renders
nothing rather than a fabricated line)."""


async def build_sparkline(bars_provider, ref, *, max_points: int = 78) -> list[float]:
    """Return up to `max_points` 5-minute closes of the most recent session, oldest→newest."""
    try:
        df = await bars_provider.fetch_bars(ref, "5m")
    except Exception:  # noqa: BLE001 - degrade to empty, never raise into the builder
        return []
    if df is None or len(df) == 0 or "close" not in df.columns:
        return []
    last_date = df.index[-1].date()                 # session = the latest bar's UTC date
    session = df[df.index.date == last_date]
    closes = [round(float(c), 4) for c in session["close"].tolist()]
    return closes[-max_points:]
