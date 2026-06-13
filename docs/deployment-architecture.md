# DC Intel — Deployment & Production Architecture (v1)

**Status:** v1 spec · **Last updated:** 2026-06-12
**Related docs:** `data-sources.md` (external APIs, circuit breakers, degradation map §9), `sentiment-pipeline.md` (sentiment jobs, classifier, its Redis keys), `technical-indicators.md` (indicator computation), `schema.md` (table definitions), `backend-design.md` (endpoint contracts, job registry), `prediction-model.md` (models, training, ship gate).

This document specifies how DC Intel runs in production: the process model, database, cache, hosting, containers, configuration, auth, rate limiting, monitoring, and graceful degradation. It is written so a single engineer can stand up production from this doc plus `.env.example`.

**Sizing assumptions (v1):** ~50 tracked stocks (per `data-sources.md` §8), low-hundreds of registered users, **local-first (single machine), $0 hosting** (§5). Every design choice below prefers the simplest thing that survives a data-source outage and a process restart.

---

## 1. System overview

One machine (local-first, §5), one `docker compose` stack, three containers:

| Container | Image | Role |
|---|---|---|
| `backend` | custom (Python 3.11) | FastAPI + uvicorn **and** APScheduler jobs, all in **one process** |
| `redis` | `redis:7-alpine` | Hot cache, rate-limit counters, circuit-breaker state, job heartbeats |
| `web` | custom (Caddy 2 + built React assets) | TLS termination, static SPA serving, reverse proxy to `backend` |

### Deployment / component diagram

Thick solid arrows (`==>`) are the **real-time request path** (user-facing, latency-sensitive). Dotted arrows (`-.->`) are **batch processes** (background jobs on the canonical cadences).

```mermaid
flowchart TB
    subgraph EXT["External data sources (see data-sources.md)"]
        YF["Yahoo Finance (yfinance)"]
        FH["Finnhub (news + quote fallback)"]
        FR["FRED (macro)"]
        CAL["Investing.com calendar scrape"]
        SOC["Reddit / StockTwits / DC Inside / Naver"]
    end

    subgraph VM["Local-first — docker compose on localhost (v1, $0); free-cloud path optional (§5)"]
        subgraph BE["backend container — ONE process (single SQLite writer)"]
            SCHED["APScheduler job groups:
            price_poller · indicator_calculator
            sentiment_refresher · intel_scraper
            calendar_sync · outcome_checker · model_retrain
            + ops jobs (win_rate_monitor, backup, heartbeat)"]
            API["FastAPI (async) on uvicorn
            --workers 1"]
        end
        R[("Redis 7
        cache · rate limits · breakers")]
        DB[("SQLite (WAL)
        /data/dcintel.db")]
        CADDY["web container — Caddy 2
        TLS + React static build
        reverse proxy"]
    end

    U["Browser — React SPA
    (Vite build, polling)"]

    YF -.->|"1–5 min, batched"| SCHED
    FH -.->|"10 min news / 5 min fallback quotes"| SCHED
    FR -.->|daily| SCHED
    CAL -.->|daily| SCHED
    SOC -.->|"5–10 min"| SCHED

    SCHED -.->|write-through| R
    SCHED -.->|persist| DB

    U ==>|HTTPS 443| CADDY
    CADDY ==>|"/auth /stocks /dashboard /healthz"| API
    API ==>|cache reads| R
    API ==>|"reads + the only writer"| DB
```

Two paths never block each other: a slow scrape cycle cannot delay an API response (jobs run on the asyncio loop with bounded runtimes, `max_instances=1, coalesce=True`), and an API traffic spike cannot starve jobs (jobs are scheduled, not request-triggered — except the documented on-demand indicator path in `technical-indicators.md` §10).

---

## 2. Database: SQLite v1, PostgreSQL upgrade path

### 2.1 v1: SQLite in WAL mode, single-writer

- **File:** `/data/dcintel.db` (named Docker volume `dbdata`, mounted into `backend` only — no other container can touch it).
- **PRAGMAs applied on every connection** (by the connection factory; same list as `backend-design.md` §11 and `schema.md` §1.2):

```sql
PRAGMA journal_mode = WAL;        -- readers never block the writer
PRAGMA synchronous = NORMAL;      -- safe with WAL, much faster than FULL
PRAGMA busy_timeout = 5000;       -- wait up to 5 s on lock instead of erroring
PRAGMA foreign_keys = ON;
```

- **Single-writer pattern, enforced by the process model:** all writes — API requests *and* every APScheduler job — happen inside the one `backend` process, because the scheduler is in-process (canonical decision). Therefore uvicorn **must run with `--workers 1`**. This is not a tunable: a second worker process would (a) duplicate every scheduled job and (b) introduce a second SQLite writer. Concurrency comes from `async`/`await`, which comfortably handles v1 traffic (the workload is cache reads + occasional inserts).
- **Access layer:** raw parameterized SQL behind a repository pattern (one module per table, per `schema.md` §11.2), with `aiosqlite` for async access. The DDL itself is owned by `schema.md` §3 and applied via migrations (§2.2); using only its portable types keeps the PostgreSQL port mechanical (`schema.md` §11.1 type map). All timestamps stored as **UTC** ISO-8601; conversion to KST/ET happens in the frontend.
- **Tables:** the canonical seven — `users`, `stocks`, `predictions`, `prediction_outcomes`, `sentiment_logs`, `economic_events`, `technical_snapshots` — plus the two documented supplementary tables `feature_importance_logs` and `market_intel`. Definitions live in `schema.md`; this doc only owns where the file lives and how it is initialized, migrated, and backed up.

### 2.2 Initialization & migrations

