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
    total_shares REAL,
    shares_updated_at TEXT,
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

CREATE TABLE IF NOT EXISTS lhb_records (
    date TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    reason TEXT,
    close REAL,
    pct_chg REAL,
    lhb_net_buy REAL,
    lhb_buy REAL,
    lhb_sell REAL,
    lhb_amount REAL,
    market_amount REAL,
    net_buy_ratio REAL,
    amount_ratio REAL,
    turnover REAL,
    float_mv REAL,
    after_1d REAL,
    after_2d REAL,
    after_5d REAL,
    after_10d REAL,
    raw_json TEXT,
    PRIMARY KEY (date, code)
);

CREATE INDEX IF NOT EXISTS idx_lhb_records_date ON lhb_records(date);
CREATE INDEX IF NOT EXISTS idx_lhb_records_code ON lhb_records(code);

CREATE TABLE IF NOT EXISTS lhb_seats (
    date TEXT NOT NULL,
    code TEXT NOT NULL,
    direction TEXT NOT NULL,
    seat_name TEXT NOT NULL,
    buy_amount REAL,
    buy_ratio REAL,
    sell_amount REAL,
    sell_ratio REAL,
    net_amount REAL,
    seat_type TEXT,
    PRIMARY KEY (date, code, direction, seat_name)
);

CREATE INDEX IF NOT EXISTS idx_lhb_seats_date_code ON lhb_seats(date, code);

-- ETF 每日快照：行情 + 技术信号
CREATE TABLE IF NOT EXISTS etf_daily (
    date TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    close REAL,
    pct_chg REAL,
    amount REAL,          -- 成交额（元）
    ma5 REAL,
    ma10 REAL,
    ma20 REAL,
    ma60 REAL,
    hist_high REAL,       -- 截至当日的历史最高收盘价
    is_new_high INTEGER DEFAULT 0,   -- 1=创历史新高
    ma20_up INTEGER DEFAULT 0,       -- 1=MA20向上（当日MA20>昨日MA20）
    ma60_up INTEGER DEFAULT 0,       -- 1=MA60向上
    above_ma20 INTEGER DEFAULT 0,    -- 1=收盘>MA20
    above_ma60 INTEGER DEFAULT 0,    -- 1=收盘>MA60
    PRIMARY KEY (date, code)
);

CREATE INDEX IF NOT EXISTS idx_etf_daily_date ON etf_daily(date);
CREATE INDEX IF NOT EXISTS idx_etf_daily_code ON etf_daily(code);

-- ETF 持仓（最新一期）
CREATE TABLE IF NOT EXISTS etf_holdings (
    code TEXT NOT NULL,           -- ETF代码（不含市场前缀）
    quarter TEXT NOT NULL,        -- 如 "2024年4季度"
    stock_code TEXT NOT NULL,
    stock_name TEXT NOT NULL,
    weight REAL,                  -- 占净值比例(%)
    shares REAL,
    market_value REAL,
    PRIMARY KEY (code, quarter, stock_code)
);

CREATE INDEX IF NOT EXISTS idx_etf_holdings_code ON etf_holdings(code);

CREATE TABLE IF NOT EXISTS market_daily (
    date TEXT PRIMARY KEY,         -- 交易日 YYYY-MM-DD
    zt_count INTEGER,              -- 涨停数（东财接口，收盘封板）
    dt_count INTEGER,              -- 跌停数（东财接口，收盘封板）
    zt_count_calc INTEGER,         -- 涨停数（pct_chg 自算，含炸板，备用）
    dt_count_calc INTEGER          -- 跌停数（pct_chg 自算，含炸板，备用）
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    # executescript() leaves connection in autocommit mode; restore normal mode
    conn.isolation_level = ""   # deferred transactions (default behaviour)
    try:
        conn.execute("ALTER TABLE strategy_backtests ADD COLUMN avg_hold_days REAL")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    return conn
