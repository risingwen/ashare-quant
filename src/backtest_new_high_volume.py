#!/usr/bin/env python3
"""Backtest historical-new-high plus heavy-volume strategies from SQLite."""

from __future__ import annotations

import argparse
import csv
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from quant_core import DEFAULT_DB_PATH, is_limit_down, is_limit_up
from quant_db import connect


@dataclass(frozen=True)
class Strategy:
    name: str
    description: str
    volume_days: int
    volume_ratio: float
    min_amount_e8: float
    min_pct: float
    max_pct: float | None
    min_turnover: float | None
    max_hold_days: int
    max_positions_per_day: int
    min_history_days: int
    cycle_filter: str


STRATEGIES = [
    Strategy(
        name="HH_VOL_MA5_BASE",
        description="可用历史收盘新高 + 近20日均量2倍以上 + 成交额>=5亿；次日开盘买入，收盘跌破5日线卖出，最多持有20日。",
        volume_days=20,
        volume_ratio=2.0,
        min_amount_e8=5.0,
        min_pct=1.0,
        max_pct=None,
        min_turnover=None,
        max_hold_days=20,
        max_positions_per_day=10,
        min_history_days=250,
        cycle_filter="none",
    ),
    Strategy(
        name="HH_VOL_MA5_WARM_CYCLE",
        description="可用历史收盘新高 + 近20日均量1.5倍以上 + 成交额>=8亿 + 当日涨幅2%-9.5% + 市场暖/强周期；跌破5日线卖出，最多持有20日。",
        volume_days=20,
        volume_ratio=1.5,
        min_amount_e8=8.0,
        min_pct=2.0,
        max_pct=9.5,
        min_turnover=None,
        max_hold_days=20,
        max_positions_per_day=8,
        min_history_days=250,
        cycle_filter="warm",
    ),
    Strategy(
        name="HH_VOL_MA5_HOT_LEADER",
        description="可用历史收盘新高 + 近60日均量1.2倍以上 + 成交额>=10亿 + 换手率>=3% + 当日涨幅>=5% + 市场强周期；跌破5日线卖出，最多持有30日。",
        volume_days=60,
        volume_ratio=1.2,
        min_amount_e8=10.0,
        min_pct=5.0,
        max_pct=None,
        min_turnover=3.0,
        max_hold_days=30,
        max_positions_per_day=5,
        min_history_days=250,
        cycle_filter="hot",
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest historical-new-high heavy-volume strategies")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--report-dir", type=Path, default=Path("reports/backtests"))
    parser.add_argument("--start-date", default="2024-01-01")
    parser.add_argument("--end-date", default=None)
    return parser.parse_args()


def mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def max_drawdown(equity_values: list[float]) -> float | None:
    if not equity_values:
        return None
    peak = equity_values[0]
    worst = 0.0
    for value in equity_values:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, (value / peak - 1) * 100)
    return worst


def trade_return(buy_open: float, sell_close: float) -> float:
    return (sell_close - buy_open) / buy_open * 100


def gap_return(signal_close: float, buy_open: float) -> float:
    return (buy_open - signal_close) / signal_close * 100


def running_prior_max(values: list[float]) -> list[float | None]:
    result: list[float | None] = []
    prior: float | None = None
    for value in values:
        result.append(prior)
        prior = value if prior is None else max(prior, value)
    return result


