"""M5 feature builder — the 15-feature vector (prediction-model.md §4.2).

`build_features(con, redis, stock_ref, timeframe, as_of)` is imported by BOTH the training
pipeline (M5b) and live serving (M6). Using the IDENTICAL as-of-bounded queries on both sides
is the #1 anti-leakage guard: nothing dated after `as_of` may influence the vector.

Output contract:
  vector: dict {feature_name -> float | None}, in FEATURE_NAMES order. None == missing.
  meta:   {
    "as_of", "timeframe", "bar_interval",
    "missing": {name -> bool},          # value is None
    "stale":   {name -> bool},          # value present but underlying data older than threshold
    "any_stale": bool,                  # any non-missing feature stale -> M6 caps confidence at 65
    "high_impact_events": [ {event_id, title_en, title_ko, country, impact, scheduled_at, relation} ],
  }

Missing convention: a missing feature is ALWAYS None in the vector (and missing=True in meta).
The dataset/training layer (§4.4) maps None -> train-mean (LR) or NaN (XGB); serving renders it as
0 in reasoning_json. We never silently zero-fill a real feature.

Documented v1 choices (see docs .../m5-...md):
  * Cross-market features (xmkt_ref_return, xmkt_corr_60d) resolve the stock's reference
    (stocks.xmkt_reference, e.g. SOXX for Samsung/SK Hynix) and read its stored daily bars +
    the stock's own daily closes; missing when the reference history is absent/short. The
    correlation uses same-date alignment (the exact exchange-calendar lag is a documented refinement).
  * Technicals staleness is BAR-INTERVAL-AWARE. The §4.5 flat "technicals 15m" threshold is correct
    only for 5m bars; a daily-bar (2d/3d/5d) snapshot's timestamp is the bar DATE, so its age is
    always hours/days. We flag technicals stale when age > (one bar interval + the §4.5 grace),
    which reduces to ~15m for 5m bars and ~1 day for 1d bars. Sentiment/econ stay flat (not
    bar-tied). Economic-event timing within the horizon is NOT leakage: the calendar is published
    ahead of time; we read only impact_level/scheduled time/country, never the realized actuals.
"""
from datetime import datetime, timedelta, timezone

from app.db.repositories import cross_market_bars as cmrepo
from app.db.repositories import economic_events as erepo
from app.db.repositories import sentiment_logs as slrepo
from app.db.repositories import technical_snapshots as trepo
from app.ml.config import FEATURE_NAMES, load_ml_config
from app.ml.xmkt import (compute_corr, compute_ref_return, cutoff_date, reference_exchange,
                         resolve_reference, session_close_dt)

# Bar interval string -> seconds (technical_snapshots.bar_interval enum).
BAR_SECONDS = {"5m": 300, "15m": 900, "1h": 3600, "1d": 86400}

# Nominal prediction-horizon length per timeframe (wall-clock hours). Used ONLY to place the
# economic-event proximity window [as_of, as_of + horizon]. The label's exact trading-calendar
# window (§3) is a separate concern; wall-clock hours are a deliberate v1 approximation here.
HORIZON_HOURS = {"1h": 1, "5h": 5, "24h": 24, "2d": 48, "3d": 72, "5d": 120}

BB_CLIP = (-0.5, 1.5)        # %B clip range (§4.2 #7)


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _sent_agg(tf_entry: dict | None) -> float | None:
    """timeframe_scores[tf].score / 100 -> [-1, 1]; null score or low_confidence -> missing."""
    if not tf_entry or tf_entry.get("low_confidence"):
        return None
    score = tf_entry.get("score")
    if score is None:
        return None
    return max(-1.0, min(1.0, score / 100.0))


