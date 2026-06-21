# DC Intel

Beginner-friendly short-term stock-direction prediction platform (Korea KRX + US + global;
Korean/English UI). Predicts up/down/neutral with a calibrated confidence and plain-language
reasoning, fusing technical indicators, multi-source sentiment, social-media market intel, and an
economic calendar — with **honest** win/loss tracking. **Local-first, completely free, real data.**

- Design docs: [`docs/`](docs/) — architecture, schema, pipelines, UI/UX, backend, decision log.
- Implementation plans: [`docs/superpowers/plans/`](docs/superpowers/plans/) — milestones M0–M10.
- Living working state: [`handoff.md`](handoff.md) · binding standards: [`CLAUDE.md`](CLAUDE.md).

Stack: Python 3.11 · FastAPI + APScheduler · SQLite (WAL) · Redis · React + Vite + TypeScript ·
Caddy · Docker Compose. Optional CPU ML (`[ml]`): mDeBERTa zero-shot sentiment + MiniLM clustering +
scikit-learn/xgboost prediction models.

## Run the whole app (local-first, $0)

```
cp .env.example .env            # then set JWT_SECRET (openssl rand -hex 32; ≥32 chars, REQUIRED)
docker compose up -d --build    # backend + redis + Caddy-served React SPA
```

- App: <http://localhost> · health: <http://localhost/healthz> → `{"sqlite":true,"redis":true}`.
- The SPA calls the API under `/api/*`; Caddy strips the prefix and proxies to the backend.
- Stop: `docker compose down` (the `dbdata` volume keeps the SQLite DB, models, backups, and the
  alert log across restarts).

> **Prediction serving needs model weights.** The trained `.pkl` files are gitignored (only the
> `manifest.json` gate results are tracked). Until they exist, `GET /api/stocks/{i}/predict` returns
> `503 MODEL_UNAVAILABLE` and the UI shows that timeframe as "in testing". Restore by re-running M5
> training (`python -m app.ml.backfill` then `python -m app.ml.train --timeframe 5d …`) or by copying
> `backend/models/**/*.pkl` from another machine. See `handoff.md`.

## Develop & test

**Backend** (uv; venv python is `backend/.venv/bin/python` on Linux/macOS,
`backend/.venv/Scripts/python.exe` on Windows):

```
uv venv --python 3.11 backend/.venv
uv pip install -p backend/.venv/bin/python -e "./backend[dev,ml]"   # [ml] is heavy CPU torch
backend/.venv/bin/python -m pytest backend/tests                    # 564 pass, 8 live deselected, offline
```

Set `UV_HTTP_TIMEOUT=900` before installing — the CPU torch wheel is large. The offline suite needs
`[dev]` + scikit-learn/xgboost/shap/joblib; the heavy torch/transformers trio is only for the
`-m live` ML tests and the docker runtime.

**Frontend** (Vite + React; Node ≥ 20, e.g. via nvm):

```
cd frontend
npm install
npm run dev        # http://localhost:5173 (proxies /api → http://localhost:8000)
npm test           # vitest, 44 tests
npm run build      # tsc --noEmit + production build
```

## Free data-source keys (all optional — each source self-disables when unset)

Fill these in `.env` to enrich the app; everything degrades gracefully without them (owner standard:
completely free, real data):

| Var | Source | Get it from |
|---|---|---|
| `FINNHUB_API_KEY` | US fallback quotes + earnings/news | finnhub.io (free tier) |
| `FRED_API_KEY` | economic-calendar release dates | fred.stlouisfed.org/docs/api |
| `NEWSAPI_API_KEY` | news sentiment | newsapi.org (free tier) |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | social intel | reddit.com/prefs/apps (script app) |
| `STOCKTWITS_ACCESS_TOKEN` | social intel | api.stocktwits.com (optional) |
| `TWITTER_AUTH_TOKEN` / `TWITTER_CT0` | X intel via logged-in session | browser cookies for x.com (personal-use; `auth_token` + `ct0` from DevTools → Application → Cookies). Requires `uv pip install twikit`. |

Ops knobs (safe defaults): `WIN_RATE_ALERT_THRESHOLD=0.50`, `WIN_RATE_WARN_THRESHOLD=0.52`,
`WIN_RATE_MIN_SAMPLE=30`; `ALERT_WEBHOOK_URL` blank → alerts go to `logs/alerts.log` + console;
`BACKUP_BUCKET` blank → nightly `VACUUM INTO` snapshots stay in the local `/data/backups` volume.

## Launch checklist (deployment-architecture §11, local-first)

1. Docker + Compose installed; `.env` populated (`JWT_SECRET` set).
2. `docker compose up -d --build` → `GET /healthz` 200.
3. Seed verified: `/api/stocks/search?q=삼성` returns Samsung Electronics with a live price overlay.
4. First nightly snapshot present in `/data/backups`; a restore drill done once.
5. A test alert appears in `logs/alerts.log` + console.
6. Ship gate: each served per-timeframe model has held-out win rate ≥ 52% (real history); failing
   timeframes ship disabled-with-note.
7. Rate-limit smoke: the 11th failed login in 15 min (same IP/email) → 429 with `Retry-After`.

## Status

✅ **M0–M10 complete** (foundation → market data → indicators → economic calendar → sentiment/intel
→ ML training → prediction serving + auth → win-loss tracking → dashboard API + hardening → React
frontend → local-first deploy). The `docker compose up` end-to-end smoke is the final gate — run it
once Docker is available on the host. See `handoff.md` for detail.
