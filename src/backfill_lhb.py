#!/usr/bin/env python3
"""
Backfill 龙虎榜历史数据（lhb_records + lhb_seats）。

用法：
  python backfill_lhb.py --start-date 20250101 --end-date 20260430
  python backfill_lhb.py --start-date 20250101  # end-date 默认今天

支持断点续传：已入库的日期自动跳过。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import akshare as ak

from quant_core import DEFAULT_DB_PATH, normalize_date, to_float
from quant_db import connect


# ── helpers ────────────────────────────────────────────────────────────────

def trading_dates_between(start: str, end: str) -> list[str]:
    """Return YYYY-MM-DD list of all calendar days (API will return empty for non-trading days)."""
    s = datetime.strptime(start[:10], "%Y-%m-%d")
    e = datetime.strptime(end[:10], "%Y-%m-%d")
    out = []
    cur = s
    while cur <= e:
        if cur.weekday() < 5:   # skip weekends; holidays return empty from API naturally
            out.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return out


def call_with_retry(fn, retries: int = 3, sleep: float = 1.0):
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:
            if attempt == retries - 1:
                raise
            print(f"  retry {attempt+1}/{retries} after error: {exc}")
            time.sleep(sleep * (attempt + 1))


def row_value(d: dict, keys: list[str]):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def code_value(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    # zero-pad to 6 digits
    if s.isdigit() and len(s) < 6:
        s = s.zfill(6)
    return s


# ── core per-date logic ─────────────────────────────────────────────────────

def backfill_date(conn, date_str: str, sleep: float, retries: int) -> int:
    """Fetch and store lhb records + seats for one date. Returns records inserted."""
    compact = date_str.replace("-", "")

    # Skip if records already exist
    existing = conn.execute(
        "SELECT COUNT(*) AS n FROM lhb_records WHERE date = ?", (date_str,)
    ).fetchone()["n"]
    if existing > 0:
        print(f"[{date_str}] already {existing} records, skip")
        return 0

    # 1) Overview
    try:
        df = call_with_retry(
            lambda: ak.stock_lhb_detail_em(start_date=compact, end_date=compact),
            retries, sleep
        )
    except Exception as exc:
        print(f"[{date_str}] overview fetch failed: {exc}")
        return 0

    if df is None or df.empty:
        print(f"[{date_str}] no data (non-trading or holiday)")
        return 0

    rec_sql = """
    INSERT OR REPLACE INTO lhb_records(
        date, code, name, reason, close, pct_chg, lhb_net_buy, lhb_buy, lhb_sell,
        lhb_amount, market_amount, net_buy_ratio, amount_ratio, turnover, float_mv,
        after_1d, after_2d, after_5d, after_10d, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    seat_sql = """
    INSERT OR REPLACE INTO lhb_seats(
        date, code, direction, seat_name, buy_amount, buy_ratio, sell_amount, sell_ratio, net_amount, seat_type
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    rec_rows = []
    for _, row in df.iterrows():
        d = row.to_dict()
        code = code_value(row_value(d, ["代码"]))
        name = row_value(d, ["名称"])
        if not code or not name:
            continue
        rec_rows.append((
            date_str, code, str(name),
            str(row_value(d, ["上榜原因"]) or ""),
            to_float(row_value(d, ["收盘价"])),
            to_float(row_value(d, ["涨跌幅"])),
            to_float(row_value(d, ["龙虎榜净买额"])),
            to_float(row_value(d, ["龙虎榜买入额"])),
            to_float(row_value(d, ["龙虎榜卖出额"])),
            to_float(row_value(d, ["龙虎榜成交额"])),
            to_float(row_value(d, ["市场总成交额"])),
            to_float(row_value(d, ["净买额占总成交比"])),
            to_float(row_value(d, ["成交额占总成交比"])),
            to_float(row_value(d, ["换手率"])),
            to_float(row_value(d, ["流通市值"])),
            to_float(row_value(d, ["上榜后1日"])),
            to_float(row_value(d, ["上榜后2日"])),
            to_float(row_value(d, ["上榜后5日"])),
            to_float(row_value(d, ["上榜后10日"])),
            json.dumps(d, ensure_ascii=False, default=str),
        ))

    with conn:
        conn.executemany(rec_sql, rec_rows)
    print(f"[{date_str}] records={len(rec_rows)}", end="  seats: ", flush=True)

    # 2) Seat details per stock
    seat_rows: list = []
    for code in [r[1] for r in rec_rows]:
        time.sleep(sleep)
        for direction in ("买入", "卖出"):
            try:
                sdf = call_with_retry(
                    lambda c=code, flag=direction: ak.stock_lhb_stock_detail_em(
                        symbol=c, date=compact, flag=flag
                    ),
                    retries, sleep
                )
            except Exception:
                continue
            if sdf is None or sdf.empty:
                continue
            for _, srow in sdf.iterrows():
                sd = srow.to_dict()
                seat_name = sd.get("交易营业部名称", "")
                seat_rows.append((
                    date_str, code, direction, str(seat_name),
                    to_float(sd.get("买入金额")),
                    to_float(sd.get("买入金额-占总成交比例")),
                    to_float(sd.get("卖出金额")),
                    to_float(sd.get("卖出金额-占总成交比例")),
                    to_float(sd.get("净额")),
                    str(sd.get("类型", "")),
                ))

    if seat_rows:
        with conn:
            conn.executemany(seat_sql, seat_rows)
    print(f"{len(seat_rows)}")
    return len(rec_rows)


# ── main ────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill 龙虎榜历史数据")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--start-date", default="20250101")
    parser.add_argument("--end-date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--sleep", type=float, default=0.5, help="每次API调用间隔(秒)")
    parser.add_argument("--retries", type=int, default=3)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    conn = connect(args.db)

    dates = trading_dates_between(args.start_date, args.end_date)
    print(f"Backfill LHB: {args.start_date} ~ {args.end_date}, {len(dates)} trading days")

    total_records = 0
    for i, date_str in enumerate(dates):
        n = backfill_date(conn, date_str, args.sleep, args.retries)
        total_records += n
        if i % 10 == 9:
            recs = conn.execute("SELECT COUNT(*) n FROM lhb_records").fetchone()["n"]
            seats = conn.execute("SELECT COUNT(*) n FROM lhb_seats").fetchone()["n"]
            print(f"--- Progress {i+1}/{len(dates)}: db records={recs}, seats={seats} ---")
        time.sleep(args.sleep)

    recs = conn.execute("SELECT COUNT(*) n FROM lhb_records").fetchone()["n"]
    seats = conn.execute("SELECT COUNT(*) n FROM lhb_seats").fetchone()["n"]
    print(f"\nDone. Total new records inserted: {total_records}")
    print(f"DB totals: lhb_records={recs}, lhb_seats={seats}")


if __name__ == "__main__":
    main()
