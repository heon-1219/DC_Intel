# DC Intel — Phase 4 Implementation Roadmap

> **STATUS (2026-06-22): 🎉 M0–M10 COMPLETE — the §11 launch gate PASSED.** Backend 569 pytest +
> frontend 44 vitest + `vite build` green, AND the full `docker compose up` stack runs on localhost
> with REAL data: /healthz {sqlite,redis,scheduler:true}, the Caddy-served SPA, search returns
> Samsung + live quotes (AAPL 298.01), /dashboard/indexes (5 tiles + intraday sparklines) and
> /dashboard/trending (10/10 movers) live, global rate-limit + request-id middleware verified.
> `/predict` is honestly disabled-with-note (no model clears the 52% gate on free data — a stronger
> retrain is in progress). See `handoff.md` for detail; `CLAUDE.md` for binding standards.

> **For agentic workers:** this is the **program roadmap** — the ordered milestones, dependencies, and test strategy. Each milestone gets its own detailed TDD plan (file `docs/superpowers/plans/YYYY-MM-DD-dc-intel-<Mn>-<name>.md`) written just before it is executed. The first one (`...-m0-foundation.md`) already exists. Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` per milestone plan.

**Goal:** Build the DC Intel stock-direction prediction platform v1 from the 12 approved `/docs`, runnable end-to-end on localhost for $0 against real data.

**Architecture:** Single `docker compose` stack on localhost — FastAPI (async) + in-process APScheduler jobs, SQLite (WAL, single writer), Redis cache, Caddy serving a React (Vite) SPA. Six per-timeframe models (logistic regression + XGBoost, ship the test winner) trained offline in `/ml`, served by the backend. Data pipeline is built and proven **before** the model.

**Tech stack:** Python 3.11, FastAPI, uvicorn, APScheduler, aiosqlite, redis-py, pydantic-settings, httpx, yfinance/pykrx/finnhub-python, fredapi, praw, transformers + sentence-transformers (zero-shot mDeBERTa), scikit-learn (logistic regression + calibration), xgboost, shap; React + Vite + TypeScript + TanStack Query; pytest + respx/vcr + fakeredis; Docker + Caddy.

---

## Governing constraints (owner standards — apply to every milestone)

1. **Completely free** — no paid APIs/hosting/tiers. Every dependency runs on a free tier or locally.
2. **International + detail-perfect UI** — green=up/red=down; clean, aligned, no layout shift, every component ships all states (`ui-ux.md` P9).
3. **Local-first** — runs via `docker compose up` on localhost; `DOMAIN=localhost`, alerts → local log, backups → local volume.
4. **Real data always** — the running app uses live data from real sources only; no mock/synthetic/seeded market data. *Tests* use fixtures **recorded from real API responses** (committed cassettes), never fabricated data — so tests are deterministic and free while the product stays real.

---

## Repository structure (locked here; tasks reference these paths)

```
dc-intel/
├─ backend/
│  ├─ app/
│  │  ├─ main.py              # app factory, router mounting, lifespan (starts APScheduler)
│  │  ├─ config.py            # pydantic-settings; all env vars (deployment-architecture.md §7.2)
│  │  ├─ db/
│  │  │  ├─ connection.py     # aiosqlite factory + WAL pragmas (schema.md §1.2)
│  │  │  ├─ migrate.py        # numbered-SQL runner + schema_migrations (schema.md §10)
│  │  │  └─ repositories/     # one module per table; insert/select/update only
│  │  ├─ cache/redis.py       # Redis client + {data, meta} envelope + is_stale helper
│  │  ├─ providers/           # external adapters behind interfaces: yfinance, pykrx, finnhub,
│  │  │                       #   fred, newsapi, reddit, stocktwits, kr_communities, twitter
│  │  │                       #   + retry (backend-design.md §9) + circuit breaker (data-sources.md §9)
│  │  ├─ services/            # price, indicators, sentiment, intel, calendar, features,
│  │  │                       #   prediction, accuracy  (pure-ish domain logic; unit-tested)
│  │  ├─ jobs/                # APScheduler defs: price_poller, indicator_calculator,
│  │  │                       #   sentiment_refresher, intel_scraper, calendar_sync,
│  │  │                       #   outcome_checker, model_retrain, ops (heartbeat/backup/win_rate_monitor)
│  │  ├─ routers/             # auth, stocks, dashboard
│  │  ├─ schemas/             # pydantic request/response models (backend-design.md shapes)
│  │  └─ core/                # auth (jwt+bcrypt), rate_limit (Redis fixed-window), logging,
│  │                          #   errors (envelope + catalog), degradation
│  ├─ migrations/             # 001_initial_schema.sql, 002_*.sql, ...
│  ├─ tests/                  # mirrors app/; unit + integration; cassettes/ for recorded API data
│  ├─ Dockerfile
│  └─ pyproject.toml
├─ ml/
│  ├─ features/               # feature builder — SHARED with backend serving (imported by both; DRY)
│  ├─ training/               # train LR + XGBoost per timeframe, calibration, walk-forward, ship gate
│  ├─ backtest/
│  └─ artifacts/              # 6 model files + manifest.json (mounted into backend MODEL_DIR)
├─ frontend/
│  └─ src/                    # components, screens, hooks, locales (ko/en), tokens, api client
├─ config/                    # seed_stocks.csv, outlets.yml, known_traders.yml, indexes.yaml, .env.example
├─ docs/                      # the 12 design docs (done) + superpowers/plans/
├─ docker-compose.yml         # backend + redis + web (Caddy)
├─ Caddyfile
└─ README.md
```

**DRY contract:** the **feature builder** (`ml/features/`) and the **`reasoning_json` schema** are shared by ML training and backend serving — one implementation, imported by both, so a model is always served the exact features it was trained on (`prediction-model.md` §8).

---

## Milestones (sequenced; each produces working, testable software)

### M0 — Foundation & scaffolding  ·  *detailed plan written*
**Delivers:** repo + backend skeleton, config, SQLite/WAL connection, migration runner + `001_initial_schema.sql` (all 9 tables), seed runner + `seed_stocks.csv`, Redis wrapper, `/healthz`, docker-compose, pytest harness.
**Depends on:** nothing.
**Key docs:** `schema.md` (§1–3, §10), `deployment-architecture.md` (§2, §7).
**Exit criteria:** `docker compose up` → `GET http://localhost/healthz` = 200; `pytest` green; migrations idempotent; the 9 tables + hot-query indexes exist; CHECK constraints reject bad timeframe/direction.
**Task breakdown:** see `2026-06-13-dc-intel-m0-foundation.md`.

