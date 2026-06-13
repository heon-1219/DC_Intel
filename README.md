# DC Intel

Beginner-friendly stock-direction prediction platform — predicts short-term up/down/neutral
with confidence and plain-language reasoning, fusing technical indicators, multi-source
sentiment, social-media market intel, and an economic calendar. **Local-first, free, real data.**

- Design docs: [`docs/`](docs/) (architecture, schema, pipelines, UI/UX, backend, decisions log).
- Implementation roadmap: [`docs/superpowers/plans/`](docs/superpowers/plans/) (milestones M0–M10).
- Working state / where we are: [`handoff.md`](handoff.md).

## Run (local-first, $0)

1. `cp config/.env.example .env` — optional for a quick start (compose has a dev default for
   `JWT_SECRET`); set your own `JWT_SECRET` (`openssl rand -hex 32`) before anything real.
2. `docker compose up -d --build`
3. Open <http://localhost/healthz> → `{"status":"ok","checks":{"sqlite":true,"redis":true}}`.

Stop with `docker compose down` (the `dbdata` named volume keeps the SQLite DB across restarts).

## Develop & test (uv)

```
uv venv --python 3.14 backend/.venv
uv pip install -p backend/.venv/Scripts/python.exe -e "./backend[dev]"
backend/.venv/Scripts/python.exe -m pytest backend/tests   # offline, no network
```

## Status

Phase 4 (implementation), milestone **M0 — Foundation** complete: FastAPI app + `/healthz`,
SQLite (WAL) schema + migration runner, real stock-universe seed, Redis, and the
docker-compose stack. Next: M1 — market-data pipeline. See `handoff.md`.
