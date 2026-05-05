"""
screener.py
选股引擎 —— 基于 daily_bars + stocks 表做规则筛选。

每条规则是一个 ScreenRule 子类，实现 apply(conn, date) -> list[dict]。
主函数跑全部规则，结果写入 screen_results 表，并输出 CSV/打印摘要。

内置规则
--------
NewHighMomentum（新高动量）
  近 N 日出现历史新高（基于 daily_bars.high 的全历史最高价）
  + 成交额 >= amount_threshold（元）
  + 总市值在 [mv_min, mv_max]（元）

Usage:
    python src/screener.py [--db data/quant.db] [--date 2026-04-30] [--rule all]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from quant_db import connect


# ── DB schema ─────────────────────────────────────────────────────────────────

SCREEN_RESULTS_DDL = """
CREATE TABLE IF NOT EXISTS screen_results (
    rule_id     TEXT NOT NULL,
    date        TEXT NOT NULL,
    code        TEXT NOT NULL,
    name        TEXT,
    detail      TEXT,          -- JSON blob 附加字段
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    PRIMARY KEY (rule_id, date, code)
);
CREATE INDEX IF NOT EXISTS idx_screen_results_date ON screen_results(date);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    for stmt in SCREEN_RESULTS_DDL.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)
    conn.commit()


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def trading_dates_before(conn: sqlite3.Connection, ref_date: str, n: int) -> list[str]:
    """返回 ref_date 往前（含）n 个有数据的交易日，降序。"""
    rows = conn.execute(
        "SELECT DISTINCT date FROM daily_bars WHERE date <= ? ORDER BY date DESC LIMIT ?",
        (ref_date, n),
    ).fetchall()
    return [r[0] for r in rows]


# ── 规则基类 ──────────────────────────────────────────────────────────────────

class ScreenRule:
    rule_id: str = ""
    description: str = ""

    def apply(self, conn: sqlite3.Connection, ref_date: str) -> list[dict[str, Any]]:
        """
        返回命中的股票列表，每项是 dict，必须包含:
            code, name, detail(dict)
        """
        raise NotImplementedError


# ── 规则：新高动量 ─────────────────────────────────────────────────────────────

class NewHighMomentum(ScreenRule):
    """
    近 recent_days 个交易日内出现历史新高，
    同时满足成交额和市值过滤条件。

    参数
    ----
    recent_days     : 近多少个交易日内出现新高（默认 3）
    amount_min      : 成交额下限，单位元（默认 1e9 = 10亿）
    mv_min          : 总市值下限，单位元（默认 10e9 = 100亿）
    mv_max          : 总市值上限，单位元（默认 50e9 = 500亿）
    history_days    : 历史新高计算窗口（默认全历史，0 = 全部）
    exclude_st      : 是否排除 ST（默认 True）
    exclude_new     : 上市不足 N 天的不计入（默认 250）
    """

    rule_id = "new_high_momentum"
    description = "近3日历史新高 + 成交额>10亿 + 总市值100-500亿"

    def __init__(
        self,
        recent_days: int = 3,
        amount_min: float = 1e9,
        mv_min: float = 10e9,
        mv_max: float = 50e9,
        history_days: int = 0,
        exclude_st: bool = True,
        exclude_new_days: int = 250,
    ):
        self.recent_days = recent_days
        self.amount_min = amount_min
        self.mv_min = mv_min
        self.mv_max = mv_max
        self.history_days = history_days
        self.exclude_st = exclude_st
        self.exclude_new_days = exclude_new_days

    def apply(self, conn: sqlite3.Connection, ref_date: str) -> list[dict[str, Any]]:
        # 近 recent_days 个交易日
        recent = trading_dates_before(conn, ref_date, self.recent_days)
        if not recent:
            return []
        cutoff_recent = recent[-1]   # 最早的那天

        # 历史窗口起点
        if self.history_days > 0:
            hist_start = (
                date.fromisoformat(ref_date) - timedelta(days=self.history_days)
            ).isoformat()
        else:
            hist_start = "2000-01-01"

        # ST 过滤
        st_filter = "AND s.is_st = 0" if self.exclude_st else ""

        sql = f"""
        WITH
        -- 近 recent_days 内每只股票的最高价及成交额
        recent AS (
            SELECT
                b.code,
                MAX(b.high)   AS recent_high,
                MAX(b.amount) AS max_amount,
                MAX(b.date)   AS last_date
            FROM daily_bars b
            WHERE b.date >= :cutoff_recent AND b.date <= :ref_date
            GROUP BY b.code
        ),
        -- 历史最高价（不含 recent 窗口，用于对比）
        hist AS (
            SELECT
                b.code,
                MAX(b.high) AS hist_high
            FROM daily_bars b
            WHERE b.date >= :hist_start AND b.date < :cutoff_recent
            GROUP BY b.code
        ),
        -- 最新收盘价（用于算市值）
        latest AS (
            SELECT b.code, b.close, b.amount AS latest_amount, b.date AS bar_date
            FROM daily_bars b
            WHERE b.date = (
                SELECT MAX(date) FROM daily_bars WHERE date <= :ref_date
            )
        )
        SELECT
            r.code,
            s.name,
            s.market,
            s.total_shares,
            r.recent_high,
            h.hist_high,
            r.max_amount,
            l.close,
            l.latest_amount,
            l.close * s.total_shares AS total_mv
        FROM recent r
        JOIN hist h      ON h.code = r.code
        JOIN latest l    ON l.code = r.code
        JOIN stocks s    ON s.code = r.code
        WHERE
            s.total_shares IS NOT NULL
            AND r.recent_high >= h.hist_high           -- 创历史新高
            AND r.max_amount  >= :amount_min            -- 成交额满足
            AND l.close * s.total_shares >= :mv_min     -- 市值下限
            AND l.close * s.total_shares <= :mv_max     -- 市值上限
            {st_filter}
        ORDER BY total_mv DESC
        """

        rows = conn.execute(sql, {
            "cutoff_recent": cutoff_recent,
            "ref_date": ref_date,
            "hist_start": hist_start,
            "amount_min": self.amount_min,
            "mv_min": self.mv_min,
            "mv_max": self.mv_max,
        }).fetchall()

        results = []
        for r in rows:
            mv_yi = round(r["total_mv"] / 1e8, 1)
            amt_yi = round(r["max_amount"] / 1e8, 2)
            results.append({
                "code": r["code"],
                "name": r["name"],
                "detail": {
                    "market": r["market"],
                    "close": r["close"],
                    "recent_high": r["recent_high"],
                    "hist_high": r["hist_high"],
                    "max_amount_yi": amt_yi,
                    "total_mv_yi": mv_yi,
                },
            })
        return results


