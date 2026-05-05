"""
api_server.py
轻量 Flask API 服务，供龙虎榜页面前端按需查询。

Endpoints:
  GET /api/lhb/stock?code=600000[&limit=50]   个股历史龙虎榜记录（含席位）
  GET /api/lhb/seat?name=华泰...              营业部历史买卖记录
  GET /api/lhb/search/stock?q=600000|平安     按代码或名称搜索出现过的股票
  GET /api/lhb/search/seat?q=华泰             按名称搜索营业部

Usage:
    python src/api_server.py --db data/quant.db --port 8081
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from flask import Flask, jsonify, request
from quant_db import connect

app = Flask(__name__)
_db_path: Path | None = None


def get_conn() -> sqlite3.Connection:
    return connect(_db_path)


def row_to_dict(row) -> dict:
    return dict(row)


# ── CORS ──────────────────────────────────────────────────────────────────────
@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


# ── /api/lhb/stock ────────────────────────────────────────────────────────────
@app.get("/api/lhb/stock")
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

    # 附加每次上榜的席位
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
               r.pct_chg, r.after_1d, r.after_2d, r.after_5d, r.after_10d,
               r.reason
        FROM lhb_seats s
        LEFT JOIN lhb_records r ON r.date = s.date AND r.code = s.code
        WHERE s.seat_name = ?
        ORDER BY s.date DESC, ABS(s.net_amount) DESC
        LIMIT ?
        """,
        (name, limit),
    ).fetchall()

    # 统计汇总
    total_buy = sum(float(r["buy_amount"] or 0) for r in rows if r["direction"] == "买入")
    total_sell = sum(float(r["buy_amount"] or 0) for r in rows if r["direction"] == "卖出")
    total_net = sum(float(r["net_amount"] or 0) for r in rows)

    return jsonify({
        "seat_name": name,
        "summary": {
            "appearances": len(rows),
            "total_buy": total_buy,
            "total_sell": total_sell,
            "total_net": total_net,
        },
        "records": [row_to_dict(r) for r in rows],
    })


# ── /api/lhb/search/stock ─────────────────────────────────────────────────────
@app.get("/api/lhb/search/stock")
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
def search_seat():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify([])
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT seat_name,
               COUNT(*) AS appearances,
               SUM(net_amount) AS total_net,
               MAX(date) AS last_date
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
    global _db_path
    _db_path = args.db
    print(f"API server starting on {args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