### M1 — Market-data pipeline (prices/volume/fundamentals)
> **Delivered as two shippable slices** (writing-plans "split independent subsystems"): **M1a — live single-listing prices** (`…-m1a-prices.md`, *detailed plan written*) and **M1b — cross-market + FX** (`/prices-across-markets`, plan written after M1a executes). M1a ships working live `/price`; M1b adds FX + ADR-normalized cross-listing comparison on top.

**Delivers:** provider interface + retry/circuit-breaker; yfinance adapter (prices/volume), Finnhub (US) + pykrx (KRX) fallbacks; FX rates; `price_poller` job; `px:quote`/`px:fx` Redis cache with `data_as_of`+`is_stale`; `GET /stocks/{i}/price` and `/prices-across-markets` (FX-normalized diff per `ui-ux.md` §6.3 / `backend-design.md` §6.6).
**Depends on:** M0.
**Key docs:** `data-sources.md` (§1, §9), `backend-design.md` (§2, §5, §6.4, §6.6, §9), `schema.md` (`stocks`).
**Exit criteria:** live KRX+US quotes cached and served with honest staleness; cross-market diff matches the §6.3 worked example; provider failure trips the breaker and serves stale-flagged cache.
**Task breakdown (high level):** provider interface + fake provider for tests → retry policy (4 attempts, 0.5 s×2, jitter) → circuit breaker (Redis `cb:*`) → yfinance adapter (cassette-tested) → pykrx + Finnhub fallback chain → FX adapter → `price_poller` writing `px:quote:*` → price service + `is_stale` computation → `/price` endpoint → `/prices-across-markets` + FX/ADR-ratio diff math.

