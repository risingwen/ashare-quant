#!/usr/bin/env python3
"""Download the four benchmark indices used by the popularity study."""

from __future__ import annotations

import argparse
import time
from datetime import date
from typing import Any

import akshare as ak
from sqlalchemy import text

from quant_platform.db import engine
from quant_platform.migrate import apply_schema


INDEX_SPECS = {
    "000001.SH": ("上证综指", "sh000001"),
    "399001.SZ": ("深证成指", "sz399001"),
    "399006.SZ": ("创业板指", "sz399006"),
    "000688.SH": ("科创50", "sh000688"),
}


def _fetch(symbol: str, attempts: int = 3):
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return ak.stock_zh_index_daily(symbol=symbol)
        except Exception as exc:  # pragma: no cover - depends on the remote source
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
    raise RuntimeError(f"failed to fetch index {symbol} after {attempts} attempts") from last_error


def sync_indices(start: str, end: str) -> dict[str, int]:
    apply_schema()
    counts: dict[str, int] = {}
    for index_code, (index_name, source_symbol) in INDEX_SPECS.items():
        frame = _fetch(source_symbol).copy()
        frame["date"] = frame["date"].astype(str)
        frame = frame[(frame["date"] >= start) & (frame["date"] <= end)]
        payload: list[dict[str, Any]] = []
        for row in frame.itertuples(index=False):
            payload.append({
                "index_code": index_code,
                "index_name": index_name,
                "trade_date": row.date,
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": float(row.volume) if row.volume is not None else None,
                "provider": "akshare_sina",
            })
        if payload:
            with engine.begin() as conn:
                conn.execute(text("""INSERT INTO market.index_daily(
                  index_code,index_name,trade_date,open,high,low,close,volume,provider,fetched_at)
                  VALUES (:index_code,:index_name,:trade_date,:open,:high,:low,:close,:volume,:provider,now())
                  ON CONFLICT(index_code,trade_date) DO UPDATE SET
                    index_name=excluded.index_name,open=excluded.open,high=excluded.high,
                    low=excluded.low,close=excluded.close,volume=excluded.volume,
                    provider=excluded.provider,fetched_at=now()"""), payload)
        counts[index_code] = len(payload)
    return counts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="同步策略研究所需的四条基准指数日线")
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default=date.today().isoformat())
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    counts = sync_indices(args.start, args.end)
    print(" ".join(f"{code}={count}" for code, count in counts.items()))


if __name__ == "__main__":
    main()
