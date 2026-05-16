#!/usr/bin/env python3
"""每日数据健康检查 + 自动补全。

检查内容：
  - daily_bars / zt_pool / lhb_records / market_daily 最新日期
  - 与最近交易日比对，找出缺失日期
  - 自动补跑缺失数据（zt_pool 用 --backfill，lhb 用 update_sqlite_data --skip-daily）
  - 输出最终健康报告

用法：
  python src/health_check.py --db data/quant.db
  python src/health_check.py --db data/quant.db --dry-run   # 只检查不修复
"""
from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# ── 项目内部模块 ────────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from quant_core import DEFAULT_DB_PATH, normalize_date
from quant_db import connect

PYTHON = sys.executable


# ── 工具函数 ────────────────────────────────────────────────────────────────────

def get_trading_days(ak, start: str, end: str) -> list[str]:
    """返回 [start, end] 区间内的交易日列表（YYYY-MM-DD）。"""
    try:
        df = ak.tool_trade_date_hist_sina()
        all_dates = sorted(df.iloc[:, 0].dropna().astype(str).tolist())
        return [d for d in all_dates if start <= d <= end]
    except Exception as exc:
        print(f"  [WARN] 获取交易日历失败: {exc}，降级用工作日估算")
        # 降级：返回区间内所有非周末的日期
        result = []
        cur = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")
        while cur <= end_dt:
            if cur.weekday() < 5:
                result.append(cur.strftime("%Y-%m-%d"))
            cur += timedelta(days=1)
        return result


def latest_date(conn, table: str) -> str | None:
    try:
        row = conn.execute(f"SELECT MAX(date) FROM {table}").fetchone()
        return row[0] if row and row[0] else None
    except Exception:
        return None


