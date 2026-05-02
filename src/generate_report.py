#!/usr/bin/env python3
"""Generate reports from the SQLite research database."""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import sqlite3
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable

from quant_core import DEFAULT_DB_PATH, is_limit_down, is_limit_up
from quant_db import connect


DEFAULT_START_DATE = "2023-01-01"
DEFAULT_TOP_N = 20


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate quant research report from SQLite")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--report-dir", type=Path, default=Path("reports"))
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    parser.add_argument("--min-amount-e8", type=float, default=5.0)
    return parser.parse_args()


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
    head = "".join(f"<th>{html.escape(label)}</th>" for _key, label in columns)
    body_rows = []
    for row in selected:
        cells = []
        for key, _label in columns:
            value = row.get(key)
            text = fmt_pct(value) if key.endswith("_rate") else fmt_num(value)
            cells.append(f"<td>{html.escape(text)}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def markdown_table(rows: list[dict[str, object]], columns: list[tuple[str, str]], limit: int | None = None) -> str:
    selected = rows[:limit] if limit else rows
    if not selected:
        return "No data.\n"
    lines = ["| " + " | ".join(label for _key, label in columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in selected:
        values = []
        for key, _label in columns:
            value = row.get(key)
            values.append(fmt_pct(value) if key.endswith("_rate") else fmt_num(value))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines) + "\n"


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


def row_to_event(row: sqlite3.Row) -> dict[str, object]:
    gap = (row["next_open"] - row["close"]) / row["close"] * 100 if row["close"] else None
    otc = (row["next_close"] - row["next_open"]) / row["next_open"] * 100 if row["next_open"] else None
    return {
        "date": row["date"],
        "next_date": row["next_date"],
        "code": row["code"],
        "name": row["name"],
        "market": row["market"],
        "signal_pct": row["pct_chg"],
        "amount_e8": row["amount"] / 100_000_000,
        "turnover": row["turnover"],
        "gap_pct": gap,
        "open_to_close_pct": otc,
        "close_to_close_pct": row["next_pct_chg"],
        "next_is_limit_up": is_limit_up(float(row["next_pct_chg"]), row["market"], bool(row["is_st"])),
    }


def fetch_event_rows(conn: sqlite3.Connection, start_date: str) -> list[sqlite3.Row]:
    sql = """
    SELECT
        b.code, s.name, s.market, s.is_st, b.date, b.open, b.close, b.high, b.low,
        b.amount, b.pct_chg, b.turnover,
        nb.date AS next_date, nb.open AS next_open, nb.close AS next_close, nb.pct_chg AS next_pct_chg,
        LAG(b.pct_chg) OVER (PARTITION BY b.code ORDER BY b.date) AS prev_pct_chg,
        ROW_NUMBER() OVER (PARTITION BY b.date ORDER BY b.amount DESC) AS amount_rank
    FROM daily_bars b
    JOIN stocks s ON s.code = b.code
    JOIN daily_bars nb ON nb.code = b.code
        AND nb.date = (SELECT MIN(date) FROM daily_bars n2 WHERE n2.code = b.code AND n2.date > b.date)
    WHERE b.date >= ? AND s.eligible = 1
    ORDER BY b.date, b.code
    """
    return list(conn.execute(sql, (start_date,)))


def compute_streaks(conn: sqlite3.Connection, start_date: str) -> dict[tuple[str, str], int]:
    sql = """
    SELECT b.code, s.market, s.is_st, b.date, b.pct_chg
    FROM daily_bars b
    JOIN stocks s ON s.code = b.code
    WHERE s.eligible = 1 AND b.date >= date(?, '-40 day')
    ORDER BY b.code, b.date
    """
    result: dict[tuple[str, str], int] = {}
    current_code = None
    streak = 0
    for row in conn.execute(sql, (start_date,)):
        if row["code"] != current_code:
            current_code = row["code"]
            streak = 0
        if is_limit_up(float(row["pct_chg"]), row["market"], bool(row["is_st"])):
            streak += 1
        else:
            streak = 0
        if row["date"] >= start_date:
            result[(row["code"], row["date"])] = streak
    return result


def fetch_latest_candidates(conn: sqlite3.Connection, latest_date: str, top_n: int) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    sql = """
    SELECT b.date, b.code, s.name, s.market, s.is_st, b.pct_chg AS pct,
           b.amount / 100000000.0 AS amount_e8, b.turnover
    FROM daily_bars b
    JOIN stocks s ON s.code = b.code
    WHERE b.date = ? AND s.eligible = 1
    """
    rows = [dict(row) for row in conn.execute(sql, (latest_date,))]
    streaks = compute_streaks(conn, latest_date)
    for item in rows:
        streak = streaks.get((str(item["code"]), latest_date), 0)
        item["is_limit_up"] = is_limit_up(float(item["pct"]), str(item["market"]), bool(item["is_st"]))
        item["streak"] = streak
        amount_score = min(float(item["amount_e8"]) / 2, 30)
        turnover_score = min(float(item["turnover"]), 20)
        momentum_score = max(min(float(item["pct"]), 20), -20)
        limit_score = 20 if item["is_limit_up"] else 0
        streak_score = min(streak, 5) * 8
        item["hot_score"] = round(amount_score + turnover_score + momentum_score + limit_score + streak_score, 2)
        item.pop("is_st", None)

    latest_top_amount = sorted(rows, key=lambda item: float(item["amount_e8"]), reverse=True)[:top_n]
    latest_hot_candidates = sorted(rows, key=lambda item: float(item["hot_score"]), reverse=True)[:top_n]
    latest_limit_up = sorted([item for item in rows if item["is_limit_up"]], key=lambda item: float(item["amount_e8"]), reverse=True)
    return latest_top_amount, unique_by_code(latest_hot_candidates + latest_limit_up[:top_n])


def fetch_popularity_rows(conn: sqlite3.Connection, latest_date: str) -> list[dict[str, object]]:
    data_date = conn.execute("SELECT MAX(date) AS date FROM popularity_rankings WHERE date >= ?", (latest_date,)).fetchone()["date"]
    if not data_date:
        data_date = conn.execute("SELECT MAX(date) AS date FROM popularity_rankings WHERE date <= ?", (latest_date,)).fetchone()["date"]
    if not data_date:
        return []
    join_date = latest_date if data_date > latest_date else data_date
    sql = """
    SELECT p.date, p.source, p.rank,
           CASE WHEN substr(p.code, 1, 2) IN ('SH', 'SZ', 'BJ') THEN substr(p.code, 3, 6) ELSE p.code END AS code,
           p.name, p.score,
           b.pct_chg AS pct, b.amount / 100000000.0 AS amount_e8, b.turnover
    FROM popularity_rankings p
    LEFT JOIN daily_bars b ON b.code = CASE WHEN substr(p.code, 1, 2) IN ('SH', 'SZ', 'BJ') THEN substr(p.code, 3, 6) ELSE p.code END AND b.date = ?
    WHERE p.date = ?
    ORDER BY p.source, p.rank
    LIMIT 80
    """
    return [dict(row) for row in conn.execute(sql, (join_date, data_date))]


def fetch_limit_pool_rows(conn: sqlite3.Connection, latest_date: str) -> list[dict[str, object]]:
    data_date = conn.execute("SELECT MAX(date) AS date FROM limit_up_pool WHERE date >= ?", (latest_date,)).fetchone()["date"]
    if not data_date:
        data_date = conn.execute("SELECT MAX(date) AS date FROM limit_up_pool WHERE date <= ?", (latest_date,)).fetchone()["date"]
    if not data_date:
        return []
    join_date = latest_date if data_date > latest_date else data_date
    sql = """
    SELECT l.date, l.source, l.code, l.name, l.reason, l.streak,
           l.first_limit_time, l.last_limit_time, l.seal_amount,
           b.pct_chg AS pct, b.amount / 100000000.0 AS amount_e8
    FROM limit_up_pool l
    LEFT JOIN daily_bars b ON b.code = l.code AND b.date = ?
    WHERE l.date = ?
    ORDER BY COALESCE(l.streak, 0) DESC, COALESCE(l.seal_amount, 0) DESC
    LIMIT 80
    """
    return [dict(row) for row in conn.execute(sql, (join_date, data_date))]


def fetch_strategy_rows(conn: sqlite3.Connection) -> list[dict[str, object]]:
    sql = """
    SELECT strategy, trades, signal_days, win_rate, avg_return_pct,
           median_return_pct, total_batch_return_pct, max_drawdown_pct,
           avg_gap_pct, avg_hold_days, description
    FROM strategy_backtests
    ORDER BY strategy
    """
    return [dict(row) for row in conn.execute(sql)]


def build_report(args: argparse.Namespace) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    conn = connect(args.db)
    counts = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM stocks) AS stock_count,
            (SELECT COUNT(*) FROM stocks WHERE eligible = 1) AS eligible_stock_count,
            (SELECT COUNT(*) FROM daily_bars) AS bar_count,
            (SELECT MIN(date) FROM daily_bars) AS first_date,
            (SELECT MAX(date) FROM daily_bars) AS latest_date,
            (SELECT COUNT(*) FROM data_quality_issues) AS quality_issue_count,
            (SELECT COUNT(*) FROM popularity_rankings) AS popularity_count,
            (SELECT COUNT(*) FROM limit_up_pool) AS limit_pool_count,
            (SELECT COUNT(*) FROM strategy_backtests) AS strategy_backtest_count
        """
    ).fetchone()
    if not counts or not counts["latest_date"]:
        raise SystemExit(f"Database has no daily bars: {args.db}")
    latest_date = counts["latest_date"]

    rows = fetch_event_rows(conn, args.start_date)
    streaks = compute_streaks(conn, args.start_date)
    top_amount_events: list[dict[str, object]] = []
    limit_up_events: list[dict[str, object]] = []
    hot_limit_up_events: list[dict[str, object]] = []
    old_reversal_events: list[dict[str, object]] = []
    streak_events_by_level: dict[int, list[dict[str, object]]] = defaultdict(list)

    for row in rows:
        event = row_to_event(row)
        streak = streaks.get((row["code"], row["date"]), 0)
        event["streak"] = streak
        if int(row["amount_rank"]) <= args.top_n:
            top_amount_events.append(event)
        if is_limit_up(float(row["pct_chg"]), row["market"], bool(row["is_st"])):
            limit_up_events.append(event)
            if float(row["amount"]) / 100_000_000 >= args.min_amount_e8:
                hot_limit_up_events.append(event)
        if streak > 0:
            streak_events_by_level[min(streak, 6)].append(event)
        if row["prev_pct_chg"] is not None and float(row["prev_pct_chg"]) > 9 and float(row["amount"]) >= 3_000_000_000 and float(row["pct_chg"]) <= -11:
            old_reversal_events.append(event)

    latest_stats = conn.execute(
        """
        SELECT
            COUNT(*) AS eligible_count,
            SUM(CASE WHEN b.pct_chg > 0 THEN 1 ELSE 0 END) AS up_count,
            SUM(CASE WHEN b.pct_chg < 0 THEN 1 ELSE 0 END) AS down_count,
            SUM(b.amount) / 100000000.0 AS amount_e8
        FROM daily_bars b
        JOIN stocks s ON s.code = b.code
        WHERE b.date = ? AND s.eligible = 1
        """,
        (latest_date,),
    ).fetchone()

    latest_rows = conn.execute(
        """
        SELECT b.pct_chg, s.market, s.is_st
        FROM daily_bars b JOIN stocks s ON s.code = b.code
        WHERE b.date = ? AND s.eligible = 1
        """,
        (latest_date,),
    ).fetchall()
    latest_limit_up_count = sum(1 for row in latest_rows if is_limit_up(float(row["pct_chg"]), row["market"], bool(row["is_st"])))
    latest_limit_down_count = sum(1 for row in latest_rows if is_limit_down(float(row["pct_chg"]), row["market"], bool(row["is_st"])))
    eligible_count = int(latest_stats["eligible_count"] or 0)
    up_ratio = float(latest_stats["up_count"] or 0) / eligible_count if eligible_count else None
    emotion_score = None
    if eligible_count:
        raw_score = min(latest_limit_up_count / 100 * 40, 40) + (up_ratio or 0) * 40 - min(latest_limit_down_count / 50 * 20, 20) + 20
        emotion_score = max(0, min(100, raw_score))

    recent_emotion_rows = []
    recent_dates = [row["date"] for row in conn.execute("SELECT DISTINCT date FROM daily_bars WHERE date >= ? ORDER BY date DESC LIMIT 20", (args.start_date,)).fetchall()]
    for date in reversed(recent_dates):
        day_rows = conn.execute(
            """
            SELECT b.pct_chg, b.amount, s.market, s.is_st
            FROM daily_bars b JOIN stocks s ON s.code = b.code
            WHERE b.date = ? AND s.eligible = 1
            """,
            (date,),
        ).fetchall()
        day_count = len(day_rows)
        recent_emotion_rows.append(
            {
                "date": date,
                "eligible_count": day_count,
                "up_ratio_rate": sum(1 for row in day_rows if float(row["pct_chg"]) > 0) / day_count if day_count else None,
                "limit_up_count": sum(1 for row in day_rows if is_limit_up(float(row["pct_chg"]), row["market"], bool(row["is_st"]))),
                "limit_down_count": sum(1 for row in day_rows if is_limit_down(float(row["pct_chg"]), row["market"], bool(row["is_st"]))),
                "amount_e8": round(sum(float(row["amount"]) for row in day_rows) / 100_000_000, 2),
            }
        )

    streak_summary_rows = []
    for level in sorted(streak_events_by_level):
        summary = summarize_events(streak_events_by_level[level])
        streak_summary_rows.append(
            {
                "streak": ">=6" if level == 6 else str(level),
                "count": summary["count"],
                "next_limit_up_rate": summary["next_limit_up_rate"],
                "gap_pct": summary["gap"]["avg"],
                "open_to_close_pct": summary["open_to_close"]["avg"],
                "median_open_to_close_pct": summary["open_to_close"]["median"],
            }
        )

    latest_top_amount, latest_hot = fetch_latest_candidates(conn, latest_date, args.top_n)
    popularity_rows = fetch_popularity_rows(conn, latest_date)
    limit_pool_rows = fetch_limit_pool_rows(conn, latest_date)
    strategy_rows = fetch_strategy_rows(conn)

    summary: dict[str, object] = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "db": str(args.db),
        "start_date": args.start_date,
        "first_date": counts["first_date"],
        "latest_date": latest_date,
        "stock_count": counts["stock_count"],
        "eligible_stock_count": counts["eligible_stock_count"],
        "bar_count": counts["bar_count"],
        "quality_issue_count": counts["quality_issue_count"],
        "popularity_count": counts["popularity_count"],
        "limit_pool_count": counts["limit_pool_count"],
        "strategy_backtest_count": counts["strategy_backtest_count"],
        "latest_market": {
            "eligible_count": eligible_count,
            "up_ratio": up_ratio,
            "limit_up_count": latest_limit_up_count,
            "limit_down_count": latest_limit_down_count,
            "amount_e8": round(float(latest_stats["amount_e8"] or 0), 2),
            "emotion_score": emotion_score,
        },
        "event_summaries": {
            "top_amount_pool": summarize_events(top_amount_events),
            "limit_up_pool": summarize_events(limit_up_events),
            "hot_limit_up_pool": summarize_events(hot_limit_up_events),
            "old_reversal_rule": summarize_events(old_reversal_events),
        },
        "streak_summary": streak_summary_rows,
        "recent_emotion": recent_emotion_rows,
    }
    return summary, latest_top_amount, latest_hot, popularity_rows, limit_pool_rows, strategy_rows


def summary_cards(summary: dict[str, object]) -> str:
    latest = summary["latest_market"]
    events = summary["event_summaries"]

    def event_card(title: str, key: str) -> str:
        item = events[key]
        otc = item["open_to_close"]
        return (
            f"<div class='card'><h3>{html.escape(title)}</h3>"
            f"<p class='big'>{fmt_num(item['count'], 0)}</p>"
            f"<p>次日涨停率: {fmt_pct(item['next_limit_up_rate'])}</p>"
            f"<p>次日开收均值: {fmt_num(otc['avg'])}%</p>"
            f"<p>胜率: {fmt_pct(otc['win_rate'])}</p></div>"
        )

    return "".join(
        [
            f"<div class='card'><h3>最新日期</h3><p class='big'>{html.escape(str(summary['latest_date']))}</p><p>起始: {html.escape(str(summary['start_date']))}</p></div>",
            f"<div class='card'><h3>市场情绪</h3><p class='big'>{fmt_num(latest['emotion_score'])}</p><p>涨停: {fmt_num(latest['limit_up_count'])}，跌停: {fmt_num(latest['limit_down_count'])}</p></div>",
            event_card("量能龙头池", "top_amount_pool"),
            event_card("涨停池", "limit_up_pool"),
            event_card("热门涨停池", "hot_limit_up_pool"),
            event_card("旧逆转规则", "old_reversal_rule"),
        ]
    )


def render_html(summary: dict[str, object], latest_top_amount: list[dict[str, object]], latest_hot: list[dict[str, object]], popularity_rows: list[dict[str, object]], limit_pool_rows: list[dict[str, object]], strategy_rows: list[dict[str, object]]) -> str:
    candidate_columns = [("code", "代码"), ("name", "名称"), ("market", "市场"), ("pct", "涨跌幅%"), ("amount_e8", "成交额(亿)"), ("turnover", "换手率%"), ("is_limit_up", "涨停"), ("streak", "连板"), ("hot_score", "热度分")]
    popularity_columns = [("source", "来源"), ("rank", "排名"), ("code", "代码"), ("name", "名称"), ("score", "评分"), ("pct", "涨跌幅%"), ("amount_e8", "成交额(亿)"), ("turnover", "换手率%")]
    limit_columns = [("source", "来源"), ("code", "代码"), ("name", "名称"), ("reason", "涨停原因"), ("streak", "连板"), ("first_limit_time", "首次封板"), ("last_limit_time", "最后封板"), ("seal_amount", "封单额"), ("amount_e8", "成交额(亿)")]
    strategy_columns = [("strategy", "策略"), ("trades", "交易次数"), ("signal_days", "信号天数"), ("win_rate", "胜率"), ("avg_return_pct", "均值%"), ("median_return_pct", "中位数%"), ("total_batch_return_pct", "批次总收益%"), ("max_drawdown_pct", "最大回撤%"), ("avg_gap_pct", "均值跳空%"), ("avg_hold_days", "均值持仓天")]
    streak_columns = [("streak", "连板数"), ("count", "信号数"), ("next_limit_up_rate", "次日涨停率"), ("gap_pct", "均值跳空%"), ("open_to_close_pct", "均值开收%"), ("median_open_to_close_pct", "中位数开收%")]
    emotion_columns = [("date", "日期"), ("eligible_count", "股票数"), ("up_ratio_rate", "上涨比例"), ("limit_up_count", "涨停数"), ("limit_down_count", "跌停数"), ("amount_e8", "成交额(亿)")]
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
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>A股量化研究报告 {html.escape(str(summary['latest_date']))}</title><style>{style}</style></head>
<body>
  <h1>A股量化研究报告</h1>
  <p class="muted">生成时间: {html.escape(str(summary['generated_at']))}　数据库: {html.escape(str(summary['db']))}</p>
  <div class="note">数据源为 SQLite 数据库，通过 update_sqlite_data.py 每日更新。人气榜数据需要 AkShare 相关接口可用时才会显示。</div>
  <div class="grid">{summary_cards(summary)}</div>
  <h2>新高+量能策略回测</h2>{simple_table(strategy_rows, strategy_columns)}
  <h2>最新人气榜</h2>{simple_table(popularity_rows, popularity_columns, 80)}
  <h2>外部涨停池</h2>{simple_table(limit_pool_rows, limit_columns, 80)}
  <h2>热门候选股</h2>{simple_table(latest_hot, candidate_columns, 40)}
  <h2>量能龙头候选股</h2>{simple_table(latest_top_amount, candidate_columns, 40)}
  <h2>连板晋级统计</h2>{simple_table(summary['streak_summary'], streak_columns)}
  <h2>近期市场情绪</h2>{simple_table(summary['recent_emotion'], emotion_columns)}
  <h2>数据质量</h2><p>股票总数: {fmt_num(summary['stock_count'])}；可交易: {fmt_num(summary['eligible_stock_count'])}；日线数据: {fmt_num(summary['bar_count'])}；质量问题: {fmt_num(summary['quality_issue_count'])}；人气榜记录: {fmt_num(summary['popularity_count'])}；外部涨停池记录: {fmt_num(summary['limit_pool_count'])}；策略回测数: {fmt_num(summary['strategy_backtest_count'])}。</p>
</body></html>"""


def render_markdown(summary: dict[str, object], latest_top_amount: list[dict[str, object]], latest_hot: list[dict[str, object]], popularity_rows: list[dict[str, object]], limit_pool_rows: list[dict[str, object]], strategy_rows: list[dict[str, object]]) -> str:
    latest = summary["latest_market"]
    events = summary["event_summaries"]
    lines = [
        "# A股量化研究报告",
        "",
        f"生成时间: {summary['generated_at']}",
        f"数据库: `{summary['db']}`",
        f"数据范围: {summary['first_date']} 至 {summary['latest_date']}",
        f"信号起始日期: {summary['start_date']}",
        "",
        "## 最新市场概况",
        "",
        f"可交易股票数: {fmt_num(latest['eligible_count'])}",
        f"上涨比例: {fmt_pct(latest['up_ratio'])}",
        f"涨停/跌停: {fmt_num(latest['limit_up_count'])}/{fmt_num(latest['limit_down_count'])}",
        f"情绪分: {fmt_num(latest['emotion_score'])}",
        "",
        "## 事件统计摘要",
        "",
    ]
    for key, title in [("top_amount_pool", "量能龙头池"), ("limit_up_pool", "涨停池"), ("hot_limit_up_pool", "热门涨停池"), ("old_reversal_rule", "旧逆转规则")]:
        item = events[key]
        otc = item["open_to_close"]
        lines.append(f"- {title}: n={fmt_num(item['count'])}，次日涨停率={fmt_pct(item['next_limit_up_rate'])}，均值开收={fmt_num(otc['avg'])}%，胜率={fmt_pct(otc['win_rate'])}")
    candidate_columns = [("code", "代码"), ("name", "名称"), ("market", "市场"), ("pct", "涨跌幅%"), ("amount_e8", "成交额(亿)"), ("turnover", "换手率%"), ("is_limit_up", "涨停"), ("streak", "连板"), ("hot_score", "热度分")]
    lines.extend([
        "", "## 新高+量能策略回测", markdown_table(strategy_rows, [("strategy", "策略"), ("trades", "交易次数"), ("signal_days", "信号天数"), ("win_rate", "胜率"), ("avg_return_pct", "均值%"), ("median_return_pct", "中位数%"), ("total_batch_return_pct", "批次总收益%"), ("max_drawdown_pct", "最大回撤%"), ("avg_gap_pct", "均值跳空%"), ("avg_hold_days", "均值持仓天")]),
        "## 最新人气榜", markdown_table(popularity_rows, [("source", "来源"), ("rank", "排名"), ("code", "代码"), ("name", "名称"), ("score", "评分"), ("pct", "涨跌幅%"), ("amount_e8", "成交额(亿)")], 50),
        "## 外部涨停池", markdown_table(limit_pool_rows, [("source", "来源"), ("code", "代码"), ("name", "名称"), ("reason", "涨停原因"), ("streak", "连板"), ("seal_amount", "封单额")], 50),
        "## 热门候选股", markdown_table(latest_hot, candidate_columns, 40),
        "## 量能龙头候选股", markdown_table(latest_top_amount, candidate_columns, 40),
        "## 连板晋级统计", markdown_table(summary["streak_summary"], [("streak", "连板数"), ("count", "信号数"), ("next_limit_up_rate", "次日涨停率"), ("gap_pct", "均值跳空%"), ("open_to_close_pct", "均值开收%"), ("median_open_to_close_pct", "中位数开收%")]),
        "## 数据质量", f"股票总数: {summary['stock_count']}；可交易: {summary['eligible_stock_count']}；日线数据: {summary['bar_count']}；质量问题: {summary['quality_issue_count']}；人气榜记录: {summary['popularity_count']}；外部涨停池记录: {summary['limit_pool_count']}；策略回测数: {summary['strategy_backtest_count']}。",
    ])
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    summary, latest_top_amount, latest_hot, popularity_rows, limit_pool_rows, strategy_rows = build_report(args)
    latest_date = str(summary["latest_date"])
    dated_dir = args.report_dir / latest_date
    latest_dir = args.report_dir / "latest"
    for output_dir in (dated_dir, latest_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "report.html").write_text(render_html(summary, latest_top_amount, latest_hot, popularity_rows, limit_pool_rows, strategy_rows), encoding="utf-8")
        (output_dir / "report.md").write_text(render_markdown(summary, latest_top_amount, latest_hot, popularity_rows, limit_pool_rows, strategy_rows), encoding="utf-8")
        (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        write_csv(output_dir / "latest_top_amount.csv", latest_top_amount, ["date", "code", "name", "market", "pct", "amount_e8", "turnover", "is_limit_up", "streak", "hot_score"])
        write_csv(output_dir / "latest_hot_candidates.csv", latest_hot, ["date", "code", "name", "market", "pct", "amount_e8", "turnover", "is_limit_up", "streak", "hot_score"])
        write_csv(output_dir / "latest_popularity_rankings.csv", popularity_rows, ["date", "source", "rank", "code", "name", "score", "pct", "amount_e8", "turnover"])
        write_csv(output_dir / "latest_external_limit_up_pool.csv", limit_pool_rows, ["date", "source", "code", "name", "reason", "streak", "first_limit_time", "last_limit_time", "seal_amount", "pct", "amount_e8"])
        write_csv(output_dir / "new_high_volume_backtests.csv", strategy_rows, ["strategy", "trades", "signal_days", "win_rate", "avg_return_pct", "median_return_pct", "total_batch_return_pct", "max_drawdown_pct", "avg_gap_pct", "avg_hold_days", "description"])
    print(f"Report generated: {dated_dir / 'report.html'}")
    print(f"Latest copy: {latest_dir / 'report.html'}")


if __name__ == "__main__":
    main()
