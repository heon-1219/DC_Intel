# M8 — Dashboard endpoints + cross-cutting API (full hardening)

> **Plan written 2026-06-21** (just-in-time, per CLAUDE.md process). Milestone M8 of the Phase-4
> roadmap. Owner approved scope/design via AskUserQuestion (see "Owner decisions" below).
> Execute TDD (red→green→refactor), one commit per slice. Stop at the milestone.

## Goal & exit criteria
Deliver the remaining **3 of the 12** backend endpoints and the cross-cutting API layer so the
backend is **fully spec-complete** (nothing left for M10 but deploy/ops). Exit (roadmap M8):
- All **12 endpoints** live and contract-accurate (9 already shipped + 3 new here).
- **Rate limits enforced** — global per-IP (100/min) + per-user (120/min) middleware **+** the
  `/stocks/search` 60/min/IP override; `429 RATE_LIMITED` + `Retry-After` + `X-RateLimit-*`.
- **Every response carries the full `{data, meta}` envelope** (5 meta fields) — including retrofits
  of the M3/M4 dashboard endpoints.
- **Structured logging + audit + redaction** (structlog JSON lines, request_id middleware).
- **Degradation flags surface** on source outage (honest `meta.source`/`is_stale`; §9.4 price-stale
  guard).
- Full test suite green offline; docker smoke green (see M8k caveat — Docker not yet on this box).

## Owner decisions (2026-06-21, binding for M8)
1. **Scope = FULL HARDENING now** — pull the global rate-limit middleware, structlog logging/audit/
   redaction, and the degradation matrix into M8 (not deferred to M10).
2. **Sparkline = ON-DEMAND INTRADAY from yfinance** — each poll cycle fetch 5m bars via the existing
   `YFinanceBarProvider`, cache the intraday series into the `dash:*` blob. No new DB table.
3. **Universe = EXPAND seed to ~50 real tickers** (liquid KRX + US, real data) so trending/search
   are meaningful.
4. **Index sessions = ADD KR/JP/DE** — extend `hours.py` with JPX + XETRA weekday sessions and map
   each index row by its `region`, so all 5 open/closed dots are correct (holidays still v1-out).

## The 12 endpoints (status)
Shipped (9): `POST /auth/register`, `POST /auth/login`, `GET /stocks/{i}/price`,
`GET /stocks/{i}/predict`, `GET /stocks/{i}/prices-across-markets`, `GET /stocks/{i}/history`,
`GET /stocks/{i}/accuracy`, `GET /dashboard/economic-calendar`, `GET /dashboard/market-intel`.
**New in M8 (3):** `GET /stocks/search`, `GET /dashboard/trending`, `GET /dashboard/indexes`.

## Reuse (do NOT reimplement)
- `app/cache/redis.py::make_envelope(data, *, source, data_as_of, is_stale, cache, request_id)` — the
  canonical envelope. Route ALL responses through it.
- `app/auth/ratelimit.py` — `hit/over_limit/record_failure/rate_limited/client_ip/sha1_email`.
- `app/db/repositories/accuracy.py::accuracy_stats(...)` + `MIN_SAMPLE=20` — win-rate badge source
  (`win_rate_pct=directional.win_rate_pct`, `n_closed=directional.predictions`; null when <20).
- `app/services/price.py::read_cached / is_stale` (`px:quote:{symbol}:{exchange}`),
  `app/services/fx.py::get_usdkrw`, `app/services/xmkt.py::_norm_usd` (USD-normalized diff).
- `app/db/repositories/stocks.py::list_active_by_region / list_active_indexes / get_company_listings`.
- `app/providers/yfinance_bars.py::YFinanceBarProvider.fetch_bars(ref, '5m')` (intraday sparkline).
- `app/market/hours.py::market_state` (extend for JP/DE), `app/auth/deps.py::get_current_user_optional`.

## Resolved design rules
- **Sparkline:** today's session at **5-min** resolution, **most-recent last, ≤78 points** (reconcile
  ui-ux §7.2.1 "≤78 @5min" with backend-design's illustrative "~24"; use the detailed ui-ux spec).
  When the market is closed, the last completed session's 5m bars. Applies to **both** trending cards
  and index tiles (ui-ux §7.2.2 requires it on index tiles even though backend-design's example omits
  it — we ADD it). On fetch failure → `[]` (UI renders nothing, never fabricated).
