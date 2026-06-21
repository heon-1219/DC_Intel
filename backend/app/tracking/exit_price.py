"""M7b exit-price resolver (win-loss-tracking.md §5.2). The realized price as-of a prediction's
window close: the first persisted bar snapshot AT/AFTER window_closes_at (the window-close bar's
close, captured once recompute_indicators has written it), falling back to the freshest cached quote
if its as_of is at/after the close. Returns (price|None, status) with status 'ok' or 'pending'
(the exit bar isn't available yet -> the caller defers + retries). Prices are listing-currency
(FX never enters grading)."""
from app.db.repositories import technical_snapshots as trepo
from app.services import price as price_svc


async def resolve_exit_price(con, redis, ref, window_closes_at: str, interval: str):
    snap = await trepo.get_first_at_or_after(con, ref.id, interval, window_closes_at)
    if snap is not None:
        close = snap["indicators"].get("close")
        if close is not None:
            return close, "ok"
    try:
        cached = await price_svc.read_cached(redis, ref.symbol, ref.exchange)
    except Exception:   # noqa: BLE001 - Redis down -> treat as no quote, defer
        cached = None
    if cached and cached.get("price") is not None and (cached.get("as_of") or "") >= window_closes_at:
        return cached["price"], "ok"
    return None, "pending"
