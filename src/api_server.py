"""
api_server.py
轻量 Flask API 服务，提供 A 股量化数据查询接口。

认证：所有 /api/* 请求需携带 Header  X-API-Key: <key>
      key 从环境变量 QUANT_API_KEY 读取；未设置时跳过认证（仅限 127.0.0.1）

Endpoints:
  # 龙虎榜
  GET /api/lhb/stock?code=600000[&limit=50]
  GET /api/lhb/seat?name=华泰...
  GET /api/lhb/search/stock?q=600000|平安
  GET /api/lhb/search/seat?q=华泰

  # 日K线
  GET /api/daily?code=600519[&start=2025-01-01][&end=2026-05-15][&limit=250]

  # 市场情绪
  GET /api/market?[start=2025-01-01][&end=2026-05-15]

  # 涨停池
  GET /api/zt?[date=2026-05-15]          单日涨停池
  GET /api/zt/range?start=...&end=...    区间涨停池

  # ETF
  GET /api/etf?[code=510300][&start=...][&end=...]

  # 选股结果
  GET /api/screen?[date=2026-05-15][&rule=]

  # 股票列表
  GET /api/stocks?[q=平安]

  # 健康检查
  GET /api/health

Usage:
    python src/api_server.py --db data/quant.db --port 8081
    QUANT_API_KEY=mysecret python src/api_server.py --db data/quant.db --port 8081
"""
from __future__ import annotations

import argparse
import os
import socket
import sqlite3
import subprocess
import sys
from datetime import date, datetime, time, timedelta
from functools import lru_cache, wraps
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from flask import Flask, jsonify, request
from quant_db import connect

app = Flask(__name__)
_db_path: Path | None = None
_api_key: str | None = None  # None = 不校验


def get_conn() -> sqlite3.Connection:
    return connect(_db_path)


def row_to_dict(row) -> dict:
    return dict(row)


def _git_output(args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        return result.stdout.strip()
    except Exception:
        return None


def get_git_info() -> dict[str, object]:
    return {
        "commit": _git_output(["rev-parse", "HEAD"]),
        "short_commit": _git_output(["rev-parse", "--short", "HEAD"]),
        "branch": _git_output(["rev-parse", "--abbrev-ref", "HEAD"]),
        "commit_time": _git_output(["log", "-1", "--format=%ci"]),
        "subject": _git_output(["log", "-1", "--format=%s"]),
        "dirty": bool(_git_output(["status", "--short"])),
    }


HEALTH_CUTOFF = time(18, 30)

HEALTH_MODULES = [
    {
        "key": "daily_bars",
        "label": "日线行情",
        "date_sql": "SELECT MAX(date) FROM daily_bars",
        "count_sql": "SELECT COUNT(*) FROM daily_bars WHERE date = ?",
        "required": True,
    },
    {
        "key": "market_daily",
        "label": "市场温度",
        "date_sql": "SELECT MAX(date) FROM market_daily",
        "count_sql": "SELECT COUNT(*) FROM market_daily WHERE date = ?",
        "required": True,
    },
    {
        "key": "limit_up_pool",
        "label": "涨停池",
        "date_sql": "SELECT MAX(date) FROM limit_up_pool",
        "count_sql": "SELECT COUNT(*) FROM limit_up_pool WHERE date = ?",
        "required": True,
    },
    {
        "key": "popularity_rankings",
        "label": "人气热榜",
        "date_sql": "SELECT MAX(date) FROM popularity_rankings",
        "count_sql": "SELECT COUNT(*) FROM popularity_rankings WHERE date = ?",
        "required": True,
    },
    {
        "key": "lhb_records",
        "label": "龙虎榜",
        "date_sql": "SELECT MAX(date) FROM lhb_records",
        "count_sql": "SELECT COUNT(*) FROM lhb_records WHERE date = ?",
        "required": True,
    },
    {
        "key": "lhb_seats",
        "label": "龙虎榜席位",
        "date_sql": "SELECT MAX(date) FROM lhb_seats",
        "count_sql": "SELECT COUNT(*) FROM lhb_seats WHERE date = ?",
        "required": True,
    },
    {
        "key": "etf_daily",
        "label": "ETF雷达",
        "date_sql": "SELECT MAX(date) FROM etf_daily",
        "count_sql": "SELECT COUNT(*) FROM etf_daily WHERE date = ?",
        "required": True,
    },
    {
        "key": "screen_results",
        "label": "选股信号",
        "date_sql": "SELECT MAX(date) FROM screen_results",
        "count_sql": "SELECT COUNT(*) FROM screen_results WHERE date = ?",
        "required": True,
    },
    {
        "key": "strategy_backtests",
        "label": "策略回测",
        "date_sql": "SELECT MAX(end_date) FROM strategy_backtests",
        "count_sql": "SELECT COUNT(*) FROM strategy_backtests WHERE end_date = ?",
        "required": True,
    },
    {
        "key": "zt_pool",
        "label": "涨停池 legacy",
        "date_sql": "SELECT MAX(date) FROM zt_pool",
        "count_sql": "SELECT COUNT(*) FROM zt_pool WHERE date = ?",
        "required": False,
        "legacy": True,
    },
]


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10] if fmt == "%Y-%m-%d" else text[:8], fmt).date()
        except ValueError:
            continue
    return None


