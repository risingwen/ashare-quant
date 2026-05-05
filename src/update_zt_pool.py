#!/usr/bin/env python3
"""
涨停池数据采集：每日涨停 + 前日涨停今日表现（用于连板晋级率统计）

用法：
  python update_zt_pool.py                    # 采集今日
  python update_zt_pool.py --date 20260430    # 指定日期
  python update_zt_pool.py --backfill 30      # 回填最近N个交易日
"""

from __future__ import annotations

import argparse
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import akshare as ak

from quant_core import DEFAULT_DB_PATH, compact_date, normalize_date, to_float
from quant_db import connect


DDL = """
CREATE TABLE IF NOT EXISTS zt_pool (
    date        TEXT NOT NULL,
    code        TEXT NOT NULL,
    name        TEXT NOT NULL,
    pct_chg     REAL,
    close       REAL,
    amount      REAL,
    float_mv    REAL,
    total_mv    REAL,
    turnover    REAL,
    seal_amount REAL,
    first_limit_time TEXT,
    last_limit_time  TEXT,
    open_times  INTEGER,
    streak      INTEGER,
    zt_stat     TEXT,
    industry    TEXT,
    PRIMARY KEY (date, code)
);
CREATE INDEX IF NOT EXISTS idx_zt_pool_date ON zt_pool(date);
CREATE INDEX IF NOT EXISTS idx_zt_pool_code ON zt_pool(code);

CREATE TABLE IF NOT EXISTS zt_previous (
    date        TEXT NOT NULL,   -- 今日日期
    code        TEXT NOT NULL,
    name        TEXT NOT NULL,
    pct_chg     REAL,            -- 今日涨跌幅
    close       REAL,
    amount      REAL,
    float_mv    REAL,
    total_mv    REAL,
    turnover    REAL,
    prev_streak INTEGER,         -- 昨日连板数
    zt_stat     TEXT,
    industry    TEXT,
    PRIMARY KEY (date, code)
);
CREATE INDEX IF NOT EXISTS idx_zt_previous_date ON zt_previous(date);
"""


def ensure_schema(conn) -> None:
    for stmt in DDL.strip().split(";"):
        s = stmt.strip()
        if s:
            conn.execute(s)


def fetch_zt_pool(date_compact: str) -> list[dict]:
    """采集当日涨停池"""
    try:
        df = ak.stock_zt_pool_em(date=date_compact)
        if df is None or df.empty:
            return []
        rows = []
        date_norm = normalize_date(date_compact)
        for _, r in df.iterrows():
            rows.append({
                "date": date_norm,
                "code": str(r.get("代码", "")).zfill(6),
                "name": str(r.get("名称", "")),
                "pct_chg": to_float(r.get("涨跌幅")),
                "close": to_float(r.get("最新价")),
                "amount": to_float(r.get("成交额")),
                "float_mv": to_float(r.get("流通市值")),
                "total_mv": to_float(r.get("总市值")),
                "turnover": to_float(r.get("换手率")),
                "seal_amount": to_float(r.get("封板资金")),
                "first_limit_time": str(r.get("首次封板时间", "") or ""),
                "last_limit_time": str(r.get("最后封板时间", "") or ""),
                "open_times": int(r.get("炸板次数") or 0),
                "streak": int(r.get("连板数") or 1),
                "zt_stat": str(r.get("涨停统计", "") or ""),
                "industry": str(r.get("所属行业", "") or ""),
            })
        return rows
    except Exception as e:
        print(f"  zt_pool fetch error {date_compact}: {e}")
        return []


def fetch_zt_previous(date_compact: str) -> list[dict]:
    """采集前日涨停股今日表现（用于晋级率）"""
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(ak.stock_zt_pool_previous_em, date=date_compact)
            try:
                df = future.result(timeout=15)
            except FuturesTimeout:
                print("  (zt_previous timeout, skip)", end=" ")
                return []
        if df is None or df.empty:
            return []
        rows = []
        date_norm = normalize_date(date_compact)
        for _, r in df.iterrows():
            rows.append({
                "date": date_norm,
                "code": str(r.get("代码", "")).zfill(6),
                "name": str(r.get("名称", "")),
                "pct_chg": to_float(r.get("涨跌幅")),
                "close": to_float(r.get("最新价")),
                "amount": to_float(r.get("成交额")),
                "float_mv": to_float(r.get("流通市值")),
                "total_mv": to_float(r.get("总市值")),
                "turnover": to_float(r.get("换手率")),
                "prev_streak": int(r.get("昨日连板数") or 1),
                "zt_stat": str(r.get("涨停统计", "") or ""),
                "industry": str(r.get("所属行业", "") or ""),
            })
        return rows
    except Exception as e:
        print(f"  zt_previous fetch error {date_compact}: {e}")
        return []


