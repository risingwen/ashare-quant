#!/usr/bin/env python3
"""Generate A-share sentiment and strategy research reports from daily CSV files.

The script intentionally uses only the Python standard library so it can run in
the current environment before pandas/akshare are installed.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


DEFAULT_DATA_DIR = Path("/data/akshare/Akshare/stock_data")
DEFAULT_START_DATE = "2023-01-01"
DEFAULT_TOP_N = 20


@dataclass(frozen=True)
class StockMeta:
    code: str
    name: str
    market: str
    is_st: bool
    eligible: bool


@dataclass(frozen=True)
class Bar:
    date: str
    open: float
    close: float
    high: float
    low: float
    volume: float
    amount: float
    amplitude: float
    pct: float
    change: float
    turnover: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate quant research report from AkShare CSV files")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--report-dir", type=Path, default=Path("reports"))
    parser.add_argument("--start-date", default=DEFAULT_START_DATE, help="Inclusive signal start date, e.g. 2023-01-01")
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N, help="Daily top-N amount pool size")
    parser.add_argument("--min-amount-e8", type=float, default=5.0, help="Minimum amount in 100M CNY for hot limit-up pool")
    return parser.parse_args()


def to_float(value: str | None) -> float | None:
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    try:
        result = float(value)
    except ValueError:
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def normalize_date(value: str) -> str:
    value = value.strip()
    if len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return value


def market_of(code: str) -> str:
    if code.startswith(("300", "301")):
        return "ChiNext"
    if code.startswith("688"):
        return "STAR"
    if code.startswith(("8", "4", "920")):
        return "BSE"
    if code.startswith(("000", "001", "002", "003", "600", "601", "603", "605")):
        return "Mainboard"
    return "Other"


def is_st_name(name: str) -> bool:
    upper = name.upper()
    return "ST" in upper or "PT" in upper or "退" in name


def parse_meta(path: Path) -> StockMeta | None:
    stem = path.name.removesuffix("_daily.csv")
    parts = stem.split("_", 1)
    if len(parts) != 2:
        return None
    code, name = parts
    market = market_of(code)
    is_st = is_st_name(name)
    eligible = market in {"Mainboard", "ChiNext", "STAR"} and not is_st
    return StockMeta(code=code, name=name, market=market, is_st=is_st, eligible=eligible)


def limit_threshold(meta: StockMeta) -> float:
    if meta.is_st:
        return 4.8
    if meta.market in {"ChiNext", "STAR"}:
        return 19.5
    if meta.market == "BSE":
        return 29.5
    return 9.8


def is_limit_up(pct: float, meta: StockMeta) -> bool:
    return pct >= limit_threshold(meta)


def is_limit_down(pct: float, meta: StockMeta) -> bool:
    return pct <= -limit_threshold(meta)


def read_bars(path: Path) -> tuple[list[Bar], str | None]:
    required = {"日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额", "振幅", "涨跌幅", "涨跌额", "换手率"}
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            fieldnames = set(reader.fieldnames or [])
            if not required.issubset(fieldnames):
                return [], "missing required columns"

            bars: list[Bar] = []
            for row in reader:
                date = normalize_date(row.get("日期", ""))
                values = {
                    "open": to_float(row.get("开盘")),
                    "close": to_float(row.get("收盘")),
                    "high": to_float(row.get("最高")),
                    "low": to_float(row.get("最低")),
                    "volume": to_float(row.get("成交量")),
                    "amount": to_float(row.get("成交额")),
                    "amplitude": to_float(row.get("振幅")),
                    "pct": to_float(row.get("涨跌幅")),
                    "change": to_float(row.get("涨跌额")),
                    "turnover": to_float(row.get("换手率")),
                }
                if not date or any(value is None for value in values.values()):
                    continue
                bars.append(Bar(date=date, **values))  # type: ignore[arg-type]
    except (OSError, UnicodeDecodeError) as exc:
        return [], f"read error: {exc}"

    bars.sort(key=lambda item: item.date)
    if not bars:
        return [], "empty after parsing"
    return bars, None


def mean(values: Iterable[float]) -> float | None:
    values = list(values)
    return statistics.fmean(values) if values else None


def stat_summary(values: Iterable[float]) -> dict[str, float | int | None]:
    data = [value for value in values if value is not None and not math.isnan(value)]
    if not data:
        return {"n": 0, "win_rate": None, "avg": None, "median": None, "min": None, "max": None}
    return {
        "n": len(data),
        "win_rate": sum(1 for value in data if value > 0) / len(data),
        "avg": statistics.fmean(data),
        "median": statistics.median(data),
        "min": min(data),
        "max": max(data),
    }


def event_observation(meta: StockMeta, bar: Bar, next_bar: Bar, streak: int) -> dict[str, object]:
    gap = (next_bar.open - bar.close) / bar.close * 100 if bar.close else None
    open_to_close = (next_bar.close - next_bar.open) / next_bar.open * 100 if next_bar.open else None
    close_to_close = next_bar.pct
    return {
        "date": bar.date,
        "next_date": next_bar.date,
        "code": meta.code,
        "name": meta.name,
        "market": meta.market,
        "streak": streak,
        "signal_pct": bar.pct,
        "amount_e8": bar.amount / 100_000_000,
        "turnover": bar.turnover,
        "gap_pct": gap,
        "open_to_close_pct": open_to_close,
        "close_to_close_pct": close_to_close,
        "next_is_limit_up": is_limit_up(next_bar.pct, meta),
    }


def push_top_amount(pool: dict[str, list[dict[str, object]]], date: str, obs: dict[str, object], top_n: int) -> None:
    bucket = pool[date]
    bucket.append(obs)
    bucket.sort(key=lambda item: float(item["amount_e8"]), reverse=True)
    if len(bucket) > top_n:
        del bucket[top_n:]


def summarize_events(events: list[dict[str, object]]) -> dict[str, object]:
    otc = [float(item["open_to_close_pct"]) for item in events if item.get("open_to_close_pct") is not None]
    gap = [float(item["gap_pct"]) for item in events if item.get("gap_pct") is not None]
    ctc = [float(item["close_to_close_pct"]) for item in events if item.get("close_to_close_pct") is not None]
    next_lu = [bool(item["next_is_limit_up"]) for item in events if "next_is_limit_up" in item]
    return {
        "count": len(events),
        "open_to_close": stat_summary(otc),
        "gap": stat_summary(gap),
        "close_to_close": stat_summary(ctc),
        "next_limit_up_rate": (sum(next_lu) / len(next_lu)) if next_lu else None,
    }


def fmt_num(value: object, digits: int = 2) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return "-"
        return f"{value:.{digits}f}"
    return str(value)


def fmt_pct(value: object, digits: int = 2) -> str:
    if value is None:
        return "-"
    if isinstance(value, (int, float)):
        return f"{value * 100:.{digits}f}%"
    return str(value)


def simple_table(rows: list[dict[str, object]], columns: list[tuple[str, str]], limit: int | None = None) -> str:
    selected = rows[:limit] if limit else rows
    if not selected:
        return "<p>No data.</p>"
    head = "".join(f"<th>{html.escape(label)}</th>" for key, label in columns)
    body_rows = []
    for row in selected:
        cells = []
        for key, _label in columns:
            value = row.get(key)
            if key.endswith("_pct") or key in {"signal_pct"}:
                text = fmt_num(value)
            elif key.endswith("_rate"):
                text = fmt_pct(value)
            else:
                text = fmt_num(value)
            cells.append(f"<td>{html.escape(text)}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def write_csv(path: Path, rows: list[dict[str, object]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def unique_by_code(rows: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[str] = set()
    result: list[dict[str, object]] = []
    for row in rows:
        code = str(row.get("code", ""))
        if code in seen:
            continue
        seen.add(code)
        result.append(row)
    return result


def markdown_table(rows: list[dict[str, object]], columns: list[tuple[str, str]], limit: int | None = None) -> str:
    selected = rows[:limit] if limit else rows
    if not selected:
        return "No data.\n"
    lines = ["| " + " | ".join(label for _key, label in columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in selected:
        values = []
        for key, _label in columns:
            value = row.get(key)
            if key.endswith("_rate"):
                values.append(fmt_pct(value))
            else:
                values.append(fmt_num(value))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines) + "\n"


def build_report(args: argparse.Namespace) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    files = sorted(args.data_dir.glob("*_daily.csv"))
    if not files:
        raise SystemExit(f"No *_daily.csv files found in {args.data_dir}")

    date_stats: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    invalid_files: list[dict[str, str]] = []
    valid_files = 0
    total_rows = 0
    global_first_date: str | None = None
    global_latest_date: str | None = None

    limit_up_events: list[dict[str, object]] = []
    hot_limit_up_events: list[dict[str, object]] = []
    old_reversal_events: list[dict[str, object]] = []
    streak_events_by_level: dict[int, list[dict[str, object]]] = defaultdict(list)
    top_amount_by_date: dict[str, list[dict[str, object]]] = defaultdict(list)
    latest_records: list[dict[str, object]] = []

    for path in files:
        meta = parse_meta(path)
        if meta is None:
            invalid_files.append({"file": path.name, "reason": "bad filename"})
            continue

        bars, error = read_bars(path)
        if error:
            invalid_files.append({"file": path.name, "reason": error})
            continue

        valid_files += 1
        total_rows += len(bars)
        first_date = bars[0].date
        last_date = bars[-1].date
        if global_first_date is None or first_date < global_first_date:
            global_first_date = first_date
        if global_latest_date is None or last_date > global_latest_date:
            global_latest_date = last_date

        streaks: list[int] = []
        streak = 0
        for bar in bars:
            if meta.eligible and is_limit_up(bar.pct, meta):
                streak += 1
            else:
                streak = 0
            streaks.append(streak)

            if bar.date < args.start_date:
                continue
            stats = date_stats[bar.date]
            stats["all_count"] += 1
            stats["amount_e8"] += bar.amount / 100_000_000
            if meta.eligible:
                stats["eligible_count"] += 1
                if bar.pct > 0:
                    stats["up_count"] += 1
                if bar.pct < 0:
                    stats["down_count"] += 1
                if is_limit_up(bar.pct, meta):
                    stats["limit_up_count"] += 1
                if is_limit_down(bar.pct, meta):
                    stats["limit_down_count"] += 1

        for idx in range(len(bars) - 1):
            bar = bars[idx]
            next_bar = bars[idx + 1]
            if bar.date < args.start_date:
                continue
            obs = event_observation(meta, bar, next_bar, streaks[idx])

            if meta.eligible:
                push_top_amount(top_amount_by_date, bar.date, obs, args.top_n)

                if is_limit_up(bar.pct, meta):
                    limit_up_events.append(obs)
                    if bar.amount / 100_000_000 >= args.min_amount_e8:
                        hot_limit_up_events.append(obs)

                if streaks[idx] > 0:
                    level = min(streaks[idx], 6)
                    streak_events_by_level[level].append(obs)

            if idx >= 1 and bars[idx - 1].pct > 9 and bar.amount >= 3_000_000_000 and bar.pct <= -11:
                old_reversal_events.append(obs)

        latest_bar = bars[-1]
        latest_records.append(
            {
                "date": latest_bar.date,
                "code": meta.code,
                "name": meta.name,
                "market": meta.market,
                "is_st": meta.is_st,
                "eligible": meta.eligible,
                "pct": latest_bar.pct,
                "amount_e8": latest_bar.amount / 100_000_000,
                "turnover": latest_bar.turnover,
                "is_limit_up": meta.eligible and is_limit_up(latest_bar.pct, meta),
                "streak": streaks[-1],
            }
        )

    if global_latest_date is None:
        raise SystemExit("No valid stock data parsed")

    top_amount_events = []
    for date in sorted(top_amount_by_date):
        top_amount_events.extend(top_amount_by_date[date])

    latest_universe = [item for item in latest_records if item["date"] == global_latest_date and item["eligible"]]
    for item in latest_universe:
        amount_score = min(float(item["amount_e8"]) / 2, 30)
        turnover_score = min(float(item["turnover"]), 20)
        momentum_score = max(min(float(item["pct"]), 20), -20)
        limit_score = 20 if item["is_limit_up"] else 0
        streak_score = min(int(item["streak"]), 5) * 8
        item["hot_score"] = round(amount_score + turnover_score + momentum_score + limit_score + streak_score, 2)

    latest_top_amount = sorted(latest_universe, key=lambda item: float(item["amount_e8"]), reverse=True)[: args.top_n]
    latest_hot_candidates = sorted(latest_universe, key=lambda item: float(item["hot_score"]), reverse=True)[: args.top_n]
    latest_limit_up = sorted([item for item in latest_universe if item["is_limit_up"]], key=lambda item: float(item["amount_e8"]), reverse=True)

    latest_stats = date_stats.get(global_latest_date, {})
    eligible_count = latest_stats.get("eligible_count", 0)
    up_ratio = latest_stats.get("up_count", 0) / eligible_count if eligible_count else None
    limit_up_count = latest_stats.get("limit_up_count", 0)
    limit_down_count = latest_stats.get("limit_down_count", 0)
    emotion_score = None
    if eligible_count:
        raw_score = min(limit_up_count / 100 * 40, 40) + (up_ratio or 0) * 40 - min(limit_down_count / 50 * 20, 20) + 20
        emotion_score = max(0, min(100, raw_score))

    recent_emotion_rows: list[dict[str, object]] = []
    for date in sorted(date_stats)[-20:]:
        stats = date_stats[date]
        eligible = stats.get("eligible_count", 0)
        recent_emotion_rows.append(
            {
                "date": date,
                "eligible_count": int(eligible),
                "up_ratio_rate": stats.get("up_count", 0) / eligible if eligible else None,
                "limit_up_count": int(stats.get("limit_up_count", 0)),
                "limit_down_count": int(stats.get("limit_down_count", 0)),
                "amount_e8": round(stats.get("amount_e8", 0), 2),
            }
        )

    streak_summary_rows: list[dict[str, object]] = []
    for level in sorted(streak_events_by_level):
        events = streak_events_by_level[level]
        summary = summarize_events(events)
        streak_summary_rows.append(
            {
                "streak": f">=6" if level == 6 else str(level),
                "count": summary["count"],
                "next_limit_up_rate": summary["next_limit_up_rate"],
                "gap_pct": summary["gap"]["avg"],
                "open_to_close_pct": summary["open_to_close"]["avg"],
                "median_open_to_close_pct": summary["open_to_close"]["median"],
            }
        )

    summary: dict[str, object] = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_dir": str(args.data_dir),
        "start_date": args.start_date,
        "first_date": global_first_date,
        "latest_date": global_latest_date,
        "csv_files": len(files),
        "valid_files": valid_files,
        "invalid_files": len(invalid_files),
        "total_rows": total_rows,
        "latest_market": {
            "eligible_count": int(eligible_count),
            "up_ratio": up_ratio,
            "limit_up_count": int(limit_up_count),
            "limit_down_count": int(limit_down_count),
            "amount_e8": round(latest_stats.get("amount_e8", 0), 2),
            "emotion_score": emotion_score,
        },
        "event_summaries": {
            "top_amount_pool": summarize_events(top_amount_events),
            "limit_up_pool": summarize_events(limit_up_events),
            "hot_limit_up_pool": summarize_events(hot_limit_up_events),
            "old_reversal_rule": summarize_events(old_reversal_events),
        },
        "streak_summary": streak_summary_rows,
        "invalid_examples": invalid_files[:20],
        "recent_emotion": recent_emotion_rows,
    }
    latest_hot = unique_by_code(latest_hot_candidates + latest_limit_up[: args.top_n])
    return summary, latest_top_amount, latest_hot


def summary_cards(summary: dict[str, object]) -> str:
    latest = summary["latest_market"]
    events = summary["event_summaries"]

    def event_card(title: str, key: str) -> str:
        item = events[key]
        otc = item["open_to_close"]
        return (
            f"<div class='card'><h3>{html.escape(title)}</h3>"
            f"<p class='big'>{fmt_num(item['count'], 0)}</p>"
            f"<p>Next limit-up: {fmt_pct(item['next_limit_up_rate'])}</p>"
            f"<p>Next open-close avg: {fmt_num(otc['avg'])}%</p>"
            f"<p>Win rate: {fmt_pct(otc['win_rate'])}</p></div>"
        )

    return "".join(
        [
            f"<div class='card'><h3>Latest date</h3><p class='big'>{html.escape(str(summary['latest_date']))}</p><p>Start: {html.escape(str(summary['start_date']))}</p></div>",
            f"<div class='card'><h3>Market emotion</h3><p class='big'>{fmt_num(latest['emotion_score'])}</p><p>Limit up: {fmt_num(latest['limit_up_count'])}, limit down: {fmt_num(latest['limit_down_count'])}</p></div>",
            event_card("Amount top pool", "top_amount_pool"),
            event_card("Limit-up pool", "limit_up_pool"),
            event_card("Hot limit-up pool", "hot_limit_up_pool"),
            event_card("Old reversal rule", "old_reversal_rule"),
        ]
    )


def render_html(summary: dict[str, object], latest_top_amount: list[dict[str, object]], latest_hot: list[dict[str, object]]) -> str:
    candidate_columns = [
        ("code", "Code"),
        ("name", "Name"),
        ("market", "Market"),
        ("pct", "Change %"),
        ("amount_e8", "Amount 100M"),
        ("turnover", "Turnover %"),
        ("is_limit_up", "Limit-up"),
        ("streak", "Streak"),
        ("hot_score", "Hot score"),
    ]
    streak_columns = [
        ("streak", "Streak"),
        ("count", "Signals"),
        ("next_limit_up_rate", "Next LU rate"),
        ("gap_pct", "Avg gap %"),
        ("open_to_close_pct", "Avg open-close %"),
        ("median_open_to_close_pct", "Median open-close %"),
    ]
    emotion_columns = [
        ("date", "Date"),
        ("eligible_count", "Stocks"),
        ("up_ratio_rate", "Up ratio"),
        ("limit_up_count", "Limit up"),
        ("limit_down_count", "Limit down"),
        ("amount_e8", "Amount 100M"),
    ]
    invalid_columns = [("file", "File"), ("reason", "Reason")]

    style = """
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #172033; background: #f6f7fb; }
    h1, h2, h3 { color: #0f172a; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin: 18px 0 28px; }
    .card { background: white; border: 1px solid #e2e8f0; border-radius: 14px; padding: 16px; box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05); }
    .big { font-size: 28px; font-weight: 700; margin: 8px 0; }
    table { width: 100%; border-collapse: collapse; background: white; border-radius: 12px; overflow: hidden; margin: 12px 0 28px; }
    th, td { padding: 8px 10px; border-bottom: 1px solid #e5e7eb; text-align: right; font-size: 13px; }
    th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) { text-align: left; }
    th { background: #e9eef8; color: #0f172a; }
    .note { background: #fff7ed; border: 1px solid #fed7aa; padding: 12px 14px; border-radius: 10px; }
    .muted { color: #64748b; }
    """
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>A-share Quant Research Report {html.escape(str(summary['latest_date']))}</title>
  <style>{style}</style>
</head>
<body>
  <h1>A-share Quant Research Report</h1>
  <p class="muted">Generated at {html.escape(str(summary['generated_at']))}. Data source: {html.escape(str(summary['data_dir']))}</p>
  <div class="note">This report is for research only. The next-day return statistics use next open to next close when possible. They do not include fees, slippage, limit-up execution failure, or intraday decision constraints.</div>
  <div class="grid">{summary_cards(summary)}</div>

  <h2>Latest Hot Candidates</h2>
  {simple_table(latest_hot, candidate_columns, 30)}

  <h2>Latest Amount Top Pool</h2>
  {simple_table(latest_top_amount, candidate_columns, 30)}

  <h2>Limit-up Streak Advancement</h2>
  {simple_table(summary['streak_summary'], streak_columns)}

  <h2>Recent Market Emotion</h2>
  {simple_table(summary['recent_emotion'], emotion_columns)}

  <h2>Data Quality</h2>
  <p>CSV files: {fmt_num(summary['csv_files'])}; valid files: {fmt_num(summary['valid_files'])}; invalid files: {fmt_num(summary['invalid_files'])}; parsed rows: {fmt_num(summary['total_rows'])}.</p>
  {simple_table(summary['invalid_examples'], invalid_columns, 20)}
</body>
</html>
"""


def render_markdown(summary: dict[str, object], latest_top_amount: list[dict[str, object]], latest_hot: list[dict[str, object]]) -> str:
    latest = summary["latest_market"]
    event_summaries = summary["event_summaries"]
    lines = [
        "# A-share Quant Research Report",
        "",
        f"Generated at: {summary['generated_at']}",
        f"Data source: `{summary['data_dir']}`",
        f"Date range: {summary['first_date']} to {summary['latest_date']}",
        f"Signal start date: {summary['start_date']}",
        "",
        "## Latest Market",
        "",
        f"Eligible stocks: {fmt_num(latest['eligible_count'])}",
        f"Up ratio: {fmt_pct(latest['up_ratio'])}",
        f"Limit up/down: {fmt_num(latest['limit_up_count'])}/{fmt_num(latest['limit_down_count'])}",
        f"Emotion score: {fmt_num(latest['emotion_score'])}",
        "",
        "## Event Summaries",
        "",
    ]
    for key, title in [
        ("top_amount_pool", "Daily amount top pool"),
        ("limit_up_pool", "Limit-up pool"),
        ("hot_limit_up_pool", "Hot limit-up pool"),
        ("old_reversal_rule", "Old reversal rule"),
    ]:
        item = event_summaries[key]
        otc = item["open_to_close"]
        lines.extend(
            [
                f"- {title}: n={fmt_num(item['count'])}, next limit-up={fmt_pct(item['next_limit_up_rate'])}, avg open-close={fmt_num(otc['avg'])}%, win={fmt_pct(otc['win_rate'])}",
            ]
        )
    lines.extend(
        [
            "",
            "## Latest Hot Candidates",
            markdown_table(
                latest_hot,
                [("code", "Code"), ("name", "Name"), ("market", "Market"), ("pct", "Change %"), ("amount_e8", "Amount 100M"), ("turnover", "Turnover %"), ("is_limit_up", "Limit-up"), ("streak", "Streak"), ("hot_score", "Hot score")],
                30,
            ),
            "## Latest Amount Top Pool",
            markdown_table(
                latest_top_amount,
                [("code", "Code"), ("name", "Name"), ("market", "Market"), ("pct", "Change %"), ("amount_e8", "Amount 100M"), ("turnover", "Turnover %"), ("is_limit_up", "Limit-up"), ("streak", "Streak"), ("hot_score", "Hot score")],
                30,
            ),
            "## Limit-up Streak Advancement",
            markdown_table(
                summary["streak_summary"],
                [("streak", "Streak"), ("count", "Signals"), ("next_limit_up_rate", "Next LU rate"), ("gap_pct", "Avg gap %"), ("open_to_close_pct", "Avg open-close %"), ("median_open_to_close_pct", "Median open-close %")],
            ),
            "## Data Quality",
            f"CSV files: {summary['csv_files']}; valid files: {summary['valid_files']}; invalid files: {summary['invalid_files']}; parsed rows: {summary['total_rows']}.",
            "",
            "Research only. No fees, slippage, or execution failure included.",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    summary, latest_top_amount, latest_hot = build_report(args)
    latest_date = str(summary["latest_date"])

    dated_dir = args.report_dir / latest_date
    latest_dir = args.report_dir / "latest"
    for output_dir in (dated_dir, latest_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "report.html").write_text(render_html(summary, latest_top_amount, latest_hot), encoding="utf-8")
        (output_dir / "report.md").write_text(render_markdown(summary, latest_top_amount, latest_hot), encoding="utf-8")
        (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        write_csv(
            output_dir / "latest_top_amount.csv",
            latest_top_amount,
            ["date", "code", "name", "market", "pct", "amount_e8", "turnover", "is_limit_up", "streak", "hot_score"],
        )
        write_csv(
            output_dir / "latest_hot_candidates.csv",
            latest_hot,
            ["date", "code", "name", "market", "pct", "amount_e8", "turnover", "is_limit_up", "streak", "hot_score"],
        )

    print(f"Report generated: {dated_dir / 'report.html'}")
    print(f"Latest copy: {latest_dir / 'report.html'}")


if __name__ == "__main__":
    main()
