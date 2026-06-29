#!/usr/bin/env python3
"""Backfill THS/iwencai historical popularity Top N into SQLite."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from quant_core import DEFAULT_DB_PATH, normalize_date  # noqa: E402
from quant_db import connect  # noqa: E402


SOURCE_THS_PYWENCAI = "ths_pywencai_hot_rank"


def parse_args() -> argparse.Namespace:
    default_start = (date.today() - timedelta(days=365)).strftime("%Y-%m-%d")
    parser = argparse.ArgumentParser(description="Backfill THS/iwencai popularity history")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--start-date", default=default_start, help="YYYY-MM-DD or YYYYMMDD")
    parser.add_argument("--end-date", default=date.today().strftime("%Y-%m-%d"), help="YYYY-MM-DD or YYYYMMDD")
    parser.add_argument("--rank-limit", type=int, default=100)
    parser.add_argument("--request-budget", type=int, default=20, help="Maximum dates to request in one run")
    parser.add_argument("--sleep", type=float, default=2.0, help="Base sleep seconds between date requests")
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--min-rows", type=int, default=80, help="Treat a date as failed if fewer rows are parsed")
    parser.add_argument("--date-order", choices=["asc", "desc"], default="asc", help="Download dates oldest-first or newest-first")
    parser.add_argument("--include-non-trading-days", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def import_deps():
    try:
        import pandas as pd  # type: ignore
        import pywencai  # type: ignore
    except ImportError as exc:
        raise SystemExit("Missing dependency. Run: pip install pywencai") from exc
    return pd, pywencai


def normalize_code(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip().upper()
    if "." in text:
        text = text.split(".", maxsplit=1)[0]
    if text.startswith(("SH", "SZ", "BJ")) and len(text) >= 8:
        text = text[2:8]
    if text.endswith((".SH", ".SZ", ".BJ")):
        text = text[:6]
    if text.isdigit() and len(text) <= 6:
        return text.zfill(6)
    return None


def normalize_date_arg(value: str) -> str:
    return normalize_date(value)


def date_range(start_date: str, end_date: str) -> list[str]:
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    days = []
    current = start
    while current <= end:
        days.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return days


def load_target_dates(conn: sqlite3.Connection, start_date: str, end_date: str, include_non_trading_days: bool) -> list[str]:
    if include_non_trading_days:
        return date_range(start_date, end_date)
    rows = conn.execute(
        """
        SELECT DISTINCT date
        FROM daily_bars
        WHERE date BETWEEN ? AND ?
        ORDER BY date
        """,
        (start_date, end_date),
    ).fetchall()
    return [row["date"] for row in rows]


def ensure_progress_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS popularity_date_backfill_progress (
            source TEXT NOT NULL,
            date TEXT NOT NULL,
            rank_limit INTEGER NOT NULL,
            status TEXT NOT NULL,
            rows INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (source, date, rank_limit)
        )
        """
    )
    conn.commit()


def is_done(conn: sqlite3.Connection, source: str, date_text: str, rank_limit: int, min_rows: int) -> bool:
    row = conn.execute(
        """
        SELECT status, rows
        FROM popularity_date_backfill_progress
        WHERE source = ? AND date = ? AND rank_limit = ?
        """,
        (source, date_text, rank_limit),
    ).fetchone()
    return bool(row and row["status"] == "ok" and int(row["rows"] or 0) >= min_rows)


