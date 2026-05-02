"""SQLite schema and write helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS stocks (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    market TEXT NOT NULL,
    is_st INTEGER NOT NULL DEFAULT 0,
    eligible INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS daily_bars (
    code TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL NOT NULL,
    close REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    volume REAL NOT NULL,
    amount REAL NOT NULL,
    amplitude REAL NOT NULL,
    pct_chg REAL NOT NULL,
    change_amount REAL NOT NULL,
    turnover REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'akshare',
    PRIMARY KEY (code, date)
);

CREATE INDEX IF NOT EXISTS idx_daily_bars_date ON daily_bars(date);
CREATE INDEX IF NOT EXISTS idx_daily_bars_code_date ON daily_bars(code, date);
CREATE INDEX IF NOT EXISTS idx_daily_bars_amount ON daily_bars(date, amount DESC);

CREATE TABLE IF NOT EXISTS popularity_rankings (
    source TEXT NOT NULL,
    date TEXT NOT NULL,
    rank INTEGER NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    score REAL,
    raw_json TEXT,
    PRIMARY KEY (source, date, code)
);

CREATE INDEX IF NOT EXISTS idx_popularity_date ON popularity_rankings(date, source, rank);

CREATE TABLE IF NOT EXISTS limit_up_pool (
    source TEXT NOT NULL,
    date TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    reason TEXT,
    streak INTEGER,
    first_limit_time TEXT,
    last_limit_time TEXT,
    seal_amount REAL,
    raw_json TEXT,
    PRIMARY KEY (source, date, code)
);

CREATE INDEX IF NOT EXISTS idx_limit_up_pool_date ON limit_up_pool(date, source, streak DESC);

CREATE TABLE IF NOT EXISTS data_quality_issues (
    run_id TEXT NOT NULL,
    file TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS strategy_backtests (
    strategy TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    trades INTEGER NOT NULL,
    signal_days INTEGER NOT NULL,
    win_rate REAL,
    avg_return_pct REAL,
    median_return_pct REAL,
    total_batch_return_pct REAL,
    max_drawdown_pct REAL,
    avg_gap_pct REAL,
    avg_hold_days REAL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS strategy_trades (
    strategy TEXT NOT NULL,
    signal_date TEXT NOT NULL,
    buy_date TEXT NOT NULL,
    sell_date TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    market TEXT NOT NULL,
    signal_close REAL NOT NULL,
    buy_open REAL NOT NULL,
    sell_close REAL NOT NULL,
    return_pct REAL NOT NULL,
    gap_pct REAL NOT NULL,
    amount_e8 REAL NOT NULL,
    volume_ratio REAL NOT NULL,
    new_high_days INTEGER NOT NULL,
    hold_days INTEGER NOT NULL,
    score REAL NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (strategy, signal_date, code)
);

CREATE INDEX IF NOT EXISTS idx_strategy_trades_strategy_date ON strategy_trades(strategy, signal_date);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    try:
        conn.execute("ALTER TABLE strategy_backtests ADD COLUMN avg_hold_days REAL")
    except sqlite3.OperationalError:
        pass
    return conn
