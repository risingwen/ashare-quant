#!/usr/bin/env python3
"""Write a daily popularity backfill progress report."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from quant_core import DEFAULT_DB_PATH  # noqa: E402
from quant_db import connect  # noqa: E402


SOURCE_EASTMONEY_ALL = "eastmoney_hot_rank_detail_em_all"
SOURCE_THS = "ths_pywencai_hot_rank"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report popularity backfill progress")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--source", default=SOURCE_EASTMONEY_ALL)
    parser.add_argument("--start-date", default="2025-06-27")
    parser.add_argument("--end-date", default="2026-06-26")
    parser.add_argument("--output", type=Path, help="Write latest report to this file")
    return parser.parse_args()


def scalar(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> int | float | str | None:
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


def source_stats(conn: sqlite3.Connection, source: str) -> dict[str, object]:
    row = conn.execute(
        """
        SELECT COUNT(*) AS rows, COUNT(DISTINCT date) AS dates, COUNT(DISTINCT code) AS codes,
               MIN(rank) AS min_rank, MAX(rank) AS max_rank, MIN(date) AS min_date, MAX(date) AS max_date
        FROM popularity_rankings
        WHERE source = ?
        """,
        (source,),
    ).fetchone()
    return dict(row) if row else {}


def progress_stats(conn: sqlite3.Connection, source: str) -> dict[str, dict[str, object]]:
    stats = {}
    for row in conn.execute(
        """
        SELECT status, COUNT(*) AS codes, COALESCE(SUM(rows), 0) AS rows, MAX(updated_at) AS latest_update
        FROM popularity_backfill_progress
        WHERE source = ?
        GROUP BY status
        ORDER BY status
        """,
        (source,),
    ):
        stats[str(row["status"])] = dict(row)
    return stats


def render_report(conn: sqlite3.Connection, source: str, start_date: str, end_date: str) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_stocks = int(scalar(conn, "SELECT COUNT(*) FROM stocks") or 0)
    eastmoney = source_stats(conn, source)
    ths = source_stats(conn, SOURCE_THS)
    progress = progress_stats(conn, source)
    ok_codes = int((progress.get("ok") or {}).get("codes") or 0)
    running_codes = int((progress.get("running") or {}).get("codes") or 0)
    failed_codes = int((progress.get("failed") or {}).get("codes") or 0)
    remaining = max(total_stocks - ok_codes, 0)
    completed_24h = int(
        scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM popularity_backfill_progress
            WHERE source = ?
              AND status = 'ok'
              AND datetime(updated_at) >= datetime('now', 'localtime', '-24 hours')
            """,
            (source,),
        )
        or 0
    )
    eta_days = remaining / completed_24h if completed_24h else None
    latest_update = (progress.get("ok") or {}).get("latest_update") or "-"
    rows = int(eastmoney.get("rows") or 0)
    dates = int(eastmoney.get("dates") or 0)
    codes = int(eastmoney.get("codes") or 0)
    ths_dates = int(ths.get("dates") or 0)
    ths_rows = int(ths.get("rows") or 0)

    error_rows = conn.execute(
        """
        SELECT code, error, updated_at
        FROM popularity_backfill_progress
        WHERE source = ? AND status = 'failed'
        ORDER BY updated_at DESC
        LIMIT 5
        """,
        (source,),
    ).fetchall()
    error_lines = [
        f"- {row['code']} @ {row['updated_at']}: {row['error'] or '-'}"
        for row in error_rows
    ] or ["- 无"]

    eta_text = f"{eta_days:.1f} 天" if eta_days is not None else "暂无估算"
    return "\n".join(
        [
            f"# 人气榜回补日报",
            "",
            f"- 生成时间：{generated_at}",
            f"- 东财全量源：`{source}`",
            f"- 扫描进度：{ok_codes} / {total_stocks} 只，剩余 {remaining} 只",
            f"- 近 24 小时完成：{completed_24h} 只，按此速度预计还需 {eta_text}",
            f"- 入库规模：{rows} 行，{dates} 个交易日，{codes} 只有排名记录",
            f"- 日期范围：{eastmoney.get('min_date') or '-'} .. {eastmoney.get('max_date') or '-'}",
            f"- 排名范围：{eastmoney.get('min_rank') or '-'} .. {eastmoney.get('max_rank') or '-'}",
            f"- 状态分布：ok={ok_codes}，running={running_codes}，failed={failed_codes}",
            f"- 最近完成更新时间：{latest_update}",
            f"- 同花顺 Top100：{ths_rows} 行，{ths_dates} 个交易日",
            "",
            "## 最近失败",
            *error_lines,
            "",
            f"监控范围：{start_date} .. {end_date}",
        ]
    )


def main() -> int:
    args = parse_args()
    conn = connect(args.db)
    report = render_report(conn, args.source, args.start_date, args.end_date)
    print(report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