def mark_progress(
    conn: sqlite3.Connection,
    source: str,
    date_text: str,
    rank_limit: int,
    status: str,
    rows: int,
    error: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO popularity_date_backfill_progress(source, date, rank_limit, status, rows, error, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, date, rank_limit)
        DO UPDATE SET
            status = excluded.status,
            rows = excluded.rows,
            error = excluded.error,
            updated_at = excluded.updated_at
        """,
        (
            source,
            date_text,
            rank_limit,
            status,
            rows,
            error,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )


def select_pending_dates(
    conn: sqlite3.Connection,
    dates: list[str],
    source: str,
    rank_limit: int,
    min_rows: int,
    force: bool,
    request_budget: int,
) -> tuple[list[str], int]:
    if force:
        pending = dates
        completed = 0
    else:
        pending = []
        completed = 0
        for date_text in dates:
            if is_done(conn, source, date_text, rank_limit, min_rows):
                completed += 1
            else:
                pending.append(date_text)
    if request_budget > 0:
        pending = pending[:request_budget]
    return pending, completed


def call_with_retry(func, retries: int, sleep_seconds: float):
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < retries:
                time.sleep(sleep_seconds * attempt)
    raise RuntimeError(last_error)


def find_date_column(columns: list[str], date_token: str, keywords: list[str], excluded: list[str] | None = None) -> str | None:
    excluded = excluded or []
    exact_candidates = [f"{keyword}[{date_token}]" for keyword in keywords]
    for candidate in exact_candidates:
        if candidate in columns:
            return candidate
    for column in columns:
        if date_token not in column:
            continue
        if any(text in column for text in excluded):
            continue
        if any(keyword in column for keyword in keywords):
            return column
    return None


def coerce_to_frame(pd, value):
    if value is None:
        return None
    if isinstance(value, pd.DataFrame):
        return value
    if isinstance(value, list):
        return pd.DataFrame(value)
    if isinstance(value, dict):
        for key in ["data", "result", "rows", "items"]:
            inner = value.get(key)
            if isinstance(inner, list):
                return pd.DataFrame(inner)
            if isinstance(inner, dict):
                return pd.DataFrame([inner])
        return pd.DataFrame([value])
    return None


def parse_rows(pd, df, date_text: str, rank_limit: int) -> list[tuple[str, str, int, str, str, float | None, str]]:
    df = coerce_to_frame(pd, df)
    if df is None or df.empty:
        return []
    date_token = date_text.replace("-", "")
    df = df.copy()
    df.columns = [str(column) for column in df.columns]
    columns = list(df.columns)

    rank_col = find_date_column(columns, date_token, ["个股热度排名", "人气排名"], excluded=["排名排名"])
    heat_col = find_date_column(columns, date_token, ["个股热度", "热度"], excluded=["排名"])
    code_col = "code" if "code" in columns else ("股票代码" if "股票代码" in columns else None)
    name_col = "股票简称" if "股票简称" in columns else ("名称" if "名称" in columns else None)
    if not rank_col or not code_col or not name_col:
        return []

    rows: list[tuple[str, str, int, str, str, float | None, str]] = []
    ranks = pd.to_numeric(df[rank_col], errors="coerce")
    heats = pd.to_numeric(df[heat_col], errors="coerce") if heat_col else None
    for idx, row in df.iterrows():
        rank = ranks.loc[idx]
        if pd.isna(rank):
            continue
        rank_int = int(rank)
        if rank_int < 1 or rank_int > rank_limit:
            continue
        code = normalize_code(row.get(code_col))
        name = str(row.get(name_col) or "").strip()
        if not code or not name:
            continue
        score = None
        if heats is not None and not pd.isna(heats.loc[idx]):
            score = float(heats.loc[idx])
        raw = {
            "query_date": date_text,
            "rank_column": rank_col,
            "heat_column": heat_col,
            "stock_code_raw": row.get(code_col),
        }
        rows.append(
            (
                SOURCE_THS_PYWENCAI,
                date_text,
                rank_int,
                code,
                name,
                score,
                json.dumps(raw, ensure_ascii=False, default=str),
            )
        )

    rows = sorted(rows, key=lambda item: (item[2], item[3]))
    unique_rows = []
    seen_codes = set()
    for row in rows:
        if row[3] in seen_codes:
            continue
        seen_codes.add(row[3])
        unique_rows.append(row)
    return unique_rows


def fetch_ths_date(pywencai, date_text: str):
    query = f"{date_text} 人气榜 股票代码 股票简称 人气排名"
    return pywencai.get(query=query, loop=False)


def insert_rows(conn: sqlite3.Connection, rows: list[tuple[str, str, int, str, str, float | None, str]]) -> None:
    conn.executemany(
        """
        INSERT OR REPLACE INTO popularity_rankings(source, date, rank, code, name, score, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def main() -> int:
    args = parse_args()
    start_date = normalize_date_arg(args.start_date)
    end_date = normalize_date_arg(args.end_date)
    if start_date > end_date:
        raise SystemExit("--start-date must be <= --end-date")
    if args.rank_limit < 1:
        raise SystemExit("--rank-limit must be >= 1")

    pd, pywencai = import_deps()
    conn = connect(args.db)
    ensure_progress_table(conn)
    target_dates = load_target_dates(conn, start_date, end_date, args.include_non_trading_days)
    if args.date_order == "desc":
        target_dates = list(reversed(target_dates))
    if not target_dates:
        raise SystemExit("No target dates found")
    pending_dates, completed_before = select_pending_dates(
        conn,
        target_dates,
        SOURCE_THS_PYWENCAI,
        args.rank_limit,
        args.min_rows,
        args.force,
        args.request_budget,
    )

    print(
        f"source={SOURCE_THS_PYWENCAI} range={start_date}..{end_date} rank_limit={args.rank_limit} "
        f"pending_dates={len(pending_dates)} completed_before={completed_before} dry_run={args.dry_run}"
    )

    failed = 0
    inserted = 0
    for idx, date_text in enumerate(pending_dates, 1):
        try:
            df = call_with_retry(lambda: fetch_ths_date(pywencai, date_text), args.retries, args.sleep)
            rows = parse_rows(pd, df, date_text, args.rank_limit)
            if len(rows) < args.min_rows:
                raise RuntimeError(f"parsed rows {len(rows)} < min_rows {args.min_rows}")
            if not args.dry_run:
                with conn:
                    insert_rows(conn, rows)
                    mark_progress(conn, SOURCE_THS_PYWENCAI, date_text, args.rank_limit, "ok", len(rows))
            inserted += len(rows)
            print(f"[{idx}/{len(pending_dates)}] {date_text} rows={len(rows)}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            if not args.dry_run:
                with conn:
                    mark_progress(
                        conn,
                        SOURCE_THS_PYWENCAI,
                        date_text,
                        args.rank_limit,
                        "failed",
                        0,
                        f"{type(exc).__name__}: {exc}",
                    )
            print(f"[{idx}/{len(pending_dates)}] failed {date_text}: {type(exc).__name__}: {exc}")
        time.sleep(args.sleep)

    print(
        f"done dates={len(pending_dates)} completed_before={completed_before} failed={failed} "
        f"rows={'would_insert' if args.dry_run else 'inserted'}:{inserted}"
    )
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