- **`dash:*` build = write-through** (per backend-design §5/§7): a 60s scheduler job assembles
  `dash:indexes` and `dash:trending:{kr,us,all}`; the handlers only READ + wrap. Cold-cache → handler
  returns an honest empty/stale payload (`cache:"miss"`), never fabricates.
- **search `fx_rate`** = multiplier to USD: USD listing → `1.0`; KRW listing → `1/usdkrw` (usdkrw =
  KRW per USD from `get_usdkrw`). `price_usd = last_price * fx_rate`.
- **search `diff_vs_primary_pct`** = `(this_usd - primary_usd)/primary_usd*100`; **null** on the
  primary listing itself and whenever either leg lacks a fresh quote (price_as_of >10min ⇒ stale).
- **search `is_primary` / `kind`** (no DB columns): `kind = 'adr' if adr_ratio else 'common'`;
  `is_primary` = the company-group listing that is non-ADR (`adr_ratio IS NULL`) and whose `region`
  is the company's home; tie-break by exchange order; if no non-ADR listing exists, the first listing.
- **Index `market_state`** resolved by the index row's `region` → KR=KRX, US=US, JP=JPX (Tokyo,
  09:00–11:30 & 12:30–15:00 weekday), DE=XETRA (Frankfurt, 09:00–17:30 weekday). pre/post US-only.
- **Global rate-limit scopes** adopt the documented namespace: `rl:ip:*` (100/60s) + `rl:user:*`
  (120/60s). Per-route overrides keep their existing scopes (`register_ip`, `login_*`, `predict_user`,
  new `search_ip`); both global + override can trip (stricter wins). `X-RateLimit-Limit/Remaining`
  emitted on every limited response (live remaining from the global IP counter); `/healthz` exempt.

---

## TDD slices (commit per slice; conventional-commit messages `feat(m8x)/...`)

### M8a — Error catalog + shared helper + global handlers + envelope consistency
- **New** `app/core/errors.py`: full §2.4 catalog. `ApiError(Exception)` (code, http_status,
  message_en, message_ko, details=None) + `error_json(request_id, err)` →
  `JSONResponse({error:{code,message_en,message_ko,details,request_id}}, status)`. Named builders for
  INVALID_PARAM(400), UNAUTHORIZED(401), INVALID_CREDENTIALS(401), SYMBOL_NOT_FOUND(404),
  NOT_FOUND(404), EMAIL_TAKEN(409), VALIDATION_ERROR(422), RATE_LIMITED(429), INTERNAL(500),
  SOURCE_DEGRADED(503), MODEL_UNAVAILABLE(503).
- **`create_app`**: register handlers — `RequestValidationError`→422 VALIDATION_ERROR
  (`details.fields=[{field,problem}]`); broad `Exception`→500 INTERNAL (request_id only, **no stack
  trace**); `ApiError`→`error_json`. Keep the existing `AuthError` handler (or fold into catalog).
- Replace the 3 duplicated `_err` helpers (stocks/dashboard/predictions) with the shared builder —
  identical wire output so existing tests stay green.
- Retrofit `economic-calendar` + `market-intel` through `make_envelope` (add `data_as_of`/`is_stale`;
  `market-intel` `source:'intel'→'composite'`).
- **Tests:** `test_errors.py` (each builder shape, 422 reshape, 500 hides stack); update the 2 dash
  tests for the fuller meta. Commit `feat(m8a)`.

### M8b — structlog logging + request_id middleware + audit + redaction
- Add `structlog` to `pyproject.toml` `dependencies`.
- **New** `app/core/logging.py`: configure structlog (JSON lines on stdout), `get_logger`, a
  **redaction** processor (drop/mask `password*`, `authorization`, `api_key`, `apikey`, `token`,
  bearer JWTs; emails only in `auth.*` events else `user_id`). Level policy per §10.2.
- **New** `RequestIdMiddleware` (in `app/core/middleware.py`): mint `req_`+8hex, honor inbound
  `X-Request-ID`, bind into a contextvar + structlog contextvars, echo `X-Request-ID` response header.
  Register in `create_app`. Refactor handlers to read request_id from the contextvar (drop ad-hoc
  `request.headers.get('x-request-id','req_local')`).
- Emit canonical events: `app.start/stop` (lifespan), `job.start/job.done` (scheduler wrapper),
  `prediction.created` (predictions), `outcome.graded` (outcome_checker), `auth.register /
  auth.login.success / auth.login.failed` (auth; failed logs IP + sha1(email) prefix only),
  `breaker.open/closed`. Minimal, real, non-breaking.