def upsert_zt_pool(conn, rows: list[dict]) -> None:
    conn.executemany("""
        INSERT OR REPLACE INTO zt_pool
            (date, code, name, pct_chg, close, amount, float_mv, total_mv,
             turnover, seal_amount, first_limit_time, last_limit_time,
             open_times, streak, zt_stat, industry)
        VALUES
            (:date, :code, :name, :pct_chg, :close, :amount, :float_mv, :total_mv,
             :turnover, :seal_amount, :first_limit_time, :last_limit_time,
             :open_times, :streak, :zt_stat, :industry)
    """, rows)


def upsert_zt_previous(conn, rows: list[dict]) -> None:
    conn.executemany("""
        INSERT OR REPLACE INTO zt_previous
            (date, code, name, pct_chg, close, amount, float_mv, total_mv,
             turnover, prev_streak, zt_stat, industry)
        VALUES
            (:date, :code, :name, :pct_chg, :close, :amount, :float_mv, :total_mv,
             :turnover, :prev_streak, :zt_stat, :industry)
    """, rows)


def get_recent_trading_dates(n: int) -> list[str]:
    """从 AkShare 获取最近 n 个交易日（compact 格式）"""
    try:
        df = ak.tool_trade_date_hist_sina()
        dates = sorted(df.iloc[:, 0].astype(str).tolist(), reverse=True)
        from datetime import date
        today = date.today().strftime("%Y-%m-%d")
        dates = [d for d in dates if d <= today]
        return [d.replace("-", "") for d in dates[:n]]
    except Exception as e:
        print(f"Failed to get trading calendar: {e}")
        return []


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="采集涨停池数据")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--date", type=str, default=None, help="指定日期 YYYYMMDD，默认今日")
    parser.add_argument("--backfill", type=int, default=0, help="回填最近N个交易日")
    parser.add_argument("--sleep", type=float, default=1.0)
    parser.add_argument("--socket-timeout", type=float, default=20.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.socket_timeout > 0:
        socket.setdefaulttimeout(args.socket_timeout)

    conn = connect(args.db)
    ensure_schema(conn)

    if args.backfill > 0:
        dates = get_recent_trading_dates(args.backfill)
        print(f"回填模式：{len(dates)} 个交易日")
    else:
        from datetime import date as _date
        d = args.date if args.date else _date.today().strftime("%Y%m%d")
        dates = [compact_date(d)]

    for d in dates:
        date_norm = normalize_date(d)
        # 跳过已采集
        existing = conn.execute(
            "SELECT COUNT(*) n FROM zt_pool WHERE date=?", (date_norm,)
        ).fetchone()["n"]
        if existing > 0:
            print(f"[{date_norm}] 已有 {existing} 条，跳过")
            continue

        print(f"[{date_norm}] 采集涨停池...", end=" ", flush=True)
        pool_rows = fetch_zt_pool(d)
        print(f"{len(pool_rows)} 条", end=" | ", flush=True)
        if pool_rows:
            upsert_zt_pool(conn, pool_rows)
            conn.commit()

        print("前日表现...", end=" ", flush=True)
        prev_rows = fetch_zt_previous(d)
        print(f"{len(prev_rows)} 条")
        if prev_rows:
            upsert_zt_previous(conn, prev_rows)
            conn.commit()

        time.sleep(args.sleep)

    total_zt = conn.execute("SELECT COUNT(DISTINCT date) n FROM zt_pool").fetchone()["n"]
    total_prev = conn.execute("SELECT COUNT(DISTINCT date) n FROM zt_previous").fetchone()["n"]
    print(f"\nDone. zt_pool={total_zt}天, zt_previous={total_prev}天")


if __name__ == "__main__":
    main()