async def build_features(con, redis, stock_ref, timeframe: str, as_of: str):
    cfg = load_ml_config()
    interval = cfg["bar_interval"][timeframe]
    stale_sec = cfg["staleness_sec"]
    weights = cfg["econ_impact_weights"]
    prox_h = cfg["econ_proximity_hours"]
    as_of_dt = _parse(as_of)

    vector = {name: None for name in FEATURE_NAMES}
    missing = {name: True for name in FEATURE_NAMES}
    stale = {name: False for name in FEATURE_NAMES}

    def setf(name: str, value, *, is_stale: bool = False) -> None:
        vector[name] = value
        missing[name] = value is None
        stale[name] = bool(is_stale) and value is not None

    # --- technical (rsi_14, rsi_slope_3, ema_cross_state, ema_bars_since_cross,
    #                macd_hist_norm, macd_hist_delta, bb_position, vol_z20) -------------------
    snaps = await trepo.get_recent_at(con, stock_ref.id, interval, as_of, limit=4)
    if snaps:
        cur = snaps[0]["indicators"]
        tech_stale = (as_of_dt - _parse(snaps[0]["timestamp"])).total_seconds() > (
            BAR_SECONDS.get(interval, 0) + stale_sec["technicals"])

        setf("rsi_14", cur.get("rsi_14"), is_stale=tech_stale)

        if len(snaps) >= 4:
            r0, r3 = cur.get("rsi_14"), snaps[3]["indicators"].get("rsi_14")
            if r0 is not None and r3 is not None:
                setf("rsi_slope_3", r0 - r3, is_stale=tech_stale)

        cd = cur.get("ema_5_20_cross_dir")
        bs = cur.get("bars_since_ema_5_20_cross")
        if cd is not None:
            setf("ema_cross_state", float(cd), is_stale=tech_stale)
            if bs is not None:
                setf("ema_bars_since_cross", float(bs * cd), is_stale=tech_stale)  # signed; cd=0 -> 0

        mh, cl = cur.get("macd_histogram"), cur.get("close")
        if mh is not None and cl:
            setf("macd_hist_norm", mh / cl, is_stale=tech_stale)
            if len(snaps) >= 2:
                prev = snaps[1]["indicators"]
                mh1, cl1 = prev.get("macd_histogram"), prev.get("close")
                if mh1 is not None and cl1:
                    setf("macd_hist_delta", (mh / cl) - (mh1 / cl1), is_stale=tech_stale)

        bb = cur.get("bb_percent_b")
        if bb is not None:
            setf("bb_position", max(BB_CLIP[0], min(BB_CLIP[1], bb)), is_stale=tech_stale)

        setf("vol_z20", cur.get("vol_z20"), is_stale=tech_stale)  # already clipped at compute time

    # --- sentiment (sent_agg, sent_delta_2h) --------------------------------------------------
    log = await slrepo.get_latest_at(con, stock_ref.id, as_of)
    if log:
        sent_stale = (as_of_dt - _parse(log["timestamp"])).total_seconds() > stale_sec["sentiment"]
        tf_scores = log["source_breakdown"].get("timeframe_scores", {})
        sa = _sent_agg(tf_scores.get(timeframe))
        if sa is not None:
            setf("sent_agg", sa, is_stale=sent_stale)
            log2 = await slrepo.get_latest_at(con, stock_ref.id, _iso(as_of_dt - timedelta(hours=2)))
            if log2:
                sa2 = _sent_agg(log2["source_breakdown"].get("timeframe_scores", {}).get(timeframe))
                if sa2 is not None:
                    setf("sent_delta_2h", sa - sa2, is_stale=sent_stale)

    # --- economic events (econ_high_impact_6h, econ_impact_score) -----------------------------
    # Window [as_of, window_close]; binary/score scan the +/- proximity margin around it. Relevance
    # = event country in {listing region, US}. Always computable -> never "missing" (0 is a real 0).
    window_close = as_of_dt + timedelta(hours=HORIZON_HOURS[timeframe])
    lo = _iso(as_of_dt - timedelta(hours=prox_h))
    hi = _iso(window_close + timedelta(hours=prox_h))
    countries = [c for c in {stock_ref.region, "US"} if c]
    events = await erepo.list_in_range(con, lo, hi, country=countries)

    econ_stale = False
    try:
        synced = await redis.get("cal:last_synced_at")
    except Exception:   # noqa: BLE001 - Redis outage must not break feature building (train CLI/serve)
        synced = None
    if synced:
        econ_stale = (as_of_dt - _parse(synced)).total_seconds() > stale_sec["econ"]

    high_in_window = 0
    score = 0.0
    high_events: list[dict] = []
    for ev in events:
        impact = ev["impact_level"]
        et = _parse(ev["event_time"])
        if as_of_dt <= et <= window_close:
            prox, relation = 1.0, "inside_window"
        elif et < as_of_dt:
            prox = max(0.0, 1.0 - (as_of_dt - et).total_seconds() / 3600.0 / prox_h)
            relation = "within_6h_before"
        else:
            prox = max(0.0, 1.0 - (et - window_close).total_seconds() / 3600.0 / prox_h)
            relation = "within_6h_after"
        score += weights.get(impact, 0.0) * prox
        if impact == "high":
            high_in_window = 1
            high_events.append({   # reasoning_json §8.1 high_impact_events[] shape (relation = temporal)
                "event_id": ev["id"], "title_en": ev["event_name"], "title_ko": ev.get("title_ko"),
                "country": ev["country"], "impact": impact, "scheduled_at": ev["event_time"],
                "relation": relation,
            })
    setf("econ_high_impact_6h", float(high_in_window), is_stale=econ_stale)
    setf("econ_impact_score", float(score), is_stale=econ_stale)

    # --- cross-market (xmkt_ref_return, xmkt_corr_60d) ---------------------------------------
    # Resolve the reference (stocks.xmkt_reference), read its stored daily bars up to the latest
    # session that had CLOSED by as_of (leak-safe cutoff), and the stock's own daily closes; both
    # features are DAILY regardless of the model's bar interval. Absent/short data -> missing.
    ref = resolve_reference(stock_ref.xmkt_reference)
    ref_exch = reference_exchange(ref)
    corr_window = cfg["xmkt_corr_window_days"]
    ref_closes = await cmrepo.get_recent_closes(con, ref, cutoff_date(as_of, ref_exch),
                                                limit=corr_window + 5)
    xmkt_stale = False
    if ref_closes:
        age = (as_of_dt - session_close_dt(ref_closes[0][0], ref_exch)).total_seconds()
        xmkt_stale = age > stale_sec["xmkt"]
    rr = compute_ref_return(ref_closes)
    if rr is not None:
        setf("xmkt_ref_return", rr, is_stale=xmkt_stale)
    day_snaps = await trepo.get_recent_at(con, stock_ref.id, "1d", as_of, limit=corr_window + 5)
    stock_closes = [(s["timestamp"][:10], s["indicators"].get("close")) for s in day_snaps
                    if s["indicators"].get("close") is not None]
    corr = compute_corr(stock_closes, ref_closes, window=corr_window, min_overlap=30)
    if corr is not None:
        setf("xmkt_corr_60d", corr, is_stale=xmkt_stale)

    # --- auxiliary (market_is_krx) — never in evidence, never missing/stale -------------------
    setf("market_is_krx", 1.0 if stock_ref.exchange == "KRX" else 0.0)

    meta = {
        "as_of": as_of,
        "timeframe": timeframe,
        "bar_interval": interval,
        "missing": missing,
        "stale": stale,
        "any_stale": any(stale[n] for n in FEATURE_NAMES),
        "high_impact_events": high_events,
    }
    return vector, meta
