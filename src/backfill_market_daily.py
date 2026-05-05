"""
backfill_market_daily.py
回填 market_daily 表中历史涨跌停数（东财接口，收盘封板口径）。

Usage:
    python src/backfill_market_daily.py --db data/quant.db [--start 2025-01-01] [--sleep 1.5]
"""

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from quant_db import connect


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill market_daily zt/dt counts from EastMoney")
    parser.add_argument("--db", type=Path, default=PROJECT_ROOT / "data" / "quant.db")
    parser.add_argument("--start", default="2025-01-01", help="Start date YYYY-MM-DD")
    parser.add_argument("--sleep", type=float, default=1.5, help="Sleep seconds between requests")
    parser.add_argument("--force", action="store_true", help="Overwrite existing records")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    try:
        import akshare as ak
    except ImportError:
        print("akshare not installed")
        sys.exit(1)

    conn = connect(args.db)

    # 取所有需要回填的交易日
    dates = [
        r["date"]
        for r in conn.execute(
            "SELECT DISTINCT date FROM daily_bars WHERE date >= ? ORDER BY date",
            (args.start,),
        )
    ]
    print(f"Trading days to process: {len(dates)} ({dates[0]} ~ {dates[-1]})")

    # 已有数据
    existing = set(
        r["date"]
        for r in conn.execute(
            "SELECT date FROM market_daily WHERE zt_count IS NOT NULL AND date >= ?",
            (args.start,),
        )
    )
    print(f"Already have: {len(existing)} days")

    to_process = dates if args.force else [d for d in dates if d not in existing]
    print(f"To fetch: {len(to_process)} days")

    ok = 0
    fail = 0
    for i, date_str in enumerate(to_process):
        date_api = date_str.replace("-", "")
        zt_count = None
        dt_count = None

        try:
            df_zt = ak.stock_zt_pool_em(date=date_api)
            zt_count = len(df_zt) if df_zt is not None and not df_zt.empty else 0
        except Exception as exc:
            print(f"  [{i+1}/{len(to_process)}] {date_str} zt FAIL: {exc}")
            fail += 1

        time.sleep(args.sleep * 0.5)

        try:
            df_dt = ak.stock_zt_pool_dtgc_em(date=date_api)
            dt_count = len(df_dt) if df_dt is not None and not df_dt.empty else 0
        except Exception as exc:
            msg = str(exc)
            if "30 个交易日" in msg or "30个交易日" in msg:
                pass  # expected limitation, skip silently
            else:
                print(f"  [{i+1}/{len(to_process)}] {date_str} dt FAIL: {exc}")
            fail += 1

        with conn:
            conn.execute(
                """
                INSERT INTO market_daily(date, zt_count, dt_count)
                VALUES(?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    zt_count = excluded.zt_count,
                    dt_count = excluded.dt_count
                """,
                (date_str, zt_count, dt_count),
            )

        ok += 1
        print(f"  [{i+1}/{len(to_process)}] {date_str}  zt={zt_count}  dt={dt_count}")
        time.sleep(args.sleep)

    print(f"\nDone. ok={ok} fail={fail}")


if __name__ == "__main__":
    main()
