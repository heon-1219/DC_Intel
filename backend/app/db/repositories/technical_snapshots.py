import json

# Map technical_snapshots scalar columns -> §10.1 payload keys (schema.md).
_SCALAR_MAP = {
    "rsi": "rsi_14", "ema_5": "ema_5", "ema_20": "ema_20", "ema_50": "ema_50",
    "ema_200": "ema_200", "macd": "macd_line", "macd_signal": "macd_signal",
    "macd_histogram": "macd_histogram", "bollinger_upper": "bb_upper",
    "bollinger_lower": "bb_lower", "bollinger_middle": "bb_middle",
}


async def upsert_snapshot(con, stock_id: int, bar_interval: str, timestamp: str,
                          payload: dict) -> None:
    """Insert (or overwrite on the same (stock, interval, timestamp)) one snapshot:
    scalar columns mapped from the payload + the full payload as indicators_json."""
    cols = ["stock_id", "timestamp", "bar_interval"] + list(_SCALAR_MAP) + ["indicators_json"]
    vals = [stock_id, timestamp, bar_interval]
    vals += [payload.get(src) for src in _SCALAR_MAP.values()]
    vals.append(json.dumps(payload))
    placeholders = ",".join("?" * len(cols))
    updates = ",".join(f"{c}=excluded.{c}" for c in cols
                       if c not in ("stock_id", "timestamp", "bar_interval"))
    await con.execute(
        f"INSERT INTO technical_snapshots ({','.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(stock_id, bar_interval, timestamp) DO UPDATE SET {updates}",
        vals,
    )
    await con.commit()


def _row_to_dict(row) -> dict:
    d = dict(row)
    d["indicators"] = json.loads(d.pop("indicators_json"))
    return d


async def get_latest_snapshot(con, stock_id: int, bar_interval: str) -> dict | None:
    cur = await con.execute(
        "SELECT * FROM technical_snapshots WHERE stock_id=? AND bar_interval=? "
        "ORDER BY timestamp DESC LIMIT 1",
        (stock_id, bar_interval),
    )
    row = await cur.fetchone()
    return _row_to_dict(row) if row is not None else None


async def get_recent_at(con, stock_id: int, bar_interval: str, as_of: str,
                        limit: int = 1) -> list[dict]:
    """The `limit` most recent snapshots with timestamp <= as_of, NEWEST FIRST.
    The #1 anti-leakage guard for M5/M6/M7: nothing after `as_of` is returned. Because the
    backfill/recompute jobs write one snapshot per bar, index 0 is bar t, index 1 is t-1,
    index 3 is t-3 — exact across session/weekend gaps (no timestamp arithmetic)."""
    cur = await con.execute(
        "SELECT * FROM technical_snapshots WHERE stock_id=? AND bar_interval=? AND timestamp<=? "
        "ORDER BY timestamp DESC LIMIT ?",
        (stock_id, bar_interval, as_of, limit),
    )
    return [_row_to_dict(r) for r in await cur.fetchall()]


async def get_latest_at(con, stock_id: int, bar_interval: str, as_of: str) -> dict | None:
    """The single most recent snapshot with timestamp <= as_of (as-of-bounded twin of
    get_latest_snapshot). Used by the feature builder (bar t) + M6 serving + M7 grading."""
    rows = await get_recent_at(con, stock_id, bar_interval, as_of, limit=1)
    return rows[0] if rows else None