### M2 — Technical indicators
**Delivers:** RSI(14 Wilder), EMA(5/20/50/200), MACD(12/26/9), Bollinger(20, 2σ), `vol_z20`; bar-interval→timeframe mapping + lookback fetch; `technical_snapshots` writes; `indicator_calculator` job; deterministic signal-state machines + EN/KO evidence copy.
**Depends on:** M1 (needs bar data).
**Key docs:** `technical-indicators.md` (all), `prediction-model.md` §4.2, `schema.md` (`technical_snapshots`).
**Exit criteria:** each indicator reproduces the **worked numeric examples** in `technical-indicators.md` (TDD oracle); snapshots populated for all timeframes; signal→evidence-bullet handshake produces the canonical strings.

### M3 — Economic calendar
**Delivers:** `economic_events` population via Investing.com scrape (primary) + free composite fallback (FRED release dates + Finnhub calendars + `config` seed files for FOMC/BOK); impact-level assignment (override table > provider > default); actual-vs-forecast tracking; `calendar_sync` job (06:30 KST); `GET /dashboard/economic-calendar`; nightly event-study stats.
**Depends on:** M0 (M1 helps for the event-study price moves).
**Key docs:** `economic-calendar.md` (all), `data-sources.md` §2–3, `schema.md` (`economic_events`).
**Exit criteria:** next-7-day calendar served from real data; actual-vs-forecast JSON shape matches the doc; primary→fallback promotion works.

### M4 — Sentiment + market-intel pipeline
**Delivers:** `intel_scraper` ingestion (Reddit, StockTwits, DC Inside/Naver, **Twitter via logged-in session scraping** per `data-sources.md` §4.1), clean/dedup/cluster (MiniLM embeddings), credibility scoring (0–100, `market-intel-pipeline.md` §6), zero-shot mDeBERTa sentiment, CONFIRMED/UNCONFIRMED matching, anomaly flag; sentiment aggregation → `sentiment_logs`; `GET /dashboard/market-intel`.
**Depends on:** M1 (anomaly trigger needs price moves), M3 (anomaly excludes high-impact-event windows).
**Key docs:** `market-intel-pipeline.md`, `sentiment-pipeline.md`, `schema.md` (`market_intel`, `sentiment_logs`).
**Exit criteria:** real intel feed with credibility + confirmed badge; per-stock per-timeframe sentiment scores; X scraper self-disables cleanly when cookies absent; graceful degradation when a source is down.

### M5 — Feature builder + model training (`/ml`)
**Delivers:** shared feature builder (assembles the `prediction-model.md` §4.2 feature vector + `reasoning_json`); label definition + per-timeframe dead-bands; time-based split (no lookahead); train LR + XGBoost ×6 timeframes; Platt/isotonic calibration; walk-forward eval; **52% ship gate**; SHAP/coefficient contributions; `model_version` + `manifest.json` artifacts.
**Depends on:** M1–M4 (needs the feature inputs on real history).
**Key docs:** `prediction-model.md` (all), `win-loss-tracking.md` §11 (backtest boundary), `data-sources.md` (history backfill).
**Exit criteria:** six models trained on real 6–12-month history; per-timeframe held-out win rate reported; gate-passing models written to `ml/artifacts/`; gate-failing timeframes flagged (shipped disabled-with-note downstream).

### M6 — Prediction serving + auth + explainability
**Delivers:** `GET /stocks/{i}/predict?timeframe=` (load model, build features via the shared builder, calibrated confidence, neutral rule, top-3 evidence in canonical format), `reasoning_json` snapshot, `pred:*` cache (per-timeframe TTLs), immutable `predictions` row logging; auth (`/auth/register`, `/auth/login`, JWT `{sub,iat,exp}`, bcrypt), auth tiers.
**Depends on:** M5.
**Key docs:** `backend-design.md` §3, §6.5, §11, `prediction-model.md` §6/§8, `win-loss-tracking.md` §3.
**Exit criteria:** authed user gets a prediction + 3 same-direction evidence bullets; every served prediction logged with full `reasoning_json`; failed-gate timeframes return the documented "in testing" state.

### M7 — Win-loss tracking
**Delivers:** `outcome_checker` job (1-min poll; trading-day window clock; exit-price + 10-min stale defer; dead-band grading; freeze `high_impact_event_overlap`; Redis retry/park); `prediction_outcomes`; `GET /stocks/{i}/accuracy` + `/history`; weekly `feature_importance_logs` correlation job.
**Depends on:** M6 (and M3 for event overlap).
**Key docs:** `win-loss-tracking.md` (all), `backend-design.md` §6.11/§6.12/§7.
**Exit criteria:** predictions grade against real outcomes; public accuracy + per-user history served with the real numbers and `low_sample` state; event-window split works off the frozen flag.