- **Tests:** `test_logging.py` (redaction masks secrets, request_id mint+echo+honor inbound, JSON
  event shape via structlog capture). Commit `feat(m8b)`.

### M8c — Global rate-limit middleware (§4.1)
- **New** `RateLimitMiddleware` (`app/core/middleware.py`): for every request (except `/healthz`),
  `rl.hit(redis,'ip',client_ip,limit=100,window_sec=60)`; if a valid Bearer decodes,
  `rl.hit(redis,'user',sub,limit=120,window_sec=60)`. Either over-limit → 429 via `rl.rate_limited`.
  Add `X-RateLimit-Limit/Remaining` (from the IP counter) to ALL responses of limited scopes; on 429
  add `Retry-After`. Fail-open + WARN sampled 1/min when Redis down. Gated by `rate_limit_enabled`.
- Per-route overrides unchanged (they compose; stricter wins). Reconcile scope names to `rl:ip`/`rl:user`.
- **Tests:** `test_ratelimit_global.py` (IP 429 at 101st, user 429 at 121st, headers on 200,
  fail-open on Redis down, disabled bypass, `/healthz` exempt, inbound request_id preserved).
  Commit `feat(m8c)`.

### M8d — Degradation matrix wiring (§9.3 / §9.4)
- Propagate the **real** `px:quote.source` into `meta.source` across price/search/trending/indexes
  (fallback source ⇒ visible); `is_stale` already computed — ensure it's set everywhere.
- Implement the §9.4 **price-staleness guard** for `/predict` (the documented M6h deferral): in the
  stock's market hours, if the freshest price >30min old → serve a cached prediction if present, else
  `503 SOURCE_DEGRADED`. Outside market hours, proceed (last close valid). `/price` never 503s.
- Document (in this plan's "Already handled / deferred") the matrix rows already covered (model-missing
  503 from M6; calendar 48h stale from M3; breaker stale-serve from M1) vs. honestly-not-applicable.
- **Tests:** `test_degradation.py` (§9.4 guard: stale-in-hours→cached or 503; source propagation;
  outside-hours proceeds). Commit `feat(m8d)`.

### M8e — Seed universe expansion (~50 real tickers)
- Curate ~25 KRX + ~25 US **real, liquid** rows into `config/seed_stocks.csv` (real `company_name` +
  `company_name_ko`, `company_group`, `security_type`, `currency`, `board`, correct `yfinance_ticker`
  (`NNNNNN.KS` KRX / plain US), `finnhub_ticker`, `adr_ratio` for ADRs, `xmkt_reference` where a real
  cross-listing/peer exists). Keep the 5 index rows. **Research the exact tickers + Korean names via a
  sub-agent; verify resolvable** with a `@pytest.mark.live` yfinance check.
- **Tests:** update `test_seed.py` (count ≥50, idempotent, spot-check specific symbol→.KS resolution,
  ADR coercion, index rows still present). Commit `feat(m8e)`.
- ⚠️ Seed is insert-only-if-empty; a populated DB won't re-seed (fine for this fresh server; note for
  existing volumes).

### M8f — hours.py index sessions (JP/DE + region mapping)
- Extend `market_state`: add JP (`Asia/Tokyo`, 09:00–11:30 & 12:30–15:00 weekday → open) and DE
  (`Europe/Berlin`, 09:00–17:30 weekday → open). Add `index_state(region, now)` mapping
  KR→KRX/US→US/JP→JP/DE→DE used by the indexes builder (index rows have `exchange='INDEX'` + a region).
- **Tests:** `test_hours.py` add JP/DE open/closed/weekend + `index_state` per region. Commit `feat(m8f)`.

### M8g — Intraday sparkline helper
- **New** `app/services/sparkline.py::build_sparkline(bars_provider, ref, *, now, max_points=78)` →
  fetch 5m bars, take the current (or last) session's closes most-recent-last, cap `max_points`;
  return `list[float]`; any error → `[]`.
- **Tests:** `test_sparkline.py` with a fake bars provider (deterministic 5m DataFrame): ordering,
  cap, empty-on-error, session selection. Commit `feat(m8g)`.

### M8h — GET /stocks/search
- **stocks repo** `search_listings(con, q, *, limit, max_groups=7)` → company-grouped rows
  (case-insensitive **prefix** on symbol + **substring** on `company_name`/`company_name_ko`, exclude
  `security_type='index'`), selecting the columns the payload needs (symbol, exchange, board, currency,
  security_type, adr_ratio, company_group, names, region).