def run(cmd: list[str], label: str) -> bool:
    """运行子命令，实时打印输出，返回是否成功。"""
    print(f"  [RUN] {label}")
    print(f"        {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=Path(__file__).parent.parent)
    if result.returncode == 0:
        print(f"  [OK]  {label}")
    else:
        print(f"  [FAIL] {label} (exit {result.returncode})")
    return result.returncode == 0


# ── 各表检查 & 修复 ─────────────────────────────────────────────────────────────

def check_and_fix_zt_pool(conn, missing_days: list[str], db_path: str, dry_run: bool) -> bool:
    """zt_pool 用 --backfill N 补全。"""
    if not missing_days:
        return True
    print(f"  zt_pool 缺失 {len(missing_days)} 天: {missing_days}")
    if dry_run:
        return True
    # 多补 2 天保险（交易日计数）
    backfill_n = len(missing_days) + 2
    return run(
        [PYTHON, "-u", "src/update_zt_pool.py",
         "--db", db_path,
         "--backfill", str(backfill_n),
         "--socket-timeout", "20"],
        f"补全 zt_pool（最近 {backfill_n} 个交易日）",
    )


def check_and_fix_lhb(conn, missing_days: list[str], db_path: str, dry_run: bool) -> bool:
    """lhb_records 按日逐个补全（update_sqlite_data --skip-daily --end-date DATE）。"""
    if not missing_days:
        return True
    print(f"  lhb_records 缺失 {len(missing_days)} 天: {missing_days}")
    if dry_run:
        return True
    ok = True
    for day in missing_days:
        compact = day.replace("-", "")
        success = run(
            [PYTHON, "-u", "src/update_sqlite_data.py",
             "--db", db_path,
             "--skip-daily", "--skip-popularity", "--skip-limit-pool",
             "--end-date", compact,
             "--socket-timeout", "20"],
            f"补全 lhb_records {day}",
        )
        ok = ok and success
        if success:
            time.sleep(1)  # 避免连续请求过快
    return ok


def check_and_fix_daily_bars(conn, missing_days: list[str], db_path: str, dry_run: bool) -> bool:
    """daily_bars 缺失时用 update_sqlite_data 全量重跑（仅 daily）。"""
    if not missing_days:
        return True
    print(f"  daily_bars 缺失 {len(missing_days)} 天: {missing_days}")
    if dry_run:
        return True
    # 取缺失范围的起止日期
    start = missing_days[0].replace("-", "")
    end = missing_days[-1].replace("-", "")
    return run(
        [PYTHON, "-u", "src/update_sqlite_data.py",
         "--db", db_path,
         "--skip-popularity", "--skip-lhb", "--skip-limit-pool",
         "--daily-source", "mootdx",
         "--start-date", start,
         "--end-date", end,
         "--socket-timeout", "20",
         "--workers", "8",
         "--stock-batch-size", "500"],
        f"补全 daily_bars {start}→{end}",
    )


def check_and_fix_market_daily(conn, missing_days: list[str], db_path: str, dry_run: bool) -> bool:
    """market_daily 按日补全（update_sqlite_data --skip-daily --skip-lhb）。"""
    if not missing_days:
        return True
    print(f"  market_daily 缺失 {len(missing_days)} 天: {missing_days}")
    if dry_run:
        return True
    ok = True
    for day in missing_days:
        compact = day.replace("-", "")
        success = run(
            [PYTHON, "-u", "src/update_sqlite_data.py",
             "--db", db_path,
             "--skip-daily", "--skip-popularity", "--skip-lhb",
             "--end-date", compact,
             "--socket-timeout", "20"],
            f"补全 market_daily {day}",
        )
        ok = ok and success
    return ok


# ── 主函数 ──────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="每日数据健康检查 + 自动补全")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--lookback-days", type=int, default=10,
                        help="向前检查多少个自然日（默认10）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印检查结果，不执行修复")
    parser.add_argument("--socket-timeout", type=float, default=15.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    socket.setdefaulttimeout(args.socket_timeout)

    try:
        import akshare as ak
    except ImportError:
        print("[ERROR] akshare 未安装")
        sys.exit(1)

    conn = connect(args.db)
    db_path = str(args.db)

    today = datetime.now().date()
    lookback_start = (today - timedelta(days=args.lookback_days)).strftime("%Y-%m-%d")
    today_str = today.strftime("%Y-%m-%d")

    print("=" * 60)
    print(f"数据健康检查  {today_str}  lookback={args.lookback_days}天")
    print("=" * 60)

    # ── 获取交易日历 ──────────────────────────────────────────────────────────
    trading_days = get_trading_days(ak, lookback_start, today_str)
    # 只检查到昨天（今天可能还未收盘）
    yesterday = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    expected_days = [d for d in trading_days if d <= yesterday]

    if not expected_days:
        print(f"  近 {args.lookback_days} 日内无交易日，无需检查")
        return

    print(f"  近期交易日（截至昨日）: {expected_days}")

    # ── 逐表检查 ──────────────────────────────────────────────────────────────
    tables = {
        "daily_bars": latest_date(conn, "daily_bars"),
        "zt_pool": latest_date(conn, "zt_pool"),
        "lhb_records": latest_date(conn, "lhb_records"),
        "market_daily": latest_date(conn, "market_daily"),
    }

    print("\n当前各表最新日期：")
    for tbl, dt in tables.items():
        status = "✓" if dt and dt >= expected_days[-1] else "✗"
        print(f"  {status} {tbl:20s} {dt or 'N/A'}")

    def missing(table: str) -> list[str]:
        """找出 expected_days 中该表缺失的日期。"""
        latest = tables[table]
        if latest is None:
            return expected_days
        return [d for d in expected_days if d > latest]

    missing_daily = missing("daily_bars")
    missing_zt = missing("zt_pool")
    missing_lhb = missing("lhb_records")
    missing_market = missing("market_daily")

    all_ok = not any([missing_daily, missing_zt, missing_lhb, missing_market])

    if all_ok:
        print("\n[HEALTHY] 所有表数据均已更新到最新交易日，无需补全。")
        return

    if args.dry_run:
        print("\n[DRY-RUN] 以下数据需要补全（--dry-run 模式，不执行）：")
        if missing_daily:  print(f"  daily_bars  缺失: {missing_daily}")
        if missing_zt:     print(f"  zt_pool     缺失: {missing_zt}")
        if missing_lhb:    print(f"  lhb_records 缺失: {missing_lhb}")
        if missing_market: print(f"  market_daily缺失: {missing_market}")
        return

    print("\n[FIXING] 开始自动补全...\n")

    # 按依赖顺序修复：daily_bars → market_daily → zt_pool → lhb
    check_and_fix_daily_bars(conn, missing_daily, db_path, dry_run=False)
    check_and_fix_market_daily(conn, missing_market, db_path, dry_run=False)
    check_and_fix_zt_pool(conn, missing_zt, db_path, dry_run=False)
    check_and_fix_lhb(conn, missing_lhb, db_path, dry_run=False)

    # ── 补全后再次验证 ────────────────────────────────────────────────────────
    conn2 = connect(args.db)
    print("\n补全后各表最新日期：")
    final_ok = True
    for tbl in tables:
        dt = latest_date(conn2, tbl)
        status = "✓" if dt and dt >= expected_days[-1] else "✗"
        if status == "✗":
            final_ok = False
        print(f"  {status} {tbl:20s} {dt or 'N/A'}")

    if final_ok:
        print("\n[HEALTHY] 补全完成，所有表均已是最新。")
    else:
        print("\n[WARN] 部分表仍有缺失，请手动检查。")
        sys.exit(1)


if __name__ == "__main__":
    main()
