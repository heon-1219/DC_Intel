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


async def list_recent(con, since_utc: str, *, stock_id: int | None = None,
                      limit: int = 500) -> list[dict]:
    """Recent rows for the feed. stock_id=None -> all (incl. market-wide); a value -> that stock."""
    q = f"SELECT {_COLS} FROM market_intel WHERE created_at>=?"
    args: list = [since_utc]
    if stock_id is not None:
        q += " AND stock_id=?"
        args.append(stock_id)
    q += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    cur = await con.execute(q, args)
    return [dict(r) for r in await cur.fetchall()]


async def list_recent_by_stock(con, stock_id: int, since_utc: str) -> list[dict]:
    cur = await con.execute(
        f"SELECT {_COLS} FROM market_intel WHERE stock_id=? AND created_at>=? "
        "ORDER BY created_at DESC", (stock_id, since_utc))
    return [dict(r) for r in await cur.fetchall()]


async def get_by_id(con, intel_id: int) -> dict | None:
    cur = await con.execute(f"SELECT {_COLS} FROM market_intel WHERE id=?", (intel_id,))
    row = await cur.fetchone()
    return dict(row) if row else None


async def set_sentiment(con, intel_id: int, sentiment: str, confidence: float) -> None:
    await con.execute(
        "UPDATE market_intel SET sentiment=?, sentiment_confidence=? WHERE id=?",
        (sentiment, round(confidence, 2), intel_id))
    await con.commit()


async def set_cluster_and_credibility(con, intel_id: int, cluster_id: str,
                                      credibility_score: int) -> None:
    await con.execute(
        "UPDATE market_intel SET cluster_id=?, credibility_score=? WHERE id=?",
        (cluster_id, credibility_score, intel_id))
    await con.commit()
