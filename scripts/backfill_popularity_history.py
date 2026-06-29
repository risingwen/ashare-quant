#!/usr/bin/env python3
"""Backfill historical popularity rankings into SQLite.

Eastmoney exposes per-stock hot-rank history. This script rebuilds daily history
by scanning stocks, filtering each stock's historical rank, and writing
qualified rows into popularity_rankings. Use --all-ranks for full-rank history,
or keep the default Top 100 source for lighter strategy inputs.
"""

from __future__ import annotations

import argparse
import json
import random
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


SOURCE_EASTMONEY_DETAIL = "eastmoney_hot_rank_detail_em"
SOURCE_EASTMONEY_DETAIL_ALL = "eastmoney_hot_rank_detail_em_all"
DEFAULT_ALL_RANK_LIMIT = 10000


def parse_args() -> argparse.Namespace:
    default_start = (date.today() - timedelta(days=365)).strftime("%Y-%m-%d")
    parser = argparse.ArgumentParser(description="Backfill historical stock popularity rankings")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--start-date", default=default_start, help="YYYY-MM-DD or YYYYMMDD")
    parser.add_argument("--end-date", default=date.today().strftime("%Y-%m-%d"), help="YYYY-MM-DD or YYYYMMDD")
    parser.add_argument("--rank-limit", type=int, default=100, help="Only insert ranks within Top N")
    parser.add_argument("--all-ranks", action="store_true", help="Store all returned ranks using a separate default source")
    parser.add_argument("--source", help="Override output source name in popularity_rankings")
    parser.add_argument("--sleep", type=float, default=2.0, help="Base sleep seconds between stock requests")
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout seconds per Eastmoney request")
    parser.add_argument("--max-symbols", type=int, help="Debug only: limit scanned stocks")
    parser.add_argument("--codes", help="Comma-separated 6-digit stock codes to scan")
    parser.add_argument("--request-budget", type=int, default=300, help="Maximum stocks to request in one run")
    parser.add_argument("--allow-full-scan", action="store_true", help="Allow scanning all database stocks")
    parser.add_argument("--include-non-trading-days", action="store_true")
    parser.add_argument("--force", action="store_true", help="Refetch even if progress says this code is done")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and summarize without writing rows")
    return parser.parse_args()


def import_deps():
    try:
        import pandas as pd  # type: ignore
        import requests  # type: ignore
    except ImportError as exc:
        raise SystemExit("Missing dependency. Run: pip install -r requirements.txt") from exc
    return pd, requests