**Migrations are owned by `schema.md` §10: numbered, forward-only raw-SQL files applied by a small custom runner** (`app/db/migrate.py`, ~25 lines, tracking applied versions in the `schema_migrations` table). We deliberately do **not** use Alembic in v1 — the v1 store is a single SQLite file and the raw-SQL runner is simpler to read and review; Alembic is reconsidered only as part of the PostgreSQL upgrade (§2.4), not before.

- Migration files live in `backend/migrations/`, numbered like `001_initial_schema.sql` (the §3 DDL in `schema.md`), `002_*.sql`, … and reviewed like code.
- **SQLite-isms to respect in every migration** (`schema.md` §10.3): SQLite has no `ALTER COLUMN`/`DROP COLUMN` for arbitrary changes, so column reshapes use the create-new-table → copy → drop → rename dance inside one migration file; never rely on PostgreSQL-only types or server-side defaults SQLite can't express.
- **Container start sequence** (the `backend` entrypoint, in order):
  1. `python -m app.db.migrate` — runs `migrate(DATABASE_URL)`; idempotent (skips versions already in `schema_migrations`), creates the DB file on first boot.
  2. `python -m app.seed` — inserts the tracked-stock universe into `stocks` from `data/seed_stocks.csv` **only if the table is empty** (symbol, exchange, names KO/EN, `yfinance_ticker`, `finnhub_ticker`).
  3. `exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1`
- A failed migration aborts startup loudly (the container exits, `restart: unless-stopped` retries, the health check stays red). Never start the API against a half-migrated schema.

### 2.3 Backups

SQLite's single file is an operational gift — use it.

- Nightly APScheduler job `db_backup` at **04:30 KST** (quietest window across KRX/US sessions): `VACUUM INTO '/data/backups/dcintel-YYYYMMDD.db'` (safe online copy, never `cp` a live WAL database). **v1 (local-first): the snapshot stays in the local `/data/backups` volume** — $0, no cloud account. If `BACKUP_BUCKET` is set (optional, only for a cloud deploy), the snapshot is also uploaded to GCS via `google-cloud-storage`. Retention: 14 daily + 8 weekly.
- Restore drill (do it once before launch): download snapshot → stop `backend` → replace `/data/dcintel.db` (delete stale `-wal`/`-shm` files) → start. Target RPO: 24 h, acceptable for v1 since all market data is re-fetchable; the only irreplaceable rows are `users`, `predictions`, `prediction_outcomes`.
- **Nicer option, noted not required:** [Litestream] sidecar for continuous WAL replication to GCS (~$0, RPO seconds). Adopt if the 24 h RPO ever feels scary.

### 2.4 PostgreSQL upgrade path (documented, not built)

Trigger to upgrade — any one of: sustained write contention (`busy_timeout` warnings in logs), need for >1 API process, tracked stocks ≳ 300, or moving jobs to Celery workers (multiple writers by definition).

What changes, exactly:

| Layer | v1 (SQLite) | After upgrade (PostgreSQL 16) |
|---|---|---|
| Connection | `DATABASE_URL=sqlite+aiosqlite:////data/dcintel.db` | `DATABASE_URL=postgresql+asyncpg://dcintel:***@db-host:5432/dcintel` — **the only code-adjacent change** if §2.1 portability rules were followed |
| Concurrency | 1 process, 1 writer, WAL readers | Connection pool (start: `pool_size=10, max_overflow=5`); `uvicorn --workers N` becomes legal **only after** the scheduler moves out of the API process (Celery beat or a dedicated scheduler container) — otherwise jobs duplicate |
| Migrations | Same numbered SQL files replayed by `app/db/migrate.py` against the new DB (`schema.md` §10) | The runner stays; from this point new migration files may use PG features behind a dialect check, or the team adopts Alembic if the migration set outgrows raw SQL |
| Data move | — | One-off script: read SQLite via SQLAlchemy, bulk-insert to PG in FK order (`users`, `stocks` → `predictions` → the rest); or `pgloader`. Verify row counts per table, then reset PG sequences |
| PRAGMAs | §2.1 connect-event handler | Handler is dialect-gated (`if engine.dialect.name == "sqlite"`), so it silently no-ops on PG |
| Backups | `VACUUM INTO` + GCS | `pg_dump` nightly or managed Cloud SQL automated backups |

---

## 3. Backend process model

- **Python 3.11+, FastAPI (async), uvicorn**, single process (`--workers 1`, see §2.1).
- **APScheduler (`AsyncIOScheduler`) in-process**: started in the FastAPI lifespan handler, shares the event loop. Every job is declared `max_instances=1, coalesce=True, misfire_grace_time=60` so a slow cycle never stacks and a restart never replays a backlog.
- Blocking work inside jobs (pandas indicator math, the sentiment classifier forward pass, bcrypt) runs via `asyncio.to_thread` / a small `ThreadPoolExecutor` so the event loop keeps serving requests. The sentiment classifier (see `sentiment-pipeline.md`) is the heavyweight resident: budget **~2 GB RSS** for the backend container.
- **Scale-up path (documented, not built):** Celery workers + Celery beat with Redis as broker. The job functions are written as plain async/sync callables registered with the scheduler, so the move is "wrap the same functions as Celery tasks" — no business-logic rewrite. This is the same trigger point as the PostgreSQL upgrade (§2.4); do both together, since Celery workers are concurrent writers.

### 3.1 Canonical cadences → background jobs

This table restates the canonical cadences and maps each **job group** (names from `data-sources.md` §0) to its concrete APScheduler job ids (fine-grained ids from `sentiment-pipeline.md` §10 and `technical-indicators.md` §10).

