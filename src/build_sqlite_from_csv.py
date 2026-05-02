#!/usr/bin/env python3
"""Build the SQLite research database from legacy CSV files once.

CSV is treated as an import source only. Reports and future updates use SQLite.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from quant_core import DEFAULT_DB_PATH, DEFAULT_LEGACY_CSV_DIR, chunked, parse_meta_from_filename, read_legacy_csv
from quant_db import connect


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import legacy AkShare CSV files into SQLite")
    parser.add_argument("--csv-dir", type=Path, default=DEFAULT_LEGACY_CSV_DIR)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--reset", action="store_true", help="Delete existing database before import")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.reset and args.db.exists():
        args.db.unlink()

    conn = connect(args.db)
    files = sorted(args.csv_dir.glob("*_daily.csv"))
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    valid_files = 0
    invalid_files = 0
    rows_inserted = 0

    stock_sql = """
    INSERT INTO stocks(code, name, market, is_st, eligible, updated_at)
    VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(code) DO UPDATE SET
        name=excluded.name,
        market=excluded.market,
        is_st=excluded.is_st,
        eligible=excluded.eligible,
        updated_at=excluded.updated_at
    """
    bar_sql = """
    INSERT OR REPLACE INTO daily_bars(
        code, date, open, close, high, low, volume, amount, amplitude,
        pct_chg, change_amount, turnover, source
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'legacy_csv')
    """
    issue_sql = """
    INSERT INTO data_quality_issues(run_id, file, reason, created_at)
    VALUES (?, ?, ?, ?)
    """

    with conn:
        for index, path in enumerate(files, start=1):
            meta = parse_meta_from_filename(path)
            if meta is None:
                invalid_files += 1
                conn.execute(issue_sql, (run_id, path.name, "bad filename", created_at))
                continue

            rows, error = read_legacy_csv(path)
            if error:
                invalid_files += 1
                conn.execute(issue_sql, (run_id, path.name, error, created_at))
                continue

            valid_files += 1
            conn.execute(stock_sql, (meta.code, meta.name, meta.market, int(meta.is_st), int(meta.eligible), created_at))
            bar_rows = [
                (
                    meta.code,
                    row["date"],
                    row["open"],
                    row["close"],
                    row["high"],
                    row["low"],
                    row["volume"],
                    row["amount"],
                    row["amplitude"],
                    row["pct_chg"],
                    row["change_amount"],
                    row["turnover"],
                )
                for row in rows
            ]
            for chunk in chunked(bar_rows, 1000):
                conn.executemany(bar_sql, chunk)
            rows_inserted += len(bar_rows)

            if index % 500 == 0:
                print(f"Imported {index}/{len(files)} files, rows={rows_inserted}")

    print(f"Done. db={args.db}, files={len(files)}, valid={valid_files}, invalid={invalid_files}, rows={rows_inserted}")


if __name__ == "__main__":
    main()
