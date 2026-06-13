# DC Intel — Handoff / Working State

Living doc to prevent information loss across check-ins and sessions. **Update after every task.**

## TL;DR — where we are right now
- **Phase:** 4 (implementation). Docs approved; building.
- **Milestone:** M0 — Foundation & scaffolding.
- **Current task:** Task 10 ✅ DONE (commit pending this turn) → **🎉 M0 COMPLETE (10/10).** **Next: M1 — market-data pipeline** (write its detailed plan first: `docs/superpowers/plans/2026-06-13-dc-intel-m1-market-data.md`, then execute).
- **Run the stack:** `docker compose up -d --build` → http://localhost/healthz = 200. Stop: `docker compose down` (the `dbdata` named volume persists the SQLite DB across down/up). First build ~1–2 min.
- **Mode:** inline execution; check in with owner after each task (commit boundary).
- **Branch:** `main` (fresh repo, git init'd in Task 1).

## How to resume (cold start)
1. Read this file, then the two plan docs:
   - `docs/superpowers/plans/2026-06-13-dc-intel-phase4-roadmap.md` (program roadmap, M0–M10 + test strategy)
   - `docs/superpowers/plans/2026-06-13-dc-intel-m0-foundation.md` (current milestone, task-by-task TDD)
2. `git log --oneline` → see completed tasks (each task = one commit).
3. Continue from the first unchecked `- [ ]` task in the current milestone plan.
4. Backend tests: `backend\.venv\Scripts\python.exe -m pytest backend\tests -v` (or `uv run --project backend pytest`).

## Environment (verified 2026-06-13)
- OS: Windows 11, PowerShell. **Project path has spaces + Korean — always quote paths.**
- git 2.46.0 · python 3.14.0 · pip 26.0.1 · docker 28.5.2 · **uv 0.9.26**.
- ⚠️ **Local Python is 3.14; Docker runtime is `python:3.11-slim`.** M0's light deps are fine on 3.14 (pydantic-core 2.46.4 had a 3.14 wheel). **Watch for wheel gaps at M5** (xgboost / transformers / scikit-learn) — if a dep has no 3.14 wheel, `uv venv --python 3.11` (uv fetches it for free) to match Docker.
- **venv is managed with `uv`** (owner standard) at `backend/.venv`. Recreate / install:
  `uv venv --python 3.14 backend\.venv` then `uv pip install -p backend\.venv\Scripts\python.exe -e "./backend[dev]"`.
  Run tests/commands via `backend\.venv\Scripts\python.exe -m pytest backend\tests` (activation does NOT persist across tool calls) or `uv run --project backend pytest`.

## Owner standards (binding — never violate)
1. **Completely FREE** — no paid APIs/hosting/tiers.
2. **International + detail-perfect UI** — green=up/red=down; aligned, no layout shift, all component states (`ui-ux.md` P9).
3. **Local-first** — runs on localhost; `DOMAIN=localhost`; alerts→local log; backups→local volume.
4. **REAL data always** — the app uses live data only; TESTS use cassettes recorded from real APIs (deterministic, offline) — never fabricated data.

## Key decisions (see docs/open-questions.md for the full decision log)
- Twitter/X = v1 via **logged-in session scraping** (personal-use, free); cookies `TWITTER_AUTH_TOKEN`+`TWITTER_CT0`; **no detection-evasion infra**. `data-sources.md` §4.1.
- Calendar = free Investing.com scrape; NewsAPI free tier; KRX fallback = pykrx; Korean community scraping approved with safeguards.
- Doc authorities: `schema.md` (tables) · `backend-design.md` (endpoints/Redis keys/rate limits) · `deployment-architecture.md` (env registry) · `prediction-model.md` (reasoning_json/explainability).

## Deviations from the plan (log)
- **Task 1 `pyproject.toml`:** added `[build-system]` (setuptools) + `[tool.setuptools.packages.find] include=["app*"]`. The plan omitted these; without them an editable install fails ("Multiple top-level packages discovered" — `app` and `tests`). No behavior change, just makes `pip install -e` discover only `app`.
- **Task 1 `.gitignore`:** added `*.egg-info/` (editable install creates `backend/dc_intel_backend.egg-info/`).
- **Task 1 commit scope:** broadened the first commit to the full repo baseline (the pre-existing approved `docs/` + `handoff.md` + scaffold) instead of scaffold-only, since this is a fresh repo and leaving 15 doc files untracked would be messy. Subsequent tasks commit per-task as planned.
- **Task 2 `config.py`:** wrote a corrected `sqlite_path` — the plan's draft returned `/./data/...` for the relative 3-slash URL (a bug it flagged with a fallback). Clean rule: strip the scheme prefix, then strip exactly one leading `/`. Added a 4th test for the absolute 4-slash form. (Confirmed pydantic v2 `ValidationError` subclasses `ValueError`, so the short-secret test passes with `pytest.raises(ValueError)`.)
- **Task 5 paths (cwd-independence):** the plan assumed pytest runs from `backend/` (hardcoded `MIG_DIR="migrations"`), but we run from the repo root. Made `test_migrate.py` resolve `MIG_DIR` via `Path(__file__).parents[1]/"migrations"`, and `migrate.py`'s `__main__` default via `Path(__file__).parents[2]/"migrations"` — both cwd-independent. Same fix will apply to the Task 6 seed CSV path. The `migrate()` function itself takes the dir as a param (unchanged).

- **Repo hygiene (`9-` chore):** the initial commit accidentally tracked Obsidian editor state (`docs/.obsidian/*`, which churns as notes are opened). Added `.obsidian/` to `.gitignore` and `git rm -r --cached docs/.obsidian`. (You use Obsidian on the `docs/` vault — its workspace files are editor cruft, not project content.)

## Task changelog
- **Task 1 ✅** (`75ae3b8`) — git init on `main`; `.gitignore`; `backend/pyproject.toml`; `app` package; pytest harness; smoke test PASS. Working tree clean.
- **uv switch ✅** (`f5bec05`) — venv now managed by uv; M0 plan + README + handoff updated.
- **Task 2 ✅** (`de94aa2`) — `config.py` (pydantic-settings, JWT_SECRET ≥32 validation, corrected `sqlite_path`) + `test_config.py` (4 tests). Full suite: **5 passed**.
- **Task 3 ✅** (`e836efc`) — `db/connection.py` (`connect()` async ctx mgr applying WAL/synchronous/busy_timeout/foreign_keys pragmas; `aiosqlite.Row` factory) + `test_connection.py`. Full suite: **6 passed**.
- **Tasks 4 + 5 ✅** — `migrations/001_initial_schema.sql` (9 tables + indexes, verbatim from `schema.md` §3) and `db/migrate.py` (numbered-SQL runner, `schema_migrations`, one-txn-per-file) + `test_migrate.py` (3 tests: all tables created, idempotent, CHECK rejects bad timeframe). Full suite: **9 passed**. Also smoke-tested the `python -m app.db.migrate` CLI (the Docker entrypoint path): applies then idempotent.
- **Task 6 ✅** — `config/seed_stocks.csv` (12 real rows: 4 KRX + AAPL/NVDA + PKX ADR + 5 index pseudo-rows) and `db/seed.py` (insert only if `stocks` empty; ""→NULL; `__file__`-relative `__main__` CSV path = `parents[3]/config`, works locally and in-container where config sits beside backend/). `test_seed.py` (4 tests: populates ≥12, idempotent, resolves 005930→005930.KS, empty→NULL + adr coercion). Full suite: **13 passed**. Seed CLI smoke-tested (seeded 12 → idempotent).
- **Task 7 ✅** — `cache/redis.py` (`get_client` via redis.asyncio decode_responses; `ping` returns False on any error; `make_envelope` = the `{data, meta}` contract, backend-design.md §12) + `test_redis.py` (3 tests, fakeredis). Full suite: **16 passed**.
- **Task 8 ✅** — `app/main.py` (`create_app()` + module-level `app`), `routers/health.py` (`/healthz` → 200 if sqlite+redis OK else 503), `tests/conftest.py` (`app_client` fixture: temp migrated DB + fakeredis, `get_settings.cache_clear()`) + `test_health.py` (2 tests: ok + degraded-503). Full suite: **18 passed**.
  - **Important pattern:** `/healthz` calls **`cache_redis.get_client()` via the module** (not `from ... import get_client`) so the conftest's `monkeypatch.setattr(cache_redis, "get_client", ...)` works. Every future handler that needs a monkeypatchable dependency should look it up via the module, not a bound import. conftest `MIG_DIR` is `__file__`-relative.
- **Task 9 ✅** — `backend/Dockerfile`, `backend/entrypoint.sh` (migrate→seed→uvicorn), `docker-compose.yml` (backend+redis+caddy), `Caddyfile`, `.dockerignore`, `.gitattributes`. **Verified: `docker compose up -d --build` → `localhost/healthz` HTTP 200 `{sqlite:true,redis:true}`; backend log applied migration + seeded 12; restart idempotent (schema up to date / already seeded); stack brought down clean.** Deviations vs plan: copy source before editable install (so `app` + the `__file__`-relative migrations/config paths resolve in-container); `.dockerignore` excludes `.venv`/git; Dockerfile `sed` strips CR from entrypoint (Windows authoring); Caddy `handle` blocks for deterministic routing.
- **Task 10 ✅** — `config/.env.example` (all env vars, local-first defaults, free data-source keys + X session cookies, commented) + `README.md` (run/test instructions). Full suite: **18 passed**.
- **🎉 M0 COMPLETE** — foundation runs end-to-end on localhost ($0): app + `/healthz`, SQLite/WAL schema + migrations, real seed, Redis, docker-compose. 18 tests green. Commits `75ae3b8`→`12d265d` (+ Task 10).
- **M1 — next milestone:** market-data pipeline (prices/volume via yfinance + pykrx/Finnhub fallback, FX, `price_poller`, `px:*` cache, `/stocks/{i}/price` + `/prices-across-markets`). Per the roadmap, **write the detailed M1 plan first**, then execute task-by-task.
