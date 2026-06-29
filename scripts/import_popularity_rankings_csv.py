#!/usr/bin/env python3
"""Import popularity_rankings CSV rows into SQLite."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from quant_core import DEFAULT_DB_PATH, normalize_date, to_float  # noqa: E402
from quant_db import connect  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import popularity rankings CSV")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--mark-date-progress", action="store_true")
    parser.add_argument("--stock-progress-csv", type=Path, help="Import per-stock Eastmoney progress CSV")
    parser.add_argument("--rank-limit", type=int, default=100)
    parser.add_argument("csv_files", nargs="+", type=Path)
    return parser.parse_args()


def normalize_code(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    if "." in text:
        text = text.split(".", maxsplit=1)[0]
    if text.startswith(("SH", "SZ", "BJ")) and len(text) >= 8:
        text = text[2:8]
    if text.endswith((".SH", ".SZ", ".BJ")):
        text = text[:6]
    if text.isdigit() and len(text) <= 6:
        return text.zfill(6)
    return None


def read_rows(path: Path) -> list[tuple[str, str, int, str, str, float | None, str]]:
    rows = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            source = str(row.get("source") or "").strip()
            date_text = normalize_date(str(row.get("date") or "").strip())
            rank = to_float(row.get("rank"))
            code = normalize_code(row.get("code"))
            name = str(row.get("name") or "").strip()
            if not source or not date_text or rank is None or not code or not name:
                continue
            rows.append(
                (
                    source,
                    date_text,
                    int(rank),
                    code,
                    name,
                    to_float(row.get("score")),
                    str(row.get("raw_json") or ""),
                )
            )
    return rows


def read_stock_progress(path: Path) -> list[tuple[str, str, str, str, int, str, int, str | None]]:
    rows = []
    if not path.exists():
        return rows
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            source = str(row.get("source") or "").strip()
            code = normalize_code(row.get("code"))
            start_date = normalize_date(str(row.get("start_date") or "").strip())
            end_date = normalize_date(str(row.get("end_date") or "").strip())
            rank_limit = to_float(row.get("rank_limit"))
            status = str(row.get("status") or "").strip()
            row_count = to_float(row.get("rows")) or 0
            error = str(row.get("error") or "").strip() or None
            if not source or not code or not start_date or not end_date or rank_limit is None or not status:
                continue
            rows.append((source, code, start_date, end_date, int(rank_limit), status, int(row_count), error))
    return rows


def main() -> int:
    args = parse_args()
    conn = connect(args.db)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS popularity_backfill_progress (
            source TEXT NOT NULL,
            code TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            rank_limit INTEGER NOT NULL,
            status TEXT NOT NULL,
            rows INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (source, code, start_date, end_date, rank_limit)
        )
        """
    )
    total = 0
    insert_sql = """
    INSERT OR REPLACE INTO popularity_rankings(source, date, rank, code, name, score, raw_json)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """
    for path in args.csv_files:
        rows = read_rows(path)
        with conn:
            conn.executemany(insert_sql, rows)
            if args.mark_date_progress:
                progress: dict[tuple[str, str], int] = {}
                for source, date_text, *_ in rows:
                    key = (source, date_text)
                    progress[key] = progress.get(key, 0) + 1
                conn.executemany(
                    """
                    INSERT INTO popularity_date_backfill_progress(
                        source, date, rank_limit, status, rows, error, updated_at
                    )
                    VALUES (?, ?, ?, 'ok', ?, NULL, datetime('now', 'localtime'))
                    ON CONFLICT(source, date, rank_limit)
                    DO UPDATE SET
                        status = excluded.status,
                        rows = excluded.rows,
                        error = excluded.error,
                        updated_at = excluded.updated_at
                    """,
                    [
                        (source, date_text, args.rank_limit, count)
                        for (source, date_text), count in progress.items()
                        if count >= 1
                    ],
                )
        total += len(rows)
        print(f"{path}: imported={len(rows)}")
    if args.stock_progress_csv:
        progress_rows = read_stock_progress(args.stock_progress_csv)
        with conn:
            conn.executemany(
                """
                INSERT INTO popularity_backfill_progress(
                    source, code, start_date, end_date, rank_limit, status, rows, error, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
                ON CONFLICT(source, code, start_date, end_date, rank_limit)
                DO UPDATE SET
                    status = excluded.status,
                    rows = excluded.rows,
                    error = excluded.error,
                    updated_at = excluded.updated_at
                """,
                progress_rows,
            )
        print(f"{args.stock_progress_csv}: stock_progress_imported={len(progress_rows)}")
    print(f"done imported={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
