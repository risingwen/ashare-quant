#!/usr/bin/env python3
"""Fetch THS/iwencai popularity Top N to a CSV file without local database access."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


SOURCE_THS_PYWENCAI = "ths_pywencai_hot_rank"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch THS/iwencai popularity rankings to CSV")
    parser.add_argument("--dates-file", type=Path, help="One YYYY-MM-DD date per line")
    parser.add_argument("--start-date", help="YYYY-MM-DD")
    parser.add_argument("--end-date", help="YYYY-MM-DD")
    parser.add_argument("--date-order", choices=["asc", "desc"], default="asc")
    parser.add_argument("--rank-limit", type=int, default=100)
    parser.add_argument("--source", default=SOURCE_THS_PYWENCAI)
    parser.add_argument("--sleep", type=float, default=4.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--min-rows", type=int, default=80)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--failed-output", type=Path)
    return parser.parse_args()


def import_deps():
    try:
        import pandas as pd  # type: ignore
        import pywencai  # type: ignore
    except ImportError as exc:
        raise SystemExit("Missing dependency. Run: pip install pywencai pandas") from exc
    return pd, pywencai


def date_range(start_date: str, end_date: str) -> list[str]:
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    dates = []
    current = start
    while current <= end:
        dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return dates


def load_dates(args: argparse.Namespace) -> list[str]:
    if args.dates_file:
        dates = [line.strip() for line in args.dates_file.read_text(encoding="utf-8").splitlines()]
        dates = [date for date in dates if date and not date.startswith("#")]
    elif args.start_date and args.end_date:
        dates = date_range(args.start_date, args.end_date)
    else:
        raise SystemExit("Provide --dates-file or both --start-date and --end-date")
    if args.date_order == "desc":
        dates = list(reversed(dates))
    return dates


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


def find_date_column(columns: list[str], date_token: str, keywords: list[str], excluded: list[str] | None = None) -> str | None:
    excluded = excluded or []
    for keyword in keywords:
        candidate = f"{keyword}[{date_token}]"
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


def parse_rows(pd, value, date_text: str, rank_limit: int, source: str) -> list[dict[str, object]]:
    df = coerce_to_frame(pd, value)
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

    ranks = pd.to_numeric(df[rank_col], errors="coerce")
    heats = pd.to_numeric(df[heat_col], errors="coerce") if heat_col else None
    rows = []
    seen_codes = set()
    for idx, row in df.iterrows():
        rank = ranks.loc[idx]
        if pd.isna(rank):
            continue
        rank_int = int(rank)
        if rank_int < 1 or rank_int > rank_limit:
            continue
        code = normalize_code(row.get(code_col))
        name = str(row.get(name_col) or "").strip()
        if not code or not name or code in seen_codes:
            continue
        seen_codes.add(code)
        score = ""
        if heats is not None and not pd.isna(heats.loc[idx]):
            score = float(heats.loc[idx])
        raw = {
            "query_date": date_text,
            "rank_column": rank_col,
            "heat_column": heat_col,
            "stock_code_raw": row.get(code_col),
        }
        rows.append(
            {
                "source": source,
                "date": date_text,
                "rank": rank_int,
                "code": code,
                "name": name,
                "score": score,
                "raw_json": json.dumps(raw, ensure_ascii=False, default=str),
            }
        )
    return sorted(rows, key=lambda item: (int(item["rank"]), str(item["code"])))


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


def fetch_date(pywencai, date_text: str, rank_limit: int):
    if rank_limit <= 100:
        query = f"{date_text} 人气榜 股票代码 股票简称 人气排名"
    else:
        query = f"{date_text} 个股热度排名前{rank_limit} 股票代码 股票简称 个股热度 个股热度排名"
    return pywencai.get(query=query, loop=False)


def write_rows(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    pd, pywencai = import_deps()
    dates = load_dates(args)
    all_rows: list[dict[str, object]] = []
    failed: list[dict[str, str]] = []
    print(f"dates={len(dates)} output={args.output}", flush=True)
    for idx, date_text in enumerate(dates, 1):
        try:
            value = call_with_retry(lambda: fetch_date(pywencai, date_text, args.rank_limit), args.retries, args.sleep)
            rows = parse_rows(pd, value, date_text, args.rank_limit, args.source)
            if len(rows) < args.min_rows:
                raise RuntimeError(f"parsed rows {len(rows)} < min_rows {args.min_rows}")
            all_rows.extend(rows)
            print(f"[{idx}/{len(dates)}] {date_text} rows={len(rows)}", flush=True)
        except Exception as exc:  # noqa: BLE001
            failed.append({"date": date_text, "error": f"{type(exc).__name__}: {exc}"})
            print(f"[{idx}/{len(dates)}] failed {date_text}: {type(exc).__name__}: {exc}", flush=True)
        time.sleep(args.sleep)
    write_rows(args.output, all_rows, ["source", "date", "rank", "code", "name", "score", "raw_json"])
    failed_output = args.failed_output or args.output.with_suffix(".failed.csv")
    write_rows(failed_output, failed, ["date", "error"]) if failed else failed_output.write_text(
        "date,error\n", encoding="utf-8"
    )
    print(f"done rows={len(all_rows)} failed={len(failed)}", flush=True)
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
