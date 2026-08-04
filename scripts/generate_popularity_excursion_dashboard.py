#!/usr/bin/env python3
"""Generate T+1 high/low excursion statistics for popularity top-ten stocks."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text

from generate_popularity_trade_dashboard import (
    BOARD_LABELS,
    PROJECT_ROOT,
    SOURCE_LABELS,
    _benchmark_for_symbol,
    _consecutive_absent_days,
    _iso,
    _rank_value,
    _source_scope,
)
from quant_platform.db import engine
from quant_platform.research.minute_analysis import BUY_COST, SELL_COST, _load_market, _signal_rows


DEFAULT_TEMPLATE = PROJECT_ROOT / "scripts" / "popularity_excursion_dashboard.html"
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "apps" / "web" / "public" / "strategy-research"
    / "popularity-top10-excursions.html"
)


def _pct(numerator: float, denominator: float) -> float:
    return (numerator / denominator - 1) * 100


def _net_return(exit_price: float, entry_price: float) -> float:
    return (exit_price * (1 - SELL_COST) / (entry_price * (1 + BUY_COST)) - 1) * 100


def _mark_to_market(close_price: float, entry_price: float) -> float:
    """T+1 closing floating return; buy cost paid, no same-day sale assumed."""
    return (close_price / (entry_price * (1 + BUY_COST)) - 1) * 100


def _strict_core(source: dict[str, Any]) -> bool:
    return bool(
        source["is_new"]
        and source["rank"] is not None
        and source["rank"] <= 5
        and source["absent_days"] >= 10
    )


def _load_benchmark_bars(start: str, end: str) -> dict[tuple[str, str], dict[str, float]]:
    with engine.connect() as conn:
        rows = conn.execute(text("""SELECT index_code,trade_date,open,close
          FROM market.index_daily WHERE trade_date BETWEEN :start AND :end"""), {
            "start": start,
            "end": end,
        }).mappings()
        return {
            (row["index_code"], _iso(row["trade_date"])): {
                "open": float(row["open"]),
                "close": float(row["close"]),
            }
            for row in rows if row["open"] is not None and row["close"] is not None
        }


def _load_down_limits(
    symbols: list[str], start: str, end: str,
) -> dict[tuple[str, str], float]:
    if not symbols:
        return {}
    with engine.connect() as conn:
        rows = conn.execute(text("""SELECT symbol,trade_date,down_limit
          FROM market.price_limit
          WHERE symbol=ANY(:symbols) AND trade_date BETWEEN :start AND :end
            AND down_limit IS NOT NULL"""), {
            "symbols": symbols,
            "start": start,
            "end": end,
        }).mappings()
        return {
            (row["symbol"], _iso(row["trade_date"])): float(row["down_limit"])
            for row in rows
        }


def _limit_flags(
    entry: dict[str, float], down_limit: float | None, tolerance: float = 0.0051,
) -> tuple[bool, bool, bool]:
    if down_limit is None:
        return False, False, False
    touch = entry["low"] <= down_limit + tolerance
    close = entry["close"] <= down_limit + tolerance
    one_word = all(
        abs(entry[field] - down_limit) <= tolerance
        for field in ("open", "high", "low", "close")
    )
    return touch, close, one_word


def build_excursion_records(start: str, end: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    padded_start = (date.fromisoformat(start) - timedelta(days=60)).isoformat()
    popularity_rows = [
        row for row in _signal_rows(padded_start, end, 100)
        if row["mode"] == "final"
    ]
    rank_map: dict[tuple[str, str], dict[str, int]] = defaultdict(dict)
    name_map: dict[tuple[str, str, str], str] = {}
    for row in popularity_rows:
        run_date = _iso(row["trade_date"])
        rank_map[(row["endpoint"], run_date)][row["symbol"]] = int(row["rank"])
        if row.get("name"):
            name_map[(row["endpoint"], run_date, row["symbol"])] = row["name"]
    top10 = {
        key: {symbol for symbol, rank in values.items() if rank <= 10}
        for key, values in rank_map.items()
    }
    with engine.connect() as conn:
        seed_calendar = [
            _iso(row[0])
            for row in conn.execute(text("""SELECT trade_date FROM market.trade_calendar
              WHERE is_open AND trade_date BETWEEN :start AND :end ORDER BY trade_date"""), {
                "start": padded_start,
                "end": (date.fromisoformat(end) + timedelta(days=10)).isoformat(),
            })
        ]
    calendar_index = {run_date: index for index, run_date in enumerate(seed_calendar)}
    signals: dict[tuple[str, str], dict[str, Any]] = {}
    for signal_date in seed_calendar:
        if not start <= signal_date <= end:
            continue
        signal_index = calendar_index[signal_date]
        if signal_index == 0 or signal_index + 1 >= len(seed_calendar):
            continue
        symbols = top10.get(("dc_hot", signal_date), set()) | top10.get(("ths_hot", signal_date), set())
        previous_date = seed_calendar[signal_index - 1]
        for symbol in symbols:
            sources = {}
            for endpoint in SOURCE_LABELS:
                rank = _rank_value(rank_map, endpoint, signal_date, symbol)
                previous_members = top10.get((endpoint, previous_date), set())
                complete = len(top10.get((endpoint, signal_date), set())) >= 10 and len(previous_members) >= 10
                is_new = bool(complete and rank is not None and rank <= 10 and symbol not in previous_members)
                absent_days = 0
                absence_complete = False
                if is_new:
                    absent_days, absence_complete = _consecutive_absent_days(
                        symbol, endpoint, signal_index, seed_calendar, top10,
                    )
                sources[endpoint] = {
                    "rank": rank,
                    "is_new": is_new,
                    "absent_days": absent_days,
                    "absence_complete": absence_complete,
                }
            signals[(symbol, signal_date)] = {
                "symbol": symbol,
                "name": name_map.get(("dc_hot", signal_date, symbol))
                or name_map.get(("ths_hot", signal_date, symbol))
                or symbol,
                "signal_date": signal_date,
                "entry_date": seed_calendar[signal_index + 1],
                "dc": sources["dc_hot"],
                "ths": sources["ths_hot"],
            }

    symbols = sorted({symbol for symbol, _ in signals})
    calendar, daily, adv20, minute_summary, _ = _load_market(symbols, start, end)
    if calendar != seed_calendar:
        market_index = {run_date: index for index, run_date in enumerate(calendar)}
        for signal in signals.values():
            signal_index = market_index.get(signal["signal_date"])
            if signal_index is not None and signal_index + 1 < len(calendar):
                signal["entry_date"] = calendar[signal_index + 1]
    market_index = {run_date: index for index, run_date in enumerate(calendar)}
    benchmark_bars = _load_benchmark_bars(calendar[0], calendar[-1]) if calendar else {}
    down_limits = _load_down_limits(symbols, calendar[0], calendar[-1]) if calendar else {}
    with engine.connect() as conn:
        instruments = {
            row["symbol"]: dict(row)
            for row in conn.execute(text("""SELECT symbol,name,exchange,board
              FROM market.instrument WHERE symbol=ANY(:symbols)"""), {"symbols": symbols}).mappings()
        }

    audit = defaultdict(int)
    records = []
    for signal in signals.values():
        symbol = signal["symbol"]
        signal_date = signal["signal_date"]
        entry_date = signal["entry_date"]
        reference = daily.get((symbol, signal_date))
        entry = daily.get((symbol, entry_date))
        if "ST" in signal["name"].upper():
            audit["excluded_st"] += 1
            continue
        if reference is None or entry is None or reference["close"] <= 0:
            audit["excluded_missing_t_or_t1_bar"] += 1
            continue
        dc, ths = signal["dc"], signal["ths"]
        instrument = instruments.get(symbol, {})
        benchmark_spec = _benchmark_for_symbol(symbol)
        entry_down_limit = down_limits.get((symbol, entry_date))
        t1_touch_down_limit, t1_close_down_limit, t1_one_word_down_limit = _limit_flags(
            entry, entry_down_limit,
        )
        drop7 = {
            "drop7_triggered": False,
            "drop7_filled": False,
            "drop7_fill_type": None,
            "drop7_entry_price": None,
            "drop7_entry_pct": None,
            "drop7_t1_float_pct": None,
            "drop7_t1_benchmark_pct": None,
            "drop7_t1_excess_pct": None,
            "drop7_t2_date": None,
            "drop7_t2_return_pct": None,
            "drop7_t2_benchmark_pct": None,
            "drop7_t2_excess_pct": None,
            "drop7_t3_date": None,
            "drop7_t3_return_pct": None,
            "drop7_t3_benchmark_pct": None,
            "drop7_t3_excess_pct": None,
        }
        target = reference["close"] * 0.93
        entry_minute = minute_summary.get((symbol, entry_date))
        entry_price = None
        fill_type = None
        if t1_one_word_down_limit and entry["low"] <= target:
            entry_price = entry["open"]
            fill_type = "一字跌停未成交"
        elif entry_minute is not None:
            if entry["open"] <= target:
                entry_price = entry["open"]
                fill_type = "低开成交"
            elif entry_minute["low"] <= target:
                entry_price = target
                fill_type = "盘中触及"
        if entry_price is not None:
            drop7.update({
                "drop7_triggered": True,
                "drop7_filled": not t1_one_word_down_limit,
                "drop7_fill_type": fill_type,
                "drop7_entry_price": entry_price,
                "drop7_entry_pct": _pct(entry_price, reference["close"]),
            })
        if entry_price is not None and not t1_one_word_down_limit:
            signal_index = market_index.get(signal_date)
            benchmark_entry = (
                benchmark_bars.get((benchmark_spec[0], entry_date)) if benchmark_spec else None
            )
            t1_float = _mark_to_market(entry["close"], entry_price)
            t1_benchmark = None
            if benchmark_entry is not None and benchmark_entry["open"] > 0:
                t1_benchmark = _pct(benchmark_entry["close"], benchmark_entry["open"])
            drop7.update({
                "drop7_t1_float_pct": t1_float,
                "drop7_t1_benchmark_pct": t1_benchmark,
                "drop7_t1_excess_pct": t1_float - t1_benchmark if t1_benchmark is not None else None,
            })
            for offset in (2, 3):
                if signal_index is None or signal_index + offset >= len(calendar):
                    continue
                exit_date = calendar[signal_index + offset]
                exit_bar = daily.get((symbol, exit_date))
                if exit_bar is None:
                    continue
                strategy_return = _net_return(exit_bar["close"], entry_price)
                benchmark_return = None
                if benchmark_entry is not None:
                    benchmark_exit = benchmark_bars.get((benchmark_spec[0], exit_date))
                    if benchmark_exit is not None and benchmark_entry["open"] > 0:
                        benchmark_return = _pct(benchmark_exit["close"], benchmark_entry["open"])
                drop7.update({
                    f"drop7_t{offset}_date": exit_date,
                    f"drop7_t{offset}_return_pct": strategy_return,
                    f"drop7_t{offset}_benchmark_pct": benchmark_return,
                    f"drop7_t{offset}_excess_pct": (
                        strategy_return - benchmark_return if benchmark_return is not None else None
                    ),
                })
        record = {
            "signal_date": signal_date,
            "entry_date": entry_date,
            "symbol": symbol,
            "name": instrument.get("name") or signal["name"],
            "board": BOARD_LABELS.get(instrument.get("board"), instrument.get("board") or instrument.get("exchange") or "其他"),
            "source_scope": _source_scope({
                "dc_rank": dc["rank"],
                "ths_rank": ths["rank"],
            }, "all"),
            "dc_rank": dc["rank"],
            "ths_rank": ths["rank"],
            "dc_new_top10": dc["is_new"],
            "ths_new_top10": ths["is_new"],
            "dc_absent_days": dc["absent_days"],
            "ths_absent_days": ths["absent_days"],
            "is_new_top10": dc["is_new"] or ths["is_new"],
            "is_strict_core": _strict_core(dc) or _strict_core(ths),
            "signal_close": reference["close"],
            "t1_open_pct": _pct(entry["open"], reference["close"]),
            "t1_low_pct": _pct(entry["low"], reference["close"]),
            "t1_high_pct": _pct(entry["high"], reference["close"]),
            "t1_close_pct": _pct(entry["close"], reference["close"]),
            "signal_amount_yi": reference["amount"] / 100_000_000,
            "t1_amount_yi": entry["amount"] / 100_000_000,
            "adv20_yi": adv20.get((symbol, entry_date), 0) / 100_000_000 if adv20.get((symbol, entry_date)) else None,
            "benchmark_code": benchmark_spec[0] if benchmark_spec else None,
            "benchmark_name": benchmark_spec[1] if benchmark_spec else None,
            "entry_down_limit": entry_down_limit,
            "t1_touch_down_limit": t1_touch_down_limit,
            "t1_close_down_limit": t1_close_down_limit,
            "t1_one_word_down_limit": t1_one_word_down_limit,
            **drop7,
        }
        records.append(record)
    records.sort(key=lambda row: (row["signal_date"], row["symbol"]), reverse=True)
    audit["eligible_stock_days"] = len(records)
    audit["new_top10_stock_days"] = sum(row["is_new_top10"] for row in records)
    audit["strict_core_stock_days"] = sum(row["is_strict_core"] for row in records)
    audit["drop7_triggered_stock_days"] = sum(row["drop7_triggered"] for row in records)
    audit["drop7_filled_stock_days"] = sum(row["drop7_filled"] for row in records)
    audit["drop7_one_word_unfilled"] = sum(
        row["drop7_triggered"] and row["t1_one_word_down_limit"] for row in records
    )
    return records, {
        "parameters": {"start": start, "end": end},
        "audit": dict(audit),
        "costs": {"buy_pct": BUY_COST * 100, "sell_pct": SELL_COST * 100},
        "definition": "T+1最高/最低价相对T日实际收盘价；−7%成交要求有分钟线，低开按开盘价、盘中触及按T收盘×93%；一字跌停标记为触发但不可成交；T+1为扣买入成本后的收盘浮盈，T+2/T+3按收盘卖出并扣双边成本。",
        "benchmark_definition": "超额收益=策略净收益−对应指数从T+1开盘到卖出日收盘的涨跌幅；盘中成交时刻不同，因此是统一近似。",
    }


def render(records: list[dict[str, Any]], metadata: dict[str, Any], template: Path, output: Path) -> None:
    source = template.read_text(encoding="utf-8")
    data = json.dumps(records, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    meta = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        source.replace("__EXCURSION_DATA__", data).replace("__EXCURSION_METADATA__", meta),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成人气前十T+1高低点分布页面")
    parser.add_argument("--start", default="2025-01-01")
    parser.add_argument("--end", default="latest", help="最后一个T日；latest自动取倒数第二个行情交易日")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    end = args.end
    if end == "latest":
        with engine.connect() as conn:
            latest_dates = [
                _iso(row[0]) for row in conn.execute(text("""SELECT DISTINCT trade_date
                  FROM market.daily_bar ORDER BY trade_date DESC LIMIT 2"""))
            ]
        if len(latest_dates) < 2:
            raise RuntimeError("at least two daily market dates are required")
        end = latest_dates[1]
    records, metadata = build_excursion_records(args.start, end)
    render(records, metadata, args.template, args.output)
    print(json.dumps({"output": str(args.output), "records": len(records)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
