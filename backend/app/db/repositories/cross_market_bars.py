"""cross_market_bars repository (M5d) — daily close series for cross-market reference instruments.
Feeds xmkt_ref_return / xmkt_corr_60d (prediction-model.md §4.2 #13/#14). Every read is bounded by
`max_date` (the as-of anti-leakage guard: the caller passes the latest reference trading date whose
session had fully closed by the prediction time t0)."""


async def upsert_bars(con, ref_ticker: str, rows: list[tuple[str, float]]) -> None:
    """rows = [(date 'YYYY-MM-DD', close), ...]; overwrite on (ref_ticker, date)."""
    await con.executemany(
        "INSERT INTO cross_market_bars (ref_ticker, date, close) VALUES (?,?,?) "
        "ON CONFLICT(ref_ticker, date) DO UPDATE SET close=excluded.close",
        [(ref_ticker, d, c) for d, c in rows])
    await con.commit()


async def get_recent_closes(con, ref_ticker: str, max_date: str, limit: int) -> list[tuple[str, float]]:
    """The `limit` most recent (date, close) with date <= max_date, NEWEST FIRST."""
    cur = await con.execute(
        "SELECT date, close FROM cross_market_bars WHERE ref_ticker=? AND date<=? "
        "ORDER BY date DESC LIMIT ?", (ref_ticker, max_date, limit))
    return [(r["date"], r["close"]) for r in await cur.fetchall()]