def _safe_scalar(conn: sqlite3.Connection, sql: str, params: tuple = ()):
    try:
        row = conn.execute(sql, params).fetchone()
        return row[0] if row else None
    except sqlite3.Error:
        return None


def _weekday_trading_days(start: date, end: date) -> list[date]:
    days: list[date] = []
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            days.append(cur)
        cur += timedelta(days=1)
    return days


@lru_cache(maxsize=8)
def _load_trading_days(start: date, end: date) -> tuple[list[date], str]:
    old_timeout = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(5)
        import akshare as ak

        df = ak.tool_trade_date_hist_sina()
        raw_dates = sorted(df.iloc[:, 0].dropna().astype(str).tolist())
        days = []
        for item in raw_dates:
            day = _parse_date(item)
            if day and start <= day <= end:
                days.append(day)
        if days:
            return days, "akshare.tool_trade_date_hist_sina"
    except Exception:
        pass
    finally:
        socket.setdefaulttimeout(old_timeout)
    return _weekday_trading_days(start, end), "weekday_fallback"


def _expected_trade_date(now: datetime) -> tuple[date | None, list[date], str]:
    start = now.date() - timedelta(days=45)
    end = now.date()
    trading_days, source = _load_trading_days(start, end)
    if not trading_days:
        return None, [], source

    completed = [day for day in trading_days if day <= now.date()]
    if now.date() in completed and now.time() < HEALTH_CUTOFF:
        completed = [day for day in completed if day < now.date()]
    return (completed[-1] if completed else None), trading_days, source


def _trading_lag_days(latest: date | None, expected: date | None, trading_days: list[date]) -> int | None:
    if latest is None or expected is None:
        return None
    if latest >= expected:
        return 0
    return len([day for day in trading_days if latest < day <= expected])


def _module_health(conn: sqlite3.Connection, module: dict, expected: date | None, trading_days: list[date]) -> dict:
    latest_text = _safe_scalar(conn, module["date_sql"])
    latest = _parse_date(latest_text)
    row_count = _safe_scalar(conn, module["count_sql"], (str(latest),)) if latest else None
    lag_days = _trading_lag_days(latest, expected, trading_days)

    if latest is None:
        status = "missing"
        status_label = "缺失"
    elif expected is not None and latest > expected:
        status = "future_date"
        status_label = "晚于最新有效交易日"
    elif lag_days is None:
        status = "unknown"
        status_label = "未知"
    elif lag_days == 0:
        status = "fresh"
        status_label = "已更新"
    else:
        status = "stale"
        status_label = f"落后{lag_days}个交易日"

    return {
        "key": module["key"],
        "label": module["label"],
        "latest_date": str(latest) if latest else None,
        "expected_trade_date": str(expected) if expected else None,
        "lag_trading_days": lag_days,
        "row_count": row_count,
        "required": bool(module.get("required", True)),
        "legacy": bool(module.get("legacy", False)),
        "status": status,
        "status_label": status_label,
    }


