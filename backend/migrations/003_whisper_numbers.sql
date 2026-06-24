-- AIWCE whisper-number corroboration results (one row per stock × earnings occurrence). The
-- scheduled whisper_corroborator job upserts the latest result OR a first-class abstention here;
-- the read API serves the newest row per stock. Mirrors the WhisperResult dataclass + the
-- corroborated/tentative/no_reliable_whisper status. Every abstention is stored (abstain_reason set,
-- whisper_value NULL) — honesty is recorded, not discarded. See
-- docs/superpowers/plans/2026-06-24-whisper-corroboration-engine.md.
CREATE TABLE whisper_numbers (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_id            INTEGER NOT NULL REFERENCES stocks(id) ON DELETE CASCADE,
    earnings_event_id   INTEGER REFERENCES economic_events(id) ON DELETE SET NULL,
    earnings_date       TEXT    NOT NULL,            -- 'YYYY-MM-DD' of the report being whispered
    status              TEXT    NOT NULL CHECK (status IN ('corroborated','tentative','no_reliable_whisper')),
    whisper_value       REAL,                        -- NULL on abstention
    confidence          INTEGER NOT NULL DEFAULT 0 CHECK (confidence BETWEEN 0 AND 100),
    anchor              REAL,                        -- official consensus EPS (mu0), NULL when NO_ANCHOR
    surprise_vs_anchor  REAL,
    inlier_dispersion   REAL,
    n_inliers           INTEGER NOT NULL DEFAULT 0,
    n_outliers_rejected INTEGER NOT NULL DEFAULT 0,
    n_distinct_families INTEGER NOT NULL DEFAULT 0,
    contributing_families_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(contributing_families_json)),
    factors_json        TEXT    NOT NULL DEFAULT '{}' CHECK (json_valid(factors_json)),
    rounds_used         INTEGER NOT NULL DEFAULT 0,
    abstain_reason      TEXT,                        -- NULL when a whisper was emitted; else the structured reason
    computed_at         TEXT    NOT NULL,
    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    -- one current row per stock × report date — the daily (denser near the date) rerun upserts in place.
    UNIQUE (stock_id, earnings_date)
);
CREATE INDEX idx_whisper_stock_recent ON whisper_numbers (stock_id, computed_at);
CREATE INDEX idx_whisper_event        ON whisper_numbers (earnings_event_id);