| Canonical cadence | Job group | Concrete APScheduler job id(s) | Schedule detail |
|---|---|---|---|
| Stock prices every 1–5 min | `price_poller` | `poll_prices_krx`, `poll_prices_us`, `poll_indexes` | 1 min while the exchange is open (KRX 09:00–15:30 KST; NYSE/NASDAQ 09:30–16:00 ET), 5 min US extended hours, paused when closed; one **batched** yfinance call per exchange per cycle |
| Technical indicators every 5 min | `indicator_calculator` | `recompute_indicators` (id per `technical-indicators.md`), `recompute_daily_snapshot` | every 5 min during any tracked session; `1d` snapshot after each home-exchange close |
| Sentiment refresh every 10–15 min | `sentiment_refresher` | `fetch_finnhub_news` (10 min), `fetch_newsapi` (hourly — NewsAPI free tier is ~24 h delayed, `data-sources.md` §5.2), `aggregate_sentiment` (10 min, +2 min offset) | per `sentiment-pipeline.md` §10 (the only three jobs that pipeline registers; author-accuracy upkeep is the daily `intel_author_stats` job under `intel_scraper` / aux jobs, owned by `market-intel-pipeline.md` §14) |
| Social-media intel scrape every 5–10 min | `intel_scraper` | `intel_scrape_reddit` (5 min), `intel_scrape_stocktwits` (5 min, +2 min offset), `scrape_kr_communities` (10 min), `intel_scrape_twitter` (10 min, **on by default** via logged-in session scraping — registered when `TWITTER_ENABLED=true` (default) and session cookies are present; self-disables if not) | job ids per `market-intel-pipeline.md` §14; cadences per `data-sources.md` §4 |
| Economic calendar daily | `calendar_sync` | `sync_calendar` (06:30 KST), `sync_fred` (07:00 KST) | per `data-sources.md` §§2–3 |
| Outcome check when each window closes | `outcome_checker` | `outcome_checker` | **every 1 min** (`max_instances=1, coalesce=True`); grades every prediction whose `window_closes_at` has passed and isn't yet graded, over the partial `idx_predictions_due` index; defers grading if the reference price is stale (per `backend-design.md` §7 / `win-loss-tracking.md` §5.4) |
| Weekly model retrain | `model_retrain` | `model_retrain` | weekly **Sun 03:00 KST** (both markets closed); walk-forward retrain + promotion guard (`prediction-model.md` §7.7); failure → `ERROR` + alert, production keeps the old artifact |
| — (ops, this doc) | ops | `win_rate_monitor` (daily 07:30 KST), `db_backup` (daily 04:30 KST), `heartbeat` (every 1 min), `metrics_rollup` (hourly) | §8 |

> Naming note (cross-doc contract): the **group name** for the indicator work is `indicator_calculator` (per `data-sources.md` §0); the **APScheduler job id** is `recompute_indicators` (per `technical-indicators.md`). Both names refer to the same work; use the group name in cross-doc prose and the job id in code/logs.

---

## 4. Frontend

- **React + Vite**, mobile-first responsive SPA, Korean/English. Output of `vite build` is a folder of static files — there is **no Node server in production**.
- Built inside the `web` image (multi-stage Dockerfile: `node:20-alpine` build stage → `caddy:2-alpine` final stage with `dist/` baked in). The deployed artifact is immutable; redeploying the frontend = rebuilding one image.
- **Caddy** serves it and reverse-proxies the API **same-origin**, which keeps the canonical endpoint paths exactly as `backend-design.md` defines them (no `/api` prefix invented at deploy time) and makes CORS a dev-only concern:

```text
# Caddyfile
{$DOMAIN} {
    encode gzip zstd

    @api path /auth/* /stocks/* /dashboard/* /healthz
    handle @api {
        reverse_proxy backend:8000
    }

    handle {
        root * /srv
        try_files {path} /index.html   # SPA fallback for client-side routes
        file_server
    }

    header /assets/* Cache-Control "public, max-age=31536000, immutable"  # Vite-hashed files
    header /index.html Cache-Control "no-cache"
}
```

- **v1 (local-first):** Caddy serves the SPA over plain HTTP on `localhost` (`DOMAIN=localhost`) — no DNS, no certificate, $0. TLS is unnecessary on a local machine. **Only if** the optional free-cloud demo (§5.3) is ever set up does Caddy provision and renew **Let's Encrypt TLS automatically**, the one prerequisite then being a DNS A record pointing a real `DOMAIN` at the host.
- **Polling (v1 real-time strategy):** the SPA polls `GET /dashboard/*` every 60 s and the currently-viewed stock's price every 30 s during market hours (backed entirely by Redis cache hits — see §6; each poll is one Redis `GET`, no upstream calls). WebSocket push is the documented v2 replacement; nothing in this architecture blocks it (uvicorn already speaks WebSocket).
- Dev mode: Vite dev server on `:5173` talking to uvicorn on `:8000` cross-origin — the **only** reason `CORS_ORIGINS` exists (§9). Production keeps CORS disabled (same-origin).

---

## 5. Hosting — local-first, completely free (owner decision)

**Owner standard: v1 must be completely free, and local-first.** v1 therefore runs on the developer's own machine via `docker compose` (the §7 stack on `localhost`) at **$0**, with the **full** multilingual sentiment classifier (the local machine has the RAM). No paid cloud service is adopted in v1. A future free *cloud* path is documented below so a hosted demo is possible without spending money — but it is a deliberate **feature-cut**, not the v1 target.

Constraints that drive the choice:

1. **RAM ≈ 3 GB** to run everything *including* the full sentiment model — trivially met on a laptop/desktop; the binding constraint only on tiny free cloud instances.
2. **Persistent disk + one long-lived process.** SQLite + in-process APScheduler want a real filesystem and a process that stays up — a local machine or a VM with a volume; serverless/scale-to-zero is disqualified.
3. **Users (and the developer) are primarily in Korea** — local-first also means lowest possible latency during development.

### 5.1 v1 target: local-first (the recommendation)

