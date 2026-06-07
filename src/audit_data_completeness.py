#!/usr/bin/env python3
"""Audit SQLite quant data completeness before downstream research runs.

The health check repairs stale tables, but it historically only compared
table-level MAX(date). This script is stricter: it checks trading-day
continuity, recent row coverage, key-table freshness, duplicates, nulls and
basic OHLC consistency. A non-zero exit code means downstream reports/backtests
should not be trusted until the data gap is fixed.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

from quant_core import DEFAULT_DB_PATH, normalize_date
from quant_db import connect

DEFAULT_AUDIT_CONFIG_PATH = Path("config/audit_completeness.yaml")


@dataclass
class AuditResult:
    """Structured audit result."""

    name: str
    status: str
    detail: str
    stats: dict[str, Any] = field(default_factory=dict)


def load_audit_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        return {}
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise SystemExit("Missing dependency for YAML config. Run: pip install -r requirements.txt") from exc
    with config_path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"Audit config must be a mapping: {config_path}")
    return data


def parse_args() -> argparse.Namespace:
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--audit-config", type=Path, default=DEFAULT_AUDIT_CONFIG_PATH)
    pre_args, _ = pre_parser.parse_known_args()
    config = load_audit_config(pre_args.audit_config)

    parser = argparse.ArgumentParser(description="Audit quant SQLite data completeness")
    parser.add_argument("--audit-config", type=Path, default=pre_args.audit_config)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--start-date", help="Start date, YYYY-MM-DD or YYYYMMDD")
    parser.add_argument("--end-date", help="End date, YYYY-MM-DD or YYYYMMDD; defaults to latest trading day <= today")
    parser.add_argument("--lookback-days", type=int, default=int(config.get("lookback_days", 20)), help="Natural-day lookback when --start-date is omitted")
    parser.add_argument("--min-daily-bars", type=int, default=int(config.get("min_daily_bars", 5000)), help="Minimum daily_bars rows per recent trading day")
    parser.add_argument("--min-etf-rows", type=int, default=int(config.get("min_etf_rows", 300)), help="Minimum etf_daily rows on latest expected trading day")
    parser.add_argument("--min-popularity-rows", type=int, default=int(config.get("min_popularity_rows", 50)), help="Minimum popularity rows on latest expected trading day")
    parser.add_argument("--min-limit-up-rows", type=int, default=int(config.get("min_limit_up_rows", 1)), help="Minimum limit_up_pool rows on latest expected trading day")
    parser.add_argument("--strict-lhb", action="store_true", default=bool(config.get("strict_lhb", False)), help="Require lhb_records rows on latest expected trading day")
    parser.add_argument("--json-output", type=Path, help="Write machine-readable audit result JSON")
    parser.add_argument("--record-issues", action="store_true", help="Append failed checks to data_quality_issues")
    parser.add_argument("--socket-timeout", type=float, default=float(config.get("socket_timeout", 15.0)))
    return parser.parse_args()


def compact_to_iso(date_text: str) -> str:
    normalized = normalize_date(date_text)
    if len(normalized) != 10:
        raise ValueError(f"Invalid date: {date_text}")
    return normalized


def fallback_weekdays(start_date: str, end_date: str) -> list[str]:
    current_date = datetime.strptime(start_date, "%Y-%m-%d")
    final_date = datetime.strptime(end_date, "%Y-%m-%d")
    days: list[str] = []
    while current_date <= final_date:
        if current_date.weekday() < 5:
            days.append(current_date.strftime("%Y-%m-%d"))
        current_date += timedelta(days=1)
    return days


def get_trading_days(start_date: str, end_date: str) -> tuple[list[str], str]:
    """Return trading days and source name."""

    try:
        import akshare as ak  # type: ignore

        calendar = ak.tool_trade_date_hist_sina()
        raw_dates = sorted(normalize_date(value) for value in calendar.iloc[:, 0].dropna().tolist())
        trade_days = [date_text for date_text in raw_dates if start_date <= date_text <= end_date]
        if trade_days:
            return trade_days, "akshare.tool_trade_date_hist_sina"
    except Exception as exc:  # noqa: BLE001 - live data dependency is heterogeneous
        print(f"[WARN] Trading calendar unavailable, fallback to weekdays: {exc}")

    return fallback_weekdays(start_date, end_date), "weekday_fallback"


def resolve_date_window(args: argparse.Namespace) -> tuple[str, str, list[str], str]:
    today = datetime.now().date()
    requested_end = compact_to_iso(args.end_date) if args.end_date else today.strftime("%Y-%m-%d")
    preliminary_start = compact_to_iso(args.start_date) if args.start_date else (
        datetime.strptime(requested_end, "%Y-%m-%d").date() - timedelta(days=args.lookback_days)
    ).strftime("%Y-%m-%d")

    preliminary_days, calendar_source = get_trading_days(preliminary_start, requested_end)
    if not preliminary_days:
        raise SystemExit(f"No trading days found in {preliminary_start}..{requested_end}")

    end_date = max(preliminary_days)
    start_date = preliminary_start
    if not args.start_date:
        start_date = min(preliminary_days)

    trading_days = [date_text for date_text in preliminary_days if start_date <= date_text <= end_date]
    return start_date, end_date, trading_days, calendar_source


def table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def scalar(conn, sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    if row is None:
        return None
    return row[0]


def audit_table_freshness(conn, table_name: str, expected_date: str, minimum_rows: int = 1) -> AuditResult:
    if not table_exists(conn, table_name):
        return AuditResult(table_name, "error", "table does not exist")

    latest_date = scalar(conn, f"SELECT MAX(date) FROM {table_name}")
    latest_rows = int(scalar(conn, f"SELECT COUNT(*) FROM {table_name} WHERE date=?", (expected_date,)) or 0)
    stats = {"expected_date": expected_date, "latest_date": latest_date, "latest_rows": latest_rows}

    if latest_date != expected_date:
        return AuditResult(table_name, "error", f"latest date {latest_date or 'N/A'} != expected {expected_date}", stats)
    if latest_rows < minimum_rows:
        return AuditResult(table_name, "error", f"rows {latest_rows} < required {minimum_rows} on {expected_date}", stats)
    return AuditResult(table_name, "ok", f"fresh at {expected_date}", stats)


def audit_market_daily(conn, trading_days: list[str]) -> AuditResult:
    placeholders = ",".join("?" for _ in trading_days)
    existing = {
        row["date"]
        for row in conn.execute(
            f"SELECT date FROM market_daily WHERE date IN ({placeholders})",
            tuple(trading_days),
        ).fetchall()
    }
    missing_days = [date_text for date_text in trading_days if date_text not in existing]
    stats = {"expected_days": len(trading_days), "missing_days": missing_days}
    if missing_days:
        return AuditResult("market_daily_continuity", "error", f"missing {len(missing_days)} trading days", stats)
    return AuditResult("market_daily_continuity", "ok", "all expected trading days exist", stats)


def audit_daily_bars(conn, trading_days: list[str], min_daily_bars: int) -> list[AuditResult]:
    results: list[AuditResult] = []
    latest_expected = trading_days[-1]

    duplicate_count = int(
        scalar(
            conn,
            """
            SELECT COUNT(*) FROM (
                SELECT code, date, COUNT(*) AS cnt
                FROM daily_bars
                GROUP BY code, date
                HAVING cnt > 1
            )
            """,
        )
        or 0
    )
    if duplicate_count:
        results.append(AuditResult("daily_bars_duplicates", "error", f"{duplicate_count} duplicate code/date keys"))
    else:
        results.append(AuditResult("daily_bars_duplicates", "ok", "no duplicate code/date keys"))

    null_count = int(
        scalar(
            conn,
            """
            SELECT COUNT(*) FROM daily_bars
            WHERE code IS NULL OR date IS NULL OR open IS NULL OR close IS NULL
               OR high IS NULL OR low IS NULL OR volume IS NULL OR amount IS NULL
            """,
        )
        or 0
    )
    if null_count:
        results.append(AuditResult("daily_bars_nulls", "error", f"{null_count} rows contain null required fields"))
    else:
        results.append(AuditResult("daily_bars_nulls", "ok", "required fields are non-null"))

    ohlc_error_count = int(
        scalar(
            conn,
            """
            SELECT COUNT(*) FROM daily_bars
            WHERE open <= 0 OR close <= 0 OR high <= 0 OR low <= 0
               OR high < low OR high < open OR high < close OR low > open OR low > close
               OR volume < 0 OR amount < 0
            """,
        )
        or 0
    )
    if ohlc_error_count:
        results.append(AuditResult("daily_bars_ohlc", "error", f"{ohlc_error_count} rows violate OHLC/volume constraints"))
    else:
        results.append(AuditResult("daily_bars_ohlc", "ok", "OHLC and volume constraints pass"))

    placeholders = ",".join("?" for _ in trading_days)
    rows_by_date = {
        row["date"]: int(row["rows"])
        for row in conn.execute(
            f"""
            SELECT date, COUNT(*) AS rows
            FROM daily_bars
            WHERE date IN ({placeholders})
            GROUP BY date
            """,
            tuple(trading_days),
        ).fetchall()
    }
    missing_days = [date_text for date_text in trading_days if rows_by_date.get(date_text, 0) == 0]
    thin_days = [
        {"date": date_text, "rows": rows_by_date.get(date_text, 0)}
        for date_text in trading_days
        if 0 < rows_by_date.get(date_text, 0) < min_daily_bars
    ]
    stats = {
        "expected_days": len(trading_days),
        "latest_expected": latest_expected,
        "latest_rows": rows_by_date.get(latest_expected, 0),
        "min_daily_bars": min_daily_bars,
        "missing_days": missing_days,
        "thin_days": thin_days,
    }
    if missing_days or thin_days:
        detail = f"missing_days={len(missing_days)}, thin_days={len(thin_days)}"
        results.append(AuditResult("daily_bars_coverage", "error", detail, stats))
    else:
        results.append(AuditResult("daily_bars_coverage", "ok", "all expected days meet row threshold", stats))

    return results


def audit_popularity_source(conn, expected_date: str, minimum_rows: int) -> AuditResult:
    rows = conn.execute(
        """
        SELECT source, COUNT(*) AS rows
        FROM popularity_rankings
        WHERE date=?
        GROUP BY source
        ORDER BY rows DESC
        """,
        (expected_date,),
    ).fetchall()
    source_rows = {row["source"]: int(row["rows"]) for row in rows}
    max_rows = max(source_rows.values(), default=0)
    stats = {"expected_date": expected_date, "source_rows": source_rows, "minimum_rows": minimum_rows}
    if max_rows < minimum_rows:
        return AuditResult("popularity_rankings_rows", "error", f"best source rows {max_rows} < required {minimum_rows}", stats)
    return AuditResult("popularity_rankings_rows", "ok", "at least one source has enough rows", stats)


def record_failed_issues(conn, results: list[AuditResult]) -> None:
    run_id = datetime.now().strftime("completeness-%Y%m%d-%H%M%S")
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    failed_results = [result for result in results if result.status == "error"]
    with conn:
        for result in failed_results:
            conn.execute(
                "INSERT INTO data_quality_issues(run_id, file, reason, created_at) VALUES (?, ?, ?, ?)",
                (run_id, result.name, result.detail, created_at),
            )


def print_results(results: list[AuditResult]) -> None:
    for result in results:
        marker = "OK" if result.status == "ok" else "FAIL"
        print(f"[{marker}] {result.name}: {result.detail}")
        if result.stats:
            print(f"       stats={json.dumps(result.stats, ensure_ascii=False, sort_keys=True)}")


def main() -> None:
    args = parse_args()
    socket.setdefaulttimeout(args.socket_timeout)

    start_date, end_date, trading_days, calendar_source = resolve_date_window(args)
    conn = connect(args.db)

    print("=" * 72)
    print("Quant data completeness audit")
    print(f"db={args.db}")
    print(f"window={start_date}..{end_date} trading_days={len(trading_days)} calendar={calendar_source}")
    print("=" * 72)

    results: list[AuditResult] = []
    results.extend(audit_daily_bars(conn, trading_days, args.min_daily_bars))
    results.append(audit_market_daily(conn, trading_days))
    results.append(audit_table_freshness(conn, "etf_daily", end_date, args.min_etf_rows))
    results.append(audit_table_freshness(conn, "popularity_rankings", end_date, args.min_popularity_rows))
    results.append(audit_popularity_source(conn, end_date, args.min_popularity_rows))
    results.append(audit_table_freshness(conn, "limit_up_pool", end_date, args.min_limit_up_rows))
    if args.strict_lhb:
        results.append(audit_table_freshness(conn, "lhb_records", end_date, 1))

    print_results(results)

    has_errors = any(result.status == "error" for result in results)
    payload = {
        "status": "error" if has_errors else "ok",
        "db": str(args.db),
        "start_date": start_date,
        "end_date": end_date,
        "trading_days": trading_days,
        "calendar_source": calendar_source,
        "results": [result.__dict__ for result in results],
    }

    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if has_errors and args.record_issues:
        record_failed_issues(conn, results)

    if has_errors:
        print("\n[ERROR] Data completeness audit failed.")
        sys.exit(1)

    print("\n[OK] Data completeness audit passed.")


if __name__ == "__main__":
    main()
