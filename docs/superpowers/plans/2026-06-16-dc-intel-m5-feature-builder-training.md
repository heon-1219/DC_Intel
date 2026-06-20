# M5 — Feature Builder + Per-Timeframe Model Training (program plan + slices)

> REQUIRED SUB-SKILL: superpowers:executing-plans. M5 is large + ML-heavy → THREE slices: **M5a feature builder + label + config/deps → M5b training pipeline (split/train/calibrate/gate/explain/manifest) → M5c backfill real seed history + train the 6 models + report gates.** This doc embeds the researched contract (from prediction-model.md) so it is never lost.

**Owner decision (2026-06-16):** train on the **current 12-seed universe** with **real backfilled yfinance history** (expand universe later). All training data REAL (no synthetic). Gate-failing timeframes ship **disabled-with-note** honestly (expected with thin data). Offline tests use fixtures.

**Goal:** A shared as-of-bounded feature builder + a training CLI that fits/calibrates/gates 6 per-timeframe 3-class models on real backfilled history, writing versioned artifacts + manifests + feature-importance rows, with the explainability + reasoning_json contract M6 serving will consume.

**Architecture:** `backend/app/ml/` (features/, train.py, model store, explain) + `backend/app/tracking/labels.py` (the shared `derive_direction` + dead-bands, imported by training AND the M7 outcome checker). The feature builder is imported by BOTH training and M6 serving — identical `as_of`-bounded queries (the #1 anti-leakage guard). Models stored under `backend/models/{tf}/{model_version}/`.

## Deps (add to backend [ml] optional group; install on the py3.11 venv via uv)
`scikit-learn>=1.4`, `xgboost>=2.0`, `shap>=0.45`, `joblib` (pandas/numpy already present). Lazy-import in train/explain so the offline suite that injects fixtures doesn't always need them.

---
## RESEARCHED CONTRACT (verbatim essentials — source: prediction-model.md digest)

### Feature vector (§4.2) — 15 features, 8 evidence groups (CONTRACT order)
| # | name | group | source | transform |
|---|---|---|---|---|
|1|`rsi_14`|rsi|technical_snapshots|RSI(14) at tf bar interval|
|2|`rsi_slope_3`|rsi|technical_snapshots|rsi_14[t]−rsi_14[t−3 bars]|
|3|`ema_cross_state`|ema|technical_snapshots|ema_5_20_cross_dir ∈ {+1,−1,0}|
|4|`ema_bars_since_cross`|ema|technical_snapshots|bars_since_ema_5_20_cross (cap20) **signed by cross_state** → ±20|
|5|`macd_hist_norm`|macd|technical_snapshots|macd_histogram ÷ close|
|6|`macd_hist_delta`|macd|technical_snapshots|macd_hist_norm[t]−[t−1 bar]|
|7|`bb_position`|bollinger|technical_snapshots|%B, clip [−0.5,1.5]|
|8|`vol_z20`|volume|technical_snapshots|vol z-score, clip [−3,+6]|
|9|`sent_agg`|sentiment|sentiment_logs|timeframe_scores[tf].score ÷ 100 → [−1,1]; null/low_confidence → **missing**|
|10|`sent_delta_2h`|sentiment|sentiment_logs|sent_agg(now)−sent_agg(now−2h)|
|11|`econ_high_impact_6h`|econ_event|economic_events|1 if any high-impact relevant event in [t0−6h,t_close+6h] (country ∈ {listing,US})|
|12|`econ_impact_score`|econ_event|economic_events|Σ w_impact×proximity; w high=3/med=1/low=0.25; proximity 1 inside window else max(0,1−gap_h/6)|
|13|`xmkt_ref_return`|cross_market|yfinance/Redis|% return of cross-mkt ref over latest completed session (§4.3 resolution)|
|14|`xmkt_corr_60d`|cross_market|daily bars|Pearson corr of daily returns vs ref, 60d|
|15|`market_is_krx`|null(aux)|stocks|1 if KRX else 0 (never in evidence)|

Bar interval per tf: 1h→5m, 5h→15m, 24h→60m, 2d/3d/5d→1d. Cross-mkt ref resolution (§4.3): KRX+ADR→ADR; KRX no ADR→sector ETF (table, fallback SOXX/SPY); US-ADR→underlying KRX; other US→^N225. Unavailable → 0 + missing flag.

### Label (§3) — shared `app/tracking/labels.py`
`derive_direction(change_pct, band_pct) -> "up"|"down"|"neutral"` (up if >band, down if <−band, else neutral). `DEAD_BAND_PCT = {"1h":0.15,"5h":0.30,"24h":0.40,"2d":0.50,"3d":0.60,"5d":0.75}`. move_pct = (exit−entry)/entry×100, last-trade prices, listing currency (no FX). Window clock: 1h/5h regular-session hours only; 24h same-time next trading day; 2d/3d/5d N trading days later (`exchange_calendars` XKRX/XNYS). Band snapshotted into reasoning_json.neutral_band_pct (grading uses the snapshot).

### Split (§7.3) — chronological 70/15/15 (oldest→newest), NO shuffle. train=fit, val=hyperparams+calibration+τ_dir, test=once(gate). Sampling stride = horizon (no overlapping labels). Walk-forward = 4 expanding folds; gate on final fold; soft-warn if any fold <48%.

### Models (§5,§7.4): LR (multinomial, L2, class_weight balanced, StandardScaler, C∈{.01,.1,1,10}) + XGBoost (multi:softprob, max_depth∈{3,4,5}, lr .05, subsample .8, colsample .8, min_child_weight∈{5,20}, reg_lambda∈{1,5}, early stop ≤600). Ship higher test directional win rate; within 0.5pp → LR. Calibration on VALIDATION only: per-class OvR isotonic if ≥5000 val samples else Platt; renormalize 3 probs to 1. ECE(10 bins) on test → warn if >0.07.

### Ship gate (§7.6, CONTRACT): on final-fold test, post-calibration+neutral-rule: directional win rate ≥ **52%** AND directional coverage ≥ **30%** (realized neutral = LOSS for a directional call). Gate-fail → don't ship that tf (disabled-with-note). Promotion guard: ≥ max(52%, prod−0.5pp).

### Neutral rule (§5.3): displayed=argmax; if up/down but max(p_up,p_down)<τ_dir(0.45) → neutral, neutral_rule_applied. confidence=round(100×P(displayed)); cap 65 if any_stale.

### Explainability (§6): contribution c_i = coef[k][i]×x_std_i (LR) or SHAP_k (XGB), toward displayed class k. Group sums (exclude missing+aux), keep positive, top3 by magnitude, normalize to 100 via largest-remainder, drop <5% + renorm. Bilingual templates `{group}.{direction}` (24-entry table in digest). 

### reasoning_json (§8.1, schema_version 1): {schema_version, model_version, algorithm, timeframe, symbol, predicted_at, window_closes_at, entry_price, neutral_band_pct, direction, confidence, probabilities{raw,calibrated}, neutral_rule_applied, confidence_capped, features[]{name,group,value,baseline,contribution_signed,missing,stale}, evidence[]{rank,group,contribution_pct,template_key,text_en,text_ko}, data_staleness{...,any_stale}, high_impact_events[]{event_id,title_en,title_ko,country,impact,scheduled_at,relation}}.

### Artifacts (§7.8): `backend/models/{tf}/{model_version}/` with model.pkl, scaler.pkl (LR only), calibrators.pkl, manifest.json (all-fold metrics, ECE, gate result, train window, feature list + means/stds, neutral_band_pct, tau_dir, git commit, lib versions, created_at). model_version = `{tf}-{algo}-{YYYYMMDD}.{seq}` (algo lr|xgb). feature_importance_logs: one row/(model_version,feature) with prefix `model_coef:`/`model_gain:`; importance = |std coef| (LR) or mean|SHAP| val (XGB).

### Staleness (§4.5): thresholds prices 10m, technicals 15m, sentiment 30m, intel 30m, econ 48h, xmkt 36h (market-open). any_stale → cap conf 65.

### Missing data (§4.4): XGB → NaN (native); LR → impute train mean (stored) + StandardScaler; flag missing → excluded from evidence. (Sentiment missing on old backfilled rows is the common case — handled here, NO separate technical-only model.)

### config/ml.yaml tunables: dead-bands, tau_dir(.45 all), staleness_cap(65), evidence_min_pct(5), econ_proximity_hours(6), econ_impact_weights, xmkt_corr_window_days(60), ship_gate(win≥52,cov≥30), promotion_margin_pp(0.5), retrain Sun 03:00 KST. (sentiment_lookback/half-lives owned by sentiment-pipeline.md — don't duplicate.)

### Data availability / backfill (§7.1): history 6–12mo (1h/5h start ~60d, grow weekly). Backfill price/technical/cross-market from yfinance (24h/2d/3d/5d full; 1h/5h ~60d). Sentiment forward-only → missing on old rows. Same §4.4 missing path at train + serve.

---
## Slice breakdown

### M5a — feature builder + label + config + deps  ✅ COMPLETE (298 tests)
> Built: labels.py, ml.yaml + ml/config.py, [ml] deps, AND `app/ml/features/builder.py`. Wrinkles
> resolved: `close` added to `compute_indicators`; `technical_snapshots.get_latest_at`/`get_recent_at`
> + `sentiment_logs.get_latest_at` (as-of-bounded). Decisions: bar-interval-aware technicals
> staleness (daily-bar timestamps are bar dates); econ window uses nominal horizon hours; cross-market
> deferred → always None+missing (§4.4 imputes). 16 builder tests assert exact values + missing/stale
> + as-of bounding on a real temp SQLite DB.
- `app/tracking/labels.py` (`derive_direction`, `DEAD_BAND_PCT`) + test (oracle: bands).
- `config/ml.yaml` + `app/ml/config.py` loader (tunables above).
- deps: scikit-learn, xgboost, shap, joblib → [ml]; install on py3.11 venv.
- `app/ml/features/builder.py`: `build_features(con, redis, stock_ref, timeframe, as_of) -> (vector: dict[name->value|None], meta)`. Reads technical_snapshots (latest ≤ as_of for the tf's bar_interval), sentiment_logs (latest ≤ as_of; null/low_conf → missing), economic_events (relevant high-impact in window), cross-market (xmkt_ref_return/corr; missing→0+flag), stocks (market_is_krx). Emits `missing`/`stale` flags. **Every query bounded by as_of.** Test with a seeded temp DB + inserted snapshots → asserts exact feature values + missing flags + as_of bounding.

### M5b — training pipeline + explainability  ✅ COMPLETE (339 tests)
> Built all six modules with TDD: `ml/split.py` (chronological 70/15/15 + 4 expanding folds),
> `ml/gate.py` (neutral rule + win-rate/coverage + 52/30 gate + confidence + promotion guard),
> `ml/calibrate.py` (isotonic≥5000/Platt + renormalize + ECE), `ml/explain.py` (§6 evidence,
> 24-row bilingual templates, §8.2 oracle reproduced 43/38/19), `ml/dataset.py` (labels from
> backfilled snapshot `close`; bar-count window for 1h/5h/2d/3d/5d, wall-clock for 24h;
> stride=horizon), `ml/train.py` (LR+XGB grids → calibrate → gate → folds → winner → artifact
> + manifest + feature_importance; deterministic; CLI `python -m app.ml.train --timeframe`).
> Decisions: `HORIZON_BARS` added to shared labels.py; v1 uses config tau (no per-fold tune),
> fixed XGB n_estimators (no early stop), XGB **gain** for global feature_importance (SHAP retained
> for serve-time §6); model fit on train only. `.pkl` gitignored, manifests tracked.
- `app/ml/dataset.py`: assemble training samples (per stock, stride=horizon, features as-of + realized label via labels.derive_direction over future price). Needs historical price for labels (from backfilled bars).
- `app/ml/split.py`: chronological 70/15/15 + 4 expanding walk-forward folds (pure, tested).
- `app/ml/calibrate.py`: per-class isotonic/Platt + renormalize (tested on synthetic probs).
- `app/ml/gate.py`: directional win rate + coverage + apply neutral rule (τ_dir) — gate computation (oracle-tested).
- `app/ml/explain.py`: contributions (coef×std / SHAP) → group sums → top-3 → largest-remainder % → templates → evidence[] (oracle-tested with the §8.2 example: sentiment43/rsi38/ema19).
- `app/ml/train.py`: CLI `python -m app.ml.train --timeframe <tf> --as-of <date>` → resample→split→LR+XGB grids→calibrate→folds→gate→pick winner→write artifact+manifest+feature_importance. Lazy ML imports.
- Tests: split boundaries/no-overlap; calibration sums to 1; gate math (52/30, neutral=loss); explain largest-remainder + drop<5%; train smoke on a tiny in-memory dataset (asserts artifact+manifest written, deterministic).

### M5c — backfill real seed history + train the 6 models
- `app/ml/backfill.py`: for each seed stock × needed bar interval, fetch yfinance history (YFinanceBarProvider with extended windows), compute historical technical_snapshots at each bar (reuse `compute_indicators`), persist. (Sentiment/calendar absent historically → missing.)
- Run `train.py` for all 6 timeframes on the backfilled seed history; capture real win rates/coverage; write artifacts; gate-fail tfs flagged disabled.
- Report per-tf gate results honestly. Docker/live not required; this is a CLI/compute step. Commit artifacts? (manifests yes; .pkl maybe gitignored — decide: gitignore models/*.pkl, keep manifests.)

## Deferrals: refit on train+val (v1.1), per-stock models (v2), London GDR cross-mkt, sentiment historical backfill via Finnhub (partial), the weekly retrain cron wiring (M7/M10). Universe expansion beyond 12 seed (later).

## Self-review: feature contract (§4.2) fully captured; label/split/calibration/gate/explain/reasoning_json/artifact contracts captured verbatim; data-availability + missing-data path captured; slices each produce tested software; M5↔M7 shared label fn + M5↔M6 shared feature builder identified.
