# M6 — Prediction serving + auth + explainability (program plan + slices)

> REQUIRED SUB-SKILL: superpowers:test-driven-development. Built just-in-time from a 5-agent
> contract study of backend-design.md / prediction-model.md / the existing code. M6 is request-path
> only (no new scheduler jobs). Reuses the M5 ML modules unchanged (feature builder, gate, calibrate,
> explain, ml/config) + the existing routers/repos/envelope.

**Goal:** A logged-in user can get an honest, explained short-term prediction for a stock+timeframe —
served ONLY for gate-passed timeframes (currently just **5d**), every other timeframe explicitly
disabled-with-note. Plus JWT auth, per-user prediction history, and the economic-calendar
"affects-your-stocks" overlay deferred from M3.

## Owner standards applied
FREE/local-first (JWT+bcrypt, SQLite, Redis cache, no paid services); REAL data (serve uses live
price cache + the real trained 5d artifact); honest (disabled-with-note, never a fake/stale/downgraded
prediction); international + bilingual error/evidence copy.

---
## Open-question RESOLUTIONS (v1 decisions — owner may override at the milestone)
1. **Rate-limiting scope (M6k):** ship the **security-binding throttles only** — login brute-force
   (per-IP 10/15min + per-email), register (5/hr/IP), predict (30/min/user), all **fail-open**.
   **Defer** the global per-IP/per-user middleware to **M10 (hardening)**. Rationale: the brute-force/
   abuse throttles are security-critical now; a global rate-limit middleware is hardening.
2. **Missing-feature `value` in reasoning_json:** store the value the model **actually consumed** —
   for LR, the imputed train-mean from `manifest.features[].mean`; `missing:true` still flags it. The
   UI renders missing as "—"/0. Rationale: fidelity to what produced the prediction.
3. **entry_price / predicted_at:** `entry_price` = last trade from the price cache
   `px:quote:{symbol}:{exchange}` at t0 (fallback: latest 1d snapshot close); `currency` =
   `StockRef.currency`; `predicted_at` = t0 (now). Both live ONLY in reasoning_json (no table column).
4. **window_closes_at clock (HIGHEST-RISK, v1 approximation):** dependency-free **business-day
   stepper** — 1h/5h = t0 + wall-clock hours; 24h = next trading day same time (skip Sat/Sun);
   2d/3d/5d = t0 + N business days (skip Sat/Sun). Holidays are absorbed by M7 grading ("first
   available price at/after window_closes_at"). **Exact holiday-aware exchange-calendar = documented
   refinement** (would add `exchange_calendars`). Flagged to owner — say the word for exact calendars.
5. **COMMON_PASSWORDS list:** bundle a curated common-passwords file (starter set, expandable);
   `validate_password_policy` rejects membership. Contract said "top-10k"; we bundle what's practical
   and note it's expandable.
6. **Coverage block:** derive from the feature builder's flags v1 — `reduced_coverage` = sentiment
   group missing; `sources_down` = [] (per-source sentiment health not surfaced at serve yet);
   `low_confidence` = reduced_coverage or thin-data timeframe. Full source-health = refinement.

---
## Serve-disabled behavior (the honesty core)
Only timeframes whose latest promoted artifact has `manifest.gate.passed == true` are servable
(today: **5d** only). `GET /stocks/{i}/predict?timeframe=<tf>` for any other tf →
**HTTP 503 MODEL_UNAVAILABLE** with bilingual message + `details.available_timeframes:['5d']`. NEVER a
null/stale/downgraded prediction; no predictions row inserted (nothing served). Distinct from
**503 SOURCE_DEGRADED** (a gate-PASSED tf whose price is >30min stale in market hours with no cache).

---
## ✅ STATUS: M6 COMPLETE — all 11 slices done (459 tests). Serving (5d enabled, rest
## disabled-with-note), auth (register/login/JWT), history, calendar overlay, rate-limit all live.

## Slices (each TDD, commit individually)
- **M6a — Auth core (pure):** `app/auth/security.py` (hash_password/verify_password bcrypt cost 12;
  encode_token/decode_token HS256, claims {sub,iat,exp}, 24h, no email) + `app/auth/passwords.py`
  (validate_password_policy: 8..72 bytes, ≥1 letter+≥1 digit, not-common) + bundled common-passwords.
- **M6b — Users repo + auth models:** `db/repositories/users.py` (create/get_by_email[NOCASE]/get_by_id)
  + `app/auth/models.py` (RegisterRequest/LoginRequest, preferred_language↔language map).
- **M6c — Auth deps:** `app/auth/deps.py` get_current_user (required→401) / get_current_user_optional
  (anon ok, present-but-invalid→401); Bearer header only; bilingual 401 envelope.
- **M6d — Auth router:** POST /auth/register (201, auto-login) + /auth/login (200); 409 EMAIL_TAKEN,
  422 VALIDATION_ERROR, 401 INVALID_CREDENTIALS (same for unknown-email/wrong-pw; timing-equalized
  via dummy bcrypt verify). Wire into main.create_app.
- **M6e — Model loader (gate-aware):** `app/ml/serving/loader.py` list_servable_timeframes /
  resolve_promoted (latest gate-passed version) / load_artifact (cached {model,scaler,calibrators,
  manifest}). Mirrors train.write_artifact layout.
- **M6f — Inference assembler:** `app/ml/serving/predict.py` run_inference → reasoning_json (§8.1):
  vectorize (LR impute mean+scale / XGB NaN) → predict_proba → apply_calibration → apply_neutral_rule
  → confidence (cap) → contributions (LR coef×std / XGB SHAP) → build_evidence → full reasoning_json
  (features[15], evidence[≤3], data_staleness, high_impact_events). + serve-time window_closes_at.
- **M6g — Predictions repo:** insert_prediction, find_audit_row, list_user_history (LEFT JOIN
  prediction_outcomes → realized_direction/move_pct/graded_at), distinct_recent_stock_ids (14d).
- **M6h — GET /stocks/{i}/predict:** auth-required; timeframe enum; per-tf cache TTL; 503
  MODEL_UNAVAILABLE for non-5d; 503 SOURCE_DEGRADED on stale price; ALWAYS audit-insert a row;
  evidence_summary join; coverage block.
- **M6i — Calendar affects overlay:** modify /dashboard/economic-calendar (optional auth) → per-user
  affects_your_stocks/match_level/matched_symbols with stock>sector>market precedence; per-user cache.
- **M6j — GET /stocks/{i}/history:** auth-required, per-user; timeframe/status filters; pagination;
  outcome mapping; empty (not 404) when none.
- **M6k — Rate limiter (security-binding subset):** `app/auth/ratelimit.py` fixed-window fail-open;
  wire login/register/predict throttles. (Global middleware → M10.)

## Integration points
main.create_app: include auth.router + predictions.router (no lifespan/scheduler change).
dashboard.economic_calendar: swap the hardcoded affects=None block (L95-97) for the M6i overlay.
predictions/prediction_outcomes/users tables already exist (001) — no migration. config already has
jwt_*/model_dir/rate_limit_enabled. Prefer make_envelope for new endpoints.

## Deferrals (noted): exact holiday-aware window clock; global rate-limit middleware (M10); full
sentiment source-health coverage; the M9 overnight-board UI; XGB SHAP path is built but 5d ships LR.