# ── 认证 ───────────────────────────────────────────────────────────────────────

def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if _api_key is None:
            return f(*args, **kwargs)
        key = request.headers.get("X-API-Key") or request.args.get("api_key")
        if key != _api_key:
            return jsonify({"error": "unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


# ── CORS ───────────────────────────────────────────────────────────────────────

@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "X-API-Key, Content-Type"
    return response


# ── /api/health ───────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    conn = get_conn()
    try:
        now = datetime.now()
        expected, trading_days, calendar_source = _expected_trade_date(now)
        modules = [
            _module_health(conn, module, expected, trading_days)
            for module in HEALTH_MODULES
        ]

        required_bad = [
            item for item in modules
            if item["required"] and item["status"] not in {"fresh"}
        ]
        any_bad = [item for item in modules if item["status"] not in {"fresh"}]
        actionable_warnings = [
            item for item in any_bad
            if item not in required_bad and item["required"] and not item["legacy"]
        ]
        if required_bad:
            status = "error"
        elif actionable_warnings:
            status = "warn"
        else:
            status = "ok"

        return jsonify({
            "status": status,
            "as_of": now.strftime("%Y-%m-%d %H:%M:%S"),
            "expected_trade_date": str(expected) if expected else None,
            "calendar_source": calendar_source,
            "git": get_git_info(),
            "latest": {item["key"]: item["latest_date"] for item in modules},
            "modules": modules,
            "errors": required_bad,
            "warnings": [item for item in any_bad if item not in required_bad],
        })
    finally:
        conn.close()


# ── /api/stocks ───────────────────────────────────────────────────────────────

@app.get("/api/stocks")
@require_api_key
def stocks():
    q = (request.args.get("q") or "").strip()
    conn = get_conn()
    if q:
        rows = conn.execute(
            "SELECT * FROM stocks WHERE code LIKE ? OR name LIKE ? LIMIT 50",
            (f"%{q}%", f"%{q}%"),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM stocks ORDER BY code LIMIT 200").fetchall()
    return jsonify([row_to_dict(r) for r in rows])


# ── /api/daily ────────────────────────────────────────────────────────────────

@app.get("/api/daily")
@require_api_key
def daily():
    code = (request.args.get("code") or "").strip()
    start = request.args.get("start", "2025-01-01")
    end = request.args.get("end", "9999-12-31")
    limit = min(int(request.args.get("limit", 500)), 2000)
    if not code:
        return jsonify({"error": "code required"}), 400

    conn = get_conn()
    rows = conn.execute(
        """
        SELECT date, code, open, high, low, close, volume, amount,
               pct_chg, turnover, amplitude, change_amount
        FROM daily_bars
        WHERE code = ? AND date BETWEEN ? AND ?
        ORDER BY date DESC
        LIMIT ?
        """,
        (code, start, end, limit),
    ).fetchall()
    return jsonify({"code": code, "count": len(rows), "bars": [row_to_dict(r) for r in rows]})


# ── /api/market ───────────────────────────────────────────────────────────────

@app.get("/api/market")
@require_api_key
def market():
    start = request.args.get("start", "2025-01-01")
    end = request.args.get("end", "9999-12-31")
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM market_daily WHERE date BETWEEN ? AND ? ORDER BY date DESC",
        (start, end),
    ).fetchall()
    return jsonify([row_to_dict(r) for r in rows])


# ── /api/zt ───────────────────────────────────────────────────────────────────

@app.get("/api/zt")
@require_api_key
def zt_single():
    conn = get_conn()
    date = request.args.get("date")
    if not date:
        row = conn.execute("SELECT MAX(date) FROM zt_pool").fetchone()
        date = row[0] if row else None
    if not date:
        return jsonify([])

    rows = conn.execute(
        "SELECT * FROM zt_pool WHERE date = ? ORDER BY amount DESC",
        (date,),
    ).fetchall()
    return jsonify({"date": date, "count": len(rows), "pool": [row_to_dict(r) for r in rows]})


@app.get("/api/zt/range")
@require_api_key
def zt_range():
    start = request.args.get("start", "2026-01-01")
    end = request.args.get("end", "9999-12-31")
    limit = min(int(request.args.get("limit", 1000)), 5000)
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM zt_pool WHERE date BETWEEN ? AND ? ORDER BY date DESC, amount DESC LIMIT ?",
        (start, end, limit),
    ).fetchall()
    return jsonify({"count": len(rows), "pool": [row_to_dict(r) for r in rows]})


# ── /api/etf ──────────────────────────────────────────────────────────────────

@app.get("/api/etf")
@require_api_key
def etf():
    code = (request.args.get("code") or "").strip()
    start = request.args.get("start", "2025-01-01")
    end = request.args.get("end", "9999-12-31")
    limit = min(int(request.args.get("limit", 500)), 2000)
    conn = get_conn()

    if code:
        rows = conn.execute(
            """
            SELECT date, code, name, close, pct_chg, amount,
                   open, high, low, volume, ma5, ma10, ma20
            FROM etf_daily
            WHERE code = ? AND date BETWEEN ? AND ?
            ORDER BY date DESC LIMIT ?
            """,
            (code, start, end, limit),
        ).fetchall()
    else:
        # 返回最新一天的 ETF 列表
        row = conn.execute("SELECT MAX(date) FROM etf_daily").fetchone()
        latest = row[0] if row else None
        rows = conn.execute(
            "SELECT * FROM etf_daily WHERE date = ? ORDER BY amount DESC LIMIT ?",
            (latest, limit),
        ).fetchall() if latest else []

    return jsonify({"count": len(rows), "data": [row_to_dict(r) for r in rows]})


# ── /api/screen ───────────────────────────────────────────────────────────────

@app.get("/api/screen")
@require_api_key
def screen():
    conn = get_conn()
    date = request.args.get("date")
    rule = (request.args.get("rule") or "").strip()

    if not date:
        row = conn.execute("SELECT MAX(date) FROM screen_results").fetchone()
        date = row[0] if row else None
    if not date:
        return jsonify([])

    params: list = [date]
    sql = "SELECT * FROM screen_results WHERE date = ?"
    if rule:
        sql += " AND rule_id = ?"
        params.append(rule)
    sql += " ORDER BY date DESC"

    rows = conn.execute(sql, params).fetchall()
    return jsonify({"date": date, "count": len(rows), "results": [row_to_dict(r) for r in rows]})


# ── /api/lhb/stock ────────────────────────────────────────────────────────────

@app.get("/api/lhb/stock")
@require_api_key
def lhb_stock():
    code = (request.args.get("code") or "").strip()
    limit = min(int(request.args.get("limit", 100)), 500)
    if not code:
        return jsonify({"error": "code required"}), 400

    conn = get_conn()
    records = conn.execute(
        """
        SELECT r.date, r.code, r.name, r.reason,
               r.close, r.pct_chg, r.lhb_net_buy, r.lhb_buy, r.lhb_sell,
               r.lhb_amount, r.market_amount, r.net_buy_ratio,
               r.after_1d, r.after_2d, r.after_5d, r.after_10d
        FROM lhb_records r
        WHERE r.code = ?
        ORDER BY r.date DESC
        LIMIT ?
        """,
        (code, limit),
    ).fetchall()

    if not records:
        return jsonify({"code": code, "records": []})

    rows = [row_to_dict(r) for r in records]
    dates = list({r["date"] for r in rows})
    seats_raw = conn.execute(
        f"""
        SELECT date, code, direction, seat_name, net_amount, buy_amount, sell_amount, seat_type
        FROM lhb_seats
        WHERE code = ? AND date IN ({','.join('?' * len(dates))})
        ORDER BY date DESC, ABS(net_amount) DESC
        """,
        (code, *dates),
    ).fetchall()

    from collections import defaultdict
    seats_by_date: dict[str, list] = defaultdict(list)
    for s in seats_raw:
        seats_by_date[s["date"]].append(row_to_dict(s))
    for row in rows:
        row["seats"] = seats_by_date.get(row["date"], [])

    return jsonify({"code": code, "name": rows[0]["name"] if rows else "", "records": rows})


# ── /api/lhb/seat ─────────────────────────────────────────────────────────────

@app.get("/api/lhb/seat")
@require_api_key
def lhb_seat():
    name = (request.args.get("name") or "").strip()
    limit = min(int(request.args.get("limit", 200)), 1000)
    if not name:
        return jsonify({"error": "name required"}), 400

    conn = get_conn()
    rows = conn.execute(
        """
        SELECT s.date, s.code, r.name AS stock_name, s.direction,
               s.net_amount, s.buy_amount, s.sell_amount,
               r.pct_chg, r.after_1d, r.after_2d, r.after_5d, r.after_10d, r.reason
        FROM lhb_seats s
        LEFT JOIN lhb_records r ON r.date = s.date AND r.code = s.code
        WHERE s.seat_name = ?
        ORDER BY s.date DESC, ABS(s.net_amount) DESC
        LIMIT ?
        """,
        (name, limit),
    ).fetchall()

    total_buy = sum(float(r["buy_amount"] or 0) for r in rows if r["direction"] == "买入")
    total_sell = sum(float(r["buy_amount"] or 0) for r in rows if r["direction"] == "卖出")
    total_net = sum(float(r["net_amount"] or 0) for r in rows)

    return jsonify({
        "seat_name": name,
        "summary": {"appearances": len(rows), "total_buy": total_buy,
                    "total_sell": total_sell, "total_net": total_net},
        "records": [row_to_dict(r) for r in rows],
    })


# ── /api/lhb/search/stock ─────────────────────────────────────────────────────

@app.get("/api/lhb/search/stock")
@require_api_key
def search_stock():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify([])
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT code, name, COUNT(*) AS appearances,
               MAX(date) AS last_date, MIN(date) AS first_date
        FROM lhb_records
        WHERE code LIKE ? OR name LIKE ?
        GROUP BY code, name
        ORDER BY appearances DESC
        LIMIT 20
        """,
        (f"%{q}%", f"%{q}%"),
    ).fetchall()
    return jsonify([row_to_dict(r) for r in rows])


# ── /api/lhb/search/seat ──────────────────────────────────────────────────────

@app.get("/api/lhb/search/seat")
@require_api_key
def search_seat():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify([])
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT seat_name, COUNT(*) AS appearances,
               SUM(net_amount) AS total_net, MAX(date) AS last_date
        FROM lhb_seats
        WHERE seat_name LIKE ?
        GROUP BY seat_name
        ORDER BY appearances DESC
        LIMIT 20
        """,
        (f"%{q}%",),
    ).fetchall()
    return jsonify([row_to_dict(r) for r in rows])


# ── main ──────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=PROJECT_ROOT / "data" / "quant.db")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--host", default="127.0.0.1")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    global _db_path, _api_key
    _db_path = args.db
    _api_key = os.environ.get("QUANT_API_KEY") or None
    if _api_key:
        print(f"API key authentication enabled")
    else:
        print(f"WARNING: QUANT_API_KEY not set, authentication disabled")
    print(f"API server starting on {args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