### M8 — Dashboard endpoints + cross-cutting API
**Delivers:** `GET /dashboard/trending` (movers + `sparkline` + win-rate badge), `/dashboard/indexes` (KOSPI/NASDAQ_COMPOSITE/SP500/NIKKEI225/DAX), `GET /stocks/search` (+ live price overlay); Redis fixed-window rate limiting (`backend-design.md` §4); `{data, meta}` envelope + error catalog; structured logging + audit; degradation matrix wiring.
**Depends on:** M1, M2, M4, M7 (data for cards/badges).
**Key docs:** `backend-design.md` §4, §6.3, §6.7, §6.8, §10, `ui-ux.md` §7.2.
**Exit criteria:** all 12 endpoints live and contract-accurate; rate limits enforced; every response carries the envelope; degradation flags surface on source outage.

### M9 — Frontend (React Vite SPA)
**Delivers:** design tokens + KO/EN i18n; routing + auth screens; dashboard (trending carousel, indexes strip, calendar widget, intel feed); search + multi-exchange dropdown with inline cross-market diff; prediction view (direction/confidence/6-timeframe selector/≤3 evidence bars/accuracy badge/cross-market table/history+trend); per-widget polling aligned to backend TTLs; all component states (loading/empty/error/stale); P9 detail-perfect; accessibility (never color-alone).
**Depends on:** M8 (live API).
**Key docs:** `ui-ux.md` (all), `backend-design.md` §5.2/§6.
**Exit criteria:** full beginner-facing UI against the live API; green=up convention; no layout shift on polling updates; passes the §9 accessibility checks.

### M10 — Hardening & local-first deploy
**Delivers:** finalized `docker-compose.yml` (Caddy serves the Vite build on localhost) + `Caddyfile`; nightly local backup; monitoring + alerts to `logs/alerts.log`; `win_rate_monitor` job; README + env-setup guide (which free keys to get, how to extract X cookies); end-to-end smoke test = the `deployment-architecture.md` §11 local checklist.
**Depends on:** M9.
**Key docs:** `deployment-architecture.md` (all).
**Exit criteria:** `docker compose up` brings up the whole app on localhost with real data at $0; the §11 launch checklist passes.

---

## Dependency graph

```
M0 ─► M1 ─► M2 ─┐
       │        ├─► M5 ─► M6 ─► M7 ─► M8 ─► M9 ─► M10
       ├─► M3 ──┤
       └─► M4 ──┘     (M3, M4 can proceed in parallel once M1 exists;
                       M4 also reads M3 for the anomaly-flag event check)
```

## Global test strategy

- **TDD throughout** (writing-plans rule): failing test → minimal code → green → commit, in 2–5-min steps.
- **Unit tests** for pure logic — the highest-value, most deterministic layer: indicator formulas (oracle = the worked numeric examples in `technical-indicators.md`), credibility formula, dead-band `derive_direction`, FX/ADR diff math, calibration mapping, evidence-bullet rendering, window-clock computation. No I/O.
- **Integration tests** for jobs, repositories, and endpoints against a **temp SQLite file** + **fakeredis**; FastAPI via `httpx.ASGITransport`.
- **Real-data adapters** tested with **recorded cassettes** (respx/vcr) captured from real API responses and committed — deterministic, free, and faithful to real payloads (honors "real data always": fixtures are recorded real data, never fabricated). A small, separately-marked `@pytest.mark.live` suite hits the real APIs on demand to catch upstream drift.
- **Contract tests:** endpoint response shapes asserted against the `backend-design.md` examples; the shared feature builder asserted to emit exactly the `reasoning_json` schema both ML and serving expect.
- **No network in the default test run.** `pytest` must pass offline.
- **Commit discipline:** one commit per green step; conventional-commit messages.

## Conventions

- All timestamps stored UTC ISO-8601; display conversion is the frontend's job.
- Repositories expose only `insert` / `select` / scoped updates (`predictions` is insert + `set_checked_at` only — immutability).
- Every external call goes through the retry + circuit-breaker layer; no bare `httpx` calls in services.
- Secrets only via env (`config.py`); never committed. X session cookies and API keys live in `.env` (git-ignored).
- Each milestone ends on a green test suite and a working `docker compose up`.
