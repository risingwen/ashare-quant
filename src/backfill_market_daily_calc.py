"""
backfill_market_daily_calc.py
用 daily_bars 的 pct_chg 自算历史涨跌停数，回填 market_daily 表。

涨跌幅限制规则：
  - 主板 (Mainboard)：±10%（ST ±5%）
  - 创业板 (ChiNext) / 科创板 (STAR)：±20%（ST ±5%）
  - 北交所 (BSE)：±30%（ST ±5%）

判断阈值（留 0.05% 浮动）：
  - 主板涨停 pct_chg >= 9.8，跌停 <= -9.8（ST: ±4.8）
  - 创业板/科创板涨停 >= 19.8，跌停 <= -19.8（ST: ±4.8）
  - 北交所涨停 >= 29.8，跌停 <= -29.8（ST: ±4.8）

Usage:
    python src/backfill_market_daily_calc.py [--db data/quant.db] [--start 2025-01-01] [--force]
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from quant_db import connect


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--db", type=Path, default=PROJECT_ROOT / "data" / "quant.db")
    p.add_argument("--start", default="2025-01-01")
    p.add_argument("--force", action="store_true", help="Overwrite existing calc records")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    conn = connect(args.db)

    # 构建 code -> (market, is_st) 映射
    stock_info = {
        r["code"]: (r["market"], bool(r["is_st"]))
        for r in conn.execute("SELECT code, market, is_st FROM stocks")
    }

    def limit_thresholds(code: str):
        """Returns (zt_threshold, dt_threshold) for a given code."""
        market, is_st = stock_info.get(code, ("Mainboard", False))
        if is_st:
            return 4.8, -4.8
        if market in ("ChiNext", "STAR"):
            return 19.8, -19.8
        if market == "BSE":
            return 29.8, -29.8
        return 9.8, -9.8  # Mainboard / Other

    # 取所有需要处理的日期
    dates = [
        r["date"]
        for r in conn.execute(
            "SELECT DISTINCT date FROM daily_bars WHERE date >= ? ORDER BY date",
            (args.start,),
        )
    ]
    print(f"Trading days: {len(dates)}  ({dates[0]} ~ {dates[-1]})")

    # 已有数据（东财接口已填好的，不覆盖）
    existing = set()
    if not args.force:
        existing = {
            r["date"]
            for r in conn.execute(
                "SELECT date FROM market_daily WHERE zt_count IS NOT NULL AND date >= ?",
                (args.start,),
            )
        }
    to_process = [d for d in dates if d not in existing]
    print(f"Already have: {len(existing)}  To calc: {len(to_process)}")

    for i, date_str in enumerate(to_process):
        rows = conn.execute(
            "SELECT code, pct_chg FROM daily_bars WHERE date = ? AND pct_chg IS NOT NULL",
            (date_str,),
        ).fetchall()

        zt = 0
        dt = 0
        for r in rows:
            code = r["code"]
            pct = float(r["pct_chg"])
            zt_thr, dt_thr = limit_thresholds(code)
            if pct >= zt_thr:
                zt += 1
            elif pct <= dt_thr:
                dt += 1

        with conn:
            conn.execute(
                """
                INSERT INTO market_daily(date, zt_count, dt_count)
                VALUES(?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    zt_count = excluded.zt_count,
                    dt_count = excluded.dt_count
                """,
                (date_str, zt, dt),
            )

        if (i + 1) % 20 == 0 or i == len(to_process) - 1:
            print(f"  [{i+1}/{len(to_process)}] {date_str}  zt={zt}  dt={dt}")

    print("Done.")


if __name__ == "__main__":
    main()
