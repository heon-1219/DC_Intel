# M0 — Foundation & Scaffolding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This is milestone M0 of `2026-06-13-dc-intel-phase4-roadmap.md`.

**Goal:** Stand up the DC Intel backend skeleton so `docker compose up` serves `GET http://localhost/healthz` = 200, with the full SQLite schema migrated, the stock universe seeded from real reference data, Redis wired, and a green pytest suite.

**Architecture:** FastAPI (async) app factory + aiosqlite (WAL) + redis-py async, all in one process. A numbered raw-SQL migration runner (`schema.md` §10) applies `001_initial_schema.sql` (the 9 tables). A three-container compose stack (backend + redis + Caddy) runs it on localhost.

**Tech stack:** Python 3.11, FastAPI, uvicorn, aiosqlite, redis, pydantic-settings, httpx; pytest, pytest-asyncio, fakeredis. Docker + Caddy.

**Conventions:** TDD (failing test → minimal code → green → commit). Exact paths. Real reference data in the seed. No network in the default test run.

---

## File structure built in M0

- `backend/pyproject.toml` — deps + pytest config
- `backend/app/__init__.py`, `backend/app/config.py` — settings
- `backend/app/db/connection.py` — aiosqlite factory + WAL pragmas
- `backend/app/db/migrate.py` — numbered-SQL runner + `schema_migrations`
- `backend/app/db/seed.py` — idempotent stock-universe seed
- `backend/migrations/001_initial_schema.sql` — the 9-table DDL (verbatim from `schema.md` §3)
- `backend/app/cache/redis.py` — async Redis client + `{data, meta}` envelope helper
- `backend/app/routers/health.py`, `backend/app/main.py` — app factory + `/healthz`
- `backend/Dockerfile`, `backend/entrypoint.sh`
- `config/seed_stocks.csv`, `config/.env.example`
- `docker-compose.yml`, `Caddyfile`, `.gitignore`, `README.md`
- `backend/tests/` — `conftest.py` + one test module per unit above

---

### Task 1: Repo init & backend package skeleton

**Files:**
- Create: `.gitignore`, `backend/pyproject.toml`, `backend/app/__init__.py`, `backend/tests/__init__.py`, `backend/tests/test_smoke.py`

- [ ] **Step 1: Initialize git and create `.gitignore`**

```bash
git init
```

`.gitignore`:
```
__pycache__/
*.pyc
.venv/
.env
data/
backend/data/
node_modules/
frontend/dist/
ml/artifacts/*.pkl
.pytest_cache/
```

- [ ] **Step 2: Create `backend/pyproject.toml`**

```toml
[project]
name = "dc-intel-backend"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "aiosqlite>=0.20",
    "redis>=5.0",
    "pydantic-settings>=2.2",
    "httpx>=0.27",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "fakeredis>=2.21", "anyio>=4.0"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 3: Write the smoke test**

`backend/tests/test_smoke.py`:
```python
def test_app_package_imports():
    import app
    assert app is not None
```

- [ ] **Step 4: Install deps and run the smoke test (expect PASS)**

Run (from `backend/`): `pip install -e ".[dev]" && pytest tests/test_smoke.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add .gitignore backend/pyproject.toml backend/app/__init__.py backend/tests/
git commit -m "chore: scaffold backend package and tooling"
```

---

### Task 2: Settings (`config.py`)

**Files:**
- Create: `backend/app/config.py`, `backend/tests/test_config.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_config.py`:
```python
import pytest
from app.config import Settings

def test_settings_load_with_required_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    s = Settings()
    assert s.env == "dev"
    assert s.database_url.startswith("sqlite")
    assert s.jwt_expiry_min == 1440
    assert s.bcrypt_rounds == 12