Run the three-container stack (§7) with `docker compose up` on the developer's machine. TLS is unnecessary on `localhost` (Caddy serves plain HTTP, or Vite dev + uvicorn directly). The full `mDeBERTa` sentiment model runs locally. Everything in this doc applies unchanged except: `DOMAIN` defaults to `localhost`, alerts go to a local log instead of a webhook (§8.3), and backups go to a local directory instead of a cloud bucket (§2.3). **Cost: $0. Real data: yes** — all external sources (yfinance, FRED, Finnhub, NewsAPI, Reddit, StockTwits, the Investing.com scrape, Korean communities) run on their free tiers against live data.

### 5.2 The GCP free-tier honesty note (only relevant if a free hosted demo is later wanted)

GCP's Always Free compute is **one e2-micro (2 shared vCPU, 1 GB RAM)** restricted to **specific US regions only — commonly `us-west1`, `us-central1`, `us-east1`** (*verify current terms at signup*). The Seoul region **`asia-northeast3` is NOT free** — an e2-micro there is paid. Any plan that says "free GCP hosting in Seoul" is wrong. Separately, **1 GB RAM cannot hold the full sentiment classifier**, so a free e2-micro must drop to the smaller **MiniLM** fallback model (`sentiment-pipeline.md` §5) — a quality feature-cut. This is why v1 stays local-first: locally we get the full model for free; the only *free cloud* option is feature-cut.

### 5.3 Free options compared (for an optional later hosted demo — no paid option is adopted)

| | **A. Local machine (v1 target)** | B. GCP free e2-micro (US region) | C. Railway free credit |
|---|---|---|---|
| Monthly cost | **$0** | ~$0 compute within Always-Free allowances (egress/disk overages billed) — *verify* | $5 starter credit; usage beyond it is billed — keep within credit or it is no longer free |
| RAM / model | Full machine — **full mDeBERTa model** | 1 GB — **MiniLM fallback only** (feature-cut) | Whatever the free credit covers — likely MiniLM |
| Latency (KR) | localhost | ~130–170 ms from US | ~70–100 ms (no Seoul region) |
| SQLite + volumes | Native disk | Native disk | Volumes, single-replica (matches our single-writer design) |
| Verdict | **Recommended v1 target** | Free hosted demo, MiniLM, US latency | Free only while within credit; MiniLM |

**Paid hosting (e.g. GCP `e2-medium` in Seoul, ~US$35–45/mo) is explicitly OUT of scope for v1** per the free-only standard. It remains the natural upgrade if the product ever needs an always-on, full-model, low-latency Korean deployment — recorded here only so the path is known, not chosen.

**Run/deploy flow (v1, deliberately boring):** `docker compose up -d --build` locally. If a free cloud demo is later wanted, the same compose stack runs on option B/C with `MODEL = MiniLM`, `DOMAIN` set, and a backup target chosen.

---

## 6. Caching: Redis

### 6.1 Role and configuration

Redis is the **hot read path** (every user-facing poll is a Redis hit), the **rate-limit counter store** (§10), the **circuit-breaker state store** (per `data-sources.md` §9.1, so breaker state survives restarts), and the **job heartbeat board** (§8). It is *not* the source of truth — everything user-durable lives in SQLite; Redis contents are reconstructible.

```text
redis-server --maxmemory 256mb --maxmemory-policy volatile-lru --save 300 1 --appendonly no
```

- `volatile-lru`: only TTL-bearing keys are evictable; breaker state and heartbeats (no TTL) are never evicted.
- RDB snapshot every 5 min is enough — losing 5 min of *cache* is a non-event; breaker state staleness of 5 min after a crash is acceptable.
- No password inside the compose network (Redis is not port-mapped to the host); if Redis ever moves off-box, `REDIS_URL` carries the auth.

### 6.2 Key naming convention (cross-doc contract)

```
{domain}:{object}[:{qualifier}...]
```

- **The namespace contract is owned by `backend-design.md` §5.1** — prefixes `px:`, `dash:`, `pred:`, `acc:`, `stocks:`, `cal:`, `sentiment:`, `intel:`, `rl:`, `cb:`. This doc uses those names verbatim and only **adds** ops/infra keys (`indicator:*`, `macro:*`, `ops:*`, `metrics:*`) that the backend contract doesn't cover, each marked **ADDITION** below.
- Lowercase ASCII, colon-separated namespaces. Stock-scoped keys embed the canonical API symbol form `{symbol}:{exchange}` verbatim (e.g. `005930:KRX`) — Redis keys are opaque strings, and glob patterns like `px:quote:*` still work; matching the API convention beats inventing a second symbol syntax.
- The `sentiment:*` keys already defined in `sentiment-pipeline.md` (`sentiment:clf:{sha1}`, `sentiment:source_health:{source}`) and the `intel:*` keys in `market-intel-pipeline.md` (including author-accuracy stats under `intel:authorstats:{source}:{handle}`, §11) are members of this convention and **must not be renamed**.

### 6.3 Keys, TTLs, and freshness — aligned with canonical cadences

**Design rule (contract with `data-sources.md` §9.2):** Redis TTLs are **garbage collection**, not freshness. Freshness (`meta.is_stale`) is computed at read time from the `data_as_of` timestamp stored *inside* each value, against the thresholds in `data-sources.md` §9.2. This is what lets us serve last-known-good data with an honest stale badge during an outage instead of serving nothing — a short TTL would delete exactly the data we need most when a source dies.

