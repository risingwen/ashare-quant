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
import sqlite3
import sys
from functools import wraps
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
    tables = {}
    for tbl, date_col in [
        ("daily_bars", "date"), ("zt_pool", "date"),
        ("lhb_records", "date"), ("market_daily", "date"),
    ]:
        row = conn.execute(f"SELECT MAX({date_col}) FROM {tbl}").fetchone()
        tables[tbl] = row[0] if row else None
    return jsonify({"status": "ok", "latest": tables})


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
