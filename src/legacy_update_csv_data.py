#!/usr/bin/env python3
"""Incrementally update A-share daily CSV data with AkShare.

This script is intended for the Oracle host after dependencies are installed.
It keeps a stock-list cache so existing symbols can still be updated when the
latest spot-list endpoint is temporarily unavailable.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path


DEFAULT_DATA_DIR = Path("data/raw/stock_daily")
DEFAULT_START_DATE = "20210101"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update A-share daily data via AkShare")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--sleep", type=float, default=0.35)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--cache-file", type=Path, default=Path("data/stock_list_cache.csv"))
    parser.add_argument("--failed-file", type=Path, default=Path("logs/failed_tasks.csv"))
    return parser.parse_args()


def import_deps():
    try:
        import akshare as ak  # type: ignore
        import pandas as pd  # type: ignore
    except ImportError as exc:
        raise SystemExit("Missing dependency. Run: pip install -r requirements.txt") from exc
    return ak, pd


def read_cached_stock_list(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_stock_list_cache(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows[["代码", "名称"]].to_csv(path, index=False)


def get_existing_files(data_dir: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    if not data_dir.exists():
        return result
    for path in data_dir.glob("*_daily.csv"):
        code = path.name.split("_", 1)[0]
        result[code] = path
    return result


def last_date_from_csv(path: Path) -> str | None:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            last = None
            for row in reader:
                last = row.get("日期")
    except OSError:
        return None
    if not last:
        return None
    last = last.replace("-", "")
    return last if len(last) == 8 else None


def next_day(date_text: str) -> str:
    return (datetime.strptime(date_text, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")


def download_hist(ak, code: str, start_date: str, end_date: str, retries: int, sleep_seconds: float):
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            return ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
        except Exception as exc:  # noqa: BLE001 - endpoint errors are varied
            last_error = exc
            if attempt < retries:
                time.sleep(sleep_seconds * 5)
    raise RuntimeError(last_error)


def append_failed(path: Path, code: str, name: str, reason: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["time", "code", "name", "reason"])
        if not exists:
            writer.writeheader()
        writer.writerow({"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "code": code, "name": name, "reason": reason})


def main() -> None:
    args = parse_args()
    ak, _pd = import_deps()
    args.data_dir.mkdir(parents=True, exist_ok=True)

    try:
        stock_df = ak.stock_zh_a_spot_em()
        write_stock_list_cache(args.cache_file, stock_df)
        stocks = stock_df[["代码", "名称"]].to_dict("records")
        print(f"Fetched live stock list: {len(stocks)} symbols")
    except Exception as exc:  # noqa: BLE001
        stocks = read_cached_stock_list(args.cache_file)
        if not stocks:
            raise SystemExit(f"Failed to fetch stock list and no cache exists: {exc}") from exc
        print(f"Using cached stock list: {len(stocks)} symbols; live error: {exc}")

    existing = get_existing_files(args.data_dir)
    updated = 0
    skipped = 0
    failed = 0
    created = 0

    for index, row in enumerate(stocks, start=1):
        code = str(row["代码"])
        name = str(row["名称"])
        path = existing.get(code, args.data_dir / f"{code}_{name}_daily.csv")
        last_date = last_date_from_csv(path) if path.exists() else None
        start_date = next_day(last_date) if last_date else args.start_date

        if start_date > args.end_date:
            skipped += 1
            continue

        print(f"[{index}/{len(stocks)}] {code} {name} {start_date} -> {args.end_date}")
        time.sleep(args.sleep)
        try:
            df = download_hist(ak, code, start_date, args.end_date, args.retries, args.sleep)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            append_failed(args.failed_file, code, name, str(exc))
            continue

        if df is None or df.empty:
            skipped += 1
            continue

        df["股票名称"] = name
        if path.exists() and last_date:
            df.to_csv(path, mode="a", header=False, index=False)
            updated += 1
        else:
            df.to_csv(path, index=False)
            created += 1

    print(f"Done. created={created}, updated={updated}, skipped={skipped}, failed={failed}")
    if failed:
        print(f"Failed tasks written to {args.failed_file}", file=sys.stderr)


if __name__ == "__main__":
    main()