| Data type | Key pattern | Written by (cadence) | Redis TTL (GC only) | Fresh if `data_as_of` younger than |
|---|---|---|---|---|
| Price quote | `px:quote:{symbol}:{exchange}` | `price_poller` (1–5 min) | overwrite each cycle (no expiry, per `backend-design.md` §5.1) | 5 min (market hours); never stale when market closed |
| FX rate | `px:fx:{pair}` (e.g. `usdkrw`) | `price_poller` | 5 min | 5 min |
| Indexes | `dash:indexes` (single blob; canonical codes `KOSPI`, `NASDAQ_COMPOSITE`, `SP500`, `NIKKEI225`, `DAX`) | `price_poller` | 60 s | 5 min (that market's hours) |
| Trending list | `dash:trending:{region}` (`kr`/`us`/`all`) | `price_poller` | 60 s | 60 s |
| Indicator snapshot **(ADDITION)** | `indicator:snapshot:{symbol}:{exchange}:{interval}` (`5m`/`15m`/`1h`/`1d`) | `indicator_calculator` (5 min) | 24 h | 15 min |
| Sentiment score (per stock, 6 timeframes) | `sentiment:score:{symbol}:{exchange}` | `aggregate_sentiment` (10 min) | 24 h | 30 min (`sentiment-pipeline.md` §8.2) |
| Sentiment internals | `sentiment:clf:*`, `sentiment:source_health:*` | per `sentiment-pipeline.md` | as that doc specifies | n/a (internal) |
| Author-accuracy stats | `intel:authorstats:{source}:{handle}` | `intel_author_stats` (daily, per `market-intel-pipeline.md` §6.2/§14) | 26 h | n/a (internal) |
| Market-intel feed | `intel:feed:latest` (global, newest 100), `intel:stock:{symbol}:{exchange}`, plus the `intel:cluster:*`/`intel:emb:*` internals | `intel_scraper` (5–10 min) | 24 h | 30 min |
| Economic calendar | `cal:list:upcoming` (next 14 days), `cal:user_affects:{user_id}` | `calendar_sync` (daily) | 600 s (`backend-design.md` §5.1) | 48 h |
| Macro (FRED) **(ADDITION)** | `macro:series:{series_id}` | `sync_fred` (daily) | 14 d | 7 d |
| Prediction (request dedupe) | `pred:{symbol}:{exchange}:{timeframe}` | `/predict` handler | **per timeframe: 5/10/15/30/45/60 min** for 1h/5h/24h/2d/3d/5d (`backend-design.md` §6.5) | n/a — durable copy is the `predictions` row; this key only prevents duplicate model runs on poll bursts |
| Accuracy stats | `acc:{symbol}:{exchange}:{timeframe}:{window}` | `/accuracy` handler | 300 s (`backend-design.md` §5.1) | n/a |
| Search results | `stocks:search:{norm_q}:{limit}` | `/search` handler | 6 h (bust on `stocks` change) | n/a |
| Rate-limit counters | `rl:ip:*`, `rl:user:*`, `rl:login_email:*` | rate-limit middleware (§10) | window length | n/a |
| Circuit breakers | `cb:{source}` | HTTP client wrapper | none (persist) | n/a |
| Job heartbeats **(ADDITION)** | `ops:heartbeat:{job_id}`, `ops:heartbeat` (global) | every job on completion | none (persist) | healthz alerts if global > 3 min old |
| Latency metrics **(ADDITION)** | `metrics:latency:{endpoint}:{yyyymmddhh}` (hash of bucket counters) | API middleware | 48 h | n/a |

**Redis-down behavior (consistent with `data-sources.md` §9.3 and `sentiment-pipeline.md` §9.4):** reads fall through to SQLite (slower, correct); the sentiment classifier runs uncached; rate limiting degrades to in-process memory counters (fail-open across restarts — accepted v1 risk); circuit breakers fall back to in-process state. The API stays up.

---

## 7. Containers & configuration

### 7.1 docker-compose sketch

```yaml
# docker-compose.yml (production VM)
services:
  backend:
    build: ./backend           # python:3.11-slim base; installs requirements.txt
    env_file: .env
    volumes:
      - dbdata:/data           # SQLite file, model artifacts, local backup staging
    expose: ["8000"]
    depends_on:
      redis: { condition: service_started }
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c",
             "import urllib.request as u; u.urlopen('http://localhost:8000/healthz', timeout=5)"]
      interval: 30s
      timeout: 10s
      retries: 3
    logging: &log
      driver: json-file
      options: { max-size: "50m", max-file: "5" }

  redis:
    image: redis:7-alpine
    command: >
      redis-server --maxmemory 256mb --maxmemory-policy volatile-lru
      --save 300 1 --appendonly no
    volumes:
      - redisdata:/data
    restart: unless-stopped
    logging: *log

  web:
    build: ./frontend          # multi-stage: node:20-alpine `vite build` -> caddy:2-alpine + dist/ + Caddyfile
    environment:
      - DOMAIN=${DOMAIN}
    ports: ["80:80", "443:443"]
    volumes:
      - caddydata:/data        # TLS certificates survive restarts
    depends_on: [backend]
    restart: unless-stopped
    logging: *log

volumes:
  dbdata:
  redisdata:
  caddydata:
```

`backend/Dockerfile` entrypoint runs the §2.2 start sequence (`python -m app.db.migrate` → seed-if-empty → `exec uvicorn ... --workers 1`). The ML model artifacts (one logistic-regression-or-XGBoost model per timeframe — six files — plus a `manifest.json` carrying `model_version` and calibration parameters, per `prediction-model.md`) ship in the image at `MODEL_DIR` so a deploy and a model release are the same atomic act.

Local dev: `docker compose -f docker-compose.dev.yml up` runs only `redis`; uvicorn (`--reload`) and Vite run on the host.

### 7.2 Environment variables (complete v1 list)

Canonical names; `pydantic-settings` loads them (fail-fast on missing required keys, per `data-sources.md` §7). Sources: `[DS]` = defined in `data-sources.md` §7, `[SP]` = defined in `sentiment-pipeline.md` §11, `[here]` = this doc owns it.

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `ENV` [here] | yes | `dev` | `dev` / `prod`; gates docs UI, CORS, log verbosity |
| `DOMAIN` [here] | no | `localhost` | v1 local-first → `localhost` (plain HTTP, no TLS). Set a real hostname only for the optional free-cloud demo (§5.3) |
| `DATABASE_URL` [here] | yes | `sqlite+aiosqlite:////data/dcintel.db` | SQLAlchemy URL; the PG upgrade is this one line (§2.4) |
| `REDIS_URL` [here] | yes | `redis://redis:6379/0` | Cache, rate limits, breakers |
| `JWT_SECRET` [here] | yes | — | ≥ 32 random bytes (`openssl rand -hex 32`); HS256 signing key |
| `JWT_SECRET_PREVIOUS` [here] | no | — | Accepted-for-verification-only during rotation (§9.3) |
| `JWT_EXPIRY_MIN` [here] | no | `1440` | Access-token lifetime (24 h, see §9.2) |
| `BCRYPT_ROUNDS` [here] | no | `12` | bcrypt cost factor |
| `RATE_LIMIT_ENABLED` [here] | no | `true` | Master switch for the §10 fixed-window middleware (read by the backend, `backend-design.md` §11) |
| `TRUST_PROXY` [here] | no | `false` | Trust `X-Forwarded-For` (set `true` only behind Caddy/LB, §10; `backend-design.md` §11) |
| `RATE_LIMIT_DEFAULT` [here] | no | `100/min` | Per-IP default. **Values owned by `backend-design.md` §4** (fixed-window `count/window`) |
| `RATE_LIMIT_USER` [here] | no | `120/min` | Per-authenticated-user default |
| `RATE_LIMIT_LOGIN` [here] | no | `10/15min` | Failed `POST /auth/login` attempts, per IP **and** per email |
| `RATE_LIMIT_REGISTER` [here] | no | `5/hour` | Per-IP, `POST /auth/register` |
| `RATE_LIMIT_PREDICT` [here] | no | `30/min` | Per-user, predict endpoint |
| `RATE_LIMIT_SEARCH` [here] | no | `60/min` | Per-IP, `GET /stocks/search` |
| `CORS_ORIGINS` [here] | no | `""` | Dev only, e.g. `http://localhost:5173`; empty in prod (same-origin) |
| `MODEL_DIR` [here] | no | `/data/models` | Six per-timeframe model artifacts + `manifest.json` (`model_version`) |
| `WIN_RATE_ALERT_THRESHOLD` [here] | no | `0.50` | Rolling 7-day win rate below this → ERROR alert (§8.3) |
| `WIN_RATE_WARN_THRESHOLD` [here] | no | `0.52` | Below the ship-gate level → WARN (§8.3) |
| `WIN_RATE_MIN_SAMPLE` [here] | no | `30` | Min graded predictions per timeframe before alerting |
| `ALERT_WEBHOOK_URL` [here] | no | — | Optional. **Unset in v1 local-first → alerts go to the local log `logs/alerts.log` + console** (§8.3). Set a Discord/Slack webhook only if you want push alerts |
| `SENTRY_DSN` [here] | no | — | Optional error tracking; unset in v1 (errors logged locally). Free tier exists — *verify at signup* |
| `BACKUP_BUCKET` [here] | no | — | Optional. Unset in v1 → nightly snapshot stays in the local `/data/backups` volume (§2.3). Set a GCS bucket only for a cloud deploy |
| `TRACKED_STOCK_CAP` [here] | no | `50` | Universe size; raising it requires redoing `data-sources.md` §8 budget math |
| `LOG_LEVEL` [here] | no | `INFO` | Root log level |
| `FRED_API_KEY` [DS] | yes | — | per `data-sources.md` §7 |
| `FINNHUB_API_KEY` [DS] | yes | — | 〃 |
| `NEWSAPI_API_KEY` [DS] | yes | — | 〃 |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` / `REDDIT_USER_AGENT` [DS] | yes | — | 〃 |
| `STOCKTWITS_ACCESS_TOKEN` [DS] | yes | — | 〃 |
| `TWITTER_AUTH_TOKEN`, `TWITTER_CT0` (or `TWITTER_COOKIES_FILE`) [DS] | no | — | X session cookies for the v1 logged-in-session scraper (`data-sources.md` §4.1). Not a password. If unset, the X job self-disables |
| `POLYGON_API_KEY`, `TRADINGECONOMICS_API_KEY`, `KIS_APP_KEY`, `KIS_APP_SECRET` [DS] | no | — | Optional/reserved, per `data-sources.md` §7 |
| `TWITTER_ENABLED` [SP] | no | `true` | v1 on by default (session scraping); per `sentiment-pipeline.md` §11 |
| `SENTIMENT_ACTIVE_STOCK_CAP`, `SENTIMENT_STALE_AFTER_MIN`, `SENTIMENT_CLF_MODEL`, `SENTIMENT_CLF_MIN_CONF`, `SENTIMENT_MIN_TEXT_LEN`, `OUTLET_WHITELIST_PATH`, `KNOWN_TRADER_LIST_PATH` [SP] | no | (see that doc) | per `sentiment-pipeline.md` §11 |

Secrets handling: `.env` on the VM, mode `600`, never committed (`.env.example` committed with placeholders, per `data-sources.md` §7). On GCP, optionally hydrate `.env` from Secret Manager in `deploy.sh`; on Railway, use its environment-variable UI. The HTTP-client log redaction rules from `data-sources.md` §7 apply to `JWT_SECRET` and all `*_KEY`/`*_SECRET`/`*_TOKEN` values too.

---

## 8. Monitoring, alerting, graceful degradation

### 8.1 Logging

- **Structured JSON lines to stdout** (one event per line: `ts`, `level`, `event`, `request_id`, plus context). Docker's json-file driver with rotation (§7.1) is the v1 log store; `docker compose logs` is the v1 log UI. No ELK, no log shipping — revisit only if debugging across days becomes painful.
- Request middleware attaches/propagates `X-Request-ID` and logs every request: method, path template (not raw path — keeps symbols out of cardinality), status, duration ms, user id if authenticated.
- Unhandled exceptions: logged at ERROR with stack trace, returned to the client as a generic 500 with a plain-language bilingual message and the `request_id` ("문제가 발생했어요. 잠시 후 다시 시도해 주세요 / Something went wrong, please try again"). If `SENTRY_DSN` is set, the exception also goes to Sentry.

### 8.2 Response-time tracking & health

- Middleware increments per-endpoint latency bucket counters (`<50ms`, `<100`, `<250`, `<500`, `<1000`, `<2500`, `≥2500`) in `metrics:latency:{endpoint}:{yyyymmddhh}` Redis hashes. The hourly `metrics_rollup` job logs a one-line p50/p95/p99 summary per endpoint and persists a daily digest row.
- **v1 latency targets** (local-first — localhost, so network latency is ~0; these are *compute* budgets): cached reads (`/dashboard/*`, `/price`) p95 < 150 ms; `/predict` warm p95 < 400 ms, cold symbol < 1.5 s (the on-demand indicator path from `technical-indicators.md` §10). (On the optional free-cloud demo, add ~130–170 ms network RTT from the US region.)
- `GET /healthz` (unauthenticated, ops-only — deliberately *not* part of the `backend-design.md` product surface): returns 200 only if (a) SQLite answers a trivial read+write, (b) Redis answers `PING`, and (c) the global scheduler heartbeat `ops:heartbeat` is < 3 min old. Used by the Docker healthcheck and by an external uptime pinger (e.g. UptimeRobot free tier — *verify current limits at signup*) hitting `https://{DOMAIN}/healthz` every 5 min — that pinger is also our "the whole VM is down" alarm.

### 8.3 Alerts

**v1 local-first: alerts are written to a local channel** — `logs/alerts.log` (structured, one JSON line per alert) plus a console line — at the level shown. If `ALERT_WEBHOOK_URL` is set (optional), the same alert is also POSTed to that one webhook. Alert events:

| Alert | Trigger | Level |
|---|---|---|
| Win rate degraded | `win_rate_monitor` (daily 07:30 KST): for each of the 6 timeframes, rolling 7-day win rate from `prediction_outcomes` (with `model_version` from `predictions` in the message) is `< WIN_RATE_ALERT_THRESHOLD` with ≥ `WIN_RATE_MIN_SAMPLE` graded predictions | ERROR — the product's honesty promise is at stake; investigate features/regime before anything else |
| Win rate below ship gate | same job, `< WIN_RATE_WARN_THRESHOLD` (the 52% ship-gate level) | WARN |
| Circuit breaker opened / fallback promoted | per `data-sources.md` §9.1 | WARN (ERROR if both a source *and* its fallback are open) |
| 429 from a provider | budget math broke (`data-sources.md` §9.1 special case) | ERROR |
| Scheduler stalled | healthz heartbeat check fails | ERROR |
| Backup failed | `db_backup` exception or GCS upload failure | ERROR |
| Calendar scraper parse-shape change | per `data-sources.md` §3 | WARN |
| Disk > 80% / RAM > 90% | `heartbeat` job samples `psutil` | WARN |

### 8.4 Degradation matrix

Consistent with — and deferring to — `data-sources.md` §9.3 for per-source detail; this table adds the **internal** failure modes this doc owns. Design principle (shared): no single failure takes down the API; features degrade in richness, not availability, and every degradation is visibly honest (gray stale badges, plain language).

| Component down | Still works | Degraded / lost | User-visible behavior |
|---|---|---|---|
| **Prediction model** (artifact missing/corrupt at load, or inference raises) | **Live prices, indicators, sentiment, calendar, market intel, accuracy history — the entire dashboard** | New predictions only | `/predict` returns `503 MODEL_UNAVAILABLE` with "예측 기능을 점검 중이에요 / Predictions are under maintenance"; most recent stored prediction still shown from `predictions` with its timestamp and a clear "past prediction" label |
| **One data source** (Yahoo, Finnhub, NewsAPI, FRED, calendar scrape, Reddit, StockTwits, KR communities) | Everything not fed by that source | Exactly per `data-sources.md` §9.3 — e.g. Yahoo→Finnhub/pykrx fallback quotes at 5 min; both-socials-down→technicals+news evidence only; evidence bullets re-normalize to sum to 100% across remaining signals | Gray "데이터 지연 / Data delayed" badges; fewer evidence bullets; `503 SOURCE_DEGRADED` only in the explicit >30-min-stale-price guard during market hours |
| **Redis** | Full API (reads fall through to SQLite), predictions, auth | Latency (no hot cache); classifier uncached; rate limiting degrades to in-process counters; breaker state in-process only | Slower responses; nothing visibly missing |
| **SQLite unavailable** (disk full/corrupt) | Cached reads from Redis keep the dashboard alive for browsing | All writes: register/login, new predictions, outcome grading, job persistence — jobs pause persistence and alert | Read-only mode; mutating endpoints return 503; ops alert fires immediately (this is the page-someone case) |
| **Scheduler stalled** (jobs stop, API alive) | All serving, from cache then SQLite | Data ages until stale thresholds trip source-by-source | Stale badges spread across the dashboard over ~5–30 min (prices at 5 min, indicators at 15 min, sentiment/intel at 30 min); healthz heartbeat alert fires within 3 min — long before users notice |
| **`web` container / Caddy** | Nothing user-facing | Everything (single entry point) | External uptime pinger alerts; `docker compose up -d` restores; `restart: unless-stopped` handles crashes automatically |
| **Whole VM** | Nothing | Everything | Uptime pinger alerts; restore = new VM + `deploy.sh` + restore §2.3 backup; target RTO < 2 h, RPO ≤ 24 h |

---

## 9. Authentication

### 9.1 Passwords

- Email/password only (canonical). Passwords hashed with **bcrypt**, cost `BCRYPT_ROUNDS=12` (~250 ms on the v1 VM — deliberate; rate limiting on auth endpoints, §10, keeps this from being a DoS vector). Stored in `users.password_hash`; the plaintext never touches logs (redaction rules §7.2).
- bcrypt's 72-byte input limit: pre-validate password length ≤ 72 bytes at registration with a friendly message (do **not** silently truncate).
- Registration: normalize email to lowercase, unique index on `users.email`; password policy v1 = minimum 8 chars (beginner-friendly product; no arbitrary complexity rules).
- bcrypt calls run in a thread (`asyncio.to_thread`) — never on the event loop.

### 9.2 JWT access tokens

- **HS256**, signed with `JWT_SECRET`. Claims: `sub` (user id, string), `iat`, `exp` (email deliberately excluded — `backend-design.md` §3.2; handlers load the user by `sub`). Sent as `Authorization: Bearer <token>`; the SPA keeps it in memory + `localStorage` (XSS exposure accepted for v1 with strict CSP via Caddy headers as mitigation; httpOnly-cookie sessions noted as a hardening option).
- **Expiry: `JWT_EXPIRY_MIN=1440` (24 h).** Rationale: the canonical v1 API surface has no `POST /auth/refresh`, so short-lived tokens would force hourly re-logins. 24 h re-login is acceptable for a free dashboard product. A refresh-token flow (`POST /auth/refresh`, rotating refresh tokens) is the documented **v1.1 extension** — flagged so `backend-design.md` doesn't grow it silently.
- No server-side token revocation list in v1 (stateless by design); compromised-account response = password change **plus secret rotation if widespread**.

### 9.3 Secret management & rotation

- `JWT_SECRET` is generated once per environment (`openssl rand -hex 32`), lives only in `.env`/Secret Manager (§7.2), distinct between dev and prod.
- **Rotation procedure** (planned, not emergency): set `JWT_SECRET_PREVIOUS` = old secret, `JWT_SECRET` = new secret, restart; tokens signed with either verify for the next `JWT_EXPIRY_MIN` window; after 24 h, unset `JWT_SECRET_PREVIOUS`. Emergency rotation (suspected leak): skip the grace period — everyone re-logs-in; that is the correct outcome.

---

## 10. Rate limiting

**Implementation (owned by `backend-design.md` §4):** a hand-rolled **Redis fixed-window** middleware (not `slowapi`) using `rl:*` counters (§6.3) so counts survive restarts and are shared if a second host ever appears. Redis-down behavior: **fail open** (requests pass; §6.3) — accepted v1 trade-off. The values below are restated from `backend-design.md` §4, which is the source of truth; this doc does not set its own limits.

**Client identity:** Caddy sets `X-Forwarded-For`; the limiter trusts that header **only** because uvicorn is reachable solely through Caddy on the compose network (it is not port-mapped, and `TRUST_PROXY=true`). Key function: per-user limits key on the JWT `sub` when a valid token is present, else per-IP.

| Scope | Limit (`backend-design.md` §4) | Why |
|---|---|---|
| Default, per IP | `100/min` | Generous for a polling SPA |
| Default, per authenticated user | `120/min` | Headroom for multi-tab usage without enabling scraping |
| `POST /auth/login` | `10` **failed** attempts per `15 min`, per IP **and** per email | Credential-stuffing brake; pairs with the ~250 ms bcrypt cost |
| `POST /auth/register`, per IP | `5/hour` | Bot-signup brake |
| `GET .../predict`, per user | `30/min` | The only endpoint that can trigger on-demand computation (cold-symbol path); protects the event loop |
| `GET /stocks/search`, per IP | `60/min` | Cheap but enumerable; frontend debounces ≥ 250 ms |

**429 response contract:** standard `Retry-After` header + the bilingual plain-language body shape used everywhere ("요청이 너무 많아요. 잠시 후 다시 시도해 주세요 / Too many requests — please try again in a moment"). 429s are counted in the metrics rollup; a sustained 429 rate > 1% of traffic is a WARN (either an abuser or limits set too tight).

Background jobs are **not** subject to these limits (they are outbound, not inbound); their outbound budgets are governed by `data-sources.md` §8 and the circuit breakers.

---

## 11. Launch checklist

**v1 local-first run-up** (steps 1–8 all run on `localhost`, $0):

1. Docker + Docker Compose installed; ports `8000`/`6379` are container-internal (Caddy serves the SPA on `localhost`). No DNS, no firewall, no TLS — `DOMAIN=localhost`.
2. `.env` populated from `.env.example`; app fail-fast confirms required keys (§7.2). All API keys are free-tier (`data-sources.md` §7).
3. `docker compose up -d --build` → `GET http://localhost/healthz` returns 200.
4. Seed verified against **real data**: `stocks` has the ~50-symbol universe; `/stocks/search?q=삼성` returns Samsung Electronics with a live price overlay.
5. Restore drill done once (§2.3); first nightly snapshot present in the local `/data/backups` volume.
6. Alerts verified locally: a test alert appears in `logs/alerts.log` + console (no webhook needed in v1).
7. Ship gate confirmed (per `prediction-model.md` §7): held-out test win rate ≥ 52% for each shipped per-timeframe model (trained on **real** 6–12-month history); `manifest.json` `model_version` matches what `predictions.model_version` will record. Timeframes that miss the gate ship disabled-with-note (`ui-ux.md`).
8. Rate limits smoke-tested (11th **failed** login within 15 min, same IP/email → 429 with `Retry-After`; per `backend-design.md` §4).

**Optional free-cloud demo only** (skip entirely for local-first): set a real `DOMAIN` + DNS A record, switch the model to MiniLM (§5.2), choose a `BACKUP_BUCKET`, and point an uptime pinger at `/healthz`.