def test_sqlite_path_strips_sqlalchemy_prefix(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./data/dcintel.db")
    assert Settings().sqlite_path == "./data/dcintel.db"

def test_jwt_secret_too_short_is_rejected(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "short")
    with pytest.raises(ValueError):
        Settings()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.config'`.

- [ ] **Step 3: Write minimal implementation**

`backend/app/config.py`:
```python
from functools import lru_cache
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"
    domain: str = "localhost"
    database_url: str = "sqlite+aiosqlite:///./data/dcintel.db"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str
    jwt_expiry_min: int = 1440
    bcrypt_rounds: int = 12
    cors_origins: str = ""
    trust_proxy: bool = False
    log_level: str = "INFO"
    rate_limit_enabled: bool = True
    model_dir: str = "/data/models"
    twitter_enabled: bool = True

    @field_validator("jwt_secret")
    @classmethod
    def _secret_long_enough(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        return v

    @property
    def sqlite_path(self) -> str:
        # 'sqlite+aiosqlite:///./data/x.db' or 'sqlite:////data/x.db' -> filesystem path
        url = self.database_url
        for prefix in ("sqlite+aiosqlite://", "sqlite://"):
            if url.startswith(prefix):
                rest = url[len(prefix):]
                return rest[1:] if rest.startswith("/") and rest[1:2] == "/" else rest.lstrip("/") if rest.startswith("///") else rest
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: 3 passed. (If `test_sqlite_path` fails on the path-stripping edge case, simplify `sqlite_path` to: `return self.database_url.split(":///")[-1].lstrip("/") if ":////" in self.database_url else self.database_url.split(":///")[-1]` — re-run until the two cases `./data/dcintel.db` and `/data/dcintel.db` both pass.)

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/tests/test_config.py
git commit -m "feat: settings with env loading and JWT_SECRET validation"
```

---

### Task 3: SQLite connection factory (`db/connection.py`)

**Files:**
- Create: `backend/app/db/__init__.py`, `backend/app/db/connection.py`, `backend/tests/test_connection.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_connection.py`:
```python
import pytest
from app.db.connection import connect

@pytest.mark.asyncio
async def test_pragmas_applied(tmp_path):
    db = tmp_path / "t.db"
    async with connect(str(db)) as con:
        mode = (await (await con.execute("PRAGMA journal_mode")).fetchone())[0]
        fk = (await (await con.execute("PRAGMA foreign_keys")).fetchone())[0]
    assert mode.lower() == "wal"
    assert fk == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_connection.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db.connection'`.

- [ ] **Step 3: Write minimal implementation**

`backend/app/db/__init__.py`: (empty file)

`backend/app/db/connection.py`:
```python
from contextlib import asynccontextmanager
import aiosqlite

PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA busy_timeout=5000",
    "PRAGMA foreign_keys=ON",
)


@asynccontextmanager
async def connect(sqlite_path: str):
    con = await aiosqlite.connect(sqlite_path)
    try:
        for p in PRAGMAS:
            await con.execute(p)
        con.row_factory = aiosqlite.Row
        yield con
    finally:
        await con.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_connection.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/__init__.py backend/app/db/connection.py backend/tests/test_connection.py
git commit -m "feat: aiosqlite connection factory with WAL pragmas"
```

---

### Task 4: Initial migration SQL (`001_initial_schema.sql`)

**Files:**
- Create: `backend/migrations/001_initial_schema.sql`

- [ ] **Step 1: Create the migration file (verbatim from `schema.md` §3 — the 9 tables + indexes)**

`backend/migrations/001_initial_schema.sql`:
```sql
-- DC Intel v1 initial schema. SQLite >= 3.38 (JSON1). schema.md §3 is authoritative.

CREATE TABLE users (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    email              TEXT    NOT NULL COLLATE NOCASE,
    password_hash      TEXT    NOT NULL,
    preferred_language TEXT    NOT NULL DEFAULT 'ko' CHECK (preferred_language IN ('ko','en')),
    created_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE UNIQUE INDEX idx_users_email ON users (email);

CREATE TABLE stocks (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol            TEXT    NOT NULL,
    exchange          TEXT    NOT NULL,
    region            TEXT    NOT NULL,
    company_name      TEXT    NOT NULL,
    company_name_ko   TEXT,
    company_group     TEXT,
    security_type     TEXT    NOT NULL DEFAULT 'common',
    currency          TEXT    NOT NULL DEFAULT 'USD',
    board             TEXT,
    yfinance_ticker   TEXT    NOT NULL,
    finnhub_ticker    TEXT,
    adr_ratio         REAL,
    xmkt_reference    TEXT,
    listing_price_usd REAL,
    is_active         INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (symbol, exchange)
);
CREATE INDEX idx_stocks_company_group ON stocks (company_group) WHERE company_group IS NOT NULL;
CREATE INDEX idx_stocks_symbol        ON stocks (symbol);

CREATE TABLE predictions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER REFERENCES users(id) ON DELETE SET NULL,
    stock_id         INTEGER NOT NULL REFERENCES stocks(id) ON DELETE RESTRICT,
    timeframe        TEXT    NOT NULL CHECK (timeframe IN ('1h','5h','24h','2d','3d','5d')),
    direction        TEXT    NOT NULL CHECK (direction IN ('up','down','neutral')),
    confidence       INTEGER NOT NULL CHECK (confidence BETWEEN 0 AND 100),
    reasoning_json   TEXT    NOT NULL CHECK (json_valid(reasoning_json)),
    model_version    TEXT    NOT NULL,
    window_closes_at TEXT    NOT NULL,
    created_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    checked_at       TEXT
);
CREATE INDEX idx_predictions_due           ON predictions (window_closes_at) WHERE checked_at IS NULL;
CREATE INDEX idx_predictions_accuracy      ON predictions (stock_id, timeframe) WHERE checked_at IS NOT NULL;
CREATE INDEX idx_predictions_model_version ON predictions (model_version) WHERE checked_at IS NOT NULL;
CREATE INDEX idx_predictions_user_recent   ON predictions (user_id, created_at);
CREATE INDEX idx_predictions_stock_latest  ON predictions (stock_id, timeframe, created_at);

CREATE TABLE prediction_outcomes (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_id               INTEGER NOT NULL UNIQUE REFERENCES predictions(id) ON DELETE CASCADE,
    actual_direction            TEXT    NOT NULL CHECK (actual_direction IN ('up','down','neutral')),
    actual_price_change_percent REAL    NOT NULL,
    marked_correct              INTEGER NOT NULL CHECK (marked_correct IN (0,1)),
    exit_price                  REAL,
    high_impact_event_overlap   INTEGER CHECK (high_impact_event_overlap IN (0,1)),
    created_at                  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE sentiment_logs (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_id                  INTEGER NOT NULL REFERENCES stocks(id) ON DELETE RESTRICT,
    timestamp                 TEXT    NOT NULL,
    aggregate_sentiment_score REAL    CHECK (aggregate_sentiment_score IS NULL OR aggregate_sentiment_score BETWEEN -100 AND 100),
    source_breakdown_json     TEXT    NOT NULL CHECK (json_valid(source_breakdown_json)),
    UNIQUE (stock_id, timestamp)
);

CREATE TABLE economic_events (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    event_name              TEXT    NOT NULL,
    event_time              TEXT    NOT NULL,
    impact_level            TEXT    NOT NULL DEFAULT 'low' CHECK (impact_level IN ('high','medium','low')),
    affected_stocks_json    TEXT    CHECK (affected_stocks_json IS NULL OR json_valid(affected_stocks_json)),
    actual_vs_forecast_json TEXT    CHECK (actual_vs_forecast_json IS NULL OR json_valid(actual_vs_forecast_json)),
    provider                TEXT    NOT NULL,
    provider_event_id       TEXT,
    event_type              TEXT    NOT NULL,
    title_ko                TEXT,
    country                 TEXT    NOT NULL,
    impact_source           TEXT    NOT NULL DEFAULT 'default' CHECK (impact_source IN ('override','provider','default')),
    status                  TEXT    NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled','released','revised','cancelled')),
    created_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (provider, provider_event_id),
    UNIQUE (event_type, event_time)
);
CREATE INDEX idx_econ_events_sched  ON economic_events (event_time);
CREATE INDEX idx_econ_events_type   ON economic_events (event_type, event_time);
CREATE INDEX idx_econ_events_impact ON economic_events (impact_level, event_time);

CREATE TABLE technical_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_id        INTEGER NOT NULL REFERENCES stocks(id) ON DELETE RESTRICT,
    timestamp       TEXT    NOT NULL,
    bar_interval    TEXT    NOT NULL CHECK (bar_interval IN ('5m','15m','1h','1d')),
    rsi             REAL    CHECK (rsi IS NULL OR (rsi >= 0 AND rsi <= 100)),
    ema_5           REAL,
    ema_20          REAL,
    ema_50          REAL,
    ema_200         REAL,
    macd            REAL,
    macd_signal     REAL,
    macd_histogram  REAL,
    bollinger_upper REAL,
    bollinger_lower REAL,
    bollinger_middle REAL,
    indicators_json TEXT    NOT NULL CHECK (json_valid(indicators_json)),
    UNIQUE (stock_id, bar_interval, timestamp)
);

CREATE TABLE feature_importance_logs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    model_version    TEXT    NOT NULL,
    timeframe        TEXT    NOT NULL CHECK (timeframe IN ('1h','5h','24h','2d','3d','5d')),
    feature_name     TEXT    NOT NULL,
    importance_score REAL    NOT NULL,
    window_start     TEXT    NOT NULL,
    window_end       TEXT    NOT NULL,
    created_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (model_version, feature_name)
);
CREATE INDEX idx_fil_version ON feature_importance_logs (model_version, timeframe);

CREATE TABLE market_intel (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_id             INTEGER REFERENCES stocks(id) ON DELETE SET NULL,
    source               TEXT    NOT NULL,
    author_handle        TEXT    NOT NULL,
    url                  TEXT,
    content_snippet      TEXT    NOT NULL,
    posted_at            TEXT    NOT NULL,
    credibility_score    INTEGER NOT NULL DEFAULT 50 CHECK (credibility_score BETWEEN 0 AND 100),
    sentiment            TEXT    NOT NULL DEFAULT 'neutral' CHECK (sentiment IN ('bullish','bearish','neutral')),
    sentiment_confidence REAL    NOT NULL DEFAULT 0 CHECK (sentiment_confidence BETWEEN 0 AND 1),
    confirmed            INTEGER NOT NULL DEFAULT 0 CHECK (confirmed IN (0,1)),
    cluster_id           TEXT,
    created_at           TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX idx_intel_recency       ON market_intel (created_at);
CREATE INDEX idx_intel_stock_recency ON market_intel (stock_id, created_at);
CREATE INDEX idx_intel_cluster       ON market_intel (cluster_id);
CREATE INDEX idx_intel_author        ON market_intel (source, author_handle, posted_at);
```

- [ ] **Step 2: Commit (file is exercised by Task 5's tests)**

```bash
git add backend/migrations/001_initial_schema.sql
git commit -m "feat: initial schema migration (9 tables) per schema.md §3"
```

---

### Task 5: Migration runner (`db/migrate.py`)

**Files:**
- Create: `backend/app/db/migrate.py`, `backend/tests/test_migrate.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_migrate.py`:
```python
import sqlite3
import pytest
from app.db.migrate import migrate

MIG_DIR = "migrations"  # run pytest from backend/

def _tables(db):
    con = sqlite3.connect(db)
    rows = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    con.close()
    return {r[0] for r in rows}

def test_migrate_creates_all_tables(tmp_path):
    db = str(tmp_path / "t.db")
    applied = migrate(db, MIG_DIR)
    assert "001_initial_schema.sql" in applied
    expected = {"users","stocks","predictions","prediction_outcomes","sentiment_logs",
                "economic_events","technical_snapshots","feature_importance_logs",
                "market_intel","schema_migrations"}
    assert expected.issubset(_tables(db))

def test_migrate_is_idempotent(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG_DIR)
    second = migrate(db, MIG_DIR)
    assert second == []          # nothing re-applied

def test_check_constraint_rejects_bad_timeframe(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG_DIR)
    con = sqlite3.connect(db)
    con.execute("INSERT INTO stocks (symbol,exchange,region,company_name,yfinance_ticker) "
                "VALUES ('T','NASDAQ','US','T','T')")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO predictions (stock_id,timeframe,direction,confidence,"
                    "reasoning_json,model_version,window_closes_at) "
                    "VALUES (1,'9h','up',50,'{}','24h-xgb-20260608.1','2026-01-01T00:00:00Z')")
    con.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_migrate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db.migrate'`.

- [ ] **Step 3: Write minimal implementation**

`backend/app/db/migrate.py`:
```python
import sqlite3
import sys
from pathlib import Path

from app.config import get_settings


def migrate(db_path: str, migrations_dir: str) -> list[str]:
    """Apply pending numbered .sql migrations. Returns filenames newly applied."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys=ON")
    con.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version TEXT PRIMARY KEY, filename TEXT NOT NULL,"
        " applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))"
    )
    con.commit()
    applied = {r[0] for r in con.execute("SELECT version FROM schema_migrations")}
    newly: list[str] = []
    for f in sorted(Path(migrations_dir).glob("*.sql")):
        version = f.name.split("_", 1)[0]
        if version in applied:
            continue
        sql = f.read_text(encoding="utf-8")
        # Wrap the file in one transaction so a mid-file failure rolls the whole file back.
        con.executescript("BEGIN;\n" + sql + "\nCOMMIT;")
        con.execute("INSERT INTO schema_migrations (version, filename) VALUES (?, ?)",
                    (version, f.name))
        con.commit()
        newly.append(f.name)
    con.close()
    return newly


if __name__ == "__main__":
    s = get_settings()
    done = migrate(s.sqlite_path, "migrations")
    print(f"applied: {done}" if done else "schema up to date")
    sys.exit(0)
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `backend/`): `pytest tests/test_migrate.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/migrate.py backend/tests/test_migrate.py
git commit -m "feat: numbered-SQL migration runner with schema_migrations tracking"
```

---

### Task 6: Stock-universe seed (`db/seed.py` + `config/seed_stocks.csv`)

**Files:**
- Create: `config/seed_stocks.csv`, `backend/app/db/seed.py`, `backend/tests/test_seed.py`

- [ ] **Step 1: Create the seed CSV (real reference data)**

`config/seed_stocks.csv`:
```csv
symbol,exchange,region,company_name,company_name_ko,company_group,security_type,currency,board,yfinance_ticker,finnhub_ticker,adr_ratio,xmkt_reference,listing_price_usd
005930,KRX,KR,Samsung Electronics,삼성전자,samsung-electronics,common,KRW,KOSPI,005930.KS,,,SOXX,
000660,KRX,KR,SK hynix,SK하이닉스,sk-hynix,common,KRW,KOSPI,000660.KS,,,SOXX,
005380,KRX,KR,Hyundai Motor,현대차,hyundai-motor,common,KRW,KOSPI,005380.KS,,,,
035420,KRX,KR,NAVER,네이버,naver,common,KRW,KOSPI,035420.KS,,,,
AAPL,NASDAQ,US,Apple Inc.,애플,apple,common,USD,,AAPL,AAPL,,^N225,
NVDA,NASDAQ,US,NVIDIA Corporation,엔비디아,nvidia,common,USD,,NVDA,NVDA,,SOXX,
PKX,NYSE,US,POSCO Holdings (ADR),포스코홀딩스 ADR,posco-holdings,adr,USD,,PKX,PKX,1,005490:KRX,
KOSPI,INDEX,KR,KOSPI,코스피,,index,KRW,,^KS11,,,,
NASDAQ_COMPOSITE,INDEX,US,NASDAQ Composite,나스닥 종합,,index,USD,,^IXIC,,,,
SP500,INDEX,US,S&P 500,S&P 500,,index,USD,,^GSPC,,,,
NIKKEI225,INDEX,JP,Nikkei 225,니케이 225,,index,JPY,,^N225,,,,
DAX,INDEX,DE,DAX,닥스,,index,EUR,,^GDAXI,,,,
```

- [ ] **Step 2: Write the failing test**

`backend/tests/test_seed.py`:
```python
import sqlite3
from app.db.migrate import migrate
from app.db.seed import seed_stocks

CSV = "../config/seed_stocks.csv"  # from backend/

def _count(db):
    con = sqlite3.connect(db); n = con.execute("SELECT COUNT(*) FROM stocks").fetchone()[0]; con.close(); return n

def test_seed_populates_when_empty(tmp_path):
    db = str(tmp_path / "t.db"); migrate(db, "migrations")
    inserted = seed_stocks(db, CSV)
    assert inserted >= 12
    assert _count(db) == inserted

def test_seed_is_idempotent(tmp_path):
    db = str(tmp_path / "t.db"); migrate(db, "migrations")
    seed_stocks(db, CSV)
    again = seed_stocks(db, CSV)        # table non-empty -> no-op
    assert again == 0

def test_seed_resolves_symbol_exchange(tmp_path):
    db = str(tmp_path / "t.db"); migrate(db, "migrations"); seed_stocks(db, CSV)
    con = sqlite3.connect(db)
    row = con.execute("SELECT yfinance_ticker FROM stocks WHERE symbol='005930' AND exchange='KRX'").fetchone()
    con.close()
    assert row[0] == "005930.KS"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_seed.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db.seed'`.

- [ ] **Step 4: Write minimal implementation**

`backend/app/db/seed.py`:
```python
import csv
import sqlite3
import sys
from pathlib import Path

from app.config import get_settings

COLUMNS = ["symbol","exchange","region","company_name","company_name_ko","company_group",
           "security_type","currency","board","yfinance_ticker","finnhub_ticker",
           "adr_ratio","xmkt_reference","listing_price_usd"]


def seed_stocks(db_path: str, csv_path: str) -> int:
    """Insert the stock universe only if `stocks` is empty. Returns rows inserted."""
    con = sqlite3.connect(db_path)
    if con.execute("SELECT COUNT(*) FROM stocks").fetchone()[0] > 0:
        con.close()
        return 0
    inserted = 0
    with open(csv_path, newline="", encoding="utf-8") as fh:
        placeholders = ",".join("?" * len(COLUMNS))
        for row in csv.DictReader(fh):
            values = [(row[c] if row[c] != "" else None) for c in COLUMNS]
            con.execute(f"INSERT INTO stocks ({','.join(COLUMNS)}) VALUES ({placeholders})", values)
            inserted += 1
    con.commit()
    con.close()
    return inserted


if __name__ == "__main__":
    s = get_settings()
    n = seed_stocks(s.sqlite_path, str(Path("../config/seed_stocks.csv")))
    print(f"seeded {n} stocks" if n else "stocks already seeded")
    sys.exit(0)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_seed.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add config/seed_stocks.csv backend/app/db/seed.py backend/tests/test_seed.py
git commit -m "feat: idempotent stock-universe seed from real reference data"
```

---

### Task 7: Redis client + response envelope (`cache/redis.py`)

**Files:**
- Create: `backend/app/cache/__init__.py`, `backend/app/cache/redis.py`, `backend/tests/test_redis.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_redis.py`:
```python
import pytest
import fakeredis.aioredis
from app.cache.redis import make_envelope, ping

@pytest.mark.asyncio
async def test_ping_ok():
    r = fakeredis.aioredis.FakeRedis()
    assert await ping(r) is True

def test_envelope_shape():
    env = make_envelope({"price": 100}, source="yfinance",
                        data_as_of="2026-06-13T00:00:00Z", is_stale=False,
                        cache="hit", request_id="req_1")
    assert env["data"] == {"price": 100}
    assert env["meta"] == {"source": "yfinance", "data_as_of": "2026-06-13T00:00:00Z",
                           "is_stale": False, "cache": "hit", "request_id": "req_1"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_redis.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.cache.redis'`.

- [ ] **Step 3: Write minimal implementation**

`backend/app/cache/__init__.py`: (empty file)

`backend/app/cache/redis.py`:
```python
from typing import Any
import redis.asyncio as aioredis

from app.config import get_settings


def get_client() -> aioredis.Redis:
    return aioredis.from_url(get_settings().redis_url, decode_responses=True)


async def ping(client) -> bool:
    try:
        return bool(await client.ping())
    except Exception:
        return False


def make_envelope(data: Any, *, source: str, data_as_of: str, is_stale: bool,
                  cache: str, request_id: str) -> dict:
    """The canonical {data, meta} response envelope (backend-design.md §12)."""
    return {
        "data": data,
        "meta": {"source": source, "data_as_of": data_as_of, "is_stale": is_stale,
                 "cache": cache, "request_id": request_id},
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_redis.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/cache/ backend/tests/test_redis.py
git commit -m "feat: async Redis client and {data, meta} response envelope"
```

---

### Task 8: App factory + `/healthz`

**Files:**
- Create: `backend/app/routers/__init__.py`, `backend/app/routers/health.py`, `backend/app/main.py`, `backend/tests/conftest.py`, `backend/tests/test_health.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/conftest.py`:
```python
import pytest
import fakeredis.aioredis

@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path/'t.db'}")
    from app.config import get_settings
    get_settings.cache_clear()
    from app.db.migrate import migrate
    migrate(get_settings().sqlite_path, "migrations")

    import app.cache.redis as rediscache
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(rediscache, "get_client", lambda: fake)

    from app.main import create_app
    import httpx
    application = create_app()
    transport = httpx.ASGITransport(app=application)
    return httpx.AsyncClient(transport=transport, base_url="http://test")
```

`backend/tests/test_health.py`:
```python
import pytest

@pytest.mark.asyncio
async def test_healthz_ok(app_client):
    async with app_client as c:
        r = await c.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["checks"]["sqlite"] is True
    assert body["checks"]["redis"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_health.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.main'`.

- [ ] **Step 3: Write minimal implementation**

`backend/app/routers/__init__.py`: (empty file)

`backend/app/routers/health.py`:
```python
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db.connection import connect
from app.cache.redis import get_client, ping

router = APIRouter()


@router.get("/healthz")
async def healthz():
    checks = {"sqlite": False, "redis": False}
    try:
        async with connect(get_settings().sqlite_path) as con:
            await (await con.execute("SELECT 1")).fetchone()
        checks["sqlite"] = True
    except Exception:
        pass
    client = get_client()
    checks["redis"] = await ping(client)
    ok = all(checks.values())
    return JSONResponse(status_code=200 if ok else 503,
                        content={"status": "ok" if ok else "degraded", "checks": checks})
```

`backend/app/main.py`:
```python
from fastapi import FastAPI

from app.routers import health


def create_app() -> FastAPI:
    app = FastAPI(title="DC Intel API", version="0.1.0")
    app.include_router(health.router)
    return app


app = create_app()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_health.py -v`
Expected: 1 passed.

- [ ] **Step 5: Run the whole suite**

Run: `pytest -v`
Expected: all tests pass (smoke, config, connection, migrate, seed, redis, health).

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/ backend/app/main.py backend/tests/conftest.py backend/tests/test_health.py
git commit -m "feat: FastAPI app factory and /healthz with sqlite+redis checks"
```

---

### Task 9: Container stack (Dockerfile, compose, Caddy, entrypoint)

**Files:**
- Create: `backend/Dockerfile`, `backend/entrypoint.sh`, `docker-compose.yml`, `Caddyfile`

- [ ] **Step 1: Write the backend entrypoint**

`backend/entrypoint.sh`:
```bash
#!/bin/sh
set -e
python -m app.db.migrate
python -m app.db.seed
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

- [ ] **Step 2: Write the Dockerfile**

`backend/Dockerfile`:
```dockerfile
FROM python:3.11-slim
WORKDIR /srv/backend
COPY backend/pyproject.toml ./
RUN pip install --no-cache-dir -e .
COPY backend/ ./
COPY config/ /srv/config/
ENV DATABASE_URL=sqlite+aiosqlite:////data/dcintel.db
RUN chmod +x entrypoint.sh
CMD ["./entrypoint.sh"]
```

(Note: `app.db.seed` reads `../config/seed_stocks.csv` relative to `/srv/backend`, resolving to `/srv/config/seed_stocks.csv` — matches the COPY above.)

- [ ] **Step 3: Write the Caddyfile (localhost, plain HTTP — local-first)**

`Caddyfile`:
```
:80 {
    reverse_proxy /healthz backend:8000
    reverse_proxy /auth/* backend:8000
    reverse_proxy /stocks/* backend:8000
    reverse_proxy /dashboard/* backend:8000
    respond "DC Intel — frontend mounts here in M9" 200
}
```

- [ ] **Step 4: Write docker-compose.yml**

`docker-compose.yml`:
```yaml
services:
  backend:
    build:
      context: .
      dockerfile: backend/Dockerfile
    environment:
      - JWT_SECRET=${JWT_SECRET:-dev-only-change-me-0000000000000000}
      - DATABASE_URL=sqlite+aiosqlite:////data/dcintel.db
      - REDIS_URL=redis://redis:6379/0
    volumes:
      - dbdata:/data
    depends_on: [redis]
    restart: unless-stopped
  redis:
    image: redis:7-alpine
    restart: unless-stopped
  web:
    image: caddy:2-alpine
    ports: ["80:80"]
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
    depends_on: [backend]
    restart: unless-stopped
volumes:
  dbdata:
```

- [ ] **Step 5: Verify the stack runs (manual integration check)**

Run:
```bash
JWT_SECRET=$(python -c "import secrets;print(secrets.token_hex(32))") docker compose up -d --build
sleep 8
curl -s -o /dev/null -w "%{http_code}" http://localhost/healthz
```
Expected: `200`. Then `docker compose logs backend` shows `applied: ['001_initial_schema.sql']` and `seeded 12 stocks` on first boot, and `docker compose down && docker compose up -d` shows `schema up to date` / `stocks already seeded` (idempotent).

- [ ] **Step 6: Commit**

```bash
git add backend/Dockerfile backend/entrypoint.sh docker-compose.yml Caddyfile
git commit -m "feat: local-first docker-compose stack (backend + redis + caddy)"
```

---

### Task 10: `.env.example` + README + final commit

**Files:**
- Create: `config/.env.example`, `README.md`

- [ ] **Step 1: Write `config/.env.example`** (mirrors `deployment-architecture.md` §7.2; local-first defaults)

```bash
ENV=dev
DOMAIN=localhost
DATABASE_URL=sqlite+aiosqlite:////data/dcintel.db
REDIS_URL=redis://redis:6379/0
JWT_SECRET=            # openssl rand -hex 32  (>= 32 chars; required)
JWT_EXPIRY_MIN=1440
BCRYPT_ROUNDS=12
CORS_ORIGINS=http://localhost:5173
TRUST_PROXY=false
LOG_LEVEL=INFO
RATE_LIMIT_ENABLED=true
MODEL_DIR=/data/models
# Data sources (all free tiers) — added as their milestones land:
# FRED_API_KEY=   FINNHUB_API_KEY=   NEWSAPI_API_KEY=
# REDDIT_CLIENT_ID=  REDDIT_CLIENT_SECRET=  REDDIT_USER_AGENT=  STOCKTWITS_ACCESS_TOKEN=
# Twitter/X (logged-in session scraping, data-sources.md §4.1):
# TWITTER_ENABLED=true  TWITTER_AUTH_TOKEN=  TWITTER_CT0=
```

- [ ] **Step 2: Write `README.md`** (M0 run instructions)

```markdown
# DC Intel

Beginner-friendly stock-direction prediction platform. Local-first, free, real data.
Design docs in `docs/`; implementation roadmap in `docs/superpowers/plans/`.

## Run (local-first, $0)
1. `cp config/.env.example .env` and set `JWT_SECRET` (`openssl rand -hex 32`).
2. `docker compose up -d --build`
3. Open http://localhost/healthz → `{"status":"ok"}`.

## Develop / test
```
cd backend
pip install -e ".[dev]"
pytest          # offline, no network
```
```

- [ ] **Step 3: Run the full suite one more time**

Run (from `backend/`): `pytest -v`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add config/.env.example README.md
git commit -m "docs: env example and README with local run instructions"
```

---

## Self-Review

**Spec coverage (vs. roadmap M0 exit criteria):**
- `docker compose up` → `/healthz` 200 → Task 8 (endpoint) + Task 9 (stack). ✓
- 9 tables + hot indexes exist, migrations idempotent → Task 4 (DDL) + Task 5 (runner + tests). ✓
- CHECK constraints reject bad timeframe/direction → Task 5 test `test_check_constraint_rejects_bad_timeframe`. ✓
- Seed from real reference data, idempotent → Task 6. ✓
- pytest green, offline → Tasks 1–8 tests; no network used (fakeredis, temp SQLite). ✓
- Config fail-fast on short `JWT_SECRET` → Task 2. ✓

**Placeholder scan:** every code/SQL/command step contains complete content; no TODO/TBD. The one judgment call (`sqlite_path` edge case) ships with an explicit fallback in Task 2 Step 4. ✓

**Type/name consistency:** `migrate(db_path, migrations_dir)` signature used identically in Tasks 5/6/8; `seed_stocks(db_path, csv_path)` consistent in Task 6 + entrypoint; `connect(sqlite_path)` consistent in Tasks 3/8; envelope keys (`data`/`meta`/`source`/`data_as_of`/`is_stale`/`cache`/`request_id`) match `backend-design.md` §12; the 9 table names match `schema.md` §3 exactly; the seed CSV columns match the `stocks` DDL column list. ✓

**Carry-forward to M1:** `/healthz` will gain the scheduler-heartbeat check (`ops:heartbeat` < 3 min) once APScheduler exists; Caddy gains the SPA mount in M9; the env file grows per-milestone.

---

## Execution Handoff

Two execution options once the plan is approved:
1. **Subagent-Driven (recommended)** — fresh subagent per task, two-stage review between tasks (`superpowers:subagent-driven-development`).
2. **Inline Execution** — batch tasks in this session with checkpoints (`superpowers:executing-plans`).
