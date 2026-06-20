"""Cross-market reference resolution + feature math (prediction-model.md §4.2 #13/#14, §4.3).

Pure (no I/O) so it's shared by training-backfill and live-serve. The two features:
  * xmkt_ref_return — % return of the resolved reference over its LATEST COMPLETED session as-of t0.
  * xmkt_corr_60d   — Pearson correlation of daily returns between the stock and its reference.

Leak-safety: we never use "the most recent reference row" — we use `cutoff_date(t0, ref_exchange)`,
the latest reference trading date whose session had fully closed by t0. v1 uses fixed UTC
session-close times (DST ignored) and same-date return alignment for the correlation (the precise
exchange-calendar lag is a documented refinement; the corr is a context weight, not a direction
signal). Display-side FX normalization (KRW=X) lives in the serving layer, not here."""
from datetime import datetime, timedelta, timezone

# Approx session-close in UTC per reference exchange (DST ignored in v1).
_SESSION_CLOSE_HOUR = {"US": 20.0, "JP": 6.0, "KR": 6.5}


def resolve_reference(stored: str | None) -> str:
    """stocks.xmkt_reference -> a yfinance ticker. Instrument form '005490:KRX' -> '005490.KS';
    empty/None -> SPY fallback (§4.3)."""
    if not stored:
        return "SPY"
    if stored.endswith(":KRX"):
        return stored.split(":", 1)[0] + ".KS"
    return stored


def reference_exchange(ref_ticker: str) -> str:
    """Classify a reference ticker to an exchange region for session-close timing."""
    if ref_ticker == "^N225":
        return "JP"
    if ref_ticker.endswith(".KS") or ref_ticker.startswith("^KS"):
        return "KR"
    return "US"


def cutoff_date(as_of: str, ref_exchange: str) -> str:
    """Latest reference trading DATE whose session-close (UTC) is <= as_of (anti-leakage)."""
    dt = datetime.fromisoformat(as_of.replace("Z", "+00:00")).astimezone(timezone.utc)
    close_hour = _SESSION_CLOSE_HOUR.get(ref_exchange, 20.0)
    as_of_hour = dt.hour + dt.minute / 60.0
    d = dt.date() if as_of_hour >= close_hour else dt.date() - timedelta(days=1)
    return d.isoformat()


def session_close_dt(date_str: str, ref_exchange: str) -> datetime:
    """UTC datetime when the reference's session on `date_str` closed (for staleness age)."""
    base = datetime.fromisoformat(date_str + "T00:00:00+00:00")
    return base + timedelta(hours=_SESSION_CLOSE_HOUR.get(ref_exchange, 20.0))


def compute_ref_return(closes_desc: list[tuple[str, float]]) -> float | None:
    """closes_desc newest-first (already <= cutoff). Return over the latest completed session."""
    if len(closes_desc) < 2:
        return None
    latest, prev = closes_desc[0][1], closes_desc[1][1]
    if not prev:
        return None
    return (latest - prev) / prev * 100.0


def daily_returns(closes: list[tuple[str, float]]) -> dict[str, float]:
    """{date -> daily return} from a (date, close) series (any order); skips the first date."""
    asc = sorted(closes, key=lambda p: p[0])
    out = {}
    for (d0, c0), (d1, c1) in zip(asc, asc[1:]):
        if c0:
            out[d1] = (c1 - c0) / c0
    return out


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx == 0 or vy == 0:
        return None
    return cov / (vx ** 0.5 * vy ** 0.5)


def compute_corr(stock_closes, ref_closes, *, window: int, min_overlap: int) -> float | None:
    """Pearson corr of daily returns over the trailing `window` common trading dates; None if the
    overlap is below `min_overlap` or either series is flat over the window."""
    sret, rret = daily_returns(stock_closes), daily_returns(ref_closes)
    common = sorted(set(sret) & set(rret))[-window:]
    if len(common) < min_overlap:
        return None
    return _pearson([sret[d] for d in common], [rret[d] for d in common])
