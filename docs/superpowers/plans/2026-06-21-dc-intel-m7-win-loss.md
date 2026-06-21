# M7 — Win-loss tracking (program plan + slices)

> REQUIRED SUB-SKILL: superpowers:test-driven-development. Built just-in-time from a contract study
> of win-loss-tracking.md + the existing code. Reuses labels.derive_direction (the shared training
> /grading contract), the predictions repo, technical_snapshots close, economic_events, make_envelope.

**Goal:** matured predictions get graded honestly into prediction_outcomes (reusing the SNAPSHOTTED
reasoning_json.neutral_band_pct so a band re-tune never changes past grades), and **public win
rates** are exposed from day one — the trust anchor of the product.

## Owner standards: FREE/local-first; REAL data (grades from persisted bar closes / live quote cache);
HONEST (strict 3-class equality, realized-neutral = loss for a directional call, parked rows excluded
from every metric, public win rates with a low-sample flag); international + bilingual errors.

## Open-question RESOLUTIONS (v1 defaults — owner may override)
1. **Exit-price granularity:** resolver uses the timeframe's FEED interval snapshot (ml.yaml
   bar_interval: 5d/3d/2d→1d, 24h→1h, 5h→15m, 1h→5m) close at/before t_close; quote-cache fallback.
   (In practice only 5d ships, so grades use 1d closes.) No dedicated OHLCV table in v1.
2. **Min sample:** single threshold `low_sample = graded_total < 20` (overall) + per-tf win_rate_pct
   null when graded < 20. The with-event/without-event split is NOT in the v1 public response.
3. **Stats caching:** yes — `acc:{symbol}:{exchange}:{tf|all}:{window}` TTL 300s, eager DEL on grade.
4. **Pending vs parked:** v1 `pending = count(checked_at IS NULL)` (DB-only). Parked rows are rare
   (split-suspects / 8-failed-retries) and counted in pending as a documented minor overcount; a
   parked-aware pending is a refinement.
5. **Warmup predictions:** DEFERRED (needs a /dashboard/trending list that doesn't exist yet).
6. **accuracy_report / retraining triggers:** DEFERRED (no dashboard sink / retrain orchestrator).
7. **Session-time staleness:** the 10-min stale guard uses WALL-CLOCK (exchange-calendar session-time
   is a refinement).

## Grading contract (the honesty core)
- maturity: `window_closes_at <= now AND checked_at IS NULL` (+ not parked, + retry-due).
- exit price = as-of `window_closes_at` (historical lookup → late grading is identical; backend-down
  recovery is free). `move_pct = 100*(exit-entry)/entry`, entry from reasoning_json.entry_price.
- `actual_direction = derive_direction(move_pct, reasoning_json.neutral_band_pct)` — SNAPSHOTTED band.
- `marked_correct = 1 iff predictions.direction == actual_direction` (strict 3-class, no partial).
  Realized neutral is a LOSS for an up/down call; correct only for a neutral call.
- split-suspect: `abs(move_pct) > 35` → park (manual backfill only).
- transient price unavailable/stale → retry backoff [5,10,20,40,80,160,320,640] min → park after 8.
- parked rows: no outcome, checked_at stays NULL, excluded from every metric denominator.

## Slices (each TDD, commit-able)
- **M7a** predictions repo: `find_due`, `insert_outcome` (UNIQUE prediction_id), `mark_checked`.
- **M7b** `tracking/exit_price.py` resolve_exit_price → (price|None, status ok|stale|unavailable).
- **M7c** `tracking/grade.py` grade_prediction (move_pct, snapshotted-band direction, marked_correct,
  split-suspect park signal, high_impact_event_overlap) + relevant_countries(exchange).
- **M7d** `tracking/retry.py` Redis retry/park (backoff, parked set, fail-open).
- **M7e** `jobs/outcome_checker.py` run_outcome_checker: scan due → resolve → grade-or-defer-or-park →
  txn(insert_outcome+mark_checked) → clear_retry → DEL acc:{symbol}:{exchange}:* . + CLI.
- **M7f** wire outcome_checker into scheduler (1-min) + main lifespan.
- **M7g** accuracy_stats repo (§6.4 SQL: de-dup MAX over (tf,direction,window_closes_at); overall +
  per-tf; directional win-rate; pending; neutral count; window 30d/90d/all by created_at).
- **M7h** public `GET /stocks/{i}/accuracy` (NO auth; §8.2 shape; low_sample; by_timeframe; optional
  by_model_version).
- **M7i** accuracy Redis cache (read/write-through, fail-open, shares M7e's DEL key scheme).
- **M7j** `tracking/backfill.py` operator CLI to grade parked rows (manual price; bypass split-park).
- **M7k** `jobs/feature_correlation.py` weekly (Sun 03:30 UTC) point-biserial of features vs
  marked_correct → feature_importance_logs `outcome_corr:` (analytics; lowest priority).

## Integration: predictions repo grows (no migration — predictions/prediction_outcomes +
idx_predictions_due/accuracy already in 001). scheduler.py JOB_INTERVALS['outcome_checker']=1 +
JOB_CRONS['feature_correlation']. main lifespan closures. /accuracy added to stocks.py (public).
