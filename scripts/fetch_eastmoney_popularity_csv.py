#!/usr/bin/env python3
"""Fetch Eastmoney per-stock popularity history to CSV.

This script is intentionally standalone for remote cloud hosts. It only needs
Python stdlib and writes both ranking rows and per-stock progress rows.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


SOURCE_EASTMONEY_DETAIL_ALL = "eastmoney_hot_rank_detail_em_all"
DEFAULT_ALL_RANK_LIMIT = 10000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch Eastmoney popularity history to CSV")
    parser.add_argument("--codes-file", type=Path, required=True, help="CSV with code,name columns")
    parser.add_argument("--dates-file", type=Path, help="Trading dates file, one YYYY-MM-DD per line")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--source", default=SOURCE_EASTMONEY_DETAIL_ALL)
    parser.add_argument("--rank-limit", type=int, default=DEFAULT_ALL_RANK_LIMIT)
    parser.add_argument("--sleep", type=float, default=3.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--progress-output", type=Path, required=True)
    return parser.parse_args()


def normalize_code(raw: object) -> str | None:
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


def read_codes(path: Path) -> list[dict[str, str]]:
    rows = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            code = normalize_code(row.get("code"))
            name = str(row.get("name") or code or "").strip()
            if code:
                rows.append({"code": code, "name": name})
    return rows


def read_dates(path: Path | None) -> set[str] | None:
    if not path:
        return None
    dates = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if text:
            dates.add(text)
    return dates


def post_json(url: str, payload: dict[str, object], timeout: float) -> dict[str, object]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://guba.eastmoney.com/rank/",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def fetch_detail(symbol: str, timeout: float) -> tuple[list[dict[str, object]], dict[str, dict[str, object]]]:
    payload = {
        "appId": "appId01",
        "globalId": "786e4c21-70dc-435a-93bb-38",
        "marketType": "",
        "srcSecurityCode": symbol,
        "yearType": "5",
    }
    rank_json = post_json("https://emappdata.eastmoney.com/stockrank/getHisList", payload, timeout)
    rank_rows = rank_json.get("data") or []
    profile_json = post_json("https://emappdata.eastmoney.com/stockrank/getHisProfileList", payload, timeout)
    profile_by_date = {}
    for item in profile_json.get("data") or []:
        date_text = str(item.get("calcTime") or "")[:10]
        if date_text:
            profile_by_date[date_text] = item
    return list(rank_rows), profile_by_date


def call_with_retry(func, retries: int, sleep_seconds: float):
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return func()
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(sleep_seconds * attempt)
    raise RuntimeError(last_error)


def main() -> int:
    args = parse_args()
    codes = read_codes(args.codes_file)
    trading_dates = read_dates(args.dates_file)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.progress_output.parent.mkdir(parents=True, exist_ok=True)
    print(
        f"source={args.source} codes={len(codes)} range={args.start_date}..{args.end_date} "
        f"rank_limit={args.rank_limit}"
    )

    with args.output.open("w", newline="", encoding="utf-8") as out_fh, args.progress_output.open(
        "w", newline="", encoding="utf-8"
    ) as progress_fh:
        writer = csv.DictWriter(out_fh, fieldnames=["source", "date", "rank", "code", "name", "score", "raw_json"])
        writer.writeheader()
        progress_writer = csv.DictWriter(
            progress_fh,
            fieldnames=["source", "code", "start_date", "end_date", "rank_limit", "status", "rows", "error"],
        )
        progress_writer.writeheader()

        total_rows = 0
        failures = 0
        for idx, stock in enumerate(codes, 1):
            code = stock["code"]
            name = stock["name"]
            inserted = 0
            error = ""
            status = "ok"
            try:
                symbol = market_symbol(code)
                rank_rows, profile_by_date = call_with_retry(
                    lambda: fetch_detail(symbol, args.timeout),
                    retries=args.retries,
                    sleep_seconds=args.sleep,
                )
                for item in rank_rows:
                    date_text = str(item.get("calcTime") or "")[:10]
                    rank = item.get("rank")
                    if not date_text or rank is None:
                        continue
                    rank_int = int(rank)
                    if date_text < args.start_date or date_text > args.end_date:
                        continue
                    if trading_dates is not None and date_text not in trading_dates:
                        continue
                    if rank_int < 1 or rank_int > args.rank_limit:
                        continue
                    profile = profile_by_date.get(date_text, {})
                    writer.writerow(
                        {
                            "source": args.source,
                            "date": date_text,
                            "rank": rank_int,
                            "code": code,
                            "name": name,
                            "score": "",
                            "raw_json": json.dumps(
                                {
                                    "source_code": symbol,
                                    "new_fans_pct": profile.get("newUidRate"),
                                    "core_fans_pct": profile.get("oldUidRate"),
                                },
                                ensure_ascii=False,
                            ),
                        }
                    )
                    inserted += 1
            except Exception as exc:  # noqa: BLE001
                failures += 1
                status = "failed"
                error = f"{type(exc).__name__}: {exc}"

            progress_writer.writerow(
                {
                    "source": args.source,
                    "code": code,
                    "start_date": args.start_date,
                    "end_date": args.end_date,
                    "rank_limit": args.rank_limit,
                    "status": status,
                    "rows": inserted,
                    "error": error,
                }
            )
            total_rows += inserted
            if idx <= 5 or idx % 25 == 0:
                print(f"[{idx}/{len(codes)}] code={code} status={status} rows={inserted} total_rows={total_rows}")
            time.sleep(args.sleep + random.uniform(0, args.sleep * 0.4))

    print(f"done codes={len(codes)} failures={failures} rows={total_rows}")
    return 0 if failures == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
