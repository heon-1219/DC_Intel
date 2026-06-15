"""market_intel repository (schema.md). Rows are written by both the intel scrapers and the
sentiment news fetchers. M4a uses insert + recent queries; M4b/M4c/M4d add cluster/sentiment/
confirm updates."""
_COLS = ("id, stock_id, source, author_handle, url, content_snippet, posted_at, "
         "credibility_score, sentiment, sentiment_confidence, confirmed, cluster_id, created_at")

_OPTIONAL = ("stock_id", "url", "cluster_id", "credibility_score", "sentiment",
             "sentiment_confidence", "confirmed")


async def insert_intel(con, *, source: str, author_handle: str, content_snippet: str,
                       posted_at: str, **opt) -> int:
    """Insert one intel row (defaults from the schema fill credibility/sentiment/confirmed
    when omitted). Returns the new row id."""
    row = {"source": source, "author_handle": author_handle,
           "content_snippet": content_snippet, "posted_at": posted_at}
    for k in _OPTIONAL:
        if opt.get(k) is not None:
            row[k] = opt[k]
    cols = list(row)
    cur = await con.execute(
        f"INSERT INTO market_intel ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        list(row.values()))
    await con.commit()
    return cur.lastrowid


async def list_recent_by_stock(con, stock_id: int, since_utc: str) -> list[dict]:
    cur = await con.execute(
        f"SELECT {_COLS} FROM market_intel WHERE stock_id=? AND created_at>=? "
        "ORDER BY created_at DESC", (stock_id, since_utc))
    return [dict(r) for r in await cur.fetchall()]


async def get_by_id(con, intel_id: int) -> dict | None:
    cur = await con.execute(f"SELECT {_COLS} FROM market_intel WHERE id=?", (intel_id,))
    row = await cur.fetchone()
    return dict(row) if row else None