- **Handler** in `stocks.py`: validate `q` (1–50 trimmed → else 400 INVALID_PARAM) + `limit` (1–20,
  default 10); 60/min/IP via `rl.hit('search_ip', client_ip)`; metadata blob cache
  `stocks:search:{norm_q}:{limit}` (6h, company-grouped, **no prices**); per-request overlay from
  `px:quote:*` + `px:fx:*` (`last_price`,`price_as_of`,`fx_rate`,`diff_vs_primary_pct`,`is_primary`,
  `kind`); `meta.cache='metadata-hit'` on blob hit, `'miss'` else. Errors 400/429.
- **Tests:** `test_search_endpoint.py` (symbol-prefix + EN/KO substring match, grouping, overlay
  merge with seeded px:quote in fakeredis, primary/diff math, kind, empty/overlong q→400, 429,
  metadata-hit). Commit `feat(m8h)`.

### M8i — dash:* write-through builders (price_poller side)
- **New** `app/jobs/dashboard_builder.py`:
  - `build_indexes_blob(db, redis, bars, *, now)` → 5 index rows: `level/change/change_pct` from
    `px:quote`, `market_state` via `index_state(region)`, `sparkline` via `build_sparkline`, per-index
    `data_as_of`; write `dash:indexes` (60s).
  - `build_trending_blob(db, redis, bars, *, region, now)` → region's active non-index stocks: rank by
    `change_pct` (price vs previous_close from `px:quote`) → top-N `gainers`/`losers`; each card gets
    `sparkline` + `win_rate_pct`/`n_closed` (`accuracy_stats`) + `market_state`; write
    `dash:trending:{region}` for `kr`,`us`,`all` (60s).
- **Wire** a `build_dashboard_blobs` job into the scheduler + lifespan (runs ~60s, after polls).
- **Tests:** `test_dashboard_builder.py` (blob shapes, gainer/loser ranking, sparkline attach,
  win-rate via fixture outcomes, index mapping/market_state) with fakes. Commit `feat(m8i)`.

### M8j — GET /dashboard/trending + GET /dashboard/indexes
- **Handlers** in `dashboard.py`: optional-auth (`get_current_user_optional`); trending validates
  `region∈{kr,us,all}` (default all) + `limit` 1–20 (default 10, applied per list); read the `dash:*`
  blob, wrap via `make_envelope` (`source` from blob, `is_stale` from blob age vs 60s, `cache`
  hit/miss); cold blob → honest empty (`regions:[]` / `indexes:[]`, `cache:'miss'`). Errors: trending
  400/429, indexes 429-only.
- **Tests:** `test_trending_endpoint.py` + `test_indexes_endpoint.py` (blob read, params + 400,
  optional-auth 401 on bad token, empty-on-cold, envelope meta). Commit `feat(m8j)`.

### M8k — Verification + docs
- Full suite green: `backend/.venv/bin/python -m pytest backend/tests`.
- **Docker smoke** = the milestone gate, but **Docker isn't installed on this server** → either install
  Docker + `docker compose up` smoke (healthz + the 3 new endpoints 200) OR an in-process ASGI smoke
  if Docker is deferred (flag to owner). Update `handoff.md` + roadmap status to **M8 COMPLETE**.

## Test strategy
- Unit: errors/logging/redaction, ratelimit middleware (fakeredis, injectable `now`), hours JP/DE,
  sparkline (fake bars), search match + overlay math, dashboard builders (fakes), envelope shape.
- Integration: the 3 endpoints via `httpx.ASGITransport` + temp SQLite (seeded) + fakeredis with
  pre-set `px:quote`/`px:fx`/`dash:*`. No network in the default run; live yfinance behind `-m live`.
- Contract: response shapes asserted against backend-design §6.3/§6.7/§6.8 field-by-field.

## Already handled / explicitly deferred
- Model-missing `503 MODEL_UNAVAILABLE` (M6), calendar 48h stale (M3), breaker stale-serve (M1) —
  already satisfy their degradation rows; M8d only adds source propagation + the §9.4 guard.
- Sentiment-down `reduced_coverage`/`low_confidence` on 1h/5h `/predict` — surfaced from the feature
  builder's `missing` meta (already computed in M5); M8d wires the flag onto the response if not
  already present, else notes it as covered.
- Holidays in session calendars remain out of v1 (documented limitation) for all exchanges.
