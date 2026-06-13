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
