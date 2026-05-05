#!/usr/bin/env python3
"""
ETF 数据采集：行情快照 + 技术信号 + 持仓明细。

用法：
  python update_etf.py                       # 采集今日快照
  python update_etf.py --date 20260430       # 指定日期
  python update_etf.py --skip-holdings       # 不采集持仓（省时间）
  python update_etf.py --min-amount 5000     # 最小成交额过滤（万元），默认1000万
"""

from __future__ import annotations

import argparse
import socket
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import akshare as ak
import pandas as pd

from quant_core import DEFAULT_DB_PATH, normalize_date, to_float
from quant_db import connect


# ── helpers ─────────────────────────────────────────────────────────────────

def call_with_retry(fn, retries: int = 3, sleep: float = 0.5):
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:
            if attempt == retries - 1:
                raise
            print(f"  retry {attempt+1}/{retries}: {exc}")
            time.sleep(sleep * (attempt + 1))


def strip_market(code: str) -> str:
    """sz159300 → 159300"""
    return code[-6:] if len(code) > 6 else code


def calc_ma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n, min_periods=n).mean()


# ── ETF 列表 & 行情 ──────────────────────────────────────────────────────────

def fetch_etf_spot() -> pd.DataFrame:
    """
    返回所有 ETF 实时行情。
    列: code(6位), name, close, pct_chg, amount(元)
    """
    df = call_with_retry(lambda: ak.fund_etf_category_sina(symbol="ETF基金"))
    df = df.rename(columns={
        "代码": "raw_code", "名称": "name",
        "最新价": "close", "涨跌幅": "pct_chg", "成交额": "amount",
    })
    df["code"] = df["raw_code"].apply(strip_market)
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["pct_chg"] = pd.to_numeric(df["pct_chg"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    return df[["code", "name", "close", "pct_chg", "amount"]].dropna(subset=["close"])


# ── 历史K线 & 技术信号 ────────────────────────────────────────────────────────

def fetch_etf_hist(code: str, days: int = 300) -> pd.DataFrame | None:
    """拉近 days 日复权K线，返回含MA/新高信号的 DataFrame。"""
    start = (datetime.now() - timedelta(days=days + 100)).strftime("%Y%m%d")
    end = datetime.now().strftime("%Y%m%d")
    try:
        df = call_with_retry(
            lambda: ak.fund_etf_hist_em(
                symbol=code, period="daily",
                start_date=start, end_date=end, adjust="qfq"
            ),
            retries=2, sleep=0.3
        )
    except Exception as exc:
        print(f"  {code} hist failed: {exc}")
        return None
    if df is None or df.empty:
        return None

    df = df.rename(columns={"日期": "date", "收盘": "close", "涨跌幅": "pct_chg", "成交额": "amount"})
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["close"]).reset_index(drop=True)
    if len(df) < 10:
        return None

    df["ma5"] = calc_ma(df["close"], 5)
    df["ma10"] = calc_ma(df["close"], 10)
    df["ma20"] = calc_ma(df["close"], 20)
    df["ma60"] = calc_ma(df["close"], 60)
    df["hist_high"] = df["close"].cummax()
    df["is_new_high"] = (df["close"] >= df["hist_high"]).astype(int)
    df["ma20_up"] = (df["ma20"] > df["ma20"].shift(1)).astype(int)
    df["ma60_up"] = (df["ma60"] > df["ma60"].shift(1)).astype(int)
    df["above_ma20"] = (df["close"] > df["ma20"]).astype(int)
    df["above_ma60"] = (df["close"] > df["ma60"]).astype(int)

    # 只保留最近 days 天
    df = df.tail(days).reset_index(drop=True)
    return df


# ── 持仓 ─────────────────────────────────────────────────────────────────────

def fetch_etf_holdings(code: str, timeout: int = 12) -> tuple[str, list[dict]] | None:
    """
    获取最新季度持仓。返回 (quarter_str, rows_list) 或 None。
    每次 HTTP 调用限制在 timeout 秒内，避免挂死。
    """
    current_year = datetime.now().year
    years_to_try = [str(current_year), str(current_year - 1)]
    for year in years_to_try:
        try:
            with ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(ak.fund_portfolio_hold_em, symbol=code, date=year)
                try:
                    df = future.result(timeout=timeout)
                except FuturesTimeoutError:
                    future.cancel()
                    continue
            if df is None or df.empty:
                continue
            quarters = df["季度"].unique() if "季度" in df.columns else []
            if not len(quarters):
                continue
            latest_q = quarters[-1]
            df_q = df[df["季度"] == latest_q]
            rows = []
            for _, row in df_q.iterrows():
                rows.append({
                    "stock_code": str(row.get("股票代码", "")).zfill(6),
                    "stock_name": str(row.get("股票名称", "")),
                    "weight": to_float(row.get("占净值比例")),
                    "shares": to_float(row.get("持股数")),
                    "market_value": to_float(row.get("持仓市值")),
                })
            return latest_q, rows
        except Exception:
            continue
    return None


# ── DB 写入 ──────────────────────────────────────────────────────────────────

def upsert_etf_daily(conn, code: str, name: str, hist_df: pd.DataFrame) -> None:
    sql = """
    INSERT OR REPLACE INTO etf_daily(
        date, code, name, close, pct_chg, amount,
        ma5, ma10, ma20, ma60, hist_high,
        is_new_high, ma20_up, ma60_up, above_ma20, above_ma60
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    rows = []
    for _, r in hist_df.iterrows():
        rows.append((
            r["date"], code, name,
            to_float(r.get("close")),
            to_float(r.get("pct_chg")),
            to_float(r.get("amount")),
            to_float(r.get("ma5")),
            to_float(r.get("ma10")),
            to_float(r.get("ma20")),
            to_float(r.get("ma60")),
            to_float(r.get("hist_high")),
            int(r.get("is_new_high", 0) or 0),
            int(r.get("ma20_up", 0) or 0),
            int(r.get("ma60_up", 0) or 0),
            int(r.get("above_ma20", 0) or 0),
            int(r.get("above_ma60", 0) or 0),
        ))
    conn.executemany(sql, rows)
    # autocommit mode — no explicit commit needed


def upsert_etf_holdings(conn, code: str, quarter: str, rows: list[dict]) -> None:
    sql = """
    INSERT OR REPLACE INTO etf_holdings(
        code, quarter, stock_code, stock_name, weight, shares, market_value
    ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """
    conn.executemany(sql, [
            (code, quarter, r["stock_code"], r["stock_name"],
             r["weight"], r["shares"], r["market_value"])
            for r in rows
        ])
    # autocommit mode — no explicit commit needed


# ── main ─────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ETF 数据采集")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--min-amount", type=float, default=5000,
                        help="最小成交额过滤（万元），默认5000（即5000万，采集时宽松留余量）")
    parser.add_argument("--hist-days", type=int, default=730,
                        help="历史K线天数，默认730（约2年）")
    parser.add_argument("--skip-holdings", action="store_true",
                        help="跳过持仓采集（节省时间）")
    parser.add_argument("--all-holdings", action="store_true",
                        help="对所有 ETF 采集持仓，不限 signal（全量模式）")
    parser.add_argument("--holdings-only", action="store_true",
                        help="只跑持仓采集，跳过行情K线步骤")
    parser.add_argument("--sleep", type=float, default=0.3)
    parser.add_argument("--max-etf", type=int, default=None,
                        help="调试用：限制处理ETF数量")
    parser.add_argument("--socket-timeout", type=float, default=25.0,
                        help="Default network socket timeout in seconds")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.socket_timeout > 0:
        socket.setdefaulttimeout(args.socket_timeout)
    # Use autocommit (isolation_level=None) from the start to avoid
    # the executescript-induced transaction state issues in quant_db.connect()
    import sqlite3 as _sqlite3
    args.db.parent.mkdir(parents=True, exist_ok=True)
    conn = _sqlite3.connect(str(args.db), isolation_level=None)
    conn.row_factory = _sqlite3.Row
    # Ensure ETF tables exist (idempotent DDL)
    conn.execute("""CREATE TABLE IF NOT EXISTS etf_daily (
        date TEXT NOT NULL, code TEXT NOT NULL, name TEXT NOT NULL,
        close REAL, pct_chg REAL, amount REAL,
        ma5 REAL, ma10 REAL, ma20 REAL, ma60 REAL, hist_high REAL,
        is_new_high INTEGER DEFAULT 0, ma20_up INTEGER DEFAULT 0,
        ma60_up INTEGER DEFAULT 0, above_ma20 INTEGER DEFAULT 0,
        above_ma60 INTEGER DEFAULT 0,
        PRIMARY KEY (date, code))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS etf_holdings (
        code TEXT NOT NULL, quarter TEXT NOT NULL,
        stock_code TEXT NOT NULL, stock_name TEXT NOT NULL,
        weight REAL, shares REAL, market_value REAL,
        PRIMARY KEY (code, quarter, stock_code))""")

    print("Step 1: 获取 ETF 列表...")
    if args.holdings_only and args.all_holdings:
        # 全量持仓模式：直接从 DB 取，不需要实时行情
        codes_in_db = [r["code"] for r in conn.execute("SELECT DISTINCT code FROM etf_daily").fetchall()]
        # 构造最小 spot_df 供后续逻辑复用
        import pandas as _pd
        spot_df = _pd.DataFrame({"code": codes_in_db, "name": [""] * len(codes_in_db), "amount": [9e9] * len(codes_in_db)})
        print(f"  DB模式：共 {len(spot_df)} 只ETF")
    else:
        spot_df = fetch_etf_spot()
        min_amount_yuan = args.min_amount * 10000
        spot_df = spot_df[spot_df["amount"] >= min_amount_yuan]
        print(f"  成交额 >= {args.min_amount:.0f}万 的ETF: {len(spot_df)} 只")

    if args.max_etf:
        spot_df = spot_df.head(args.max_etf)
        print(f"  (调试模式：只处理前 {args.max_etf} 只)")

    if not args.holdings_only:
        print(f"\nStep 2: 拉取历史K线 & 计算技术信号 (共{len(spot_df)}只)...")
        processed = 0
        new_high_count = 0
        ma_up_count = 0

        for idx, row in spot_df.iterrows():
            code = row["code"]
            name = row["name"]
            print(f"  [{processed+1}/{len(spot_df)}] {code} {name}", end="  ")

            hist = fetch_etf_hist(code, days=args.hist_days)
            if hist is None or hist.empty:
                print("skip (no hist)")
                processed += 1
                time.sleep(args.sleep)
                continue

            upsert_etf_daily(conn, code, name, hist)

            latest = hist.iloc[-1]
            nh = int(latest.get("is_new_high", 0) or 0)
            mu = int(latest.get("ma20_up", 0) or 0)
            new_high_count += nh
            ma_up_count += mu
            print(f"rows={len(hist)} | 新高={'✓' if nh else '-'} MA20向上={'✓' if mu else '-'}")

            processed += 1
            time.sleep(args.sleep)

        print(f"\n  技术信号汇总: 新高={new_high_count}只, MA20向上={ma_up_count}只")

    if not args.skip_holdings:
        print(f"\nStep 3: 采集持仓（已有记录的ETF跳过）...")
        if args.all_holdings:
            codes_to_fetch = [r["code"] for r in conn.execute(
                "SELECT DISTINCT code FROM etf_daily"
            ).fetchall()]
            print(f"  全量模式：共 {len(codes_to_fetch)} 只")
        else:
            codes_to_fetch = [r["code"] for r in conn.execute("""
                SELECT DISTINCT code FROM etf_daily
                WHERE date = (SELECT MAX(date) FROM etf_daily)
                  AND (is_new_high=1 OR ma20_up=1 OR above_ma60=1)
            """).fetchall()]
            print(f"  信号模式：需要采集持仓的ETF: {len(codes_to_fetch)} 只")

        # 过滤已有持仓的
        codes_to_fetch = [
            c for c in codes_to_fetch
            if conn.execute("SELECT COUNT(*) n FROM etf_holdings WHERE code=?", (c,)).fetchone()["n"] == 0
        ]
        print(f"  待采集（跳过已有）：{len(codes_to_fetch)} 只")

        import threading
        db_lock = threading.Lock()
        counter = {"done": 0, "total": len(codes_to_fetch)}

        def fetch_one(idx_code):
            idx, code = idx_code
            result = fetch_etf_holdings(code)
            label = f"[{idx+1}/{counter['total']}] {code}"
            if result:
                quarter, rows = result
                with db_lock:
                    upsert_etf_holdings(conn, code, quarter, rows)
                    counter["done"] += 1
                print(f"  {label} {quarter} {len(rows)}只")
            else:
                print(f"  {label} 无持仓数据")

        with ThreadPoolExecutor(max_workers=4) as pool:
            pool.map(fetch_one, enumerate(codes_to_fetch))

    # 汇总
    total_etf = conn.execute("SELECT COUNT(DISTINCT code) n FROM etf_daily").fetchone()["n"]
    total_holdings = conn.execute("SELECT COUNT(DISTINCT code) n FROM etf_holdings").fetchone()["n"]
    latest_date = conn.execute("SELECT MAX(date) d FROM etf_daily").fetchone()["d"]
    print(f"\nDone. DB: etf_daily={total_etf}只, 持仓={total_holdings}只, 最新日期={latest_date}")


if __name__ == "__main__":
    main()