def normalize_code(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip().upper()
    if text.startswith(("SH", "SZ", "BJ")) and len(text) >= 8:
        text = text[2:8]
    if text.endswith((".SH", ".SZ", ".BJ")):
        text = text[:6]
    if text.isdigit() and len(text) <= 6:
        return text.zfill(6)
    return None


def market_symbol(code: str) -> str:
    if code.startswith(("8", "4", "9")):
        return f"BJ{code}"
    if code.startswith(("6", "5")):
        return f"SH{code}"
    return f"SZ{code}"


def normalize_date_arg(value: str) -> str:
    return normalize_date(value)


def load_stocks(conn: sqlite3.Connection, codes_arg: str | None, max_symbols: int | None) -> list[dict[str, str]]:
    if codes_arg:
        codes = [normalize_code(item) for item in codes_arg.split(",")]
        codes = [code for code in codes if code]
        if not codes:
            return []
        placeholders = ",".join("?" for _ in codes)
        rows = conn.execute(
            f"SELECT code, name FROM stocks WHERE code IN ({placeholders}) ORDER BY code",
            codes,
        ).fetchall()
        by_code = {row["code"]: row["name"] for row in rows}
        stocks = [{"code": code, "name": by_code.get(code, code)} for code in codes]
    else:
        rows = conn.execute("SELECT code, name FROM stocks ORDER BY code").fetchall()
        stocks = [{"code": row["code"], "name": row["name"]} for row in rows]
    if max_symbols:
        stocks = stocks[:max_symbols]
    return stocks


def select_pending_stocks(
    conn: sqlite3.Connection,
    stocks: list[dict[str, str]],
    source: str,
    start_date: str,
    end_date: str,
    rank_limit: int,
    force: bool,
    request_budget: int,
) -> tuple[list[dict[str, str]], int]:
    if force:
        pending = stocks
        completed = 0
    else:
        pending = []
        completed = 0
        for stock in stocks:
            if is_done(conn, source, stock["code"], start_date, end_date, rank_limit):
                completed += 1
            else:
                pending.append(stock)

    if request_budget > 0:
        pending = pending[:request_budget]
    return pending, completed


def load_trading_dates(conn: sqlite3.Connection, start_date: str, end_date: str) -> set[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT date
        FROM daily_bars
        WHERE date BETWEEN ? AND ?
        ORDER BY date
        """,
        (start_date, end_date),
    ).fetchall()
    return {row["date"] for row in rows}


def ensure_progress_table(conn: sqlite3.Connection) -> None:
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
    conn.commit()


def is_done(
    conn: sqlite3.Connection,
    source: str,
    code: str,
    start_date: str,
    end_date: str,
    rank_limit: int,
) -> bool:
    row = conn.execute(
        """
        SELECT status, updated_at
        FROM popularity_backfill_progress
        WHERE source = ? AND code = ? AND start_date = ? AND end_date = ? AND rank_limit = ?
        """,
        (source, code, start_date, end_date, rank_limit),
    ).fetchone()
    if not row:
        return False
    if row["status"] == "ok":
        return True
    if row["status"] == "running":
        updated_at = row["updated_at"]
        if updated_at:
            try:
                updated = datetime.strptime(str(updated_at), "%Y-%m-%d %H:%M:%S")
                return datetime.now() - updated < timedelta(hours=12)
            except ValueError:
                return False
    return False


def mark_progress(
    conn: sqlite3.Connection,
    source: str,
    code: str,
    start_date: str,
    end_date: str,
    rank_limit: int,
    status: str,
    rows: int,
    error: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO popularity_backfill_progress(
            source, code, start_date, end_date, rank_limit, status, rows, error, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, code, start_date, end_date, rank_limit)
        DO UPDATE SET
            status = excluded.status,
            rows = excluded.rows,
            error = excluded.error,
            updated_at = excluded.updated_at
        """,
        (
            source,
            code,
            start_date,
            end_date,
            rank_limit,
            status,
            rows,
            error,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )


def first_existing_column(columns: list[str], candidates: list[str]) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def parse_eastmoney_detail_rows(
    pd,
    df,
    source: str,
    code: str,
    name: str,
    start_date: str,
    end_date: str,
    rank_limit: int,
    trading_dates: set[str] | None,
) -> list[tuple[str, str, int, str, str, float | None, str]]:
    if df is None or df.empty:
        return []

    columns = [str(column) for column in df.columns]
    df = df.copy()
    df.columns = columns

    date_col = first_existing_column(columns, ["时间", "日期", "date"])
    rank_col = first_existing_column(columns, ["排名", "当前排名", "rank", "hot_rank"])
    code_col = first_existing_column(columns, ["证券代码", "股票代码", "代码", "code"])
    new_fans_col = first_existing_column(columns, ["新晋粉丝", "new_fans_pct"])
    core_fans_col = first_existing_column(columns, ["铁杆粉丝", "core_fans_pct"])
    if not date_col or not rank_col:
        return []

    parsed_dates = pd.to_datetime(df[date_col], errors="coerce").dt.strftime("%Y-%m-%d")
    ranks = pd.to_numeric(df[rank_col], errors="coerce")
    rows: list[tuple[str, str, int, str, str, float | None, str]] = []

    for idx, row in df.iterrows():
        row_date = parsed_dates.loc[idx]
        rank = ranks.loc[idx]
        if pd.isna(row_date) or pd.isna(rank):
            continue
        row_date = str(row_date)
        rank_int = int(rank)
        if row_date < start_date or row_date > end_date:
            continue
        if trading_dates is not None and row_date not in trading_dates:
            continue
        if rank_int < 1 or rank_int > rank_limit:
            continue

        row_code = normalize_code(row.get(code_col)) if code_col else None
        raw = {
            "source_code": row.get(code_col) if code_col else market_symbol(code),
            "new_fans_pct": row.get(new_fans_col) if new_fans_col else None,
            "core_fans_pct": row.get(core_fans_col) if core_fans_col else None,
        }
        rows.append(
            (
                source,
                row_date,
                rank_int,
                row_code or code,
                name,
                None,
                json.dumps(raw, ensure_ascii=False, default=str),
            )
        )
    return rows


def parse_percent(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("%"):
            return float(text[:-1]) / 100.0
        return float(text)
    except ValueError:
        return None


def fetch_eastmoney_detail_df(pd, session, symbol: str, timeout: float):
    payload = {
        "appId": "appId01",
        "globalId": "786e4c21-70dc-435a-93bb-38",
        "marketType": "",
        "srcSecurityCode": symbol,
        "yearType": "5",
    }
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": f"https://guba.eastmoney.com/rank/stock?code={symbol[-6:]}",
        "Content-Type": "application/json",
    }
    rank_resp = session.post(
        "https://emappdata.eastmoney.com/stockrank/getHisList",
        json=payload,
        headers=headers,
        timeout=timeout,
    )
    rank_resp.raise_for_status()
    rank_data = rank_resp.json().get("data") or []
    if not rank_data:
        return pd.DataFrame()

    profile_by_date: dict[str, dict[str, Any]] = {}
    profile_resp = session.post(
        "https://emappdata.eastmoney.com/stockrank/getHisProfileList",
        json=payload,
        headers=headers,
        timeout=timeout,
    )
    profile_resp.raise_for_status()
    for item in profile_resp.json().get("data") or []:
        date_text = str(item.get("calcTime") or "")[:10]
        if date_text:
            profile_by_date[date_text] = item

    rows = []
    for item in rank_data:
        row_date = str(item.get("calcTime") or "")[:10]
        if not row_date:
            continue
        profile = profile_by_date.get(row_date, {})
        rows.append(
            {
                "时间": row_date,
                "排名": item.get("rank"),
                "证券代码": symbol,
                "新晋粉丝": parse_percent(profile.get("newUidRate")),
                "铁杆粉丝": parse_percent(profile.get("oldUidRate")),
            }
        )
    return pd.DataFrame(rows)


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
    rank_limit = DEFAULT_ALL_RANK_LIMIT if args.all_ranks and args.rank_limit == 100 else args.rank_limit
    source = args.source or (SOURCE_EASTMONEY_DETAIL_ALL if args.all_ranks else SOURCE_EASTMONEY_DETAIL)
    if args.rank_limit < 1:
        raise SystemExit("--rank-limit must be >= 1")

    pd, requests = import_deps()
    session = requests.Session()
    conn = connect(args.db)
    ensure_progress_table(conn)
    stocks = load_stocks(conn, args.codes, args.max_symbols)
    if not args.codes and not args.max_symbols and not args.allow_full_scan and args.request_budget <= 0:
        raise SystemExit(
            "Refusing full-market Eastmoney scan by default. Use --max-symbols for batches, "
            "--request-budget for resumable batches, --codes for targeted checks, or "
            "--allow-full-scan only from a controlled network."
        )
    stocks, completed_before = select_pending_stocks(
        conn,
        stocks,
        source,
        start_date,
        end_date,
        rank_limit,
        args.force,
        args.request_budget,
    )
    trading_dates = None if args.include_non_trading_days else load_trading_dates(conn, start_date, end_date)
    if not args.include_non_trading_days and not trading_dates:
        raise SystemExit("No trading dates found in daily_bars for requested range")

    print(
        f"source={source} range={start_date}..{end_date} "
        f"rank_limit={rank_limit} pending_stocks={len(stocks)} "
        f"completed_before={completed_before} dry_run={args.dry_run}"
    )

    scanned = 0
    failed = 0
    inserted = 0
    for idx, stock in enumerate(stocks, 1):
        code = stock["code"]
        name = stock["name"]
        scanned += 1
        try:
            symbol = market_symbol(code)
            df = call_with_retry(
                lambda: fetch_eastmoney_detail_df(pd, session, symbol, args.timeout),
                retries=args.retries,
                sleep_seconds=args.sleep,
            )
            rows = parse_eastmoney_detail_rows(
                pd,
                df,
                source,
                code,
                name,
                start_date,
                end_date,
                rank_limit,
                trading_dates,
            )
            if not args.dry_run:
                with conn:
                    insert_rows(conn, rows)
                    mark_progress(
                        conn,
                        source,
                        code,
                        start_date,
                        end_date,
                        rank_limit,
                        "ok",
                        len(rows),
                    )
            inserted += len(rows)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            if not args.dry_run:
                with conn:
                    mark_progress(
                        conn,
                        source,
                        code,
                        start_date,
                        end_date,
                        rank_limit,
                        "failed",
                        0,
                        f"{type(exc).__name__}: {exc}",
                    )
            print(f"[{idx}/{len(stocks)}] failed {code} {name}: {type(exc).__name__}: {exc}")

        if idx <= 5 or idx % 100 == 0:
            print(
                f"[{idx}/{len(stocks)}] scanned={scanned} completed_before={completed_before} "
                f"failed={failed} rows={inserted}"
            )
        time.sleep(args.sleep + random.uniform(0, args.sleep * 0.4))

    print(
        f"done scanned={scanned} completed_before={completed_before} failed={failed} "
        f"rows={'would_insert' if args.dry_run else 'inserted'}:{inserted}"
    )
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
