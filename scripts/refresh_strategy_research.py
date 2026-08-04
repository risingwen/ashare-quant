#!/usr/bin/env python3
"""Refresh recent hot-stock minute bars and publish the strategy ledgers."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import text

from generate_strategy_research_pages import build_pages
from generate_popularity_excursion_dashboard import build_excursion_records, render as render_excursions
from generate_factor_validation_dashboard import PAPERS, market_validation, popularity_validation, render as render_factor
from generate_ultra_short_research_report import (
    DEFAULT_MARKDOWN,
    DEFAULT_TEMPLATE as ULTRA_SHORT_TEMPLATE,
    build_payload as build_ultra_short_payload,
    render_html as render_ultra_short,
    render_markdown,
)
from quant_platform.db import engine
from quant_platform.intraday import ingest_minute_bars, ingest_price_limits, minute_candidates, save_progress
from quant_platform.providers.replay import ReplayProvider


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PRODUCTION_OUTPUT = PROJECT_ROOT / "reports" / "latest" / "strategy-research"


def _recent_dates(lookback: int) -> tuple[list[str], str]:
    with engine.connect() as conn:
        latest = conn.execute(text("SELECT max(trade_date) FROM market.daily_bar")).scalar_one()
        if latest is None:
            raise RuntimeError("market.daily_bar is empty")
        dates = [
            row[0].isoformat() for row in conn.execute(text("""SELECT trade_date
              FROM market.trade_calendar WHERE is_open AND trade_date<=:latest
              ORDER BY trade_date DESC LIMIT :lookback"""), {"latest": latest, "lookback": lookback})
        ]
    return sorted(dates), latest.isoformat()


def _missing_minutes(candidates: list[tuple[str, str]]) -> list[tuple[str, str]]:
    if not candidates:
        return []
    with engine.connect() as conn:
        covered = {
            (row[0].isoformat(), row[1]) for row in conn.execute(text("""SELECT trade_date,symbol
              FROM market.minute_bar WHERE freq='1min'
                AND trade_date=ANY(:dates) AND symbol=ANY(:symbols)
              GROUP BY trade_date,symbol HAVING count(*)>=240"""), {
                "dates": sorted({run_date for run_date, _ in candidates}),
                "symbols": sorted({symbol for _, symbol in candidates}),
            })
        }
    return [candidate for candidate in candidates if candidate not in covered]


def refresh_minutes(signal_start: str, signal_end: str, workers: int) -> dict:
    candidates = minute_candidates(signal_start, signal_end, 10)
    pending = _missing_minutes(candidates)

    def download(candidate: tuple[str, str]) -> tuple[str, str, dict]:
        trade_date, symbol = candidate
        error = None
        try:
            output = ingest_minute_bars(ReplayProvider(), symbol, trade_date, "1min")
        except Exception as exc:
            output = {"status": "failed", "rows": 0}
            error = str(exc)[:1000]
        save_progress(symbol, trade_date, "1min", output, error)
        return trade_date, symbol, output

    outputs = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        outputs = list(executor.map(download, pending))

    by_date: dict[str, set[str]] = {}
    for trade_date, symbol in candidates:
        by_date.setdefault(trade_date, set()).add(symbol)
    limit_outputs = {}
    for trade_date, symbols in by_date.items():
        with engine.connect() as conn:
            covered = conn.execute(text("""SELECT count(*) FROM market.price_limit
              WHERE trade_date=:date AND symbol=ANY(:symbols)"""), {
                "date": trade_date, "symbols": sorted(symbols),
            }).scalar_one()
        if covered < len(symbols):
            try:
                limit_outputs[trade_date] = ingest_price_limits(ReplayProvider(), trade_date, symbols)
            except Exception as exc:
                limit_outputs[trade_date] = {"status": "failed", "error": str(exc)[:1000]}
    return {
        "candidates": len(candidates),
        "minute_requested": len(pending),
        "minute_success": sum(item[2].get("status") == "success" for item in outputs),
        "limits": limit_outputs,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="刷新近期分钟数据和策略复盘页面")
    parser.add_argument("--lookback", type=int, default=6)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=PRODUCTION_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dates, latest = _recent_dates(args.lookback)
    minute_result = {"skipped": True} if args.skip_download else refresh_minutes(dates[0], latest, args.workers)
    pages = build_pages("2025-01-01", latest, 1_000_000_000, args.output_dir)
    excursion_end = dates[-2] if len(dates) >= 2 else latest
    excursion_records, excursion_metadata = build_excursion_records("2025-01-01", excursion_end)
    excursion_output = args.output_dir / "popularity-top10-excursions.html"
    render_excursions(
        excursion_records,
        excursion_metadata,
        Path(__file__).with_name("popularity_excursion_dashboard.html"),
        excursion_output,
    )
    factor_payload = {
        "generated_for": latest,
        "papers": PAPERS,
        "market": market_validation("2025-01-01", latest),
        "popularity": popularity_validation("2025-01-01", latest, 1_000_000_000),
    }
    factor_output = args.output_dir / "factor-validation.html"
    render_factor(factor_payload, Path(__file__).with_name("factor_validation_dashboard.html"), factor_output)
    report_payload = build_ultra_short_payload("2025-01-01", latest, args.output_dir)
    report_output = args.output_dir / "ultra-short-research-report.html"
    render_ultra_short(report_payload, ULTRA_SHORT_TEMPLATE, report_output)
    render_markdown(report_payload, DEFAULT_MARKDOWN)
    print(json.dumps({
        "latest": latest,
        "minute": minute_result,
        "pages": pages,
        "excursion_output": str(excursion_output),
        "factor_output": str(factor_output),
        "report_output": str(report_output),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
