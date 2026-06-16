"""sentiment_logs repository (schema.md). One row per active stock per aggregation cycle:
the 24h headline score + the full source_breakdown_json (sentiment-pipeline.md §7)."""
import json

_COLS = "id, stock_id, timestamp, aggregate_sentiment_score, source_breakdown_json"


async def insert_log(con, stock_id: int, timestamp: str, aggregate_sentiment_score: float | None,
                     source_breakdown: dict) -> None:
    await con.execute(
        "INSERT INTO sentiment_logs (stock_id, timestamp, aggregate_sentiment_score, "
        "source_breakdown_json) VALUES (?,?,?,?) "
        "ON CONFLICT(stock_id, timestamp) DO UPDATE SET "
        "aggregate_sentiment_score=excluded.aggregate_sentiment_score, "
        "source_breakdown_json=excluded.source_breakdown_json",
        [stock_id, timestamp, aggregate_sentiment_score, json.dumps(source_breakdown)])
    await con.commit()


async def get_latest(con, stock_id: int) -> dict | None:
    cur = await con.execute(
        f"SELECT {_COLS} FROM sentiment_logs WHERE stock_id=? ORDER BY timestamp DESC LIMIT 1",
        (stock_id,))
    row = await cur.fetchone()
    if not row:
        return None
    d = dict(row)
    d["source_breakdown"] = json.loads(d.pop("source_breakdown_json"))
    return d