def rolling_prior_avg(values: list[float], window: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    prefix = [0.0]
    for value in values:
        prefix.append(prefix[-1] + value)
    for index in range(window, len(values)):
        result[index] = (prefix[index] - prefix[index - window]) / window
    return result


def rolling_ma(values: list[float], window: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    prefix = [0.0]
    for value in values:
        prefix.append(prefix[-1] + value)
    for index in range(window - 1, len(values)):
        result[index] = (prefix[index + 1] - prefix[index + 1 - window]) / window
    return result


def cycle_rank(state: str) -> int:
    return {"cold": 0, "warm": 1, "hot": 2}.get(state, 0)


def compute_market_cycles(conn, start_date: str) -> dict[str, dict[str, object]]:
    rows = conn.execute(
        """
        SELECT b.date, b.pct_chg, s.market, s.is_st
        FROM daily_bars b
        JOIN stocks s ON s.code = b.code
        WHERE b.date >= date(?, '-30 day') AND s.eligible = 1
        ORDER BY b.date
        """,
        (start_date,),
    ).fetchall()
    grouped: dict[str, list] = defaultdict(list)
    for row in rows:
        grouped[row["date"]].append(row)

    cycles: dict[str, dict[str, object]] = {}
    for date, day_rows in grouped.items():
        count = len(day_rows)
        up_count = sum(1 for row in day_rows if float(row["pct_chg"]) > 0)
        limit_up_count = sum(1 for row in day_rows if is_limit_up(float(row["pct_chg"]), row["market"], bool(row["is_st"])))
        limit_down_count = sum(1 for row in day_rows if is_limit_down(float(row["pct_chg"]), row["market"], bool(row["is_st"])))
        up_ratio = up_count / count if count else 0.0
        score = min(limit_up_count / 100 * 40, 40) + up_ratio * 40 - min(limit_down_count / 50 * 25, 25) + 20
        if score >= 70 and limit_up_count >= 60 and up_ratio >= 0.50 and limit_down_count <= 25:
            state = "hot"
        elif score >= 50 and limit_up_count >= 35 and up_ratio >= 0.40 and limit_down_count <= 50:
            state = "warm"
        else:
            state = "cold"
        cycles[date] = {
            "state": state,
            "score": round(score, 2),
            "up_ratio": up_ratio,
            "limit_up_count": limit_up_count,
            "limit_down_count": limit_down_count,
        }
    return cycles


def passes_cycle(strategy: Strategy, cycle: dict[str, object] | None) -> bool:
    if strategy.cycle_filter == "none":
        return True
    if not cycle:
        return False
    return cycle_rank(str(cycle["state"])) >= cycle_rank(strategy.cycle_filter)


def passes_strategy(strategy: Strategy, bar: dict[str, object], index: int, prior_high: float | None, avg_volume: float | None, market: str, is_st: bool, cycle: dict[str, object] | None) -> tuple[bool, float, float]:
    if index < strategy.min_history_days or prior_high is None or avg_volume is None:
        return False, 0.0, 0.0
    if not passes_cycle(strategy, cycle):
        return False, 0.0, 0.0

    close = float(bar["close"])
    pct_chg = float(bar["pct_chg"])
    volume = float(bar["volume"])
    amount_e8 = float(bar["amount"]) / 100_000_000
    turnover = float(bar["turnover"])
    if avg_volume <= 0:
        return False, 0.0, 0.0
    vol_ratio = volume / avg_volume

    if close <= prior_high:
        return False, vol_ratio, 0.0
    if vol_ratio < strategy.volume_ratio:
        return False, vol_ratio, 0.0
    if amount_e8 < strategy.min_amount_e8:
        return False, vol_ratio, 0.0
    if pct_chg < strategy.min_pct:
        return False, vol_ratio, 0.0
    if strategy.max_pct is not None and pct_chg > strategy.max_pct:
        return False, vol_ratio, 0.0
    if strategy.min_turnover is not None and turnover < strategy.min_turnover:
        return False, vol_ratio, 0.0

    cycle_score = float(cycle["score"]) if cycle else 50.0
    limit_penalty = 0.6 if is_limit_up(pct_chg, market, is_st) else 1.0
    score = amount_e8 * vol_ratio * (1 + cycle_score / 100) * limit_penalty
    return True, vol_ratio, score


def load_stock_rows(conn, code: str) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT date, open, close, high, low, volume, amount, pct_chg, turnover
        FROM daily_bars
        WHERE code = ?
        ORDER BY date
        """,
        (code,),
    ).fetchall()
    return [dict(row) for row in rows]


def find_exit(bars: list[dict[str, object]], ma5: list[float | None], buy_index: int, max_hold_days: int) -> tuple[int, str] | None:
    max_sell_index = buy_index + max_hold_days - 1
    available_sell_index = min(max_sell_index, len(bars) - 1)
    for sell_index in range(buy_index, available_sell_index + 1):
        if ma5[sell_index] is not None and float(bars[sell_index]["close"]) < float(ma5[sell_index]):
            return sell_index, "break_ma5"
    if max_sell_index < len(bars):
        return max_sell_index, "max_hold"
    return None


def generate_raw_trades(conn, strategy: Strategy, start_date: str, end_date: str | None, cycles: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    stocks = conn.execute("SELECT code, name, market, is_st FROM stocks WHERE eligible = 1 ORDER BY code").fetchall()
    trades: list[dict[str, object]] = []
    for stock in stocks:
        bars = load_stock_rows(conn, stock["code"])
        if len(bars) < strategy.min_history_days + strategy.max_hold_days + 1:
            continue
        closes = [float(item["close"]) for item in bars]
        volumes = [float(item["volume"]) for item in bars]
        prior_highs = running_prior_max(closes)
        avg_volumes = rolling_prior_avg(volumes, strategy.volume_days)
        ma5 = rolling_ma(closes, 5)

        for index in range(len(bars) - 1):
            signal = bars[index]
            signal_date = str(signal["date"])
            if signal_date < start_date:
                continue
            if end_date and signal_date > end_date:
                continue

            cycle = cycles.get(signal_date)
            ok, vol_ratio, score = passes_strategy(strategy, signal, index, prior_highs[index], avg_volumes[index], stock["market"], bool(stock["is_st"]), cycle)
            if not ok:
                continue

            buy_index = index + 1
            exit_result = find_exit(bars, ma5, buy_index, strategy.max_hold_days)
            if exit_result is None:
                continue
            sell_index, exit_reason = exit_result
            buy_bar = bars[buy_index]
            sell_bar = bars[sell_index]
            if end_date and str(sell_bar["date"]) > end_date:
                continue
            if float(buy_bar["open"]) <= 0 or float(signal["close"]) <= 0:
                continue

            trades.append(
                {
                    "strategy": strategy.name,
                    "signal_date": signal_date,
                    "buy_date": buy_bar["date"],
                    "sell_date": sell_bar["date"],
                    "code": stock["code"],
                    "name": stock["name"],
                    "market": stock["market"],
                    "signal_close": float(signal["close"]),
                    "buy_open": float(buy_bar["open"]),
                    "sell_close": float(sell_bar["close"]),
                    "return_pct": trade_return(float(buy_bar["open"]), float(sell_bar["close"])),
                    "gap_pct": gap_return(float(signal["close"]), float(buy_bar["open"])),
                    "amount_e8": float(signal["amount"]) / 100_000_000,
                    "volume_ratio": vol_ratio,
                    "new_high_days": 0,
                    "hold_days": sell_index - buy_index + 1,
                    "score": score,
                    "cycle_state": cycle["state"] if cycle else "unknown",
                    "cycle_score": cycle["score"] if cycle else None,
                    "exit_reason": exit_reason,
                }
            )
    return trades


def apply_daily_position_limit(trades: list[dict[str, object]], max_positions: int) -> list[dict[str, object]]:
    by_day: dict[str, list[dict[str, object]]] = defaultdict(list)
    for trade in trades:
        by_day[str(trade["signal_date"])].append(trade)
    selected: list[dict[str, object]] = []
    for date in sorted(by_day):
        day_trades = sorted(by_day[date], key=lambda item: float(item["score"]), reverse=True)
        selected.extend(day_trades[:max_positions])
    return selected


def summarize_strategy(strategy: Strategy, trades: list[dict[str, object]], start_date: str, end_date: str) -> dict[str, object]:
    returns = [float(item["return_pct"]) for item in trades]
    gaps = [float(item["gap_pct"]) for item in trades]
    holds = [float(item["hold_days"]) for item in trades]
    by_day: dict[str, list[float]] = defaultdict(list)
    for item in trades:
        by_day[str(item["signal_date"])].append(float(item["return_pct"]))

    equity = 1.0
    equity_values = [equity]
    for date in sorted(by_day):
        batch_return = statistics.fmean(by_day[date]) / 100
        equity *= 1 + batch_return
        equity_values.append(equity)

    return {
        "strategy": strategy.name,
        "description": strategy.description,
        "start_date": start_date,
        "end_date": end_date,
        "trades": len(trades),
        "signal_days": len(by_day),
        "win_rate": sum(1 for value in returns if value > 0) / len(returns) if returns else None,
        "avg_return_pct": mean(returns),
        "median_return_pct": median(returns),
        "total_batch_return_pct": (equity - 1) * 100 if trades else None,
        "max_drawdown_pct": max_drawdown(equity_values),
        "avg_gap_pct": mean(gaps),
        "avg_hold_days": mean(holds),
    }


def write_outputs(report_dir: Path, summaries: list[dict[str, object]], trades: list[dict[str, object]]) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    summary_columns = ["strategy", "start_date", "end_date", "trades", "signal_days", "win_rate", "avg_return_pct", "median_return_pct", "total_batch_return_pct", "max_drawdown_pct", "avg_gap_pct", "avg_hold_days", "description"]
    trade_columns = ["strategy", "signal_date", "buy_date", "sell_date", "code", "name", "market", "return_pct", "gap_pct", "amount_e8", "volume_ratio", "hold_days", "cycle_state", "cycle_score", "exit_reason", "score"]

    with (report_dir / "new_high_volume_summary.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=summary_columns)
        writer.writeheader()
        writer.writerows(summaries)

    with (report_dir / "new_high_volume_trades.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=trade_columns)
        writer.writeheader()
        for trade in trades:
            writer.writerow({column: trade.get(column, "") for column in trade_columns})

    lines = ["# 历史新高放量策略回测", "", "| 策略 | 交易数 | 信号日 | 胜率 | 单笔均值 | 单笔中位数 | 批次复利收益 | 最大回撤 | 平均跳空 | 平均持有 |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for item in summaries:
        def pct(value: object) -> str:
            return "-" if value is None else f"{float(value):.2f}%"
        win = "-" if item["win_rate"] is None else f"{float(item['win_rate']) * 100:.2f}%"
        hold = "-" if item.get("avg_hold_days") is None else f"{float(item['avg_hold_days']):.2f}日"
        lines.append(
            f"| {item['strategy']} | {item['trades']} | {item['signal_days']} | {win} | {pct(item['avg_return_pct'])} | {pct(item['median_return_pct'])} | {pct(item['total_batch_return_pct'])} | {pct(item['max_drawdown_pct'])} | {pct(item['avg_gap_pct'])} | {hold} |"
        )
    lines.extend(["", "## 策略定义", ""])
    for item in summaries:
        lines.append(f"- `{item['strategy']}`: {item['description']}")
    lines.append("\n说明：历史新高基于数据库已有前复权日线。回测不包含手续费、滑点、涨停无法买入、跌停无法卖出和持仓重叠资金占用。")
    (report_dir / "new_high_volume_backtest.md").write_text("\n".join(lines), encoding="utf-8")


def persist_results(conn, summaries: list[dict[str, object]], trades: list[dict[str, object]], created_at: str) -> None:
    with conn:
        conn.execute("DELETE FROM strategy_backtests")
        conn.execute("DELETE FROM strategy_trades")
        conn.executemany(
            """
            INSERT INTO strategy_backtests(
                strategy, description, start_date, end_date, trades, signal_days,
                win_rate, avg_return_pct, median_return_pct, total_batch_return_pct,
                max_drawdown_pct, avg_gap_pct, avg_hold_days, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item["strategy"], item["description"], item["start_date"], item["end_date"],
                    item["trades"], item["signal_days"], item["win_rate"], item["avg_return_pct"],
                    item["median_return_pct"], item["total_batch_return_pct"], item["max_drawdown_pct"],
                    item["avg_gap_pct"], item["avg_hold_days"], created_at,
                )
                for item in summaries
            ],
        )
        conn.executemany(
            """
            INSERT INTO strategy_trades(
                strategy, signal_date, buy_date, sell_date, code, name, market,
                signal_close, buy_open, sell_close, return_pct, gap_pct, amount_e8,
                volume_ratio, new_high_days, hold_days, score, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item["strategy"], item["signal_date"], item["buy_date"], item["sell_date"],
                    item["code"], item["name"], item["market"], item["signal_close"], item["buy_open"],
                    item["sell_close"], item["return_pct"], item["gap_pct"], item["amount_e8"],
                    item["volume_ratio"], item["new_high_days"], item["hold_days"], item["score"], created_at,
                )
                for item in trades
            ],
        )


def main() -> None:
    args = parse_args()
    conn = connect(args.db)
    latest = conn.execute("SELECT MAX(date) AS latest_date FROM daily_bars").fetchone()
    if not latest or not latest["latest_date"]:
        raise SystemExit(f"Database has no daily bars: {args.db}")
    end_date = args.end_date or latest["latest_date"]
    cycles = compute_market_cycles(conn, args.start_date)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    all_summaries: list[dict[str, object]] = []
    all_trades: list[dict[str, object]] = []
    for strategy in STRATEGIES:
        raw_trades = generate_raw_trades(conn, strategy, args.start_date, end_date, cycles)
        trades = apply_daily_position_limit(raw_trades, strategy.max_positions_per_day)
        all_trades.extend(trades)
        summary = summarize_strategy(strategy, trades, args.start_date, end_date)
        all_summaries.append(summary)
        print(f"{strategy.name}: raw={len(raw_trades)}, selected={len(trades)}, total_batch_return={summary['total_batch_return_pct']}")

    persist_results(conn, all_summaries, all_trades, created_at)
    write_outputs(args.report_dir, all_summaries, all_trades)
    print(f"Backtest report: {args.report_dir / 'new_high_volume_backtest.md'}")


if __name__ == "__main__":
    main()
