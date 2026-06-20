"""predictions repository (SERVING §9, win-loss-tracking §3.1). Every served prediction is inserted
synchronously (audit trail — never show an unlogged prediction). History is per-user and LEFT JOINs
prediction_outcomes (graded later by M7). reasoning_json is stored as JSON text (json_valid CHECK)."""
import json

_OUT_COLS = ("po.actual_direction AS po_dir, po.actual_price_change_percent AS po_pct, "
             "po.marked_correct AS po_correct, po.exit_price AS po_exit, po.created_at AS po_at")


async def insert_prediction(con, *, user_id, stock_id, timeframe, direction, confidence,
                            reasoning_json: dict, model_version, window_closes_at) -> int:
    cur = await con.execute(
        "INSERT INTO predictions (user_id, stock_id, timeframe, direction, confidence, "
        "reasoning_json, model_version, window_closes_at) VALUES (?,?,?,?,?,?,?,?)",
        (user_id, stock_id, timeframe, direction, confidence, json.dumps(reasoning_json),
         model_version, window_closes_at))
    await con.commit()
    return cur.lastrowid


async def find_audit_row(con, user_id, stock_id, timeframe, window_closes_at):
    cur = await con.execute(
        "SELECT id FROM predictions WHERE user_id=? AND stock_id=? AND timeframe=? "
        "AND window_closes_at=? LIMIT 1", (user_id, stock_id, timeframe, window_closes_at))
    return await cur.fetchone()


async def distinct_recent_stock_ids(con, user_id, since_iso) -> list[int]:
    cur = await con.execute(
        "SELECT DISTINCT stock_id FROM predictions WHERE user_id=? AND created_at>=?",
        (user_id, since_iso))
    return [r["stock_id"] for r in await cur.fetchall()]


async def list_user_history(con, *, user_id, stock_id, timeframe=None, status=None,
                            limit=20, offset=0):
    where = ["p.user_id=?", "p.stock_id=?"]
    params: list = [user_id, stock_id]
    if timeframe:
        where.append("p.timeframe=?")
        params.append(timeframe)
    if status == "pending":
        where.append("po.id IS NULL")
    elif status == "correct":
        where.append("po.marked_correct=1")
    elif status == "incorrect":
        where.append("po.marked_correct=0")
    base = ("FROM predictions p LEFT JOIN prediction_outcomes po ON po.prediction_id=p.id "
            f"WHERE {' AND '.join(where)}")
    cur = await con.execute(f"SELECT COUNT(*) AS c {base}", params)
    total = (await cur.fetchone())["c"]
    cur = await con.execute(
        f"SELECT p.id, p.timeframe, p.direction, p.confidence, p.reasoning_json, p.model_version, "
        f"p.window_closes_at, p.created_at, {_OUT_COLS} {base} "
        "ORDER BY p.created_at DESC, p.id DESC LIMIT ? OFFSET ?", params + [limit, offset])
    return total, [dict(r) for r in await cur.fetchall()]
