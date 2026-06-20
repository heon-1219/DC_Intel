-- M5d: daily bars for cross-market REFERENCE instruments (SOXX, ^N225, SPY, KR underlyings, ...).
-- Separate from technical_snapshots (which is keyed to a tracked stock_id); references are external
-- instruments we only need a split/div-adjusted daily close series for, to compute xmkt_ref_return
-- and xmkt_corr_60d (prediction-model.md §4.2 #13/#14). One row per (reference ticker, trading date).
CREATE TABLE cross_market_bars (
    ref_ticker TEXT NOT NULL,            -- yfinance ticker of the reference (e.g. 'SOXX', '^N225')
    date       TEXT NOT NULL,            -- reference trading date, 'YYYY-MM-DD'
    close      REAL NOT NULL,            -- adjusted close in the reference's own currency
    PRIMARY KEY (ref_ticker, date)
);