# ── 规则注册表 ────────────────────────────────────────────────────────────────

RULES: dict[str, ScreenRule] = {
    "new_high_momentum": NewHighMomentum(),
}


# ── 写库 ──────────────────────────────────────────────────────────────────────

def save_results(
    conn: sqlite3.Connection,
    rule_id: str,
    ref_date: str,
    results: list[dict],
) -> None:
    with conn:
        # 先清除当天旧结果
        conn.execute(
            "DELETE FROM screen_results WHERE rule_id=? AND date=?",
            (rule_id, ref_date),
        )
        conn.executemany(
            """
            INSERT INTO screen_results(rule_id, date, code, name, detail)
            VALUES(?, ?, ?, ?, ?)
            """,
            [
                (rule_id, ref_date, r["code"], r["name"], json.dumps(r["detail"], ensure_ascii=False))
                for r in results
            ],
        )


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Stock screener")
    p.add_argument("--db", type=Path, default=PROJECT_ROOT / "data" / "quant.db")
    p.add_argument("--date", default=None, help="YYYY-MM-DD, default=latest in daily_bars")
    p.add_argument("--rule", default="all", help="Rule id or 'all'")
    p.add_argument("--no-save", action="store_true", help="Print only, don't write to DB")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    conn = connect(args.db)
    ensure_schema(conn)

    # 确定基准日期
    if args.date:
        ref_date = args.date
    else:
        ref_date = conn.execute(
            "SELECT MAX(date) d FROM daily_bars"
        ).fetchone()["d"]
    print(f"Screener date: {ref_date}")

    rules = list(RULES.values()) if args.rule == "all" else [RULES[args.rule]]

    for rule in rules:
        print(f"\n[{rule.rule_id}] {rule.description}")
        results = rule.apply(conn, ref_date)
        print(f"  命中 {len(results)} 只")
        for r in results:
            d = r["detail"]
            print(
                f"  {r['code']} {r['name']:<8} "
                f"市值={d['total_mv_yi']}亿  成交={d['max_amount_yi']}亿  "
                f"新高={d['recent_high']:.2f}  历史高={d['hist_high']:.2f}"
            )
        if not args.no_save:
            save_results(conn, rule.rule_id, ref_date, results)
            print(f"  已写入 screen_results 表")


if __name__ == "__main__":
    main()
