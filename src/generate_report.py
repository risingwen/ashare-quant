#!/usr/bin/env python3
"""Generate reports from the SQLite research database."""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import shutil
import sqlite3
import statistics
import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable

from quant_core import DEFAULT_DB_PATH, is_limit_down, is_limit_up
from quant_db import connect
from reporting.formatters import fmt_num, fmt_pct, format_table_cell
from reporting.theme import BASE_STYLE as _BASE_STYLE
from reporting.theme import navbar as _NAVBAR


DEFAULT_START_DATE = "2025-01-01"
DEFAULT_TOP_N = 20
STATIC_ASSETS_DIR = Path(__file__).resolve().parent.parent / "deploy" / "static"


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


def _git_output(args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=Path(__file__).resolve().parent.parent,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        return result.stdout.strip()
    except Exception:
        return None


def get_git_info() -> dict[str, object]:
    commit = _git_output(["rev-parse", "HEAD"])
    short_commit = _git_output(["rev-parse", "--short", "HEAD"])
    branch = _git_output(["rev-parse", "--abbrev-ref", "HEAD"])
    commit_time = _git_output(["log", "-1", "--format=%ci"])
    subject = _git_output(["log", "-1", "--format=%s"])
    dirty = bool(_git_output([
        "status", "--short", "--", ".",
        ":(exclude)data", ":(exclude)reports", ":(exclude)logs",
    ]))
    return {
        "commit": commit,
        "short_commit": short_commit,
        "branch": branch,
        "commit_time": commit_time,
        "subject": subject,
        "dirty": dirty,
    }


def calc_day_gap(latest_date: str, data_date: str | None) -> int | None:
    if not latest_date or not data_date:
        return None
    try:
        latest_dt = datetime.strptime(str(latest_date), "%Y-%m-%d")
        data_dt = datetime.strptime(str(data_date), "%Y-%m-%d")
    except ValueError:
        return None
    return (latest_dt - data_dt).days


def build_data_status(latest_date: str, module_latest_dates: dict[str, str | None]) -> list[dict[str, object]]:
    labels = {
        "daily_bars": "日线行情",
        "market_daily": "市场温度",
        "limit_up_pool": "涨停池",
        "popularity_rankings": "人气热榜",
        "lhb_records": "龙虎榜",
        "lhb_seats": "龙虎榜席位",
        "etf_daily": "ETF雷达",
        "screen_results": "选股信号",
        "strategy_backtests": "策略回测",
    }
    status_rows: list[dict[str, object]] = []
    for key, label in labels.items():
        data_date = module_latest_dates.get(key)
        gap_days = calc_day_gap(latest_date, data_date)
        if data_date is None:
            status = "missing"
            status_label = "缺失"
        elif gap_days is None:
            status = "unknown"
            status_label = "未知"
        elif gap_days <= 0:
            status = "fresh"
            status_label = "已更新"
        elif gap_days <= 3:
            status = "lagging"
            status_label = f"落后{gap_days}天"
        else:
            status = "stale"
            status_label = f"严重落后{gap_days}天"
        status_rows.append({
            "key": key,
            "label": label,
            "latest_date": data_date,
            "gap_days": gap_days,
            "status": status,
            "status_label": status_label,
        })
    return status_rows


def safe_scalar(conn: sqlite3.Connection, sql: str) -> str | None:
    try:
        row = conn.execute(sql).fetchone()
    except sqlite3.OperationalError:
        return None
    if not row:
        return None
    return row[0]


def simple_table(rows: list[dict[str, object]], columns: list[tuple[str, str]], limit: int | None = None) -> str:
    selected = rows[:limit] if limit else rows
    if not selected:
        return "<p class='empty'>暂无数据</p>"
    head = "".join(f"<th>{html.escape(label)}</th>" for _key, label in columns)
    body_rows = []
    for row in selected:
        cells = []
        for key, _label in columns:
            text = format_table_cell(key, row.get(key))
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


def fetch_screen_results(conn: sqlite3.Connection, latest_date: str) -> list[dict[str, object]]:
    """Fetch latest screener results for report."""
    import json as _json
    # 表不存在时静默返回空
    try:
        rows = conn.execute(
            """
            SELECT r.rule_id, r.date, r.code, r.name, r.detail
            FROM screen_results r
            WHERE r.date = (
                SELECT MAX(date) FROM screen_results WHERE date <= ?
            )
            ORDER BY r.rule_id, r.code
            """,
            (latest_date,),
        ).fetchall()
    except Exception:
        return []
    result = []
    for row in rows:
        d = dict(row)
        try:
            d["detail"] = _json.loads(d["detail"] or "{}")
        except Exception:
            d["detail"] = {}
        result.append(d)
    return result


def fetch_lhb_rows(conn: sqlite3.Connection, latest_date: str, days: int = 30) -> list[dict[str, object]]:
    """Fetch recent LHB records with seat details joined.

    Returns records for the last `days` trading days up to latest_date,
    plus seat-level breakdown per (date, code).
    """
    data_date = conn.execute("SELECT MAX(date) AS date FROM lhb_records WHERE date <= ?", (latest_date,)).fetchone()["date"]
    if not data_date:
        return []
    # Find the Nth-previous trading date from data_date
    all_dates = [r[0] for r in conn.execute(
        "SELECT DISTINCT date FROM lhb_records WHERE date <= ? ORDER BY date DESC LIMIT ?",
        (data_date, days),
    )]
    cutoff = all_dates[-1] if all_dates else data_date
    sql = """
    SELECT r.date, r.code, r.name, r.reason,
           r.close, r.pct_chg, r.lhb_net_buy, r.lhb_buy, r.lhb_sell,
           r.lhb_amount, r.market_amount, r.net_buy_ratio, r.amount_ratio,
           r.turnover, r.float_mv,
           r.after_1d, r.after_2d, r.after_5d, r.after_10d
    FROM lhb_records r
    WHERE r.date >= ?
    ORDER BY r.date DESC, r.lhb_net_buy DESC
    """
    rows = [dict(row) for row in conn.execute(sql, (cutoff,))]
    seats: dict[tuple, list] = {}
    for row in conn.execute(
        "SELECT date, code, direction, seat_name, net_amount, seat_type FROM lhb_seats WHERE date >= ? ORDER BY date DESC, ABS(net_amount) DESC",
        (cutoff,),
    ):
        key = (row["date"], row["code"])
        if key not in seats:
            seats[key] = []
        if len(seats[key]) < 10:
            seats[key].append(dict(row))
    for row in rows:
        row["seats"] = seats.get((row["date"], row["code"]), [])
    return rows


def fetch_lhb_seat_stats(conn: sqlite3.Connection, latest_date: str, days: int = 30) -> list[dict]:
    """按营业部统计近 days 个交易日的净买入金额排行，并附带每个营业部的明细记录。"""
    data_date = conn.execute("SELECT MAX(date) AS date FROM lhb_seats WHERE date <= ?", (latest_date,)).fetchone()["date"]
    if not data_date:
        return []
    all_dates = [r[0] for r in conn.execute(
        "SELECT DISTINCT date FROM lhb_seats WHERE date <= ? ORDER BY date DESC LIMIT ?",
        (data_date, days),
    )]
    cutoff = all_dates[-1] if all_dates else data_date
    rows = conn.execute("""
        SELECT seat_name,
               COUNT(DISTINCT date || code) AS appearances,
               SUM(CASE WHEN direction='买入' THEN net_amount ELSE 0 END) AS total_buy,
               SUM(CASE WHEN direction='卖出' THEN ABS(net_amount) ELSE 0 END) AS total_sell,
               SUM(net_amount) AS total_net
        FROM lhb_seats
        WHERE date >= ?
        GROUP BY seat_name
        ORDER BY total_net DESC
    """, (cutoff,)).fetchall()
    stats = [dict(r) for r in rows]

    # 为每个营业部附上近期涉及的股票明细（最多 50 条，按日期倒序）
    detail_rows = conn.execute("""
        SELECT s.seat_name, s.date, s.code, r.name, s.direction, s.net_amount, r.pct_chg, r.after_1d, r.after_5d
        FROM lhb_seats s
        LEFT JOIN lhb_records r ON r.date = s.date AND r.code = s.code
        WHERE s.date >= ?
        ORDER BY s.seat_name, s.date DESC, ABS(s.net_amount) DESC
    """, (cutoff,)).fetchall()

    from collections import defaultdict
    seat_details: dict[str, list] = defaultdict(list)
    for row in detail_rows:
        seat_name = row["seat_name"]
        if len(seat_details[seat_name]) < 50:
            seat_details[seat_name].append(dict(row))

    for s in stats:
        s["details"] = seat_details.get(s["seat_name"], [])

    return stats


def render_longhu_html(lhb_rows: list[dict[str, object]], latest_date: str, seat_stats: list[dict] | None = None) -> str:
    def fmt_e8(val: object) -> str:
        if val is None:
            return "-"
        try:
            v = float(val) / 1e8
            return f"{v:.2f}亿"
        except Exception:
            return "-"

    def pct_class(val: object) -> str:
        try:
            v = float(val)
            return "up" if v > 0 else ("dn" if v < 0 else "")
        except Exception:
            return ""

    def fmt_pct_str(val: object) -> str:
        if val is None:
            return "-"
        try:
            return f"{float(val):.2f}%"
        except Exception:
            return "-"

    from collections import OrderedDict
    import json as _json

    # ── 按日期分组 ────────────────────────────────────────────────────────────
    by_date: dict[str, list] = OrderedDict()
    for row in lhb_rows:
        d = str(row["date"])
        by_date.setdefault(d, []).append(row)

    all_dates = list(by_date.keys())  # sorted DESC

    # ── 每日面板 ──────────────────────────────────────────────────────────────
    date_tabs_html = ""
    date_panels_html = ""
    for i, (date, rows) in enumerate(by_date.items()):
        active = "active" if i == 0 else ""
        date_tabs_html += (
            f'<button class="dtab {active}" data-date="{date}" onclick="switchDate(this)">'
            f'{date}（{len(rows)}只）</button>'
        )
        table_rows = ""
        for row_idx, r in enumerate(rows):
            rid = f"{date}-{r['code']}"
            # 席位展开行
            seats = r.get("seats", [])
            seat_detail_html = ""
            if seats:
                seat_rows_html = ""
                for s in seats:
                    d_cls = "seat-buy" if s["direction"] == "买入" else "seat-sell"
                    seat_rows_html += (
                        f'<tr class="seat-row">'
                        f'<td colspan="2"><span class="{d_cls}">{html.escape(str(s["direction"]))}</span></td>'
                        f'<td colspan="4">{html.escape(str(s["seat_name"]))}</td>'
                        f'<td colspan="4" class="{d_cls}">{fmt_e8(s.get("net_amount"))}</td>'
                        f'</tr>'
                    )
                seat_detail_html = (
                    f'<tr class="seat-detail" id="sd-{rid}" style="display:none">'
                    f'<td colspan="10" style="padding:0"><table class="seat-table">'
                    f'<thead><tr><th colspan="2">方向</th><th colspan="4">营业部</th><th colspan="4">净额</th></tr></thead>'
                    f'<tbody>{seat_rows_html}</tbody></table></td></tr>'
                )
            pct = r.get("pct_chg")
            net = r.get("lhb_net_buy")
            a1 = r.get("after_1d")
            a5 = r.get("after_5d")
            seat_count = len(seats)
            toggle_btn = (
                f'<button class="expand-btn" onclick="toggleSeats(\'{rid}\')" title="展开席位明细">'
                f'席位 {seat_count}</button>'
            ) if seat_count else f'<span style="color:#484f58;font-size:11px">-</span>'
            table_rows += f"""<tr class="stock-row" onclick="toggleSeats('{rid}')">
              <td><b>{html.escape(str(r['code']))}</b> <small>{html.escape(str(r['name']))}</small></td>
              <td class="{pct_class(pct)}">{fmt_pct_str(pct)}</td>
              <td class="{pct_class(net)}">{fmt_e8(net)}</td>
              <td>{fmt_e8(r.get('lhb_buy'))}</td>
              <td>{fmt_e8(r.get('lhb_sell'))}</td>
              <td>{fmt_num(r.get('net_buy_ratio'))}%</td>
              <td class="reason-cell">{html.escape(str(r.get('reason') or ''))}</td>
              <td class="{pct_class(a1)}">{fmt_pct_str(a1)}</td>
              <td class="{pct_class(a5)}">{fmt_pct_str(a5)}</td>
              <td>{toggle_btn}</td>
            </tr>{seat_detail_html}"""
        date_panels_html += f"""<div class="dpanel {active}" id="panel-{date}">
          <table>
            <thead><tr>
              <th>代码/名称</th><th>涨跌幅</th><th>净买额</th><th>买入额</th><th>卖出额</th>
              <th>净买比%</th><th>上榜原因</th><th>后1日</th><th>后5日</th><th>席位明细</th>
            </tr></thead>
            <tbody>{table_rows}</tbody>
          </table>
        </div>"""

    # ── 营业部排行面板 ────────────────────────────────────────────────────────
    seat_panel_html = ""
    seat_detail_js = ""
    if seat_stats:
        import json as _json2

        # 把每个席位的 details 序列化为 JS，供点击展开
        # Key: 席位排名索引（buy/sell 两个列表各自的 index）
        def render_seat_table(seats_list: list, table_prefix: str) -> tuple[str, str]:
            """Returns (table_rows_html, js_data_snippet)."""
            rows_html = ""
            js_snippets = []
            for i, s in enumerate(seats_list, 1):
                net = s.get("total_net") or 0
                buy = s.get("total_buy") or 0
                sell = s.get("total_sell") or 0
                apps = s.get("appearances") or 0
                net_cls = "up" if net > 0 else "dn"
                sid = f"{table_prefix}-{i}"
                details = s.get("details", [])
                # 每条明细序列化为精简数据
                detail_data = [
                    {
                        "date": d.get("date", ""),
                        "code": d.get("code", ""),
                        "name": d.get("name") or "",
                        "direction": d.get("direction", ""),
                        "net_amount": d.get("net_amount"),
                        "pct_chg": d.get("pct_chg"),
                        "after_1d": d.get("after_1d"),
                        "after_5d": d.get("after_5d"),
                    }
                    for d in details
                ]
                js_snippets.append(f'seatDetails["{sid}"] = {_json2.dumps(detail_data, ensure_ascii=False)};')
                rows_html += (
                    f'<tr class="seat-stat-row" onclick="toggleSeatDetail(\'{sid}\')" style="cursor:pointer">'
                    f'<td>{i}</td>'
                    f'<td>{html.escape(str(s["seat_name"]))}</td>'
                    f'<td>{apps}</td>'
                    f'<td>{fmt_e8(buy)}</td>'
                    f'<td>{fmt_e8(sell)}</td>'
                    f'<td class="{net_cls}">{fmt_e8(net)}</td>'
                    f'<td><button class="expand-btn">明细</button></td>'
                    f'</tr>'
                    f'<tr id="sd-{sid}" style="display:none"><td colspan="7" style="padding:0">'
                    f'<div class="seat-records" id="records-{sid}"></div>'
                    f'</td></tr>'
                )
            return rows_html, "\n".join(js_snippets)

        buy_rows, buy_js = render_seat_table(seat_stats[:50], "buy")
        sell_sorted = sorted(seat_stats, key=lambda x: x.get("total_net") or 0)[:50]
        sell_rows, sell_js = render_seat_table(sell_sorted, "sell")
        seat_detail_js = f"const seatDetails = {{}};\n{buy_js}\n{sell_js}"

        seat_panel_html = f"""
        <div style="display:flex;gap:24px;flex-wrap:wrap">
          <div style="flex:1;min-width:500px">
            <h3 style="font-size:14px;color:#8b949e;margin-bottom:10px">净买入 Top 50</h3>
            <table><thead><tr><th>#</th><th>营业部</th><th>出现次数</th><th>买入额</th><th>卖出额</th><th>净买额</th><th></th></tr></thead>
            <tbody>{buy_rows}</tbody></table>
          </div>
          <div style="flex:1;min-width:500px">
            <h3 style="font-size:14px;color:#8b949e;margin-bottom:10px">净卖出 Top 50</h3>
            <table><thead><tr><th>#</th><th>营业部</th><th>出现次数</th><th>买入额</th><th>卖出额</th><th>净买额</th><th></th></tr></thead>
            <tbody>{sell_rows}</tbody></table>
          </div>
        </div>"""

    main_content = '<p class="empty">暂无龙虎榜数据，待下次采集后自动更新</p>'
    if lhb_rows:
        # 日期范围选择器
        range_btns = ""
        for label, n in [("近10日", 10), ("近20日", 20), ("近30日", 30)]:
            active = "range-active" if n == 30 else ""
            range_btns += f'<button class="range-btn {active}" data-days="{n}">{label}</button>'

        main_content = f"""
        <div class="toolbar">
          <div class="date-tabs" id="dateTabs">{date_tabs_html}</div>
          <div class="range-btns">{range_btns}</div>
        </div>
        <div id="datePanels">{date_panels_html}</div>"""

    seat_section = ""
    if seat_stats:
        seat_section = f"""
        <div class="view-panel" id="view-seats">
          <h2 style="font-size:16px;margin-bottom:16px">营业部净买卖排行（近30个交易日）</h2>
          {seat_panel_html}
        </div>"""

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>龙虎榜 · A股量化研究</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif; background: #0d1117; color: #e6edf3; min-height: 100vh; }}
.navbar {{ background: #161b22; border-bottom: 1px solid #30363d; padding: 0 32px; display: flex; align-items: center; height: 60px; gap: 24px; position: sticky; top: 0; z-index: 100; flex-wrap: wrap; }}
.navbar-brand {{ color: #58a6ff; font-weight: 700; font-size: 16px; text-decoration: none; white-space: nowrap; }}
.navbar-links {{ display: flex; gap: 2px; flex-wrap: wrap; }}
.navbar-links a {{ color: #8b949e; text-decoration: none; font-size: 13px; padding: 5px 10px; border-radius: 6px; transition: all .15s; }}
.navbar-links a:hover {{ color: #e6edf3; background: #21262d; }}
.navbar-links a.active {{ color: #e6edf3; background: #21262d; }}
.navbar-date {{ margin-left: auto; font-size: 12px; color: #484f58; }}
.container {{ max-width: 1500px; margin: 0 auto; padding: 24px 20px; }}
h1 {{ font-size: 22px; margin-bottom: 6px; }}
.sub {{ color: #8b949e; font-size: 13px; margin-bottom: 16px; }}
/* view tabs */
.view-tabs {{ display: flex; gap: 0; margin-bottom: 20px; border-bottom: 1px solid #30363d; }}
.vtab {{ background: none; border: none; border-bottom: 2px solid transparent; color: #8b949e; padding: 8px 20px; cursor: pointer; font-size: 14px; transition: all .15s; }}
.vtab.active {{ color: #e6edf3; border-bottom-color: #1f6feb; }}
.view-panel {{ display: none; }} .view-panel.active {{ display: block; }}
/* toolbar */
.toolbar {{ display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 10px; margin-bottom: 14px; }}
.date-tabs {{ display: flex; gap: 6px; flex-wrap: wrap; flex: 1; }}
.dtab {{ background: #21262d; border: 1px solid #30363d; color: #8b949e; padding: 5px 12px; border-radius: 16px; cursor: pointer; font-size: 12px; transition: all .15s; white-space: nowrap; }}
.dtab.active, .dtab:hover {{ background: #1f6feb; border-color: #1f6feb; color: #fff; }}
.dpanel {{ display: none; }} .dpanel.active {{ display: block; }}
/* range buttons */
.range-btns {{ display: flex; gap: 4px; }}
.range-btn {{ background: #21262d; border: 1px solid #30363d; color: #8b949e; padding: 5px 12px; border-radius: 16px; cursor: pointer; font-size: 12px; white-space: nowrap; }}
.range-btn.range-active {{ background: #1f6feb26; border-color: #1f6feb; color: #79c0ff; }}
/* table */
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
thead tr {{ background: #161b22; position: sticky; top: 56px; z-index: 10; }}
th {{ padding: 9px 8px; text-align: left; color: #8b949e; font-weight: 600; border-bottom: 1px solid #30363d; white-space: nowrap; }}
td {{ padding: 8px 8px; border-bottom: 1px solid #21262d; vertical-align: middle; }}
.stock-row {{ cursor: pointer; }}
.stock-row:hover td {{ background: #161b22; }}
.up {{ color: #e84c3d; }} .dn {{ color: #07a071; }}
.reason-cell {{ max-width: 160px; word-break: break-all; color: #8b949e; font-size: 11px; }}
/* expand button */
.expand-btn {{ background: #21262d; border: 1px solid #30363d; color: #8b949e; padding: 2px 8px; border-radius: 10px; cursor: pointer; font-size: 11px; white-space: nowrap; }}
.expand-btn:hover {{ border-color: #1f6feb; color: #79c0ff; }}
/* seat detail */
.seat-detail td {{ padding: 0; background: #0d1117; }}
.seat-table {{ width: 100%; font-size: 12px; border-top: 1px solid #30363d; }}
.seat-table th {{ background: #161b22; padding: 6px 10px; top: auto; position: static; }}
.seat-table td {{ padding: 6px 10px; background: #0d1117; border-bottom: 1px solid #161b22; }}
.seat-buy {{ color: #07a071; font-weight: 600; }}
.seat-sell {{ color: #07a071; font-weight: 600; }}
.seat-buy {{ color: #e84c3d; font-weight: 600; }}
.seat-stat-row:hover td {{ background: #161b22; }}
/* 营业部明细展开 */
.seat-records {{ background: #0d1117; border-top: 1px solid #30363d; padding: 8px 0; }}
.seat-records table {{ font-size: 12px; }}
.seat-records th {{ position: static; background: #161b22; padding: 6px 10px; }}
.seat-records td {{ padding: 6px 10px; background: #0d1117; border-bottom: 1px solid #161b22; }}
.empty {{ color: #484f58; text-align: center; padding: 60px; }}
.footer {{ text-align: center; color: #484f58; font-size: 12px; padding: 48px 0 24px; }}
/* ── 搜索 Tab ── */
.search-box {{ display: flex; gap: 8px; margin-bottom: 12px; }}
.search-box input {{ flex: 1; background: #161b22; border: 1px solid #30363d; color: #e6edf3; padding: 8px 12px; border-radius: 6px; font-size: 14px; outline: none; }}
.search-box input:focus {{ border-color: #1f6feb; }}
.search-box button {{ background: #1f6feb; border: none; color: #fff; padding: 8px 18px; border-radius: 6px; cursor: pointer; font-size: 14px; }}
.suggest-list {{ background: #161b22; border: 1px solid #30363d; border-radius: 6px; margin-bottom: 8px; overflow: hidden; }}
.suggest-item {{ padding: 8px 14px; cursor: pointer; color: #c9d1d9; font-size: 13px; display: flex; justify-content: space-between; }}
.suggest-item:hover {{ background: #21262d; }}
.suggest-item .s-count {{ color: #484f58; font-size: 12px; }}
.result-area {{ overflow-x: auto; }}
.result-area table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
.result-area th {{ background: #161b22; padding: 7px 10px; text-align: right; color: #8b949e; font-weight: 500; white-space: nowrap; }}
.result-area th:first-child, .result-area th:nth-child(2), .result-area th:nth-child(3) {{ text-align: left; }}
.result-area td {{ padding: 7px 10px; border-bottom: 1px solid #21262d; text-align: right; white-space: nowrap; }}
.result-area td:first-child, .result-area td:nth-child(2), .result-area td:nth-child(3) {{ text-align: left; }}
.result-loading {{ color: #484f58; padding: 40px; text-align: center; }}
.result-summary {{ color: #8b949e; font-size: 12px; margin-bottom: 8px; padding: 6px 0; border-bottom: 1px solid #21262d; }}
</style>
</head>
<body>
{_NAVBAR("longhu.html", "最新数据：" + html.escape(latest_date))}
<div class="container">
  <h1>龙虎榜</h1>
  <p class="sub">来源：东方财富 · 点击行可展开席位明细 · 含上榜后收益追踪</p>
  <div class="view-tabs">
    <button class="vtab active" onclick="switchView(this,'view-daily')">按日期</button>
    {'<button class="vtab" onclick="switchView(this,\'view-seats\')">营业部排行</button>' if seat_stats else ''}
    <button class="vtab" onclick="switchView(this,'view-stock-search')">个股历史</button>
    <button class="vtab" onclick="switchView(this,'view-seat-search')">营业部历史</button>
  </div>
  <div class="view-panel active" id="view-daily">
    {main_content}
  </div>
  {seat_section}

  <!-- 个股历史查询 -->
  <div class="view-panel" id="view-stock-search">
    <div class="search-box">
      <input type="text" id="stockInput" placeholder="输入股票代码或名称，如 000001 或 平安" autocomplete="off">
      <button onclick="searchStock()">查询</button>
    </div>
    <div id="stockSuggest" class="suggest-list"></div>
    <div id="stockResult" class="result-area"></div>
  </div>

  <!-- 营业部历史查询 -->
  <div class="view-panel" id="view-seat-search">
    <div class="search-box">
      <input type="text" id="seatInput" placeholder="输入营业部名称，如 华泰证券" autocomplete="off">
      <button onclick="searchSeat()">查询</button>
    </div>
    <div id="seatSuggest" class="suggest-list"></div>
    <div id="seatResult" class="result-area"></div>
  </div>

</div>
<div class="footer">数据来源：AkShare 东方财富 · 每工作日 19:45 (北京时间) 自动更新</div>
<script>
// 营业部明细数据
{seat_detail_js}
// 所有日期数据（用于日期范围过滤）
const allDates = {_json.dumps(all_dates)};

function switchView(btn, viewId) {{
  document.querySelectorAll('.vtab').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.view-panel').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById(viewId).classList.add('active');
}}

function switchDate(btn) {{
  const date = btn.dataset.date;
  document.querySelectorAll('.dtab').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.dpanel').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  const panel = document.getElementById('panel-' + date);
  if (panel) panel.classList.add('active');
}}

function toggleSeats(rid) {{
  const row = document.getElementById('sd-' + rid);
  if (!row) return;
  row.style.display = row.style.display === 'none' ? '' : 'none';
}}

function toggleSeatDetail(sid) {{
  const row = document.getElementById('sd-' + sid);
  if (!row) return;
  const isHidden = row.style.display === 'none';
  row.style.display = isHidden ? '' : 'none';
  if (!isHidden) return;
  // 渲染明细（只渲染一次）
  const container = document.getElementById('records-' + sid);
  if (container.dataset.rendered) return;
  container.dataset.rendered = '1';
  const details = seatDetails[sid] || [];
  if (!details.length) {{
    container.innerHTML = '<p style="color:#484f58;padding:12px 16px;font-size:12px">暂无明细数据</p>';
    return;
  }}
  let html = '<table><thead><tr><th>日期</th><th>代码</th><th>名称</th><th>方向</th><th>净额</th><th>当日涨跌</th><th>后1日</th><th>后5日</th></tr></thead><tbody>';
  details.forEach(d => {{
    const dirCls = d.direction === '买入' ? 'seat-buy' : 'seat-sell';
    const pctFmt = v => v == null ? '-' : (parseFloat(v) >= 0 ? '<span class="up">' : '<span class="dn">') + parseFloat(v).toFixed(2) + '%</span>';
    const amtFmt = v => v == null ? '-' : (parseFloat(v)/1e8).toFixed(2) + '亿';
    html += `<tr>
      <td>${{d.date}}</td>
      <td>${{d.code}}</td>
      <td>${{d.name || '-'}}</td>
      <td class="${{dirCls}}">${{d.direction}}</td>
      <td class="${{d.net_amount > 0 ? 'up' : 'dn'}}">${{amtFmt(d.net_amount)}}</td>
      <td>${{pctFmt(d.pct_chg)}}</td>
      <td>${{pctFmt(d.after_1d)}}</td>
      <td>${{pctFmt(d.after_5d)}}</td>
    </tr>`;
  }});
  html += '</tbody></table>';
  container.innerHTML = html;
}}

// 日期范围过滤
document.querySelectorAll('.range-btn').forEach(btn => {{
  btn.addEventListener('click', function() {{
    document.querySelectorAll('.range-btn').forEach(b => b.classList.remove('range-active'));
    this.classList.add('range-active');
    const days = parseInt(this.dataset.days);
    const visible = new Set(allDates.slice(0, days));
    const tabs = document.querySelectorAll('.dtab');
    tabs.forEach(t => {{
      t.style.display = visible.has(t.dataset.date) ? '' : 'none';
    }});
    // 如果当前 active tab 被隐藏了，切换到第一个可见的
    const activeTab = document.querySelector('.dtab.active');
    if (activeTab && !visible.has(activeTab.dataset.date)) {{
      const firstVisible = [...tabs].find(t => visible.has(t.dataset.date));
      if (firstVisible) switchDate(firstVisible);
    }}
  }});
}});

// ── 个股历史查询 ─────────────────────────────────────────────────────────────
const API_BASE = '/api/lhb';
let stockDebounceTimer = null;
let seatDebounceTimer = null;

function debounce(fn, ms) {{
  return function(...args) {{
    clearTimeout(arguments.callee._t);
    arguments.callee._t = setTimeout(() => fn(...args), ms);
  }};
}}

document.getElementById('stockInput').addEventListener('input', function() {{
  clearTimeout(stockDebounceTimer);
  const q = this.value.trim();
  if (!q) {{ document.getElementById('stockSuggest').innerHTML = ''; return; }}
  stockDebounceTimer = setTimeout(() => fetchStockSuggest(q), 300);
}});

document.getElementById('seatInput').addEventListener('input', function() {{
  clearTimeout(seatDebounceTimer);
  const q = this.value.trim();
  if (!q) {{ document.getElementById('seatSuggest').innerHTML = ''; return; }}
  seatDebounceTimer = setTimeout(() => fetchSeatSuggest(q), 300);
}});

document.getElementById('stockInput').addEventListener('keydown', function(e) {{
  if (e.key === 'Enter') searchStock();
}});
document.getElementById('seatInput').addEventListener('keydown', function(e) {{
  if (e.key === 'Enter') searchSeat();
}});

function fetchStockSuggest(q) {{
  fetch(API_BASE + '/search/stock?q=' + encodeURIComponent(q))
    .then(r => r.json()).then(data => {{
      const box = document.getElementById('stockSuggest');
      if (!data.length) {{ box.innerHTML = ''; return; }}
      box.innerHTML = data.map(d =>
        `<div class="suggest-item" onclick="loadStock('${{d.code}}','${{d.name}}')">
          <span>${{d.code}} ${{d.name}}</span>
          <span class="s-count">上榜 ${{d.appearances}} 次 · 最近 ${{d.last_date}}</span>
        </div>`
      ).join('');
    }}).catch(() => {{}});
}}

function fetchSeatSuggest(q) {{
  fetch(API_BASE + '/search/seat?q=' + encodeURIComponent(q))
    .then(r => r.json()).then(data => {{
      const box = document.getElementById('seatSuggest');
      if (!data.length) {{ box.innerHTML = ''; return; }}
      box.innerHTML = data.map(d => {{
        const net = d.total_net == null ? '-' : (parseFloat(d.total_net)/1e8).toFixed(1) + '亿';
        return `<div class="suggest-item" onclick="loadSeat('${{d.seat_name.replace(/'/g, "\\'")}}')">
          <span>${{d.seat_name}}</span>
          <span class="s-count">${{d.appearances}} 次 · 净买 ${{net}} · 最近 ${{d.last_date}}</span>
        </div>`;
      }}).join('');
    }}).catch(() => {{}});
}}

function searchStock() {{
  const q = document.getElementById('stockInput').value.trim();
  if (!q) return;
  // 如果像股票代码（6位数字）直接加载
  if (/^\\d{{6}}$/.test(q)) {{ loadStock(q, ''); return; }}
  fetchStockSuggest(q);
}}

function searchSeat() {{
  const q = document.getElementById('seatInput').value.trim();
  if (!q) return;
  loadSeat(q);
}}

function loadStock(code, name) {{
  document.getElementById('stockSuggest').innerHTML = '';
  document.getElementById('stockInput').value = code + (name ? ' ' + name : '');
  const result = document.getElementById('stockResult');
  result.innerHTML = '<div class="result-loading">加载中…</div>';
  fetch(API_BASE + '/stock?code=' + encodeURIComponent(code))
    .then(r => r.json()).then(data => {{
      if (!data.records || !data.records.length) {{
        result.innerHTML = '<div class="result-loading">暂无龙虎榜记录</div>'; return;
      }}
      const pct = v => v == null ? '-' : `<span class="${{parseFloat(v)>=0?'up':'dn'}}">${{parseFloat(v).toFixed(2)}}%</span>`;
      const amt = v => v == null ? '-' : (parseFloat(v)/1e8).toFixed(2) + '亿';
      let html = `<div class="result-summary">${{data.name}} (${{code}}) · 共上榜 ${{data.records.length}} 次</div>`;
      html += '<table><thead><tr><th>日期</th><th>原因</th><th>涨跌幅</th><th>龙虎净买</th><th>后1日</th><th>后2日</th><th>后5日</th><th>后10日</th></tr></thead><tbody>';
      data.records.forEach((r, i) => {{
        const rid = 'lhb-' + code + '-' + i;
        html += `<tr style="cursor:pointer" onclick="toggleStockSeats('${{rid}}')">
          <td>${{r.date}}</td><td style="max-width:200px;white-space:normal;font-size:12px;color:#8b949e">${{r.reason||'-'}}</td>
          <td>${{pct(r.pct_chg)}}</td><td>${{amt(r.lhb_net_buy)}}</td>
          <td>${{pct(r.after_1d)}}</td><td>${{pct(r.after_2d)}}</td><td>${{pct(r.after_5d)}}</td><td>${{pct(r.after_10d)}}</td>
        </tr>`;
        if (r.seats && r.seats.length) {{
          html += `<tr id="${{rid}}" style="display:none"><td colspan="8" style="padding:0;background:#0d1117">`;
          html += '<table style="width:100%;font-size:12px"><thead><tr><th>方向</th><th>席位</th><th>净额</th><th>买额</th><th>卖额</th></tr></thead><tbody>';
          r.seats.forEach(s => {{
            const cls = s.direction === '买入' ? 'seat-buy' : 'seat-sell';
            html += `<tr><td class="${{cls}}">${{s.direction}}</td><td style="text-align:left;color:#c9d1d9">${{s.seat_name}}</td>
              <td class="${{parseFloat(s.net_amount||0)>=0?'up':'dn'}}">${{amt(s.net_amount)}}</td>
              <td>${{amt(s.buy_amount)}}</td><td>${{amt(s.sell_amount)}}</td></tr>`;
          }});
          html += '</tbody></table></td></tr>';
        }}
      }});
      html += '</tbody></table>';
      result.innerHTML = html;
    }}).catch(e => {{ result.innerHTML = '<div class="result-loading">请求失败：' + e + '</div>'; }});
}}

function toggleStockSeats(rid) {{
  const row = document.getElementById(rid);
  if (row) row.style.display = row.style.display === 'none' ? '' : 'none';
}}

function loadSeat(name) {{
  document.getElementById('seatSuggest').innerHTML = '';
  document.getElementById('seatInput').value = name;
  const result = document.getElementById('seatResult');
  result.innerHTML = '<div class="result-loading">加载中…</div>';
  fetch(API_BASE + '/seat?name=' + encodeURIComponent(name))
    .then(r => r.json()).then(data => {{
      if (!data.records || !data.records.length) {{
        result.innerHTML = '<div class="result-loading">暂无记录</div>'; return;
      }}
      const pct = v => v == null ? '-' : `<span class="${{parseFloat(v)>=0?'up':'dn'}}">${{parseFloat(v).toFixed(2)}}%</span>`;
      const amt = v => v == null ? '-' : (parseFloat(v)/1e8).toFixed(2) + '亿';
      const s = data.summary;
      let html = `<div class="result-summary">${{name}} · ${{s.appearances}} 条记录 · 净买合计 <span class="${{s.total_net>=0?'up':'dn'}}">${{(s.total_net/1e8).toFixed(1)}}亿</span></div>`;
      html += '<table><thead><tr><th>日期</th><th>代码</th><th>名称</th><th>方向</th><th>净额</th><th>买额</th><th>涨跌幅</th><th>后1日</th><th>后5日</th></tr></thead><tbody>';
      data.records.forEach(r => {{
        const cls = r.direction === '买入' ? 'seat-buy' : 'seat-sell';
        html += `<tr>
          <td>${{r.date}}</td><td>${{r.code}}</td><td style="text-align:left">${{r.stock_name||'-'}}</td>
          <td class="${{cls}}">${{r.direction}}</td>
          <td class="${{parseFloat(r.net_amount||0)>=0?'up':'dn'}}">${{amt(r.net_amount)}}</td>
          <td>${{amt(r.buy_amount)}}</td>
          <td>${{pct(r.pct_chg)}}</td><td>${{pct(r.after_1d)}}</td><td>${{pct(r.after_5d)}}</td>
        </tr>`;
      }});
      html += '</tbody></table>';
      result.innerHTML = html;
    }}).catch(e => {{ result.innerHTML = '<div class="result-loading">请求失败：' + e + '</div>'; }});
}}
</script>
</body>
</html>"""


def render_etf_html(conn, latest_date: str) -> str:
    """生成 ETF 专题页 etf.html。"""
    import html as html_mod

    # ── 债市关键词（精确匹配，排除现金流策略ETF）──────────────────────────────
    BOND_KEYWORDS = [
        "国债", "地方债", "政金债", "国开债", "信用债", "公司债", "城投债",
        "科创债", "可转债", "货币ETF", "货币", "增益货币",
        "日利ETF", "日鑫ETF", "添益ETF", "短融ETF", "短债ETF",
    ]
    # 债市名称判断：包含债市关键词且不是"现金流"策略ETF
    def is_bond(name: str) -> bool:
        return any(k in name for k in BOND_KEYWORDS) and "现金流" not in name

    # ── ETF 类型分类 ─────────────────────────────────────────────────────────
    # 宽基指数关键词（包括跨境/商品/主题宽基）
    BROAD_INDEX_KW = [
        "上证50", "沪深300", "中证500", "中证800", "中证1000", "中证2000",
        "A500", "A50", "A100", "A股ETF", "全A", "万得全A",
        "上证180", "上证指数", "深证成指", "创业板指", "科创50", "双创50",
        "科创创业", "MSCI", "中国A50", "中国国企", "中概互联",
        "标普", "纳指", "纳斯达克", "道琼斯", "日经", "恒生",
        "港股通100", "港股通50", "亚太", "新兴市场", "欧洲", "德国",
        "黄金ETF", "上海金ETF", "白银ETF", "豆粕ETF", "原油ETF",
        "TMTETF", "VRETF", "红利ETF", "红利低波", "红利质量",
        "价值ETF", "成长ETF", "质量ETF", "动量ETF",
        "300红利", "500红利", "1000红利",
        "国证2000", "中证全指",
    ]
    def classify_etf(name: str) -> str:
        """返回 'index'（宽基/跨境）或 'sector'（行业/主题）"""
        if any(k in name for k in BROAD_INDEX_KW):
            return "index"
        return "sector"

    # ── 查最新日期的ETF快照，成交额≥5亿，排除债市 ───────────────────────────
    db_latest = conn.execute("SELECT MAX(date) d FROM etf_daily").fetchone()["d"] or latest_date
    all_db_rows = conn.execute("""
        SELECT code, name, close, pct_chg, amount,
               ma20, ma60, hist_high,
               is_new_high, ma20_up, ma60_up, above_ma20, above_ma60
        FROM etf_daily
        WHERE date = ?
        ORDER BY amount DESC
    """, (db_latest,)).fetchall()

    # 计算每只ETF最近30天价格区间（用于过滤极低波动的准货币/短融产品）
    _low_vol_codes: set[str] = set()
    _range_rows = conn.execute("""
        SELECT code,
               (MAX(close) - MIN(close)) / MIN(close) * 100 AS range_pct
        FROM etf_daily
        WHERE date >= date(?, '-35 days') AND date <= ?
        GROUP BY code
        HAVING COUNT(*) >= 10
    """, (db_latest, db_latest)).fetchall()
    for rr in _range_rows:
        if (rr["range_pct"] or 0) < 1.0:
            _low_vol_codes.add(rr["code"])

    # 过滤：去掉债市、成交额≥5亿、去掉近30天振幅<1%的极低波动产品
    rows = [r for r in all_db_rows
            if not is_bond(r["name"])
            and (r["amount"] or 0) >= 5e8
            and r["code"] not in _low_vol_codes]

    # 加载持仓
    holdings_map: dict[str, list] = {}
    if rows:
        codes = [r["code"] for r in rows]
        placeholders = ",".join("?" * len(codes))
        ph = conn.execute(
            f"SELECT code, quarter, stock_code, stock_name, weight FROM etf_holdings "
            f"WHERE code IN ({placeholders}) ORDER BY code, weight DESC",
            codes
        ).fetchall()
        for h in ph:
            holdings_map.setdefault(h["code"], []).append(h)

    # 加载近 65 日 K 线（open/high/low/close/amount/ma5/ma20/ma60）
    import json as _json_etf
    kline_map: dict[str, list] = {}
    if rows:
        codes = [r["code"] for r in rows]
        placeholders = ",".join("?" * len(codes))
        kl_rows = conn.execute(
            f"""SELECT code, date, open, high, low, close, amount, ma5, ma20, ma60
                FROM etf_daily
                WHERE code IN ({placeholders})
                  AND date >= date(?, '-95 days')
                ORDER BY code, date ASC""",
            codes + [db_latest]
        ).fetchall()
        for kr in kl_rows:
            kline_map.setdefault(kr["code"], []).append([
                kr["date"],
                round(kr["open"] or kr["close"] or 0, 4),
                round(kr["high"] or kr["close"] or 0, 4),
                round(kr["low"]  or kr["close"] or 0, 4),
                round(kr["close"] or 0, 4),
                round((kr["amount"] or 0) / 1e8, 3),  # 亿元
                round(kr["ma5"]  or 0, 4),
                round(kr["ma20"] or 0, 4),
                round(kr["ma60"] or 0, 4),
            ])
        # 只保留最近 65 根
        kline_map = {code: bars[-65:] for code, bars in kline_map.items()}
    kline_json = _json_etf.dumps(kline_map, ensure_ascii=False, separators=(',', ':'))

    # ── helpers ───────────────────────────────────────────────────────────────
    def fmt_amt(v):
        if v is None: return "-"
        if v >= 1e8: return f"{v/1e8:.2f}亿"
        return f"{v/1e4:.0f}万"

    def get_signals(r) -> list[str]:
        sigs = []
        if r["is_new_high"]:     sigs.append("历史新高")
        if r["ma20_up"] and r["above_ma20"]: sigs.append("MA20向上")
        if r["ma60_up"] and r["above_ma60"]: sigs.append("MA60向上")
        elif r["above_ma60"]:    sigs.append("站上MA60")
        return sigs

    BADGE_CLASS = {
        "历史新高": "badge-high",
        "MA20向上":  "badge-ma20",
        "MA60向上":  "badge-ma60",
        "站上MA60":  "badge-above60",
    }

    def signal_badges(sigs: list[str]) -> str:
        return "".join(
            f'<span class="badge {BADGE_CLASS.get(s,"")}" data-sig="{s}">{s}</span>'
            for s in sigs
        )

    def type_badge(name: str) -> str:
        t = classify_etf(name)
        if t == "index":
            return '<span class="type-badge type-index">宽基</span>'
        return '<span class="type-badge type-sector">行业</span>'

    def holding_html(code: str) -> str:
        hs = holdings_map.get(code, [])
        if not hs:
            return '<p class="no-hold">暂无持仓数据（指数/商品ETF或待采集）</p>'
        quarter = hs[0]["quarter"] if hs else ""
        rows_html = "".join(
            f'<tr><td>{html_mod.escape(h["stock_code"])}</td>'
            f'<td>{html_mod.escape(h["stock_name"])}</td>'
            f'<td class="weight-bar-cell">'
            f'  <div class="weight-bar" style="width:{min(h["weight"] or 0,15)/15*100:.1f}%"></div>'
            f'  <span>{h["weight"]:.2f}%</span>'
            f'</td></tr>'
            for h in hs[:15]
        )
        return f"""<p class="hold-quarter">{html_mod.escape(quarter)} 前{min(len(hs),15)}大持仓</p>
<table class="hold-table">
  <thead><tr><th>代码</th><th>名称</th><th>占净值比例</th></tr></thead>
  <tbody>{rows_html}</tbody>
</table>"""

    # ── 分组数据 ──────────────────────────────────────────────────────────────
    signal_rows  = [r for r in rows if get_signals(r)]
    index_rows   = [r for r in rows if classify_etf(r["name"]) == "index"]
    sector_rows  = [r for r in rows if classify_etf(r["name"]) == "sector"]

    # 统计
    n_new_high = sum(1 for r in rows if r["is_new_high"])
    n_ma20     = sum(1 for r in rows if r["ma20_up"] and r["above_ma20"])
    n_ma60     = sum(1 for r in rows if r["above_ma60"])

    # ── 渲染表格（data-* 属性供 JS 筛选用）──────────────────────────────────
    def build_table(data: list, tab_id: str) -> str:
        if not data:
            return '<p class="empty">暂无数据</p>'
        trs = []
        for r in data:
            pct      = r["pct_chg"] or 0
            pct_cls  = "up" if pct > 0 else ("dn" if pct < 0 else "")
            pct_str  = f"{pct:+.2f}%" if pct else "0.00%"
            ma20_str = f'{r["ma20"]:.3f}' if r["ma20"] else "-"
            ma60_str = f'{r["ma60"]:.3f}' if r["ma60"] else "-"
            close_str= f'{r["close"]:.3f}' if r["close"] else "-"
            sigs     = get_signals(r)
            badges   = signal_badges(sigs)
            tbadge   = type_badge(r["name"])
            hold_html= holding_html(r["code"])
            row_id   = f'{tab_id}_{r["code"]}'
            etf_type = classify_etf(r["name"])
            sig_attr = " ".join(sigs)       # e.g. "历史新高 MA20向上"
            trs.append(f"""<tr class="etf-row" data-sig="{sig_attr}" data-type="{etf_type}" data-pct="{pct}" onclick="toggleHold('{row_id}')">
  <td>{tbadge} <span class="etf-code">{html_mod.escape(r["code"])}</span> <span class="etf-name">{html_mod.escape(r["name"])}</span></td>
  <td class="{pct_cls}">{pct_str}</td>
  <td>{close_str}</td>
  <td>{ma20_str}</td>
  <td>{ma60_str}</td>
  <td>{fmt_amt(r["amount"])}</td>
  <td>{badges}</td>
</tr>
<tr class="hold-row" id="{row_id}" style="display:none">
  <td colspan="7" class="hold-cell">
    <div class="expand-inner">
      <div class="kline-wrap">
        <canvas id="kc_{r["code"]}" width="520" height="240" style="display:block"></canvas>
        <div class="kline-legend" id="kl_{r["code"]}"></div>
      </div>
      <div class="hold-wrap">{hold_html}</div>
    </div>
  </td>
</tr>""")
        return f"""<table id="tbl-{tab_id}">
  <thead><tr>
    <th>ETF</th><th class="sortable-pct" onclick="sortByPct('{tab_id}')" style="cursor:pointer;user-select:none" title="点击排序">涨跌幅 <span id="sort-icon-{tab_id}">⇅</span></th><th>现价</th><th>MA20</th><th>MA60</th><th>成交额</th><th>信号</th>
  </tr></thead>
  <tbody>{"".join(trs)}</tbody>
</table>"""

    signal_table = build_table(signal_rows,  "s")
    index_table  = build_table(index_rows,   "i")
    sector_table = build_table(sector_rows,  "e")

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ETF雷达 · A股量化研究</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif; background: #0d1117; color: #e6edf3; min-height: 100vh; }}
.navbar {{ background: #161b22; border-bottom: 1px solid #30363d; padding: 0 32px; display: flex; align-items: center; height: 60px; gap: 24px; position: sticky; top: 0; z-index: 100; flex-wrap: wrap; }}
.navbar-brand {{ color: #58a6ff; font-weight: 700; font-size: 16px; text-decoration: none; white-space: nowrap; }}
.navbar-links {{ display: flex; gap: 2px; flex-wrap: wrap; }}
.navbar-links a {{ color: #8b949e; text-decoration: none; font-size: 13px; padding: 5px 10px; border-radius: 6px; transition: all .15s; }}
.navbar-links a:hover {{ color: #e6edf3; background: #21262d; }}
.navbar-links a.active {{ color: #e6edf3; background: #21262d; }}
.navbar-date {{ margin-left: auto; font-size: 12px; color: #484f58; }}
.container {{ max-width: 1400px; margin: 0 auto; padding: 24px 20px; }}
h1 {{ font-size: 22px; margin-bottom: 6px; }}
.sub {{ color: #8b949e; font-size: 13px; margin-bottom: 20px; }}
.stat-row {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 20px; }}
.stat-card {{ background: #161b22; border: 1px solid #30363d; border-radius: 10px;
              padding: 12px 18px; min-width: 110px; text-align: center; cursor: pointer;
              transition: border-color .15s; user-select: none; }}
.stat-card:hover {{ border-color: #58a6ff; }}
.stat-card.active {{ border-color: #58a6ff; background: #1a2233; }}
.stat-card .sv {{ font-size: 26px; font-weight: 700; }}
.stat-card .sl {{ font-size: 12px; color: #8b949e; margin-top: 2px; }}
.sv-all {{ color: #e6edf3; }}
.sv-high {{ color: #e84c3d; }}
.sv-ma20 {{ color: #58a6ff; }}
.sv-ma60 {{ color: #ffa657; }}
.filter-bar {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; align-items: center; }}
.filter-label {{ font-size: 12px; color: #484f58; margin-right: 4px; }}
.ftab {{ background: #21262d; border: 1px solid #30363d; color: #8b949e;
         padding: 5px 14px; border-radius: 20px; cursor: pointer; font-size: 13px; transition: all .15s; }}
.ftab.active {{ background: #1f6feb; border-color: #1f6feb; color: #fff; }}
.ftab:hover:not(.active) {{ border-color: #58a6ff; color: #e6edf3; }}
.type-filter {{ display: flex; gap: 6px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
thead tr {{ background: #161b22; position: sticky; top: 56px; z-index: 10; }}
th {{ padding: 10px 8px; text-align: left; color: #8b949e; font-weight: 600;
      border-bottom: 1px solid #30363d; white-space: nowrap; }}
td {{ padding: 9px 8px; border-bottom: 1px solid #21262d; vertical-align: middle; }}
.etf-row {{ cursor: pointer; transition: background .1s; }}
.etf-row:hover td {{ background: #161b22; }}
.etf-row.hidden {{ display: none; }}
.etf-code {{ font-family: monospace; color: #8b949e; font-size: 12px; margin-right: 4px; }}
.etf-name {{ font-weight: 500; }}
.up {{ color: #e84c3d; }} .dn {{ color: #07a071; }}
.badge {{ display: inline-block; font-size: 11px; font-weight: 600; border-radius: 4px;
          padding: 2px 6px; margin: 1px; cursor: pointer; }}
.badge:hover {{ opacity: .8; }}
.badge-high    {{ background: rgba(232,76,61,.15);  color: #e84c3d; border: 1px solid rgba(232,76,61,.3); }}
.badge-ma20    {{ background: rgba(88,166,255,.12); color: #58a6ff; border: 1px solid rgba(88,166,255,.25); }}
.badge-ma60    {{ background: rgba(255,166,87,.12); color: #ffa657; border: 1px solid rgba(255,166,87,.25); }}
.badge-above60 {{ background: rgba(139,148,158,.1); color: #8b949e; border: 1px solid #30363d; }}
.type-badge {{ display: inline-block; font-size: 10px; font-weight: 700; border-radius: 3px;
               padding: 1px 5px; margin-right: 4px; vertical-align: middle; }}
.type-index  {{ background: rgba(88,166,255,.12); color: #58a6ff; border: 1px solid rgba(88,166,255,.2); }}
.type-sector {{ background: rgba(255,166,87,.12);  color: #ffa657; border: 1px solid rgba(255,166,87,.2); }}
.hold-row td {{ padding: 0; }}
.hold-cell {{ padding: 16px 24px !important; background: #0d1117; border-left: 3px solid #1f6feb; }}
.expand-inner {{ display: flex; gap: 24px; flex-wrap: wrap; align-items: flex-start; }}
.kline-wrap {{ flex: 0 0 auto; }}
.kline-legend {{ font-size: 11px; color: #8b949e; margin-top: 4px; display: flex; gap: 12px; flex-wrap: wrap; }}
.kline-legend span {{ display: flex; align-items: center; gap: 4px; }}
.hold-wrap {{ flex: 1 1 280px; }}
.no-hold {{ color: #484f58; font-size: 12px; padding: 12px 0; }}
.hold-table {{ font-size: 12px; max-width: 480px; }}
.hold-table th {{ top: auto; position: static; font-size: 11px; padding: 6px 8px; }}
.hold-table td {{ padding: 5px 8px; border-bottom: 1px solid #21262d; }}
.weight-bar-cell {{ display: flex; align-items: center; gap: 8px; }}
.weight-bar {{ height: 6px; background: #1f6feb; border-radius: 3px; min-width: 2px; }}
.empty {{ color: #484f58; text-align: center; padding: 60px; }}
.footer {{ text-align: center; color: #484f58; font-size: 12px; padding: 48px 0 24px; }}
.result-count {{ font-size: 12px; color: #484f58; margin-bottom: 8px; }}
.sortable-pct:hover {{ color: #e6edf3; }}
</style>
</head>
<body>
{_NAVBAR("etf.html", "数据日期：" + html_mod.escape(db_latest))}
<div class="container">
  <h1>📡 ETF雷达</h1>
  <p class="sub">数据日期：{html_mod.escape(db_latest)} · 成交额≥5亿 · 已去除债券/货币ETF · 点击行展开持仓</p>

  <!-- 统计卡片（可点击筛选信号） -->
  <div class="stat-row" id="sig-filter-cards">
    <div class="stat-card active" data-filter="" onclick="filterBySig(this,'')">
      <div class="sv sv-all">{len(rows)}</div><div class="sl">全部ETF</div>
    </div>
    <div class="stat-card" data-filter="历史新高" onclick="filterBySig(this,'历史新高')">
      <div class="sv sv-high">{n_new_high}</div><div class="sl">历史新高</div>
    </div>
    <div class="stat-card" data-filter="MA20向上" onclick="filterBySig(this,'MA20向上')">
      <div class="sv sv-ma20">{n_ma20}</div><div class="sl">MA20向上</div>
    </div>
    <div class="stat-card" data-filter="站上MA60" onclick="filterBySig(this,'站上MA60')">
      <div class="sv sv-ma60">{n_ma60}</div><div class="sl">站上MA60</div>
    </div>
  </div>

  <!-- 类型 + tab 筛选栏 -->
  <div class="filter-bar">
    <span class="filter-label">类型：</span>
    <div class="type-filter" id="type-filter">
      <button class="ftab active" data-type="" onclick="filterByType(this,'')">全部</button>
      <button class="ftab" data-type="index"  onclick="filterByType(this,'index')">🔵 宽基指数</button>
      <button class="ftab" data-type="sector" onclick="filterByType(this,'sector')">🟠 行业/主题</button>
    </div>
  </div>
  <div class="filter-bar" style="margin-bottom:16px">
    <span class="filter-label">范围：</span>
    <button class="ftab active" id="tab-signal" onclick="switchScope(this,'signal')">有信号 ({len(signal_rows)})</button>
    <button class="ftab" id="tab-index"  onclick="switchScope(this,'index')">宽基指数 ({len(index_rows)})</button>
    <button class="ftab" id="tab-sector" onclick="switchScope(this,'sector')">行业/主题 ({len(sector_rows)})</button>
  </div>

  <div class="result-count" id="result-count"></div>

  <div id="panel-signal" class="panel-scope">{signal_table}</div>
  <div id="panel-index"  class="panel-scope" style="display:none">{index_table}</div>
  <div id="panel-sector" class="panel-scope" style="display:none">{sector_table}</div>
</div>
<div class="footer">数据来源：AkShare · 每工作日 19:45 (北京时间) 自动更新</div>
<script>
// ── state ─────────────────────────────────────────────
let _scope = 'signal';   // which panel is visible
let _sigFilter = '';     // signal filter string (empty = all)
let _typeFilter = '';    // 'index' | 'sector' | ''

// ── scope switch (tab bar) ────────────────────────────
function switchScope(btn, scope) {{
  _scope = scope;
  document.querySelectorAll('.panel-scope').forEach(p => p.style.display = 'none');
  document.getElementById('panel-' + scope).style.display = '';
  document.querySelectorAll('#tab-signal,#tab-index,#tab-sector')
    .forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  applyFilters();
}}

// ── signal filter (stat cards) ────────────────────────
function filterBySig(card, sig) {{
  _sigFilter = (_sigFilter === sig) ? '' : sig;   // toggle
  document.querySelectorAll('#sig-filter-cards .stat-card')
    .forEach(c => c.classList.remove('active'));
  if (!_sigFilter) {{
    document.querySelector('#sig-filter-cards .stat-card[data-filter=""]')
      .classList.add('active');
  }} else {{
    card.classList.add('active');
  }}
  applyFilters();
}}

// ── type filter (宽基 / 行业) ──────────────────────────
function filterByType(btn, type) {{
  _typeFilter = (_typeFilter === type) ? '' : type;  // toggle
  document.querySelectorAll('#type-filter .ftab')
    .forEach(b => b.classList.remove('active'));
  if (!_typeFilter) {{
    document.querySelector('#type-filter .ftab[data-type=""]').classList.add('active');
  }} else {{
    btn.classList.add('active');
  }}
  applyFilters();
}}

// ── apply both filters to visible panel ───────────────
function applyFilters() {{
  const panel = document.getElementById('panel-' + _scope);
  if (!panel) return;
  let visible = 0;
  panel.querySelectorAll('tr.etf-row').forEach(tr => {{
    const sigAttr = tr.dataset.sig || '';
    const typeAttr = tr.dataset.type || '';
    const sigOk  = !_sigFilter  || sigAttr.includes(_sigFilter);
    const typeOk = !_typeFilter || typeAttr === _typeFilter;
    const show   = sigOk && typeOk;
    tr.classList.toggle('hidden', !show);
    // also hide/show its sibling hold-row
    const next = tr.nextElementSibling;
    if (next && next.classList.contains('hold-row')) {{
      if (!show) next.style.display = 'none';
    }}
    if (show) visible++;
  }});
  const cnt = document.getElementById('result-count');
  if (cnt) cnt.textContent = visible ? `显示 ${{visible}} 只` : '没有符合条件的ETF';
}}

// ── hold detail expand ────────────────────────────────
function toggleHold(id) {{
  const row = document.getElementById(id);
  if (!row) return;
  // only toggle if parent row is visible
  const prev = row.previousElementSibling;
  if (prev && prev.classList.contains('hidden')) return;
  const opening = row.style.display === 'none';
  row.style.display = opening ? 'table-row' : 'none';
  if (opening) {{
    // extract code from id (format: tabid_code)
    const code = id.split('_').slice(1).join('_');
    drawKline(code);
  }}
}}

// ── sort by pct_chg ───────────────────────────────────
const _sortState = {{}};   // tab_id → 'asc' | 'desc' | null
function sortByPct(tabId) {{
  const dir = (_sortState[tabId] === 'desc') ? 'asc' : 'desc';
  _sortState[tabId] = dir;
  const icon = document.getElementById('sort-icon-' + tabId);
  if (icon) icon.textContent = dir === 'desc' ? '↓' : '↑';

  const tbody = document.querySelector('#tbl-' + tabId + ' tbody');
  if (!tbody) return;

  // 收集 (etf-row, hold-row) 对
  const pairs = [];
  const children = Array.from(tbody.children);
  for (let i = 0; i < children.length; i++) {{
    const tr = children[i];
    if (tr.classList.contains('etf-row')) {{
      const next = children[i + 1];
      pairs.push({{
        etf: tr,
        hold: (next && next.classList.contains('hold-row')) ? next : null,
        pct: parseFloat(tr.dataset.pct || '0'),
      }});
      if (next && next.classList.contains('hold-row')) i++;
    }}
  }}

  pairs.sort((a, b) => dir === 'desc' ? b.pct - a.pct : a.pct - b.pct);

  pairs.forEach(p => {{
    tbody.appendChild(p.etf);
    if (p.hold) tbody.appendChild(p.hold);
  }});
}}

// badge click → filter by that signal
document.addEventListener('click', function(e) {{
  const badge = e.target.closest('.badge[data-sig]');
  if (!badge) return;
  e.stopPropagation();
  const sig = badge.dataset.sig;
  const card = document.querySelector(`#sig-filter-cards .stat-card[data-filter="${{sig}}"]`);
  if (card) filterBySig(card, sig);
}});

// init count
window.addEventListener('DOMContentLoaded', applyFilters);

// ── K线数据 ─────────────────────────────────────────────
const KLINE = {kline_json};
// 每条: [date, open, high, low, close, amtYi, ma5, ma20, ma60]

function drawKline(code) {{
  const canvas = document.getElementById('kc_' + code);
  if (!canvas) return;
  const bars = KLINE[code];
  if (!bars || bars.length < 2) {{
    const ctx2 = canvas.getContext('2d');
    ctx2.fillStyle = '#484f58';
    ctx2.font = '13px sans-serif';
    ctx2.fillText('暂无K线数据', 20, 120);
    return;
  }}
  if (canvas.dataset.drawn === '1') return;  // 已绘制，不重复

  const W = canvas.width, H = canvas.height;
  const VOL_H = 50;  // 成交额区高度
  const CHART_H = H - VOL_H - 4;
  const PAD_L = 8, PAD_R = 8, PAD_T = 12;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, W, H);

  const n = bars.length;
  const barW = Math.max(2, Math.floor((W - PAD_L - PAD_R) / n) - 1);
  const gap   = Math.floor((W - PAD_L - PAD_R) / n);

  // 价格范围
  let pMin = Infinity, pMax = -Infinity;
  for (const b of bars) {{
    if (b[2] > 0) pMax = Math.max(pMax, b[2]);
    if (b[3] > 0) pMin = Math.min(pMin, b[3]);
  }}
  const pRange = pMax - pMin || pMax * 0.02 || 1;
  const py = v => PAD_T + (pMax - v) / pRange * (CHART_H - PAD_T - 4);

  // 成交额范围
  let aMax = 0;
  for (const b of bars) aMax = Math.max(aMax, b[5]);
  if (!aMax) aMax = 1;
  const ay = v => H - (v / aMax) * (VOL_H - 4);

  // 背景网格（3条横线）
  ctx.strokeStyle = '#21262d';
  ctx.lineWidth = 1;
  for (let i = 1; i <= 3; i++) {{
    const y = PAD_T + (CHART_H - PAD_T) * i / 4;
    ctx.beginPath(); ctx.moveTo(PAD_L, y); ctx.lineTo(W - PAD_R, y); ctx.stroke();
  }}

  // MA 线
  const MA_COLORS = ['#ffa657', '#79c0ff', '#ff7b72'];  // ma5, ma20, ma60
  [6, 7, 8].forEach((idx, mi) => {{
    ctx.beginPath();
    ctx.strokeStyle = MA_COLORS[mi];
    ctx.lineWidth = 1;
    let started = false;
    bars.forEach((b, i) => {{
      const v = b[idx];
      if (!v) return;
      const x = PAD_L + i * gap + gap / 2;
      const y = py(v);
      if (!started) {{ ctx.moveTo(x, y); started = true; }} else ctx.lineTo(x, y);
    }});
    ctx.stroke();
  }});

  // 蜡烛
  bars.forEach((b, i) => {{
    const [date, o, h, l, c] = b;
    if (!c) return;
    const x = PAD_L + i * gap;
    const cx = x + gap / 2;
    const isUp = c >= o;
    const color = isUp ? '#e84c3d' : '#07a071';
    ctx.fillStyle = color;
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;

    // 影线
    ctx.beginPath();
    ctx.moveTo(cx, py(h));
    ctx.lineTo(cx, py(l));
    ctx.stroke();

    // 实体
    const yTop = py(Math.max(o, c));
    const yBot = py(Math.min(o, c));
    const bodyH = Math.max(1, yBot - yTop);
    if (isUp) {{
      ctx.strokeRect(x + 1, yTop, barW - 2, bodyH);
    }} else {{
      ctx.fillRect(x + 1, yTop, barW - 2, bodyH);
    }}

    // 成交额柱
    const volColor = isUp ? '#5a1f1f' : '#1a3a2a';
    ctx.fillStyle = volColor;
    const volY = ay(b[5]);
    ctx.fillRect(x + 1, volY, barW - 2, H - volY);
  }});

  // 分隔线
  ctx.strokeStyle = '#30363d';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(PAD_L, H - VOL_H);
  ctx.lineTo(W - PAD_R, H - VOL_H);
  ctx.stroke();

  // 最新收盘价标注
  const last = bars[bars.length - 1];
  ctx.fillStyle = '#e6edf3';
  ctx.font = '10px sans-serif';
  ctx.fillText(last[4].toFixed(3), W - PAD_R - 40, py(last[4]) - 3);

  canvas.dataset.drawn = '1';

  // 图例
  const legend = document.getElementById('kl_' + code);
  if (legend) {{
    legend.innerHTML =
      `<span><span style="display:inline-block;width:20px;height:2px;background:#ffa657"></span> MA5</span>` +
      `<span><span style="display:inline-block;width:20px;height:2px;background:#79c0ff"></span> MA20</span>` +
      `<span><span style="display:inline-block;width:20px;height:2px;background:#ff7b72"></span> MA60</span>` +
      `<span style="color:#484f58">${{n}}根 · 最新 ${{last[0]}}</span>`;
  }}
}}
</script>
</body>
</html>"""


def render_emotion_html(summary: dict[str, object]) -> str:
    recent = summary.get("recent_emotion", [])
    streak_summary = summary.get("streak_summary", [])

    # recent already has emotion_score computed by build_report
    emotion_series = []
    for row in recent:
        emotion_series.append({
            "date": row["date"],
            "score": row.get("emotion_score") or 0,
            "limit_up": row.get("limit_up_count", 0) or 0,
            "limit_down": row.get("limit_down_count", 0) or 0,
            "up_count": row.get("up_count", 0) or 0,
            "down_count": row.get("down_count", 0) or 0,
            "up_ratio": round((row.get("up_ratio_rate") or 0) * 100, 1),
            "amount_e8": row.get("amount_e8", 0),
        })

    all_labels  = json.dumps([r["date"]      for r in emotion_series], ensure_ascii=False)
    all_scores  = json.dumps([r["score"]     for r in emotion_series])
    all_lu      = json.dumps([r["limit_up"]  for r in emotion_series])
    all_ld      = json.dumps([r["limit_down"] for r in emotion_series])
    all_up      = json.dumps([r["up_count"]  for r in emotion_series])
    all_dn      = json.dumps([r["down_count"] for r in emotion_series])
    all_amt     = json.dumps([r["amount_e8"] for r in emotion_series])

    streak_rows_html = ""
    for r in streak_summary:
        lu_rate = r.get("next_limit_up_rate")
        lu_str = f"{lu_rate*100:.1f}%" if lu_rate is not None else "-"
        streak_rows_html += f"""<tr>
          <td><b>{html.escape(str(r['streak']))}板</b></td>
          <td>{fmt_num(r.get('count'), 0)}</td>
          <td>{lu_str}</td>
          <td>{fmt_num(r.get('gap_pct'))}%</td>
          <td>{fmt_num(r.get('open_to_close_pct'))}%</td>
          <td>{fmt_num(r.get('median_open_to_close_pct'))}%</td>
        </tr>"""

    latest_e = emotion_series[-1] if emotion_series else {}
    score = latest_e.get("score", 0)
    if score >= 80:
        label, cls = "极热 🔥", "hot"
    elif score >= 60:
        label, cls = "偏暖 ☀️", "warm"
    elif score >= 40:
        label, cls = "中性 🌤", "cool"
    else:
        label, cls = "偏冷 🌧", "cold"

    amt_val = float(latest_e.get("amount_e8") or 0)
    amt_str = f"{amt_val/10000:.2f}万亿" if amt_val >= 10000 else f"{amt_val:.0f}亿"
    start_date_str = html.escape(str(summary.get("start_date", "")))
    latest_date_str = html.escape(str(summary.get("latest_date", "")))

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>市场温度 · A股量化研究</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif; background: #0d1117; color: #e6edf3; min-height: 100vh; }}
.navbar {{ background: #161b22; border-bottom: 1px solid #30363d; padding: 0 32px; display: flex; align-items: center; height: 60px; gap: 24px; position: sticky; top: 0; z-index: 100; flex-wrap: wrap; }}
.navbar-brand {{ color: #58a6ff; font-weight: 700; font-size: 16px; text-decoration: none; white-space: nowrap; }}
.navbar-links {{ display: flex; gap: 2px; flex-wrap: wrap; }}
.navbar-links a {{ color: #8b949e; text-decoration: none; font-size: 13px; padding: 5px 10px; border-radius: 6px; transition: all .15s; }}
.navbar-links a:hover {{ color: #e6edf3; background: #21262d; }}
.navbar-links a.active {{ color: #e6edf3; background: #21262d; }}
.navbar-date {{ margin-left: auto; font-size: 12px; color: #484f58; }}
.container {{ max-width: 1100px; margin: 0 auto; padding: 24px 20px; }}
h1 {{ font-size: 22px; margin-bottom: 6px; }}
.sub {{ color: #8b949e; font-size: 13px; margin-bottom: 20px; }}
.score-row {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 20px; }}
.score-card {{ background: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 18px 24px; min-width: 140px; }}
.score-card .label {{ color: #8b949e; font-size: 12px; margin-bottom: 6px; }}
.score-card .val {{ font-size: 32px; font-weight: 700; }}
.score-card .sub2 {{ font-size: 12px; color: #8b949e; margin-top: 4px; }}
.hot {{ color: #ff7043; }} .warm {{ color: #ffa726; }} .cool {{ color: #42a5f5; }} .cold {{ color: #78909c; }}
.chart-card {{ background: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 20px; margin-bottom: 20px; }}
.toolbar {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-bottom: 12px; }}
.ctab {{ background: #21262d; border: 1px solid #30363d; color: #8b949e; padding: 4px 12px; border-radius: 14px; cursor: pointer; font-size: 12px; transition: all .15s; }}
.ctab.active {{ background: #1f6feb; border-color: #1f6feb; color: #fff; }}
.range-sep {{ width: 1px; height: 20px; background: #30363d; margin: 0 4px; }}
canvas {{ max-height: 280px; }}
.formula-box {{ background: #161b22; border: 1px solid #30363d; border-left: 3px solid #58a6ff; border-radius: 10px; padding: 16px 20px; margin-bottom: 20px; font-size: 13px; color: #8b949e; line-height: 1.8; }}
.formula-box strong {{ color: #e6edf3; }}
.formula-box code {{ background: #0d1117; padding: 2px 6px; border-radius: 4px; color: #ffa657; font-size: 12px; }}
.formula-box .ref {{ font-size: 11px; color: #484f58; margin-top: 8px; }}
.formula-box summary::-webkit-details-marker {{ display: none; }}
.formula-box[open] summary span span {{ display: none; }}
.streak-section {{ margin-top: 4px; }}
.streak-section h2 {{ font-size: 15px; margin-bottom: 12px; color: #8b949e; }}
table {{ width: 100%; border-collapse: collapse; background: #161b22; border-radius: 10px; overflow: hidden; font-size: 13px; }}
th {{ background: #0d1117; padding: 9px 12px; text-align: left; color: #8b949e; font-weight: 600; border-bottom: 1px solid #21262d; }}
td {{ padding: 9px 12px; border-bottom: 1px solid #21262d; }}
tr:last-child td {{ border-bottom: none; }}
.footer {{ text-align: center; color: #484f58; font-size: 12px; padding: 48px 0 24px; }}
</style>
</head>
<body>
{_NAVBAR("emotion.html", "最新数据：" + latest_date_str)}
<div class="container">
  <h1>🌡️ 市场温度</h1>
  <p class="sub">情绪分历史走势 · 涨跌停比 · 成交额 · 连板晋级统计 · 数据范围 {start_date_str} 至今</p>

  <div class="score-row">
    <div class="score-card">
      <div class="label">上涨 / 下跌家数</div>
      <div class="val" style="font-size:24px">
        <span style="color:#e84c3d">{latest_e.get('up_count', '-')}</span>
        <span style="color:#484f58;font-size:16px"> / </span>
        <span style="color:#07a071">{latest_e.get('down_count', '-')}</span>
      </div>
      <div class="sub2">{"⚠️ 冰点区域" if (latest_e.get('up_count') or 9999) <= 1000 else "上涨家数 / 下跌家数"}</div>
    </div>
    <div class="score-card">
      <div class="label">成交额</div>
      <div class="val" style="font-size:24px">{amt_str}</div>
      <div class="sub2">全市场</div>
    </div>
    <div class="score-card">
      <div class="label">最新情绪分</div>
      <div class="val {cls}">{score:.1f}</div>
      <div class="sub2">{label}</div>
    </div>
    <div class="score-card">
      <div class="label">涨停 / 跌停</div>
      <div class="val">{latest_e.get('limit_up', '-')} <span style="color:#484f58;font-size:18px">/</span> {latest_e.get('limit_down', '-')}</div>
      <div class="sub2">{html.escape(str(latest_e.get('date', '')))}</div>
    </div>
    <div class="score-card">
      <div class="label">上涨比例</div>
      <div class="val">{latest_e.get('up_ratio', '-')}%</div>
      <div class="sub2">当日上涨家数占比</div>
    </div>
  </div>

  <!-- 情绪分说明（折叠） -->
  <details class="formula-box" style="cursor:pointer">
    <summary style="list-style:none;outline:none">
      <span style="color:#8b949e;font-size:13px">情绪分计算说明 &nbsp;<span style="font-size:11px">▶ 点击展开</span></span>
    </summary>
    <div style="margin-top:10px">
      <code>情绪分 = ADR×40 + min(涨停率/3%,1)×40 − min(跌停率/2%,1)×20</code><br><br>
      <strong>ADR（涨跌家数比）</strong>= 上涨家数 ÷ (上涨+下跌家数)，取值 0~1，权重 40 分。<br>
      参考：NYSE Advance-Decline Ratio（涨跌线），Wind 市场宽度指标，申万宏源 A 股情绪指数均采用此项。<br><br>
      <strong>涨停率</strong> = 当日涨停家数 ÷ 可交易股票总数，历史均值约 0.8%，3% 以上满分，权重 40 分。<br>
      参考：东方财富、同花顺「当日涨停家数」情绪热度测量。<br><br>
      <strong>跌停惩罚</strong> = 当日跌停家数 ÷ 可交易股票总数，历史均值约 0.3%，2% 以上扣满，权重 −20 分。<br>
      <span class="ref">⚠️ 本指数为自定义合成指标，仅供辅助参考，不作为买卖依据。与任何商业指数无关联。</span>
    </div>
  </details>

  <!-- 图表区：4个独立图表 + 共用时间范围切换 -->
  <div class="toolbar" style="margin-bottom:12px">
    <button class="ctab active" onclick="switchRange(this,30)" id="range30">近30日</button>
    <button class="ctab" onclick="switchRange(this,90)" id="range90">近90日</button>
    <button class="ctab" onclick="switchRange(this,0)" id="rangeAll">全部</button>
  </div>
  <div class="chart-card">
    <div style="color:#8b949e;font-size:12px;margin-bottom:8px">情绪分</div>
    <canvas id="chartScore"></canvas>
  </div>
  <div class="chart-card">
    <div style="color:#8b949e;font-size:12px;margin-bottom:8px">涨跌家数</div>
    <canvas id="chartUpdown"></canvas>
  </div>
  <div class="chart-card">
    <div style="color:#8b949e;font-size:12px;margin-bottom:8px">涨跌停数</div>
    <canvas id="chartLu"></canvas>
  </div>
  <div class="chart-card">
    <div style="color:#8b949e;font-size:12px;margin-bottom:8px">成交额(亿)</div>
    <canvas id="chartAmt"></canvas>
  </div>

  <div class="streak-section">
    <h2>连板晋级统计（{start_date_str} 至今）</h2>
    <table>
      <thead><tr><th>连板级别</th><th>信号数</th><th>次日涨停率</th><th>均值跳空%</th><th>均值开收%</th><th>中位数开收%</th></tr></thead>
      <tbody>{streak_rows_html}</tbody>
    </table>
  </div>
</div>
<div class="footer">数据来源：AkShare · daily_bars 全量计算 · 每工作日 19:45 (北京时间) 自动更新</div>
<script>
const allLabels = {all_labels};
const allScores = {all_scores};
const allLu     = {all_lu};
const allLd     = {all_ld};
const allUp     = {all_up};
const allDn     = {all_dn};
const allAmt    = {all_amt};

let currentRange = 30;
const charts = {{}};

const chartOptions = (yTitle) => ({{
  responsive: true, maintainAspectRatio: true,
  interaction: {{ mode: 'index', intersect: false }},
  plugins: {{
    legend: {{ labels: {{ color: '#8b949e', boxWidth: 12 }} }},
    tooltip: {{
      backgroundColor: '#161b22',
      borderColor: '#30363d',
      borderWidth: 1,
      titleColor: '#e6edf3',
      bodyColor: '#8b949e',
    }}
  }},
  scales: {{
    x: {{ ticks: {{ color: '#484f58', maxTicksLimit: 12, maxRotation: 0 }}, grid: {{ color: '#21262d' }} }},
    y: {{ ticks: {{ color: '#8b949e' }}, grid: {{ color: '#21262d' }},
         title: {{ display: true, text: yTitle, color: '#484f58' }} }}
  }}
}});

// 冰点线插件（涨跌家数图）
const freezeLinePlugin = {{
  id: 'freezeLine',
  afterDraw(chartInst) {{
    if (chartInst.canvas.id !== 'chartUpdown') return;
    const yScale = chartInst.scales['y'];
    const xScale = chartInst.scales['x'];
    const y = yScale.getPixelForValue(1000);
    if (y < yScale.top || y > yScale.bottom) return;
    const ctx = chartInst.ctx;
    ctx.save();
    ctx.beginPath();
    ctx.setLineDash([6, 4]);
    ctx.strokeStyle = 'rgba(88,166,255,0.55)';
    ctx.lineWidth = 1.5;
    ctx.moveTo(xScale.left, y);
    ctx.lineTo(xScale.right, y);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = 'rgba(88,166,255,0.8)';
    ctx.font = '11px sans-serif';
    ctx.fillText('冰点线 1000', xScale.left + 6, y - 5);
    ctx.restore();
  }}
}};

function sliceData(n) {{
  if (!n) return {{ labels: allLabels, scores: allScores, lu: allLu, ld: allLd, up: allUp, dn: allDn, amt: allAmt }};
  return {{
    labels: allLabels.slice(-n),
    scores: allScores.slice(-n),
    lu:     allLu.slice(-n),
    ld:     allLd.slice(-n),
    up:     allUp.slice(-n),
    dn:     allDn.slice(-n),
    amt:    allAmt.slice(-n),
  }};
}}

function renderAll() {{
  const d = sliceData(currentRange);

  const configs = [
    {{ id: 'chartScore', datasets: [
      {{ label: '情绪分', data: d.scores, borderColor: '#ffa726', backgroundColor: 'rgba(255,167,38,.1)', tension: .35, fill: true, pointRadius: 2, pointHoverRadius: 5 }}
    ], yTitle: '情绪分 (0-100)' }},
    {{ id: 'chartUpdown', datasets: [
      {{ label: '上涨家数', data: d.up, borderColor: '#e84c3d', backgroundColor: 'rgba(232,76,61,.08)', tension: .3, fill: false, pointRadius: 2, pointHoverRadius: 5 }},
      {{ label: '下跌家数', data: d.dn, borderColor: '#07a071', backgroundColor: 'rgba(7,160,113,.08)', tension: .3, fill: false, pointRadius: 2, pointHoverRadius: 5 }},
    ], yTitle: '家数' }},
    {{ id: 'chartLu', datasets: [
      {{ label: '涨停数', data: d.lu, borderColor: '#e84c3d', backgroundColor: 'rgba(232,76,61,.1)', tension: .35, fill: false, pointRadius: 2, pointHoverRadius: 5 }},
      {{ label: '跌停数', data: d.ld, borderColor: '#07a071', backgroundColor: 'rgba(7,160,113,.1)', tension: .35, fill: false, pointRadius: 2, pointHoverRadius: 5 }},
    ], yTitle: '家数' }},
    {{ id: 'chartAmt', datasets: [
      {{ label: '成交额(亿)', data: d.amt, borderColor: '#58a6ff', backgroundColor: 'rgba(88,166,255,.1)', tension: .35, fill: true, pointRadius: 2, pointHoverRadius: 5 }}
    ], yTitle: '亿元' }},
  ];

  configs.forEach(({{ id, datasets, yTitle }}) => {{
    if (charts[id]) charts[id].destroy();
    charts[id] = new Chart(document.getElementById(id), {{
      type: 'line',
      data: {{ labels: d.labels, datasets }},
      plugins: [freezeLinePlugin],
      options: chartOptions(yTitle),
    }});
  }});
}}

function switchRange(btn, n) {{
  document.querySelectorAll('.ctab[onclick*="switchRange"]').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  currentRange = n;
  renderAll();
}}

renderAll();
</script>
</body>
</html>"""


def build_report(args: argparse.Namespace) -> tuple[
    dict[str, object],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict],
    list[dict[str, object]],
]:
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
    # 全量口径的涨跌家数（与东财一致，不过滤eligible）
    latest_stats_all = conn.execute(
        """
        SELECT
            SUM(CASE WHEN b.pct_chg > 0 THEN 1 ELSE 0 END) AS up_count_all,
            SUM(CASE WHEN b.pct_chg < 0 THEN 1 ELSE 0 END) AS down_count_all
        FROM daily_bars b JOIN stocks s ON s.code=b.code
        WHERE b.date = ? AND s.market != 'Other'
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
    latest_limit_up_count_calc = sum(1 for row in latest_rows if is_limit_up(float(row["pct_chg"]), row["market"], bool(row["is_st"])))
    latest_limit_down_count_calc = sum(1 for row in latest_rows if is_limit_down(float(row["pct_chg"]), row["market"], bool(row["is_st"])))

    # 优先用东财接口涨跌停数（收盘封板口径），无则 fallback 自算
    md_latest = conn.execute(
        "SELECT zt_count, dt_count FROM market_daily WHERE date = ?", (latest_date,)
    ).fetchone()
    latest_limit_up_count = int(md_latest["zt_count"]) if md_latest and md_latest["zt_count"] is not None else latest_limit_up_count_calc
    latest_limit_down_count = int(md_latest["dt_count"]) if md_latest and md_latest["dt_count"] is not None else latest_limit_down_count_calc
    eligible_count = int(latest_stats["eligible_count"] or 0)
    # 情绪分ADR用eligible口径（涨停判断准确），展示用全量口径与东财对齐
    up_count = int(latest_stats["up_count"] or 0)
    down_count = int(latest_stats["down_count"] or 0)
    up_count_display = int(latest_stats_all["up_count_all"] or 0)
    down_count_display = int(latest_stats_all["down_count_all"] or 0)
    up_ratio = up_count / eligible_count if eligible_count else None

    def calc_emotion(n: int, up: int, down: int, lu: int, ld: int) -> float | None:
        """
        业界常用 A 股情绪分（0-100），三指标加权：
          - 涨跌家数比（ADR）= 上涨家数 / (上涨+下跌家数)，权重 40 分
            参考：Wind 市场宽度指标、申万宏源情绪指数
          - 涨停率 = 涨停数 / 可交易股票数，历史均值约 0.8%，满分阈值 3%，权重 40 分
            参考：东方财富、同花顺「涨停家数」指标
          - 跌停惩罚 = 跌停数 / 可交易股票数，历史均值约 0.3%，满分扣除阈值 2%，权重 -20 分
        合计: score = ADR×40 + min(lu_rate/0.03,1)×40 - min(ld_rate/0.02,1)×20
        结果裁剪至 [0, 100]。
        """
        if not n:
            return None
        adr = up / (up + down) if (up + down) else 0.5
        lu_rate = lu / n
        ld_rate = ld / n
        raw = adr * 40 + min(lu_rate / 0.03, 1.0) * 40 - min(ld_rate / 0.02, 1.0) * 20
        return round(max(0.0, min(100.0, raw)), 1)

    emotion_score = calc_emotion(eligible_count, up_count, down_count, latest_limit_up_count, latest_limit_down_count)

    # 历史情绪：从 start_date 起全量，供 emotion.html 按时间段切换
    recent_emotion_rows = []
    history_sql = """
    SELECT b.date,
           COUNT(*) AS n,
           SUM(CASE WHEN b.pct_chg > 0 THEN 1 ELSE 0 END) AS up_count,
           SUM(CASE WHEN b.pct_chg < 0 THEN 1 ELSE 0 END) AS down_count,
           SUM(b.amount) / 100000000.0 AS amount_e8
    FROM daily_bars b
    JOIN stocks s ON s.code = b.code
    WHERE b.date >= ? AND s.eligible = 1
    GROUP BY b.date
    ORDER BY b.date ASC
    """
    # 全量口径涨跌家数（展示用，与东财对齐）
    history_sql_all = """
    SELECT b.date,
           SUM(CASE WHEN b.pct_chg > 0 THEN 1 ELSE 0 END) AS up_count_all,
           SUM(CASE WHEN b.pct_chg < 0 THEN 1 ELSE 0 END) AS down_count_all
    FROM daily_bars b JOIN stocks s ON s.code=b.code
    WHERE b.date >= ? AND s.market != 'Other'
    GROUP BY b.date
    """
    all_updn = {r["date"]: dict(r) for r in conn.execute(history_sql_all, (args.start_date,))}
    # 从 market_daily 表读接口涨跌停数（优先使用）
    all_market_daily = {
        r["date"]: dict(r)
        for r in conn.execute(
            "SELECT date, zt_count, dt_count FROM market_daily WHERE date >= ?", (args.start_date,)
        )
    }
    for hrow in conn.execute(history_sql, (args.start_date,)):
        day_rows2 = conn.execute(
            "SELECT b.pct_chg, s.market, s.is_st FROM daily_bars b JOIN stocks s ON s.code=b.code WHERE b.date=? AND s.eligible=1",
            (hrow["date"],),
        ).fetchall()
        lu_calc = sum(1 for r in day_rows2 if is_limit_up(float(r["pct_chg"]), r["market"], bool(r["is_st"])))
        ld_calc = sum(1 for r in day_rows2 if is_limit_down(float(r["pct_chg"]), r["market"], bool(r["is_st"])))
        md = all_market_daily.get(hrow["date"], {})
        lu = int(md["zt_count"]) if md.get("zt_count") is not None else lu_calc
        ld = int(md["dt_count"]) if md.get("dt_count") is not None else ld_calc
        n = hrow["n"] or 1
        score = calc_emotion(n, hrow["up_count"] or 0, hrow["down_count"] or 0, lu, ld)
        updn_all = all_updn.get(hrow["date"], {})
        recent_emotion_rows.append({
            "date": hrow["date"],
            "eligible_count": n,
            "up_count": int(updn_all.get("up_count_all") or 0),
            "down_count": int(updn_all.get("down_count_all") or 0),
            "up_ratio_rate": (hrow["up_count"] or 0) / n,
            "limit_up_count": lu,
            "limit_down_count": ld,
            "amount_e8": round(float(hrow["amount_e8"] or 0), 2),
            "emotion_score": score,
        })

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
    lhb_rows = fetch_lhb_rows(conn, latest_date)
    lhb_seat_stats = fetch_lhb_seat_stats(conn, latest_date)
    screen_rows = fetch_screen_results(conn, latest_date)
    module_latest_dates = {
        "daily_bars": safe_scalar(conn, "SELECT MAX(date) FROM daily_bars"),
        "market_daily": safe_scalar(conn, "SELECT MAX(date) FROM market_daily"),
        "limit_up_pool": safe_scalar(conn, "SELECT MAX(date) FROM limit_up_pool"),
        "popularity_rankings": safe_scalar(conn, "SELECT MAX(date) FROM popularity_rankings"),
        "lhb_records": safe_scalar(conn, "SELECT MAX(date) FROM lhb_records"),
        "lhb_seats": safe_scalar(conn, "SELECT MAX(date) FROM lhb_seats"),
        "etf_daily": safe_scalar(conn, "SELECT MAX(date) FROM etf_daily"),
        "screen_results": safe_scalar(conn, "SELECT MAX(date) FROM screen_results"),
        "strategy_backtests": safe_scalar(conn, "SELECT MAX(end_date) FROM strategy_backtests"),
    }
    data_status = build_data_status(latest_date, module_latest_dates)

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
        "git": get_git_info(),
        "latest_market": {
            "eligible_count": eligible_count,
            "up_ratio": up_ratio,
            "up_count": up_count_display,
            "down_count": down_count_display,
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
        "data_status": data_status,
        "streak_summary": streak_summary_rows,
        "recent_emotion": recent_emotion_rows,
    }
    return summary, latest_top_amount, latest_hot, popularity_rows, limit_pool_rows, strategy_rows, lhb_rows, lhb_seat_stats, screen_rows


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


def data_status_table(status_rows: list[dict[str, object]]) -> str:
    if not status_rows:
        return "<p>No data.</p>"
    body_rows = []
    for row in status_rows:
        status = str(row["status"])
        status_class = {
            "fresh": "status-fresh",
            "lagging": "status-lagging",
            "stale": "status-stale",
        }.get(status, "status-missing")
        gap_text = "-" if row["gap_days"] is None else str(row["gap_days"])
        latest_text = row["latest_date"] or "-"
        body_rows.append(
            "<tr>"
            f"<td>{html.escape(str(row['label']))}</td>"
            f"<td>{html.escape(str(latest_text))}</td>"
            f"<td>{html.escape(str(gap_text))}</td>"
            f"<td><span class='status-pill {status_class}'>{html.escape(str(row['status_label']))}</span></td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>模块</th><th>最新日期</th><th>落后天数</th><th>状态</th></tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody></table>"
    )


def publish_static_assets(output_dir: Path) -> None:
    for name in ("index.html", "index-responsive.css"):
        source = STATIC_ASSETS_DIR / name
        if source.exists():
            shutil.copy2(source, output_dir / name)


def render_html(summary: dict[str, object], latest_top_amount: list[dict[str, object]], latest_hot: list[dict[str, object]], popularity_rows: list[dict[str, object]], limit_pool_rows: list[dict[str, object]], strategy_rows: list[dict[str, object]], screen_rows: list[dict[str, object]] | None = None) -> str:
    candidate_columns = [("code", "代码"), ("name", "名称"), ("market", "市场"), ("pct", "涨跌幅%"), ("amount_e8", "成交额(亿)"), ("turnover", "换手率%"), ("is_limit_up", "涨停"), ("streak", "连板"), ("hot_score", "热度分")]
    popularity_columns = [("source", "来源"), ("rank", "排名"), ("code", "代码"), ("name", "名称"), ("score", "评分"), ("pct", "涨跌幅%"), ("amount_e8", "成交额(亿)"), ("turnover", "换手率%")]
    limit_pool_display_rows = []
    for row in limit_pool_rows:
        display_row = dict(row)
        display_row["seal_amount_yi"] = None if row.get("seal_amount") is None else float(row["seal_amount"]) / 100_000_000
        limit_pool_display_rows.append(display_row)
    limit_columns = [("source", "来源"), ("code", "代码"), ("name", "名称"), ("reason", "涨停原因/行业"), ("streak", "连板数"), ("first_limit_time", "首次封板"), ("last_limit_time", "最后封板"), ("seal_amount_yi", "封单金额(亿)"), ("amount_e8", "成交额(亿)")]
    strategy_columns = [("strategy", "策略"), ("trades", "交易次数"), ("signal_days", "信号天数"), ("win_rate", "胜率"), ("avg_return_pct", "均值%"), ("median_return_pct", "中位数%"), ("total_batch_return_pct", "批次总收益%"), ("max_drawdown_pct", "最大回撤%"), ("avg_gap_pct", "均值跳空%"), ("avg_hold_days", "均值持仓天")]

    def _render_screen_section(rows: list[dict] | None) -> str:
        if not rows:
            return ""
        from itertools import groupby
        import json as _json
        sections = []
        for rule_id, group in groupby(rows, key=lambda r: r["rule_id"]):
            items = list(group)
            screen_date = items[0]["date"] if items else ""
            rule_labels = {
                "new_high_momentum": "近3日历史新高 + 成交额>10亿 + 总市值100-500亿",
            }
            label = rule_labels.get(rule_id, rule_id)
            trs = ""
            for r in items:
                d = r.get("detail") or {}
                trs += f"""<tr>
                  <td>{html.escape(r['code'])}</td>
                  <td>{html.escape(r['name'] or '')}</td>
                  <td>{html.escape(d.get('market',''))}</td>
                  <td>{d.get('close','')}</td>
                  <td>{d.get('recent_high','')}</td>
                  <td>{d.get('hist_high','')}</td>
                  <td>{d.get('max_amount_yi','')}</td>
                  <td>{d.get('total_mv_yi','')}</td>
                </tr>"""
            sections.append(f"""<h2>选股信号 · {html.escape(label)} <span class="muted" style="font-size:13px;font-weight:400">({html.escape(screen_date)}，共{len(items)}只)</span></h2>
            <table><thead><tr>
              <th>代码</th><th>名称</th><th>市场</th><th>收盘</th>
              <th>近期新高</th><th>历史高</th><th>成交额(亿)</th><th>总市值(亿)</th>
            </tr></thead><tbody>{trs}</tbody></table>""")
        return "\n".join(sections)

    streak_columns = [("streak", "连板数"), ("count", "信号数"), ("next_limit_up_rate", "次日涨停率"), ("gap_pct", "均值跳空%"), ("open_to_close_pct", "均值开收%"), ("median_open_to_close_pct", "中位数开收%")]
    emotion_columns = [("date", "日期"), ("eligible_count", "股票数"), ("up_count", "上涨家数"), ("down_count", "下跌家数"), ("up_ratio_rate", "上涨比例"), ("limit_up_count", "涨停数"), ("limit_down_count", "跌停数"), ("amount_e8", "成交额(亿)")]
    style = _BASE_STYLE + """
    .container { max-width: 1500px; margin: 0 auto; padding: 28px 20px 72px; }
    .hero { margin-bottom: 20px; }
    h1 { font-size: 24px; margin-bottom: 8px; color: #e6edf3; }
    h2 { font-size: 16px; color: #8b949e; text-transform: uppercase; letter-spacing: .06em; border-left: 3px solid #58a6ff; padding-left: 12px; margin: 34px 0 14px; }
    h3 { color: #e6edf3; font-size: 14px; }
    .muted { color: #8b949e; font-size: 13px; line-height: 1.6; }
    .note { background: #161b22; border: 1px solid #30363d; border-left: 3px solid #ffa657; padding: 12px 14px; border-radius: 10px; color: #c9d1d9; margin: 14px 0 22px; font-size: 13px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin: 18px 0 28px; }
    .card { background: #161b22; border: 1px solid #30363d; border-radius: 14px; padding: 16px 18px; box-shadow: 0 8px 24px #0003; }
    .card p { color: #8b949e; font-size: 12px; line-height: 1.7; }
    .big { font-size: 30px; font-weight: 800; color: #e6edf3; margin: 6px 0; }
    .table-wrap { overflow-x: auto; }
    table { margin: 12px 0 28px; }
    th, td { padding: 9px 10px; border-bottom: 1px solid #30363d; text-align: right; font-size: 13px; white-space: nowrap; }
    th:first-child, td:first-child, th:nth-child(2), td:nth-child(2), th:nth-child(3), td:nth-child(3), th:nth-child(4), td:nth-child(4) { text-align: left; }
    .empty { color: #484f58; padding: 20px; background: #161b22; border: 1px solid #30363d; border-radius: 10px; }
    .status-pill { display:inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; font-weight: 600; }
    .status-fresh { background:#1a3a25; color:#07a071; }
    .status-lagging { background:#3a2a1a; color:#ffa657; }
    .status-stale { background:#3a1a1a; color:#e84c3d; }
    .status-missing { background:#2b3137; color:#c9d1d9; }
    .footer { text-align: center; color: #484f58; font-size: 12px; padding: 48px 0 12px; }
    @media (max-width: 760px) {
      .navbar { padding: 10px 16px; align-items: flex-start; }
      .navbar-date { margin-left: 0; width: 100%; }
      .container { padding: 24px 14px 56px; }
      th, td { padding: 8px 9px; font-size: 12px; }
    }
    """
    return f"""<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>A股量化研究报告 {html.escape(str(summary['latest_date']))}</title><style>{style}</style></head>
<body>
  {_NAVBAR("report.html", html.escape(str(summary["latest_date"])))}
  <main class="container">
    <div class="hero">
      <h1>A股量化研究报告</h1>
      <p class="muted">生成时间: {html.escape(str(summary['generated_at']))}　数据库: {html.escape(str(summary['db']))}　commit: {html.escape(str((summary.get('git') or {}).get('short_commit') or '-'))}</p>
      <div class="note">数据源为 SQLite 生产库。核心数据已由完备性审计校验；涨停池采用东方财富封板口径，日线涨跌幅和成交额来自本地 daily_bars。</div>
    </div>
    <div class="grid">{summary_cards(summary)}</div>
    <h2>数据更新状态</h2>{data_status_table(summary.get('data_status', []))}
    {_render_screen_section(screen_rows)}
    <h2>新高+量能策略回测</h2>{simple_table(strategy_rows, strategy_columns)}
    <h2>最新人气榜</h2>{simple_table(popularity_rows, popularity_columns, 80)}
    <h2 id="limitup">涨停池（东方财富封板口径）</h2>{simple_table(limit_pool_display_rows, limit_columns, 80)}
    <h2>热门候选股</h2>{simple_table(latest_hot, candidate_columns, 40)}
    <h2>量能龙头候选股</h2>{simple_table(latest_top_amount, candidate_columns, 40)}
    <h2>连板晋级统计</h2>{simple_table(summary['streak_summary'], streak_columns)}
    <h2 id="limitdown">近期市场情绪（涨跌停走势）</h2>{simple_table(summary['recent_emotion'], emotion_columns)}
    <h2>数据质量</h2><p class="muted">股票总数: {fmt_num(summary['stock_count'])}；可交易: {fmt_num(summary['eligible_stock_count'])}；日线数据: {fmt_num(summary['bar_count'])}；质量问题: {fmt_num(summary['quality_issue_count'])}；人气榜记录: {fmt_num(summary['popularity_count'])}；涨停池记录: {fmt_num(summary['limit_pool_count'])}；策略回测数: {fmt_num(summary['strategy_backtest_count'])}。</p>
    <div class="footer">数据来源：AkShare / 东方财富 · 每工作日 19:45 (北京时间) 自动更新</div>
  </main>
</body></html>"""


def render_markdown(summary: dict[str, object], latest_top_amount: list[dict[str, object]], latest_hot: list[dict[str, object]], popularity_rows: list[dict[str, object]], limit_pool_rows: list[dict[str, object]], strategy_rows: list[dict[str, object]]) -> str:
    latest = summary["latest_market"]
    events = summary["event_summaries"]
    lines = [
        "# A股量化研究报告",
        "",
        f"生成时间: {summary['generated_at']}",
        f"Git commit: {(summary.get('git') or {}).get('short_commit') or '-'}",
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


# ─────────────────────────────────────────────────────────────────────────────
# 连板晋级页面
# ─────────────────────────────────────────────────────────────────────────────



def render_monitor_html(summary: dict[str, object]) -> str:
    rows = summary.get("data_status", [])
    git = summary.get("git", {}) or {}
    fresh = sum(1 for row in rows if row.get("status") == "fresh")
    bad_rows = [row for row in rows if row.get("status") != "fresh"]
    overall = "暂无监控数据" if not rows else ("全部更新成功" if not bad_rows else f"{len(bad_rows)} 个模块需要处理")
    overall_class = "ok" if rows and not bad_rows else "warn"
    short_commit = git.get("short_commit") or "-"
    commit = git.get("commit") or "-"
    dirty_text = "有未提交变更" if git.get("dirty") else "工作区干净"

    def status_badge(row: dict[str, object]) -> str:
        status = str(row.get("status") or "unknown")
        label = html.escape(str(row.get("status_label") or status))
        return f'<span class="pill {status}">{label}</span>'

    status_rows = []
    for row in rows:
        gap = row.get("gap_days")
        gap_text = "-" if gap is None else f"{gap} 天"
        status_rows.append(
            "<tr>"
            f"<td>{html.escape(str(row.get('label') or row.get('key') or '-'))}</td>"
            f"<td>{html.escape(str(row.get('latest_date') or '-'))}</td>"
            f"<td>{html.escape(gap_text)}</td>"
            f"<td>{status_badge(row)}</td>"
            "</tr>"
        )
    body = "".join(status_rows) or '<tr><td colspan="4">暂无监控数据</td></tr>'

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>运行监控 · A股量化平台</title>
<style>
{_BASE_STYLE}
.hero {{ display:flex; justify-content:space-between; gap:24px; align-items:flex-end; margin:18px 0 24px; }}
.hero h1 {{ font-size:28px; margin-bottom:8px; }}
.sub {{ color:#8b949e; }}
.status-banner {{ border:1px solid #30363d; background:#161b22; border-radius:16px; padding:18px 22px; min-width:260px; }}
.status-banner.ok {{ border-color:#23863666; box-shadow:0 0 0 1px #23863622 inset; }}
.status-banner.warn {{ border-color:#d2992266; box-shadow:0 0 0 1px #d2992222 inset; }}
.status-label {{ font-size:12px; color:#8b949e; margin-bottom:6px; }}
.status-value {{ font-size:24px; font-weight:800; color:#e6edf3; }}
.monitor-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:16px; margin-bottom:24px; }}
.monitor-card {{ background:#161b22; border:1px solid #30363d; border-radius:14px; padding:18px 20px; }}
.monitor-card h3 {{ font-size:14px; color:#8b949e; margin-bottom:8px; }}
.monitor-card .value {{ font-size:20px; font-weight:700; word-break:break-all; }}
.monitor-card .desc {{ color:#8b949e; font-size:12px; margin-top:8px; }}
.status-table {{ background:#161b22; border:1px solid #30363d; border-radius:14px; overflow:hidden; }}
.status-table table {{ width:100%; }}
.status-table th, .status-table td {{ padding:10px 14px; }}
.status-table th {{ background:#0d1117; color:#8b949e; }}
.pill {{ display:inline-block; border-radius:999px; padding:3px 9px; font-size:12px; font-weight:700; }}
.pill.fresh {{ background:#1a3a25; color:#3fb950; }}
.pill.lagging {{ background:#3a2a1a; color:#ffa657; }}
.pill.stale, .pill.missing, .pill.future_date {{ background:#3a1a1a; color:#ff7b72; }}
.pill.unknown {{ background:#2b3137; color:#c9d1d9; }}
.code {{ font-family:ui-monospace,SFMono-Regular,Consolas,monospace; color:#79c0ff; }}
</style>
</head>
<body>
{_NAVBAR("monitor.html", "最新数据：" + html.escape(str(summary.get("latest_date", "-"))))}
<main class="page">
  <div class="hero">
    <div>
      <h1>运行监控</h1>
      <p class="sub">确认每日数据链路是否更新成功，并记录当前页面由哪个 Git commit 生成。</p>
    </div>
    <div class="status-banner {overall_class}">
      <div class="status-label">数据更新结论</div>
      <div class="status-value">{html.escape(overall)}</div>
      <div class="sub">已更新模块：{fresh} / {len(rows)}</div>
    </div>
  </div>

  <div class="monitor-grid">
    <div class="monitor-card"><h3>报告生成时间</h3><div class="value">{html.escape(str(summary.get("generated_at", "-")))}</div></div>
    <div class="monitor-card"><h3>最新交易数据</h3><div class="value">{html.escape(str(summary.get("latest_date", "-")))}</div></div>
    <div class="monitor-card"><h3>Git commit</h3><div class="value code">{html.escape(str(short_commit))}</div><div class="desc">{html.escape(str(git.get("subject") or "-"))}</div></div>
    <div class="monitor-card"><h3>Git 分支</h3><div class="value">{html.escape(str(git.get("branch") or "-"))}</div><div class="desc">{html.escape(dirty_text)}</div></div>
  </div>

  <div class="section-title">数据模块状态</div>
  <div class="status-table">
    <table>
      <thead><tr><th>模块</th><th>最新日期</th><th>落后天数</th><th>状态</th></tr></thead>
      <tbody>{body}</tbody>
    </table>
  </div>

  <div class="section-title">代码版本详情</div>
  <div class="monitor-card">
    <div>完整 commit：<span class="code">{html.escape(str(commit))}</span></div>
    <div class="desc">commit 时间：{html.escape(str(git.get("commit_time") or "-"))}</div>
    <div class="desc">生产运行日志路径：<span class="code">/data/quant_research/logs/daily-run-YYYYMMDD.log</span></div>
  </div>
</main>
</body>
</html>"""


def fetch_zt_pool_data(conn, latest_date: str) -> dict:
    """从 zt_pool / zt_previous 取连板数据，计算晋级率"""
    # 有数据的日期列表
    dates = [r[0] for r in conn.execute(
        "SELECT DISTINCT date FROM zt_pool ORDER BY date DESC LIMIT 60"
    ).fetchall()]

    if not dates:
        return {"dates": [], "daily": {}, "promotion": {}}

    daily = {}
    for d in dates:
        rows = conn.execute("""
            SELECT code, name, pct_chg, amount, float_mv, total_mv,
                   turnover, seal_amount, first_limit_time, open_times, streak, zt_stat, industry
            FROM zt_pool WHERE date=? ORDER BY streak DESC, amount DESC
        """, (d,)).fetchall()
        daily[d] = [dict(r) for r in rows]

    # 晋级率：用 zt_pool 相邻两日计算
    # 如果 streak 在 T 日比 T-1 日同代码增加了 1，说明晋级成功
    promotion = {}
    for i in range(len(dates) - 1):
        today, yesterday = dates[i], dates[i + 1]
        today_stocks = {r["code"]: r["streak"] for r in daily[today]}
        yest_stocks  = {r["code"]: r["streak"] for r in daily[yesterday]}
        # 对每个昨日连板层级统计晋级情况
        by_level: dict[int, dict] = {}
        for code, ys in yest_stocks.items():
            ts = today_stocks.get(code)
            level = ys  # 昨日连板层级
            if level not in by_level:
                by_level[level] = {"total": 0, "promoted": 0}
            by_level[level]["total"] += 1
            if ts is not None and ts == ys + 1:
                by_level[level]["promoted"] += 1
        promotion[today] = by_level

    return {"dates": dates, "daily": daily, "promotion": promotion}


def render_lianban_html(conn, latest_date: str) -> str:
    data = fetch_zt_pool_data(conn, latest_date)
    dates = data["dates"]
    daily = data["daily"]
    promotion = data["promotion"]

    if not dates:
        no_data = '<div class="no-data">暂无连板数据，请等待 update_zt_pool.py 采集后重新生成。</div>'
        return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>连板晋级 · A股量化平台</title>
<style>{_BASE_STYLE}</style></head><body>
{_NAVBAR("lianban.html", latest_date)}
<div class="page">{no_data}</div></body></html>"""

    # 统计卡片（最新日）
    today_rows = daily[dates[0]]
    streak_dist = {}
    for r in today_rows:
        s = int(r["streak"] or 1)
        streak_dist[s] = streak_dist.get(s, 0) + 1

    cards_html = ""
    for s in sorted(streak_dist):
        label = f"{s}板"
        cards_html += f'<div class="card"><div class="val">{streak_dist[s]}</div><div class="lbl">{label}</div></div>\n'

    # 日期 tab 选项
    date_opts = "\n".join(f'<option value="{d}"{" selected" if d==dates[0] else ""}>{d}</option>' for d in dates)

    # 晋级率表格数据（JSON 给 JS）
    import json as _json
    promo_json = _json.dumps(promotion, ensure_ascii=False)

    # 各日涨停池详情表（JSON 给 JS）
    daily_json = _json.dumps(daily, ensure_ascii=False)

    def streak_badge(s):
        cls = f"badge-streak-{min(s, 5)}"
        return f'<span class="badge {cls}">{s}连板</span>'

    def pct_cls(v):
        if v is None: return "flat"
        return "up" if v > 0 else ("down" if v < 0 else "flat")

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>连板晋级 · A股量化平台</title>
<style>
{_BASE_STYLE}
.promo-table td:first-child {{ font-weight:600; color:#e6edf3; }}
.bar {{ display:inline-block; height:8px; border-radius:4px; background:#3fb950; vertical-align:middle; margin-left:6px; }}
</style>
</head>
<body>
{_NAVBAR("lianban.html", latest_date)}
<div class="page">
  <h1>连板晋级统计</h1>
  <p class="subtitle">基于东财涨停池接口，统计每日各连板层级晋级率与今日梯队</p>

  <!-- 今日梯队概览 -->
  <section class="section">
    <div class="section-title">今日连板梯队 · {dates[0]}</div>
    <div class="card-grid" id="cards">
      {cards_html}
    </div>
  </section>

  <!-- 晋级率统计 -->
  <section class="section">
    <div class="section-title">历史晋级率</div>
    <div class="filter-row">
      <label style="color:#8b949e;font-size:13px;">查看日期：</label>
      <select id="promo-date-sel">{date_opts}</select>
    </div>
    <table id="promo-table">
      <thead><tr>
        <th>昨日连板</th><th>昨日只数</th><th>今日晋级</th><th>晋级率</th><th>未晋级</th>
      </tr></thead>
      <tbody id="promo-body"></tbody>
    </table>
  </section>

  <!-- 今日涨停明细 -->
  <section class="section">
    <div class="section-title">涨停明细</div>
    <div class="filter-row">
      <label style="color:#8b949e;font-size:13px;">日期：</label>
      <select id="detail-date-sel">{date_opts}</select>
      <select id="streak-filter">
        <option value="0">全部连板</option>
        <option value="2">≥2连板</option>
        <option value="3">≥3连板</option>
        <option value="4">≥4连板</option>
      </select>
    </div>
    <table id="detail-table">
      <thead><tr>
        <th>代码</th><th>名称</th><th>连板</th><th>涨跌幅</th>
        <th>成交额(亿)</th><th>流通市值(亿)</th><th>封板资金(亿)</th>
        <th>首封时间</th><th>炸板</th><th>板统计</th><th>行业</th>
      </tr></thead>
      <tbody id="detail-body"></tbody>
    </table>
  </section>

</div>

<script>
const PROMO = {promo_json};
const DAILY = {daily_json};

function fmtAmt(v) {{
  if (v == null) return '-';
  return (v / 1e8).toFixed(2);
}}
function pctCls(v) {{
  if (v == null) return 'flat';
  return v > 0 ? 'up' : (v < 0 ? 'down' : 'flat');
}}
function streakBadge(s) {{
  const cls = 'badge-streak-' + Math.min(s, 5);
  return `<span class="badge ${{cls}}">${{s}}连板</span>`;
}}

function renderPromo(date) {{
  const data = PROMO[date] || {{}};
  const levels = Object.keys(data).map(Number).sort((a,b)=>a-b);
  let html = '';
  if (!levels.length) {{ html = '<tr><td colspan="5" class="no-data">无晋级数据</td></tr>'; }}
  for (const lv of levels) {{
    const {{ total, promoted }} = data[lv];
    const rate = total > 0 ? (promoted / total * 100).toFixed(1) : '0.0';
    const barW = Math.round(promoted / total * 120);
    html += `<tr>
      <td>${{lv}}连板</td>
      <td>${{total}}</td>
      <td>${{promoted}}</td>
      <td><span class="up">${{rate}}%</span><span class="bar" style="width:${{barW}}px"></span></td>
      <td>${{total - promoted}}</td>
    </tr>`;
  }}
  document.getElementById('promo-body').innerHTML = html;
}}

function renderDetail(date, minStreak) {{
  const rows = (DAILY[date] || []).filter(r => (r.streak || 1) >= minStreak);
  let html = '';
  if (!rows.length) {{ html = '<tr><td colspan="11" class="no-data">无数据</td></tr>'; }}
  for (const r of rows) {{
    const cls = pctCls(r.pct_chg);
    const pct = r.pct_chg != null ? r.pct_chg.toFixed(2) + '%' : '-';
    html += `<tr>
      <td style="font-family:monospace;color:#79c0ff">${{r.code}}</td>
      <td>${{r.name}}</td>
      <td>${{streakBadge(r.streak || 1)}}</td>
      <td class="${{cls}}">${{pct}}</td>
      <td>${{fmtAmt(r.amount)}}</td>
      <td>${{fmtAmt(r.float_mv)}}</td>
      <td>${{fmtAmt(r.seal_amount)}}</td>
      <td>${{r.first_limit_time || '-'}}</td>
      <td>${{r.open_times ?? 0}}</td>
      <td style="color:#8b949e">${{r.zt_stat || '-'}}</td>
      <td style="color:#8b949e">${{r.industry || '-'}}</td>
    </tr>`;
  }}
  document.getElementById('detail-body').innerHTML = html;
}}

// 初始化
const promoSel  = document.getElementById('promo-date-sel');
const detailSel = document.getElementById('detail-date-sel');
const streakFil = document.getElementById('streak-filter');

renderPromo(promoSel.value);
renderDetail(detailSel.value, 0);

promoSel.addEventListener('change', () => renderPromo(promoSel.value));
detailSel.addEventListener('change', () => renderDetail(detailSel.value, +streakFil.value));
streakFil.addEventListener('change', () => renderDetail(detailSel.value, +streakFil.value));
</script>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────────────────────
# 选股信号页面
# ─────────────────────────────────────────────────────────────────────────────

def fetch_screener_data(conn) -> dict:
    """取 screen_results 全量数据 + 计算胜率（信号后5日收益）"""
    import json as _json

    empty_result = {
        "rules": [],
        "dates": [],
        "records": [],
        "win_stats": {},
    }

    try:
        conn.execute("SELECT 1 FROM screen_results LIMIT 1").fetchone()
    except sqlite3.OperationalError:
        return empty_result

    # 所有规则
    rules = [r[0] for r in conn.execute(
        "SELECT DISTINCT rule_id FROM screen_results ORDER BY rule_id"
    ).fetchall()]

    # 所有日期
    dates = [r[0] for r in conn.execute(
        "SELECT DISTINCT date FROM screen_results ORDER BY date DESC"
    ).fetchall()]

    # 全量信号数据
    rows = conn.execute("""
        SELECT rule_id, date, code, name, detail FROM screen_results
        ORDER BY date DESC, rule_id, code
    """).fetchall()

    records = []
    for r in rows:
        detail = {}
        try:
            detail = _json.loads(r["detail"] or "{}")
        except Exception:
            pass
        records.append({
            "rule_id": r["rule_id"],
            "date": r["date"],
            "code": r["code"],
            "name": r["name"],
            **detail,
        })

    # 计算信号后 N 日收益（用 daily_bars）
    win_stats: dict[str, dict] = {}  # rule_id -> {n_day: {win_rate, avg_ret, count}}
    for rule_id in rules:
        rule_records = [r for r in records if r["rule_id"] == rule_id]
        hold_days_list = [3, 5, 10]
        stats_by_days: dict[int, dict] = {}
        for hd in hold_days_list:
            returns = []
            for rec in rule_records:
                sig_date = rec["date"]
                code = rec["code"]
                # 取信号日后第 hd 个交易日的收盘价
                prices = conn.execute("""
                    SELECT close FROM daily_bars
                    WHERE code=? AND date > ?
                    ORDER BY date ASC LIMIT ?
                """, (code, sig_date, hd)).fetchall()
                if len(prices) < hd:
                    continue
                entry_prices = conn.execute("""
                    SELECT close FROM daily_bars
                    WHERE code=? AND date=?
                """, (code, sig_date)).fetchall()
                if not entry_prices:
                    continue
                entry = entry_prices[0][0]
                exit_ = prices[-1][0]
                if entry and entry > 0:
                    returns.append((exit_ - entry) / entry * 100)
            if returns:
                wins = sum(1 for r in returns if r > 0)
                stats_by_days[hd] = {
                    "count": len(returns),
                    "win_rate": round(wins / len(returns) * 100, 1),
                    "avg_ret": round(sum(returns) / len(returns), 2),
                    "median_ret": round(sorted(returns)[len(returns)//2], 2),
                }
        win_stats[rule_id] = stats_by_days

    return {
        "rules": rules,
        "dates": dates,
        "records": records,
        "win_stats": win_stats,
    }


def render_screener_html(conn, latest_date: str) -> str:
    import json as _json
    data = fetch_screener_data(conn)
    rules = data["rules"]
    dates = data["dates"]
    records = data["records"]
    win_stats = data["win_stats"]

    if not records:
        no_data = '<div class="no-data">暂无选股数据，请先运行 screener.py。</div>'
        return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>选股信号 · A股量化平台</title>
<style>{_BASE_STYLE}</style></head><body>
{_NAVBAR("screener.html", latest_date)}
<div class="page">{no_data}</div></body></html>"""

    # 规则说明映射
    rule_labels = {
        "new_high_momentum": "新高动量（近3日新高 + 成交>10亿 + 市值100~500亿）",
    }

    rule_opts = "\n".join(
        f'<option value="{r}">{rule_labels.get(r, r)}</option>' for r in rules
    )
    date_opts = "\n".join(
        f'<option value="{d}"{" selected" if d==dates[0] else ""}>{d}</option>'
        for d in dates
    )

    records_json = _json.dumps(records, ensure_ascii=False)
    win_stats_json = _json.dumps(win_stats, ensure_ascii=False)

    # 胜率统计表 HTML
    win_html = ""
    for rule_id in rules:
        label = rule_labels.get(rule_id, rule_id)
        stats = win_stats.get(rule_id, {})
        win_html += f'<h3 style="font-size:14px;color:#cdd9e5;margin:16px 0 8px">{label}</h3>'
        if not stats:
            win_html += '<p style="color:#484f58;font-size:13px">数据不足，无法统计</p>'
            continue
        win_html += """<table><thead><tr>
            <th>持仓天数</th><th>样本数</th><th>胜率</th><th>平均收益</th><th>中位数收益</th>
        </tr></thead><tbody>"""
        for hd in sorted(stats.keys()):
            s = stats[hd]
            cls = "up" if s["avg_ret"] > 0 else "down"
            win_html += f"""<tr>
                <td>{hd}日</td>
                <td>{s["count"]}</td>
                <td class="up">{s["win_rate"]}%</td>
                <td class="{cls}">{s["avg_ret"]:+.2f}%</td>
                <td class="{cls}">{s["median_ret"]:+.2f}%</td>
            </tr>"""
        win_html += "</tbody></table>"

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>选股信号 · A股量化平台</title>
<style>
{_BASE_STYLE}
.rule-tag {{
  display:inline-block; padding:2px 8px; border-radius:12px;
  font-size:11px; background:#1a1f3a; color:#79c0ff; border:1px solid #1f6feb;
}}
</style>
</head>
<body>
{_NAVBAR("screener.html", latest_date)}
<div class="page">
  <h1>选股信号</h1>
  <p class="subtitle">基于规则引擎的每日选股，支持历史回溯与多规则筛选</p>

  <!-- 胜率统计 -->
  <section class="section">
    <div class="section-title">历史胜率统计（信号日收盘买入 → N日后收盘卖出）</div>
    {win_html}
  </section>

  <!-- 信号筛选 -->
  <section class="section">
    <div class="section-title">信号明细</div>
    <div class="filter-row">
      <label style="color:#8b949e;font-size:13px;">规则：</label>
      <select id="rule-sel">
        <option value="all">全部规则</option>
        {rule_opts}
      </select>
      <label style="color:#8b949e;font-size:13px;">日期：</label>
      <select id="date-sel">
        <option value="all">全部日期</option>
        {date_opts}
      </select>
    </div>
    <div style="color:#484f58;font-size:12px;margin-bottom:10px" id="result-count"></div>
    <table id="signal-table">
      <thead><tr>
        <th>日期</th><th>规则</th><th>代码</th><th>名称</th>
        <th>收盘(元)</th><th>近期最高(元)</th><th>成交额(亿)</th><th>总市值(亿)</th>
      </tr></thead>
      <tbody id="signal-body"></tbody>
    </table>
  </section>

</div>

<script>
const RECORDS = {records_json};
const RULE_LABELS = {_json.dumps(rule_labels, ensure_ascii=False)};

function fmt(v, digits=2) {{
  return v != null ? Number(v).toFixed(digits) : '-';
}}

function renderSignals() {{
  const ruleVal = document.getElementById('rule-sel').value;
  const dateVal = document.getElementById('date-sel').value;
  let rows = RECORDS;
  if (ruleVal !== 'all') rows = rows.filter(r => r.rule_id === ruleVal);
  if (dateVal !== 'all') rows = rows.filter(r => r.date === dateVal);

  document.getElementById('result-count').textContent = `共 ${{rows.length}} 条信号`;

  let html = '';
  if (!rows.length) {{
    html = '<tr><td colspan="8" class="no-data">无符合条件的信号</td></tr>';
  }}
  for (const r of rows) {{
    const ruleLabel = RULE_LABELS[r.rule_id] || r.rule_id;
    html += `<tr>
      <td>${{r.date}}</td>
      <td><span class="rule-tag">${{ruleLabel}}</span></td>
      <td style="font-family:monospace;color:#79c0ff">${{r.code}}</td>
      <td>${{r.name}}</td>
      <td>${{fmt(r.close)}}</td>
      <td>${{fmt(r.recent_high)}}</td>
      <td>${{r.max_amount_yi != null ? fmt(r.max_amount_yi) : '-'}}</td>
      <td>${{r.total_mv_yi != null ? fmt(r.total_mv_yi) : '-'}}</td>
    </tr>`;
  }}
  document.getElementById('signal-body').innerHTML = html;
}}

document.getElementById('rule-sel').addEventListener('change', renderSignals);
document.getElementById('date-sel').addEventListener('change', renderSignals);
renderSignals();
</script>
</body>
</html>"""


def render_docs_html(generated_date: str) -> str:
    """生成平台开发文档 / 用户手册页面"""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>平台文档 · A股量化研究平台</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
  background: #0d1117; color: #e6edf3; min-height: 100vh; font-size: 14px; line-height: 1.7;
}}
.navbar {{
  background: #161b22; border-bottom: 1px solid #30363d;
  padding: 0 32px; display: flex; align-items: center;
  height: 60px; gap: 32px; position: sticky; top: 0; z-index: 100;
}}
.navbar-brand {{ font-size: 17px; font-weight: 700; color: #58a6ff; text-decoration: none; white-space: nowrap; }}
.navbar-links {{ display: flex; gap: 4px; }}
.navbar-links a {{
  color: #8b949e; text-decoration: none; padding: 6px 12px;
  border-radius: 6px; font-size: 14px; transition: all .15s;
}}
.navbar-links a:hover {{ color: #e6edf3; background: #21262d; }}
.navbar-links a.active {{ color: #e6edf3; background: #21262d; }}
.navbar-date {{ margin-left: auto; font-size: 13px; color: #484f58; }}

.layout {{ display: flex; max-width: 1200px; margin: 0 auto; padding: 40px 24px 80px; gap: 40px; }}

/* 左侧目录 */
.sidebar {{
  width: 220px; flex-shrink: 0;
  position: sticky; top: 80px; align-self: flex-start;
  max-height: calc(100vh - 100px); overflow-y: auto;
}}
.sidebar h3 {{ font-size: 11px; text-transform: uppercase; letter-spacing: .08em; color: #484f58; margin-bottom: 12px; }}
.sidebar a {{
  display: block; color: #8b949e; text-decoration: none;
  padding: 4px 10px; border-radius: 5px; font-size: 13px;
  border-left: 2px solid transparent; margin-bottom: 2px;
}}
.sidebar a:hover {{ color: #e6edf3; border-left-color: #58a6ff; background: #161b22; }}
.sidebar a.sub {{ padding-left: 20px; font-size: 12px; }}
.sidebar .sep {{ margin: 10px 0 8px; border-top: 1px solid #21262d; }}

/* 主内容 */
.content {{ flex: 1; min-width: 0; }}
.content h1 {{ font-size: 26px; font-weight: 700; color: #e6edf3; margin-bottom: 8px; }}
.content .subtitle {{ color: #8b949e; font-size: 14px; margin-bottom: 40px; }}

.section {{ margin-bottom: 48px; }}
.section h2 {{
  font-size: 18px; font-weight: 700; color: #e6edf3;
  padding-bottom: 10px; border-bottom: 1px solid #21262d; margin-bottom: 20px;
}}
.section h3 {{ font-size: 15px; font-weight: 600; color: #cdd9e5; margin: 20px 0 10px; }}
.section p {{ color: #8b949e; margin-bottom: 10px; }}
.section ul, .section ol {{ color: #8b949e; padding-left: 20px; margin-bottom: 10px; }}
.section li {{ margin-bottom: 4px; }}
.section li strong {{ color: #cdd9e5; }}

/* 状态标签 */
.badge {{
  display: inline-block; padding: 2px 8px; border-radius: 20px;
  font-size: 11px; font-weight: 600; vertical-align: middle; margin-left: 8px;
}}
.badge-done {{ background: #0d2f1f; color: #3fb950; border: 1px solid #238636; }}
.badge-wip  {{ background: #2d2208; color: #ffa657; border: 1px solid #9e6a03; }}
.badge-todo {{ background: #1c2333; color: #8b949e; border: 1px solid #30363d; }}
.badge-beta {{ background: #1a1f3a; color: #79c0ff; border: 1px solid #1f6feb; }}

/* 功能模块卡片 */
.module-grid {{
  display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px; margin-bottom: 20px;
}}
.module-card {{
  background: #161b22; border: 1px solid #30363d; border-radius: 10px;
  padding: 18px; transition: border-color .15s;
}}
.module-card:hover {{ border-color: #58a6ff44; }}
.module-card .m-title {{ font-size: 14px; font-weight: 600; color: #e6edf3; margin-bottom: 6px; }}
.module-card .m-file {{ font-size: 11px; color: #484f58; font-family: monospace; margin-bottom: 8px; }}
.module-card .m-desc {{ font-size: 13px; color: #8b949e; line-height: 1.6; }}

/* 数据表格 */
.data-table {{ width: 100%; border-collapse: collapse; margin-bottom: 16px; font-size: 13px; }}
.data-table th {{
  text-align: left; padding: 8px 12px; font-size: 11px; text-transform: uppercase;
  letter-spacing: .05em; color: #484f58; border-bottom: 1px solid #21262d;
}}
.data-table td {{ padding: 8px 12px; border-bottom: 1px solid #161b22; color: #8b949e; }}
.data-table tr:hover td {{ background: #161b22; color: #cdd9e5; }}
.data-table td:first-child {{ font-family: monospace; color: #79c0ff; }}

/* changelog */
.changelog-item {{
  display: flex; gap: 16px; padding: 12px 0; border-bottom: 1px solid #161b22;
}}
.cl-date {{ font-size: 12px; color: #484f58; white-space: nowrap; width: 90px; flex-shrink: 0; padding-top: 2px; }}
.cl-body {{ flex: 1; }}
.cl-body .cl-title {{ font-size: 14px; color: #cdd9e5; margin-bottom: 4px; }}
.cl-body .cl-desc {{ font-size: 13px; color: #8b949e; }}

/* 配置说明 */
.code-block {{
  background: #161b22; border: 1px solid #30363d; border-radius: 8px;
  padding: 14px 16px; font-family: monospace; font-size: 12px;
  color: #79c0ff; overflow-x: auto; margin: 10px 0 16px;
}}
</style>
</head>
<body>
{_NAVBAR("docs.html", "更新于 " + html.escape(generated_date))}

<div class="layout">

<!-- 左侧目录 -->
<nav class="sidebar">
  <h3>目录</h3>
  <a href="#overview">平台概览</a>
  <a href="#pages">功能页面</a>
  <a href="#pages" class="sub">首页</a>
  <a href="#page-report" class="sub">综合报告</a>
  <a href="#page-hotrank" class="sub">人气热榜</a>
  <a href="#page-longhu" class="sub">龙虎榜</a>
  <a href="#page-lianban" class="sub">连板晋级</a>
  <a href="#page-screener" class="sub">选股信号</a>
  <a href="#page-emotion" class="sub">市场温度</a>
  <a href="#page-etf" class="sub">ETF雷达</a>
  <a href="#page-monitor" class="sub">运行监控</a>
  <div class="sep"></div>
  <a href="#data">数据模块</a>
  <a href="#data-daily" class="sub">每日行情</a>
  <a href="#data-lhb" class="sub">龙虎榜数据</a>
  <a href="#data-etf" class="sub">ETF数据</a>
  <a href="#data-shares" class="sub">总股本采集</a>
  <a href="#data-screener" class="sub">选股引擎</a>
  <a href="#data-api" class="sub">Flask API</a>
  <div class="sep"></div>
  <a href="#backtest">回测模块</a>
  <a href="#infra">基础设施</a>
  <a href="#db-schema">数据库结构</a>
  <a href="#schedule">定时任务</a>
  <div class="sep"></div>
  <a href="#roadmap">待办 / Roadmap</a>
  <a href="#changelog">更新日志</a>
</nav>

<!-- 主内容 -->
<main class="content">

  <h1>平台文档</h1>
  <p class="subtitle">A股量化研究平台 · 开发手册 &amp; 用户指南 · 自动生成于每日报告更新时</p>

  <!-- 平台概览 -->
  <section class="section" id="overview">
    <h2>平台概览</h2>
    <p>基于 Python + SQLite 的轻量化 A 股量化研究平台，部署在 Oracle 云主机（公网 <code style="color:#79c0ff">140.245.53.52:8080</code>），每个工作日 19:45（北京时间）自动采集数据并更新静态 HTML 报告。</p>
    <h3>技术栈</h3>
    <ul>
      <li><strong>数据采集：</strong>AkShare（行情/龙虎榜/ETF）、新浪财经、东方财富</li>
      <li><strong>存储：</strong>SQLite（WAL 模式，~2.6G），位于 <code style="color:#79c0ff">/data/quant_research/data/quant.db</code></li>
      <li><strong>报告生成：</strong>纯 Python 生成静态 HTML，无前端框架</li>
      <li><strong>部署：</strong>nginx 反向代理 8080 端口，systemd timer 定时触发</li>
      <li><strong>配色规范：</strong>涨红 <code style="color:#e84c3d">#e84c3d</code>，跌绿 <code style="color:#07a071">#07a071</code>，主题蓝 <code style="color:#58a6ff">#58a6ff</code></li>
    </ul>
    <h3>数据统计范围</h3>
    <ul>
      <li>历史数据起始日期：<strong>2025-01-01</strong></li>
      <li>A 股全市场日线数据（沪深京）</li>
      <li>ETF 日线行情：~947 只（成交额 ≥ 1 亿过滤）</li>
      <li>龙虎榜：2025-01-01 起历史数据补采中</li>
    </ul>
  </section>

  <!-- 功能页面 -->
  <section class="section" id="pages">
    <h2>功能页面</h2>
    <div class="module-grid">
      <div class="module-card">
        <div class="m-title">🏠 首页 <span class="badge badge-done">已上线</span></div>
        <div class="m-file">index.html</div>
        <div class="m-desc">情绪仪表盘（市场情绪分）、关键统计指标、各功能模块入口卡片，加载 summary.json 动态渲染。</div>
      </div>
      <div class="module-card" id="page-report">
        <div class="m-title">📈 综合报告 <span class="badge badge-done">已上线</span></div>
        <div class="m-file">report.html · generate_report.py</div>
        <div class="m-desc">选股信号、热门候选股、量能龙头、人气榜、涨停池、策略回测结果汇总。每日自动生成。</div>
      </div>
      <div class="module-card" id="page-hotrank">
        <div class="m-title">🔥 人气热榜 <span class="badge badge-done">已上线</span></div>
        <div class="m-file">hot_rank_iframe.html</div>
        <div class="m-desc">聚合通达信、东方财富、财联社、同花顺四大平台人气排行，iframe 嵌入展示。</div>
      </div>
       <div class="module-card" id="page-longhu">
        <div class="m-title">🐉 龙虎榜 <span class="badge badge-done">已上线</span></div>
        <div class="m-file">longhu.html · generate_report.py:render_longhu_html()</div>
        <div class="m-desc">每日龙虎榜上榜股票，含涨跌幅、成交额、上榜原因。按日期切换，营业部排行 Top50，席位明细展开。新增"个股历史"和"营业部历史" Tab，通过 Flask API 按需查询。</div>
      </div>
      <div class="module-card" id="page-lianban">
        <div class="m-title">🔥 连板晋级 <span class="badge badge-done">已上线</span></div>
        <div class="m-file">lianban.html · generate_report.py:render_lianban_html()</div>
        <div class="m-desc">基于东财涨停池接口，展示每日连板梯队（1/2/3/4+板分组），历史各层级晋级率统计，涨停明细含封板资金、首封时间、炸板次数、行业。数据来自 zt_pool 表，由 update_zt_pool.py 每日采集。</div>
      </div>
      <div class="module-card" id="page-screener">
        <div class="m-title">🔍 选股信号 <span class="badge badge-done">已上线</span></div>
        <div class="m-file">screener.html · generate_report.py:render_screener_html()</div>
        <div class="m-desc">规则引擎每日选股，支持多规则筛选与历史回溯，含信号后3/5/10日胜率、均值收益、中位数收益统计。数据来自 screen_results 表，由 screener.py 每日运行写入。</div>
      </div>
      <div class="module-card" id="page-emotion">
        <div class="m-title">🌡 市场温度 <span class="badge badge-done">已上线</span></div>
        <div class="m-file">emotion.html · generate_report.py:render_emotion_html()</div>
        <div class="m-desc">情绪分趋势、涨跌家数、涨跌停数、成交额四图独立展示，支持近30日/近90日/全部切换。涨跌停数来源东财收盘封板接口（market_daily 表），情绪分公式说明可点击展开。</div>
      </div>
      <div class="module-card" id="page-etf">
        <div class="m-title">📡 ETF雷达 <span class="badge badge-beta">Beta</span></div>
        <div class="m-file">etf.html · generate_report.py:render_etf_html()</div>
        <div class="m-desc">ETF 行情快照（成交额 ≥ 5 亿），技术信号（历史新高 / MA20向上 / 站上MA60），
          宽基 vs 行业主题分类，三维联动筛选。点击行展开持仓 Top10。</div>
      </div>
      <div class="module-card" id="page-monitor">
        <div class="m-title">🧭 运行监控 <span class="badge badge-done">已上线</span></div>
        <div class="m-file">monitor.html · generate_report.py:render_monitor_html()</div>
        <div class="m-desc">展示每日数据模块更新结论、报告生成时间、Git commit、分支和生产运行日志路径，方便判断当前页面对应的代码版本。</div>
      </div>
      <div class="module-card">
        <div class="m-title">📄 平台文档 <span class="badge badge-done">已上线</span></div>
        <div class="m-file">docs.html · generate_report.py:render_docs_html()</div>
        <div class="m-desc">本页面。记录所有功能模块状态、数据库结构、定时任务配置及开发 Roadmap。每日自动更新。</div>
      </div>
    </div>
  </section>

  <!-- 数据模块 -->
  <section class="section" id="data">
    <h2>数据模块</h2>

    <h3 id="data-daily">每日行情采集 <span class="badge badge-done">已上线</span></h3>
    <p>脚本：<code style="color:#79c0ff">src/update_sqlite_data.py</code></p>
    <ul>
      <li>采集全市场 A 股日线行情（沪深京），来源：新浪财经（<code>--daily-source sina</code>）</li>
      <li>并发工作线程：8（<code>--workers 8</code>）</li>
      <li>同步人气榜（东财/问财）、外部涨停池、龙虎榜、市场涨跌停汇总</li>
      <li>写入表：<code>stocks</code>、<code>daily_bars</code>、<code>popularity_rankings</code>、<code>limit_up_pool</code>、<code>lhb_records</code>、<code>lhb_seats</code>、<code>market_daily</code></li>
    </ul>

    <h3 id="data-lhb">龙虎榜数据 <span class="badge badge-done">已上线</span></h3>
    <p>脚本：<code style="color:#79c0ff">src/update_sqlite_data.py:update_lhb()</code>（每日增量）</p>
    <p>脚本：<code style="color:#79c0ff">src/backfill_lhb.py</code>（历史批量补采，2025-01-01 起，已完成）</p>
    <ul>
      <li>来源：东方财富 AkShare 接口</li>
      <li>写入表：<code>lhb_records</code>（概览）、<code>lhb_seats</code>（席位明细）</li>
      <li>限速：每请求间隔 1~2 秒，避免封禁</li>
      <li>断点续传：已入库日期自动跳过</li>
    </ul>

    <h3 id="data-etf">ETF数据</h3>
    <p>脚本：<code style="color:#79c0ff">src/update_etf.py</code></p>
    <ul>
      <li>行情来源：新浪财经实时接口（当日快照）+ 东方财富历史 K 线</li>
      <li>技术指标：MA20、MA60，MA20 方向，历史新高信号</li>
      <li>成交额过滤：采集时 ≥ 5000 万（展示时 ≥ 5 亿）</li>
      <li>持仓明细：东方财富基金持仓接口，按季度更新，点击 ETF 行展开 Top10</li>
      <li>写入表：<code>etf_daily</code>、<code>etf_holdings</code></li>
    </ul>

    <h3 id="data-shares">总股本采集 <span class="badge badge-done">已上线</span></h3>
    <p>脚本：<code style="color:#79c0ff">src/update_shares.py</code></p>
    <ul>
      <li>来源：mootdx <code>finance()</code> 接口，字段 <code>zongguben</code></li>
      <li>并发：20 线程，全量约 5 分钟完成；每日增量仅更新 <code>total_shares IS NULL</code> 的股票</li>
      <li>写入：<code>stocks.total_shares</code>、<code>stocks.shares_updated_at</code></li>
      <li>覆盖率：5196 / 5707 只（511 只退市/停牌无数据）</li>
    </ul>

    <h3 id="data-screener">选股引擎 <span class="badge badge-done">已上线</span></h3>
    <p>脚本：<code style="color:#79c0ff">src/screener.py</code></p>
    <ul>
      <li>规则基类 <code>ScreenRule</code>，子类注册到 <code>RULES</code> 字典，新增规则只需继承并注册</li>
      <li>内置规则 <strong>NewHighMomentum</strong>：近3日历史新高 + 成交额 &gt; 10 亿 + 总市值 100~500 亿</li>
      <li>结果写入 <code>screen_results</code> 表，保留历史；综合报告首部展示最新一期结果</li>
      <li>每日定时任务自动运行，2026-04-30 命中 94 只</li>
    </ul>

    <h3 id="data-api">Flask API 服务 <span class="badge badge-done">已上线</span></h3>
    <p>脚本：<code style="color:#79c0ff">src/api_server.py</code>，systemd 服务：<code style="color:#79c0ff">quant-api.service</code></p>
    <ul>
      <li>端口：8081（nginx 将 <code>/api/</code> 反向代理到此）</li>
      <li><code>GET /api/lhb/stock?code=xxxxxx</code>：查询个股龙虎榜历史（分页）</li>
      <li><code>GET /api/lhb/seat?name=营业部名称</code>：查询营业部操作历史（分页）</li>
      <li><code>GET /api/lhb/search/stock?q=关键词</code>：股票代码/名称联想搜索</li>
      <li><code>GET /api/lhb/search/seat?q=关键词</code>：营业部名称联想搜索</li>
      <li>每个请求独立新建 SQLite 连接，避免跨线程问题；开机自启</li>
    </ul>
  </section>

  <!-- 回测模块 -->
  <section class="section" id="backtest">
    <h2>回测模块 <span class="badge badge-done">已上线</span></h2>
    <p>脚本：<code style="color:#79c0ff">src/backtest_new_high_volume.py</code></p>
    <ul>
      <li>策略：新高 + 量能（历史新高信号叠加成交额突破）</li>
      <li>回测范围：2025-01-01 至今，全市场 A 股</li>
      <li>评估指标：胜率、均值收益、中位数收益、批次总收益、最大回撤、平均跳空、平均持仓天数</li>
      <li>结果写入 <code>strategy_backtests</code> 表，同步输出 CSV</li>
      <li>每日定时任务自动重跑，结果展示在综合报告中</li>
    </ul>
  </section>

  <!-- 基础设施 -->
  <section class="section" id="infra">
    <h2>基础设施</h2>

    <h3 id="db-schema">数据库结构</h3>
    <p>数据库文件：<code style="color:#79c0ff">/data/quant_research/data/quant.db</code>（SQLite，WAL 模式）</p>
    <table class="data-table">
      <thead><tr><th>表名</th><th>说明</th><th>主要字段</th></tr></thead>
      <tbody>
        <tr><td>stocks</td><td>股票基础信息</td><td>code, name, market, industry, eligible, total_shares, shares_updated_at</td></tr>
        <tr><td>daily_bars</td><td>A股日线行情</td><td>date, code, open, high, low, close, volume, amount, pct_chg</td></tr>
        <tr><td>popularity_rankings</td><td>人气榜排名</td><td>date, source, rank, code, name, score</td></tr>
        <tr><td>limit_up_pool</td><td>涨停池（东财，含炸板）</td><td>date, source, code, name, reason, streak, first_limit_time, seal_amount</td></tr>
        <tr><td>market_daily</td><td>市场日汇总（接口涨跌停数）</td><td>date, zt_count, dt_count, zt_count_calc, dt_count_calc</td></tr>
        <tr><td>strategy_backtests</td><td>回测结果</td><td>strategy, date, trades, win_rate, avg_return_pct</td></tr>
        <tr><td>screen_results</td><td>选股结果</td><td>date, rule, code, name, pct_chg, amount, total_mktcap, signal_detail</td></tr>
        <tr><td>lhb_records</td><td>龙虎榜概览</td><td>date, code, name, pct_chg, amount, reason</td></tr>
        <tr><td>lhb_seats</td><td>龙虎榜席位明细</td><td>date, code, seat_name, buy_amount, sell_amount, direction</td></tr>
        <tr><td>etf_daily</td><td>ETF每日行情+信号</td><td>date, code, name, close, pct_chg, amount, ma20, ma60, is_new_high, ma20_up, above_ma60</td></tr>
        <tr><td>etf_holdings</td><td>ETF持仓明细</td><td>code, quarter, stock_code, stock_name, weight</td></tr>
      </tbody>
    </table>

    <h3 id="schedule">定时任务</h3>
    <p>systemd timer：<code style="color:#79c0ff">quant-daily.timer</code>，触发时间：UTC 11:45（北京时间 19:45），仅工作日</p>
    <p>执行脚本：<code style="color:#79c0ff">/data/quant_research/logs/quant-daily-run.sh</code></p>
    <div class="code-block">1. update_sqlite_data.py         # 全市场行情 + 人气榜 + 涨停池 + 龙虎榜 + 市场涨跌停汇总(market_daily)
2. update_etf.py --skip-holdings # ETF行情快照 + 技术信号更新；持仓抓取单独按需运行
3. update_shares.py              # 补全 total_shares IS NULL 的股票总股本
4. screener.py                   # 选股引擎，结果写入 screen_results 表
5. backtest_new_high_volume.py   # 策略回测
6. generate_report.py            # 生成所有HTML报告页面</div>

    <h3>关键路径</h3>
    <table class="data-table">
      <thead><tr><th>路径</th><th>说明</th></tr></thead>
      <tbody>
        <tr><td>/data/quant_research/src/</td><td>所有 Python 脚本</td></tr>
        <tr><td>/data/quant_research/data/quant.db</td><td>主数据库</td></tr>
        <tr><td>/data/quant_research/reports/latest/</td><td>nginx 服务根目录（最新报告）</td></tr>
        <tr><td>/data/quant_research/reports/YYYY-MM-DD/</td><td>历史归档报告</td></tr>
        <tr><td>/data/quant_research/logs/</td><td>定时任务脚本 + 运行日志</td></tr>
        <tr><td>/data/quant_research_venv/</td><td>Python 虚拟环境</td></tr>
      </tbody>
    </table>
  </section>

  <!-- Roadmap -->
  <section class="section" id="roadmap">
    <h2>待办 / Roadmap</h2>
    <h3>进行中</h3>
    <ul>
      <li><strong>ETF持仓回补</strong>：定时任务按日增量抓取，避免全量任务长时间阻塞</li>
    </ul>
    <h3>已知问题 / 待排查</h3>
    <ul>
      <li>
        <strong>涨跌家数与东财差 ~2，合计股票数少 61：</strong>
        东财 04-30 显示 5521 只，我们 DB 只有 5460 条，差 61 只。
        已排查：<code>stocks</code> 表中有 194 只已退市股票（名含"退"，从无行情数据）；
        另有 51 只近期停牌（最后数据在 04-29 或更早）；
        还有约 10 只在东财有数据但 mootdx 和 akshare 均无法拉到，来源未确定。
        涨跌数固定差 2，东财历史 K 线接口确认这 2 只 pct=0%，可能是东财内部用了不同参考价（如复牌调整价）。
        <br><em>待办：清理 stocks 表中已退市股票；排查 mootdx/akshare 未覆盖的 ~10 只股票来源。</em>
      </li>
    </ul>
    <h3>近期计划</h3>
    <ul>
      <li><strong>龙虎榜个股历史/营业部历史 Tab：</strong>Flask API 按需查询 ✓ 已完成</li>
      <li><strong>总股本采集：</strong>update_shares.py + stocks.total_shares ✓ 已完成</li>
      <li><strong>选股引擎：</strong>screener.py + screen_results 表 + 报告集成 ✓ 已完成</li>
      <li><strong>龙虎榜历史补采：</strong>backfill_lhb.py 覆盖 2025-07-22~2026-04-30 ✓ 已完成</li>
      <li><strong>市场温度历史数据：</strong>backfill_market_daily_calc.py 自算填满320天 ✓ 已完成</li>
      <li><strong>板块轮动热力图：</strong>在 emotion.html 中新增行业板块涨跌热力图</li>
    </ul>
    <h3>中期计划</h3>
    <ul>
      <li>新增选股规则（量价背离、连板晋级、资金净流入等）</li>
      <li>连板晋级追踪页面（今日连板梯队、历史晋级率）</li>
      <li>个股详情页（点击股票代码跳转，展示K线+信号历史）</li>
      <li>回测策略扩展（趋势跟踪、均值回归）</li>
      <li>资金流向分析（主力净流入、北向资金）</li>
    </ul>
  </section>

  <!-- Changelog -->
  <section class="section" id="changelog">
    <h2>更新日志</h2>

    <div class="changelog-item">
      <div class="cl-date">2026-05-05</div>
      <div class="cl-body">
        <div class="cl-title">选股引擎上线（screener.py）+ 综合报告集成</div>
        <div class="cl-desc">新增 screener.py，规则基类 ScreenRule + NewHighMomentum 规则（近3日新高、成交额&gt;10亿、市值100~500亿）；结果写入 screen_results 表；综合报告首部新增选股信号区块；daily-run 加入 screener 步骤。2026-04-30 命中 94 只。</div>
      </div>
    </div>

    <div class="changelog-item">
      <div class="cl-date">2026-05-05</div>
      <div class="cl-body">
        <div class="cl-title">总股本采集（update_shares.py）+ stocks 表新增字段</div>
        <div class="cl-desc">stocks 表新增 total_shares / shares_updated_at；update_shares.py 用 mootdx finance() 接口 20 线程并发拉取，全量约 5 分钟；5196/5707 只有数据；daily-run 加入增量更新步骤。</div>
      </div>
    </div>

    <div class="changelog-item">
      <div class="cl-date">2026-05-05</div>
      <div class="cl-body">
        <div class="cl-title">龙虎榜新增个股历史 / 营业部历史 Tab（Flask API）</div>
        <div class="cl-desc">longhu.html 新增两个查询 Tab，前端 300ms 防抖联想搜索，结果通过 fetch() 调用 api_server.py（Flask，端口 8081，nginx /api/ 反向代理）按需获取；quant-api.service systemd 服务开机自启。</div>
      </div>
    </div>

    <div class="changelog-item">
      <div class="cl-date">2026-05-05</div>
      <div class="cl-body">
        <div class="cl-title">龙虎榜历史数据补采完成（2025-07-22 ~ 2026-04-30）</div>
        <div class="cl-desc">backfill_lhb.py 补齐 203 个交易日缺口，lhb_records 现覆盖 185 个有数据交易日，lhb_seats 87964+ 条。</div>
      </div>
    </div>

    <div class="changelog-item">
      <div class="cl-date">2026-05-05</div>
      <div class="cl-body">
        <div class="cl-title">market_daily 表 320 天历史数据填满（自算版）</div>
        <div class="cl-desc">backfill_market_daily_calc.py 从 daily_bars.pct_chg 自算填满 2025-01-02~2026-04-30 全部交易日；各板块涨跌停阈值：主板±9.8%，创业板/科创板±19.8%，北交所±29.8%，ST±4.8%。</div>
      </div>
     </div>

    <div class="changelog-item">
      <div class="cl-date">2026-05-05</div>
      <div class="cl-body">
        <div class="cl-title">新增连板晋级页面（lianban.html）与选股信号页面（screener.html）</div>
        <div class="cl-desc">lianban.html：基于东财涨停池，展示今日连板梯队、历史各层级晋级率（从 zt_pool.streak 跨日推算）、涨停明细含封板资金/首封时间/行业；screener.html：选股规则历史回溯、多规则筛选、信号后 3/5/10 日胜率统计；update_zt_pool.py 加入每日定时任务；所有页面导航栏统一加入两个新入口。</div>
      </div>
    </div>

    <div class="changelog-item">
      <div class="cl-date">2026-05-04</div>
      <div class="cl-body">
        <div class="cl-title">市场温度页改版：4图独立展示 + 涨跌停改接口数据</div>
        <div class="cl-desc">情绪分/涨跌家数/涨跌停数/成交额由 Tab 切换改为4个独立图表上下排列；新增 market_daily 表，每日从东财接口采集收盘封板涨跌停数（口径与东财一致），报告优先使用接口数据，无数据时 fallback 自算；情绪分公式说明改为折叠展开。</div>
      </div>
    </div>

    <div class="changelog-item">
      <div class="cl-date">2026-05-04</div>
      <div class="cl-body">
        <div class="cl-title">新增平台文档页面（本页）</div>
        <div class="cl-desc">集成用户指南与开发文档，每日报告生成时自动更新。加入导航栏。</div>
      </div>
    </div>
    <div class="changelog-item">
      <div class="cl-date">2026-05-04</div>
      <div class="cl-body">
        <div class="cl-title">ETF雷达页上线，update_etf.py 加入定时任务</div>
        <div class="cl-desc">947 只 ETF 行情已入库，技术信号（新高/MA20/MA60）、宽基vs行业分类、三维联动筛选、持仓 Top10 展开、涨跌幅列排序。</div>
      </div>
    </div>
    <div class="changelog-item">
      <div class="cl-date">2026-05-04</div>
      <div class="cl-body">
        <div class="cl-title">启动龙虎榜历史数据补采（2025-01-01 起）</div>
        <div class="cl-desc">backfill_lhb.py 后台运行，覆盖 349 个交易日的概览和席位明细数据。</div>
      </div>
    </div>
    <div class="changelog-item">
      <div class="cl-date">2026-05-03</div>
      <div class="cl-body">
        <div class="cl-title">全站 A 股配色切换</div>
        <div class="cl-desc">涨色统一为 #e84c3d（红），跌色统一为 #07a071（绿），符合 A 股习惯。</div>
      </div>
    </div>
    <div class="changelog-item">
      <div class="cl-date">2026-04-30</div>
      <div class="cl-body">
        <div class="cl-title">龙虎榜、市场温度、人气热榜页面上线</div>
        <div class="cl-desc">新增 longhu.html、emotion.html、hot_rank_iframe.html，首页集成情绪仪表盘。</div>
      </div>
    </div>
    <div class="changelog-item">
      <div class="cl-date">2026-04-15</div>
      <div class="cl-body">
        <div class="cl-title">平台初始部署</div>
        <div class="cl-desc">Oracle 云主机，nginx + systemd timer，A 股日线行情 + 策略回测 + 综合报告自动生成。</div>
      </div>
    </div>
  </section>

</main>
</div>
</body>
</html>"""


def main() -> None:
    args = parse_args()
    summary, latest_top_amount, latest_hot, popularity_rows, limit_pool_rows, strategy_rows, lhb_rows, lhb_seat_stats, screen_rows = build_report(args)
    latest_date = str(summary["latest_date"])
    dated_dir = args.report_dir / latest_date
    latest_dir = args.report_dir / "latest"
    # ETF 页面需要直接访问数据库
    _conn = connect(args.db)
    for output_dir in (dated_dir, latest_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "report.html").write_text(render_html(summary, latest_top_amount, latest_hot, popularity_rows, limit_pool_rows, strategy_rows, screen_rows), encoding="utf-8")
        (output_dir / "report.md").write_text(render_markdown(summary, latest_top_amount, latest_hot, popularity_rows, limit_pool_rows, strategy_rows), encoding="utf-8")
        (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        publish_static_assets(output_dir)
        (output_dir / "longhu.html").write_text(render_longhu_html(lhb_rows, latest_date, lhb_seat_stats), encoding="utf-8")
        (output_dir / "emotion.html").write_text(render_emotion_html(summary), encoding="utf-8")
        (output_dir / "etf.html").write_text(render_etf_html(_conn, latest_date), encoding="utf-8")
        (output_dir / "lianban.html").write_text(render_lianban_html(_conn, latest_date), encoding="utf-8")
        (output_dir / "screener.html").write_text(render_screener_html(_conn, latest_date), encoding="utf-8")
        (output_dir / "monitor.html").write_text(render_monitor_html(summary), encoding="utf-8")
        (output_dir / "docs.html").write_text(render_docs_html(latest_date), encoding="utf-8")
        write_csv(output_dir / "latest_top_amount.csv", latest_top_amount, ["date", "code", "name", "market", "pct", "amount_e8", "turnover", "is_limit_up", "streak", "hot_score"])
        write_csv(output_dir / "latest_hot_candidates.csv", latest_hot, ["date", "code", "name", "market", "pct", "amount_e8", "turnover", "is_limit_up", "streak", "hot_score"])
        write_csv(output_dir / "latest_popularity_rankings.csv", popularity_rows, ["date", "source", "rank", "code", "name", "score", "pct", "amount_e8", "turnover"])
        write_csv(output_dir / "latest_external_limit_up_pool.csv", limit_pool_rows, ["date", "source", "code", "name", "reason", "streak", "first_limit_time", "last_limit_time", "seal_amount", "pct", "amount_e8"])
        write_csv(output_dir / "new_high_volume_backtests.csv", strategy_rows, ["strategy", "trades", "signal_days", "win_rate", "avg_return_pct", "median_return_pct", "total_batch_return_pct", "max_drawdown_pct", "avg_gap_pct", "avg_hold_days", "description"])
    print(f"Report generated: {dated_dir / 'report.html'}")
    print(f"Latest copy: {latest_dir / 'report.html'}")


if __name__ == "__main__":
    main()
