#!/usr/bin/env python3
"""Print popularity backfill coverage and recent source status."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from quant_core import DEFAULT_DB_PATH, normalize_date  # noqa: E402
from quant_db import connect  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor popularity backfill coverage")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--start-date", default="2025-06-27")
    parser.add_argument("--end-date", default="2026-06-26")
    parser.add_argument("--source", default="ths_pywencai_hot_rank")
    parser.add_argument("--min-rows", type=int, default=80)
    parser.add_argument("--show-missing", type=int, default=20)
    return parser.parse_args()


def scalar(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0] or 0)


def main() -> int:
    args = parse_args()
    start_date = normalize_date(args.start_date)
    end_date = normalize_date(args.end_date)
    conn = connect(args.db)

    total_dates = scalar(
        conn,
        "SELECT COUNT(DISTINCT date) FROM daily_bars WHERE date BETWEEN ? AND ?",
        (start_date, end_date),
    )
    complete_dates = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM (
            SELECT date
            FROM popularity_rankings
            WHERE source = ? AND date BETWEEN ? AND ?
            GROUP BY date
            HAVING COUNT(*) >= ?
        )
        """,
        (args.source, start_date, end_date, args.min_rows),
    )
    coverage = complete_dates / total_dates * 100 if total_dates else 0
    print(f"source={args.source}")
    print(f"range={start_date}..{end_date}")
    print(f"coverage={complete_dates}/{total_dates} ({coverage:.2f}%)")

    print("\nsource_summary:")
    for row in conn.execute(
        """
        SELECT source, COUNT(*) rows, COUNT(DISTINCT date) dates, MIN(date) min_date, MAX(date) max_date
        FROM popularity_rankings
        GROUP BY source
        ORDER BY source
        """
    ):
        print(f"- {row['source']}: rows={row['rows']} dates={row['dates']} range={row['min_date']}..{row['max_date']}")

    missing_sql = """
    WITH trading AS (
      SELECT DISTINCT date FROM daily_bars WHERE date BETWEEN ? AND ?
    ),
    complete AS (
      SELECT date
      FROM popularity_rankings
      WHERE source = ?
      GROUP BY date
      HAVING COUNT(*) >= ?
    )
    SELECT trading.date
    FROM trading
    LEFT JOIN complete USING(date)
    WHERE complete.date IS NULL
    ORDER BY trading.date DESC
    LIMIT ?
    """
    missing = [row["date"] for row in conn.execute(missing_sql, (start_date, end_date, args.source, args.min_rows, args.show_missing))]
    print(f"\nmissing_latest_{len(missing)}:")
    for date_text in missing:
        print(f"- {date_text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
