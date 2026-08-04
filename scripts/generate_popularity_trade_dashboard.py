#!/usr/bin/env python3
"""Generate a standalone, filterable dashboard for popularity-entry trades."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text

from quant_platform.db import engine
from quant_platform.research.minute_analysis import BUY_COST, SELL_COST, _load_market, _signal_rows


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEMPLATE = PROJECT_ROOT / "scripts" / "popularity_trade_dashboard.html"
DEFAULT_OUTPUT = PROJECT_ROOT / "reports" / "popularity_new_top10_trade_dashboard.html"
DEFAULT_SITE_OUTPUT = PROJECT_ROOT / "apps" / "web" / "public" / "strategy-research" / "popularity-new-top10.html"
SHANGHAI = ZoneInfo("Asia/Shanghai")
SOURCE_LABELS = {"dc_hot": "东方财富", "ths_hot": "同花顺"}
BOARD_LABELS = {"Mainboard": "主板", "ChiNext": "创业板", "STAR": "科创板", "BSE": "北交所"}
BENCHMARK_LABELS = {
    "000001.SH": "上证综指",
    "399001.SZ": "深证成指",
    "399006.SZ": "创业板指",
    "000688.SH": "科创50",
}


def _iso(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _number(value: Any) -> float | None:
    return float(value) if value is not None else None


def _pct(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return (numerator / denominator - 1) * 100


def _net_return(exit_price: float | None, entry_price: float) -> float | None:
    if exit_price is None:
        return None
    return (exit_price * (1 - SELL_COST) / (entry_price * (1 + BUY_COST)) - 1) * 100


def _candle_label(open_price: float, close_price: float) -> str:
    if close_price > open_price:
        return "阳线"
    if close_price < open_price:
        return "阴线"
    return "平盘"


def _consecutive_absent_days(
    symbol: str,
    endpoint: str,
    signal_index: int,
    calendar: list[str],
    top10: dict[tuple[str, str], set[str]],
    cap: int = 30,
) -> tuple[int, bool]:
    """Count complete prior trading days outside the source's top ten."""
    absent = 0
    for index in range(signal_index - 1, max(-1, signal_index - cap - 1), -1):
        run_date = calendar[index]
        members = top10.get((endpoint, run_date), set())
        if len(members) < 10:
            return absent, False
        if symbol in members:
            return absent, True
        absent += 1
    return absent, True


def _rank_value(rank_map: dict[tuple[str, str], dict[str, int]], endpoint: str, run_date: str, symbol: str) -> int | None:
    return rank_map.get((endpoint, run_date), {}).get(symbol)


def _source_scope(record: dict[str, Any], signal_scope: str = "new") -> str:
    if signal_scope == "all":
        in_dc = record.get("dc_rank") is not None and record["dc_rank"] <= 10
        in_ths = record.get("ths_rank") is not None and record["ths_rank"] <= 10
        if in_dc and in_ths:
            return "双榜前十"
        return "东方财富" if in_dc else "同花顺"
    if record["dc_new_top10"] and record["ths_new_top10"]:
        return "双榜新进"
    if record["dc_new_top10"]:
        return "东方财富"
    return "同花顺"


def _benchmark_for_symbol(symbol: str) -> tuple[str, str] | None:
    """Map complete board code families to the user's requested benchmark."""
    if symbol.startswith(("600", "601", "603", "605")):
        code = "000001.SH"
    elif symbol.startswith(("000", "001", "002", "003")):
        code = "399001.SZ"
    elif symbol.startswith(("300", "301")):
        code = "399006.SZ"
    elif symbol.startswith(("688", "689")):
        code = "000688.SH"
    else:
        return None
    return code, BENCHMARK_LABELS[code]


def _load_benchmark_states(start: str, end: str) -> dict[tuple[str, str], dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(text("""SELECT index_code,index_name,trade_date,close,ma5,observations,provider
          FROM (
            SELECT index_code,index_name,trade_date,close,provider,
              avg(close) OVER (
                PARTITION BY index_code ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
              ) ma5,
              count(*) OVER (
                PARTITION BY index_code ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
              ) observations
            FROM market.index_daily
            WHERE trade_date BETWEEN :start AND :end
          ) states
          ORDER BY index_code,trade_date"""), {"start": start, "end": end}).mappings()
        result = {}
        for row in rows:
            close = _number(row["close"])
            ma5 = _number(row["ma5"])
            observations = int(row["observations"])
            if close is None or ma5 is None or observations < 5:
                continue
            run_date = _iso(row["trade_date"])
            result[(row["index_code"], run_date)] = {
                "code": row["index_code"],
                "name": row["index_name"],
                "close": close,
                "ma5": ma5,
                "above_ma5": close >= ma5,
                "distance_pct": _pct(close, ma5),
                "provider": row["provider"],
            }
        return result


def _load_high_factors(
    signal_keys: set[tuple[str, str]],
    end: str,
) -> dict[tuple[str, str], dict[str, dict[str, Any]]]:
    """Calculate prior rolling highs without using any bars after the signal day."""
    if not signal_keys:
        return {}
    symbols = sorted({symbol for symbol, _ in signal_keys})
    windows = (20, 60, 120, 250)
    window_columns = ",\n".join(
        f"max(high) OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN {window} PRECEDING AND 1 PRECEDING) prior_high_{window},\n"
        f"count(*) OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN {window} PRECEDING AND 1 PRECEDING) observations_{window}"
        for window in windows
    )
    with engine.connect() as conn:
        rows = conn.execute(text(f"""SELECT symbol,trade_date,high,close,{window_columns}
          FROM market.daily_bar
          WHERE symbol=ANY(:symbols) AND trade_date<=:end
          ORDER BY symbol,trade_date"""), {"symbols": symbols, "end": end}).mappings()
        result: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
        for row in rows:
            key = (row["symbol"], _iso(row["trade_date"]))
            if key not in signal_keys:
                continue
            close = _number(row["close"])
            high = _number(row["high"])
            factors: dict[str, dict[str, Any]] = {}
            for window in windows:
                observations = int(row[f"observations_{window}"])
                prior_high = _number(row[f"prior_high_{window}"])
                if observations < window or prior_high in (None, 0) or close is None or high is None:
                    continue
                factors[str(window)] = {
                    "prior_high": prior_high,
                    "distance_pct": _pct(close, prior_high),
                    "high_breakout": high >= prior_high,
                    "close_breakout": close >= prior_high,
                }
            result[key] = factors
        return result


def _performance_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [float(row["rule_return_pct"]) for row in records if row.get("rule_return_pct") is not None]
    return {
        "records": len(records),
        "completed_returns": len(returns),
        "wins": sum(value > 0 for value in returns),
        "win_rate_pct": sum(value > 0 for value in returns) / len(returns) * 100 if returns else None,
        "average_return_pct": mean(returns) if returns else None,
        "median_return_pct": median(returns) if returns else None,
    }


def _benchmark_comparison(records: list[dict[str, Any]]) -> dict[str, Any]:
    covered = [row for row in records if row.get("benchmark_above_ma5") is not None]
    above = [row for row in covered if row["benchmark_above_ma5"]]
    below = [row for row in covered if not row["benchmark_above_ma5"]]
    baseline = _performance_summary(covered)
    filtered = _performance_summary(above)
    comparison = {
        "all_records": len(records),
        "covered_records": len(covered),
        "missing_records": len(records) - len(covered),
        "baseline": baseline,
        "above_ma5": filtered,
        "below_ma5": _performance_summary(below),
        "retained_pct": len(above) / len(covered) * 100 if covered else None,
        "win_rate_delta_pp": None,
        "average_return_delta_pp": None,
        "by_index": {},
    }
    if baseline["win_rate_pct"] is not None and filtered["win_rate_pct"] is not None:
        comparison["win_rate_delta_pp"] = filtered["win_rate_pct"] - baseline["win_rate_pct"]
    if baseline["average_return_pct"] is not None and filtered["average_return_pct"] is not None:
        comparison["average_return_delta_pp"] = filtered["average_return_pct"] - baseline["average_return_pct"]
    for code, name in BENCHMARK_LABELS.items():
        group = [row for row in covered if row.get("benchmark_code") == code]
        group_above = [row for row in group if row["benchmark_above_ma5"]]
        comparison["by_index"][code] = {
            "name": name,
            "baseline": _performance_summary(group),
            "above_ma5": _performance_summary(group_above),
        }
    return comparison


def _load_daily_extras(symbols: list[str], start: str, end: str) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, dict[str, Any]]]:
    with engine.connect() as conn:
        daily_rows = conn.execute(text("""SELECT symbol,trade_date,open,high,low,close,volume,amount,pct_change,turnover
          FROM market.daily_bar WHERE symbol=ANY(:symbols) AND trade_date BETWEEN :start AND :end
          ORDER BY symbol,trade_date"""), {"symbols": symbols, "start": start, "end": end}).mappings()
        daily = {}
        for row in daily_rows:
            item = dict(row)
            item["trade_date"] = _iso(item["trade_date"])
            for field in ("open", "high", "low", "close", "volume", "amount", "pct_change", "turnover"):
                item[field] = _number(item[field])
            if item["amount"] is not None:
                item["amount_yuan"] = item["amount"] * 1000
            daily[(item["symbol"], item["trade_date"])] = item
        instruments = {
            row["symbol"]: dict(row)
            for row in conn.execute(text("""SELECT symbol,name,exchange,board,list_date
              FROM market.instrument WHERE symbol=ANY(:symbols)"""), {"symbols": symbols}).mappings()
        }
    return daily, instruments


def _first_touch_rows(specs: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    if not specs:
        return {}
    payload = json.dumps(specs, ensure_ascii=False)
    with engine.connect() as conn:
        rows = conn.execute(text("""SELECT c.symbol,c.trade_date,m.trade_time,m.open,m.high,m.low,m.close,m.volume,m.amount
          FROM jsonb_to_recordset(CAST(:payload AS jsonb))
            AS c(symbol text,trade_date date,target numeric)
          JOIN LATERAL (
            SELECT trade_time,open,high,low,close,volume,amount
            FROM market.minute_bar
            WHERE freq='1min' AND symbol=c.symbol AND trade_date=c.trade_date AND low<=c.target
            ORDER BY trade_time LIMIT 1
          ) m ON true"""), {"payload": payload}).mappings()
        result = {}
        for row in rows:
            item = dict(row)
            item["trade_date"] = _iso(item["trade_date"])
            local_time = item["trade_time"].astimezone(SHANGHAI)
            item["trade_time"] = local_time.isoformat()
            item["time_label"] = local_time.strftime("%H:%M")
            for field in ("open", "high", "low", "close", "volume", "amount"):
                item[field] = _number(item[field])
            result[(item["symbol"], item["trade_date"])] = item
        return result


def _rank_history(
    symbol: str,
    signal_index: int,
    calendar: list[str],
    rank_map: dict[tuple[str, str], dict[str, int]],
) -> list[dict[str, Any]]:
    rows = []
    for offset in range(-5, 6):
        index = signal_index + offset
        if not 0 <= index < len(calendar):
            continue
        run_date = calendar[index]
        rows.append({
            "offset": offset,
            "date": run_date,
            "dc_rank": _rank_value(rank_map, "dc_hot", run_date, symbol),
            "ths_rank": _rank_value(rank_map, "ths_hot", run_date, symbol),
        })
    return rows


def _kline_window(
    symbol: str,
    signal_index: int,
    calendar: list[str],
    daily_extra: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for index in range(max(0, signal_index - 10), min(len(calendar), signal_index + 11)):
        run_date = calendar[index]
        bar = daily_extra.get((symbol, run_date))
        if bar is None:
            continue
        rows.append({
            "offset": index - signal_index,
            "date": run_date,
            "open": bar["open"],
            "high": bar["high"],
            "low": bar["low"],
            "close": bar["close"],
            "amount_yi": bar.get("amount_yuan", 0) / 100_000_000,
        })
    return rows


def build_records(
    start: str,
    end: str,
    min_adv20: float,
    buy_discount: float,
    signal_scope: str = "new",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if signal_scope not in {"new", "all"}:
        raise ValueError("signal_scope must be 'new' or 'all'")
    padded_start = (date.fromisoformat(start) - timedelta(days=60)).isoformat()
    padded_end = (date.fromisoformat(end) + timedelta(days=30)).isoformat()
    popularity_rows = [row for row in _signal_rows(padded_start, padded_end, 100) if row["mode"] == "final"]

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
        calendar = [
            _iso(row[0])
            for row in conn.execute(text("""SELECT trade_date FROM market.trade_calendar
              WHERE is_open AND trade_date BETWEEN :start AND :end ORDER BY trade_date"""), {
                "start": padded_start,
                "end": padded_end,
            })
        ]
    calendar_index = {run_date: index for index, run_date in enumerate(calendar)}

    signals: dict[tuple[str, str], dict[str, Any]] = {}
    audit = defaultdict(int)
    for signal_date in calendar:
        if not start <= signal_date <= end:
            continue
        signal_index = calendar_index[signal_date]
        if signal_index == 0 or signal_index + 1 >= len(calendar):
            continue
        symbols = top10.get(("dc_hot", signal_date), set()) | top10.get(("ths_hot", signal_date), set())
        for symbol in symbols:
            source_details = {}
            for endpoint in SOURCE_LABELS:
                current_rank = _rank_value(rank_map, endpoint, signal_date, symbol)
                previous_date = calendar[signal_index - 1]
                previous_members = top10.get((endpoint, previous_date), set())
                source_complete = len(top10.get((endpoint, signal_date), set())) >= 10 and len(previous_members) >= 10
                is_new = bool(source_complete and current_rank is not None and current_rank <= 10 and symbol not in previous_members)
                absent_days, absence_complete = (0, False)
                if is_new:
                    absent_days, absence_complete = _consecutive_absent_days(
                        symbol, endpoint, signal_index, calendar, top10,
                    )
                source_details[endpoint] = {
                    "rank": current_rank,
                    "previous_rank": _rank_value(rank_map, endpoint, previous_date, symbol),
                    "is_new": is_new,
                    "absent_days": absent_days,
                    "absence_complete": absence_complete,
                }
            if signal_scope == "new" and not any(value["is_new"] for value in source_details.values()):
                continue
            audit[f"{signal_scope}_signal_stock_days"] += 1
            name = (
                name_map.get(("dc_hot", signal_date, symbol))
                or name_map.get(("ths_hot", signal_date, symbol))
                or symbol
            )
            signals[(symbol, signal_date)] = {
                "symbol": symbol,
                "name": name,
                "signal_date": signal_date,
                "signal_index": signal_index,
                "entry_date": calendar[signal_index + 1],
                "dc": source_details["dc_hot"],
                "ths": source_details["ths_hot"],
            }

    symbols = sorted({symbol for symbol, _ in signals})
    if not symbols:
        return [], {"audit": dict(audit)}
    market_calendar, daily, adv20, minute_summary, limits = _load_market(symbols, start, end)
    if market_calendar != calendar:
        calendar = market_calendar
        calendar_index = {run_date: index for index, run_date in enumerate(calendar)}
        for signal in signals.values():
            signal["signal_index"] = calendar_index[signal["signal_date"]]
            signal["entry_date"] = calendar[signal["signal_index"] + 1]
    daily_extra, instruments = _load_daily_extras(symbols, padded_start, padded_end)
    benchmark_states = _load_benchmark_states(padded_start, padded_end)

    eligible = []
    touch_specs = []
    for signal in signals.values():
        symbol = signal["symbol"]
        signal_date = signal["signal_date"]
        entry_date = signal["entry_date"]
        reference = daily.get((symbol, signal_date))
        entry_daily = daily.get((symbol, entry_date))
        entry_minute = minute_summary.get((symbol, entry_date))
        liquidity = adv20.get((symbol, entry_date))
        if "ST" in signal["name"].upper():
            audit["excluded_st"] += 1
            continue
        if reference is None or entry_daily is None or entry_minute is None:
            audit["excluded_market_or_minute_missing"] += 1
            continue
        if liquidity is None or liquidity < min_adv20:
            audit["excluded_liquidity"] += 1
            continue
        audit["liquid_with_minute"] += 1
        target = reference["close"] * (1 - buy_discount)
        if entry_daily["open"] <= target:
            fill_type = "低开成交"
            entry_price = entry_daily["open"]
        elif entry_minute["low"] <= target:
            fill_type = "盘中触及"
            entry_price = target
            touch_specs.append({"symbol": symbol, "trade_date": entry_date, "target": target})
        else:
            audit["not_filled"] += 1
            continue
        eligible.append({
            **signal,
            "target_price": target,
            "entry_price": entry_price,
            "fill_type": fill_type,
            "reference": reference,
            "entry_daily": entry_daily,
            "entry_minute": entry_minute,
            "adv20": liquidity,
        })

    touches = _first_touch_rows(touch_specs)
    high_factors = _load_high_factors(
        {(item["symbol"], item["signal_date"]) for item in eligible},
        padded_end,
    )
    records = []
    for item in eligible:
        symbol = item["symbol"]
        signal_date = item["signal_date"]
        entry_date = item["entry_date"]
        signal_index = item["signal_index"]
        reference = item["reference"]
        entry_daily = item["entry_daily"]
        minute = item["entry_minute"]
        reference_extra = daily_extra.get((symbol, signal_date), {})
        entry_extra = daily_extra.get((symbol, entry_date), {})
        if item["fill_type"] == "低开成交":
            fill_time = "09:30"
            fill_minute_amount = None
        else:
            touch = touches.get((symbol, entry_date))
            if touch is None:
                audit["excluded_touch_time_missing"] += 1
                continue
            fill_time = touch["time_label"]
            fill_minute_amount = touch["amount"]

        horizon = {}
        for offset in (1, 2, 3, 5):
            index = signal_index + offset
            if index >= len(calendar):
                continue
            horizon_date = calendar[index]
            bar = daily.get((symbol, horizon_date))
            extra = daily_extra.get((symbol, horizon_date), {})
            if bar is None:
                continue
            up_limit = limits.get((symbol, horizon_date))
            horizon[str(offset)] = {
                "date": horizon_date,
                "close": bar["close"],
                "natural_pct": _pct(bar["close"], reference["close"]),
                "from_entry_pct": _net_return(bar["close"], item["entry_price"]),
                "daily_pct": extra.get("pct_change"),
                "amount_yi": extra.get("amount_yuan", 0) / 100_000_000 if extra else None,
                "limit_up": bool(up_limit is not None and bar["close"] >= up_limit - 0.005),
            }

        exit_date = None
        exit_price = None
        limit_holds = 0
        for candidate_date in calendar[signal_index + 2:]:
            bar = daily.get((symbol, candidate_date))
            if bar is None:
                continue
            up_limit = limits.get((symbol, candidate_date))
            if up_limit is None:
                break
            if bar["close"] >= up_limit - 0.005:
                limit_holds += 1
                continue
            exit_date = candidate_date
            exit_price = bar["close"]
            break

        dc = item["dc"]
        ths = item["ths"]
        instrument = instruments.get(symbol, {})
        board = instrument.get("board") or instrument.get("exchange") or "其他"
        benchmark_spec = _benchmark_for_symbol(symbol)
        benchmark = benchmark_states.get((benchmark_spec[0], signal_date)) if benchmark_spec else None
        eligible_ranks = [
            source["rank"] for source in (dc, ths)
            if source["rank"] is not None and (
                source["is_new"] if signal_scope == "new" else source["rank"] <= 10
            )
        ]
        signal_amount_yi = reference_extra.get("amount_yuan", 0) / 100_000_000 if reference_extra else None
        entry_amount_yi = entry_extra.get("amount_yuan", 0) / 100_000_000 if entry_extra else None
        adv20_yi = item["adv20"] / 100_000_000
        record = {
            "trade_key": f"{signal_date}-{symbol}",
            "symbol": symbol,
            "name": item["name"],
            "board": BOARD_LABELS.get(board, board),
            "benchmark_code": benchmark_spec[0] if benchmark_spec else None,
            "benchmark_name": benchmark_spec[1] if benchmark_spec else None,
            "benchmark_close": benchmark["close"] if benchmark else None,
            "benchmark_ma5": benchmark["ma5"] if benchmark else None,
            "benchmark_above_ma5": benchmark["above_ma5"] if benchmark else None,
            "benchmark_distance_pct": benchmark["distance_pct"] if benchmark else None,
            "high_factors": high_factors.get((symbol, signal_date), {}),
            "signal_date": signal_date,
            "entry_date": entry_date,
            "source_scope": None,
            "dc_new_top10": dc["is_new"],
            "ths_new_top10": ths["is_new"],
            "dc_rank": dc["rank"],
            "ths_rank": ths["rank"],
            "dc_previous_rank": dc["previous_rank"],
            "ths_previous_rank": ths["previous_rank"],
            "dc_absent_days": dc["absent_days"] if dc["is_new"] else 0,
            "ths_absent_days": ths["absent_days"] if ths["is_new"] else 0,
            "best_rank": min(eligible_ranks),
            "max_absent_days": max(dc["absent_days"], ths["absent_days"]),
            "signal_close": reference["close"],
            "signal_daily_pct": reference_extra.get("pct_change"),
            "target_price": item["target_price"],
            "entry_open": entry_daily["open"],
            "entry_high": entry_daily["high"],
            "entry_low": minute["low"],
            "entry_close": entry_daily["close"],
            "entry_candle": _candle_label(entry_daily["open"], entry_daily["close"]),
            "entry_candle_pct": _pct(entry_daily["close"], entry_daily["open"]),
            "entry_open_gap_pct": _pct(entry_daily["open"], reference["close"]),
            "entry_low_pct": _pct(minute["low"], reference["close"]),
            "entry_price": item["entry_price"],
            "entry_price_vs_signal_pct": _pct(item["entry_price"], reference["close"]),
            "fill_type": item["fill_type"],
            "fill_time": fill_time,
            "fill_minute_amount_wan": fill_minute_amount / 10_000 if fill_minute_amount is not None else None,
            "signal_amount_yi": signal_amount_yi,
            "entry_amount_yi": entry_amount_yi,
            "adv20_yi": adv20_yi,
            "entry_amount_vs_adv20": entry_amount_yi / adv20_yi if entry_amount_yi is not None and adv20_yi else None,
            "signal_turnover": reference_extra.get("turnover"),
            "entry_turnover": entry_extra.get("turnover"),
            "horizon": horizon,
            "rule_exit_date": exit_date,
            "rule_exit_price": exit_price,
            "rule_return_pct": _net_return(exit_price, item["entry_price"]),
            "limit_hold_days": limit_holds,
            "rank_history": _rank_history(symbol, signal_index, calendar, rank_map),
            "kline": _kline_window(symbol, signal_index, calendar, daily_extra),
        }
        record["source_scope"] = _source_scope(record, signal_scope)
        records.append(record)

    records.sort(key=lambda row: (row["signal_date"], row["best_rank"], row["symbol"]), reverse=True)
    audit["filled_trade_records"] = len(records)
    metadata = {
        "parameters": {
            "start": start,
            "end": end,
            "min_adv20_yi": min_adv20 / 100_000_000,
            "buy_discount_pct": buy_discount * 100,
            "signal_scope": signal_scope,
            "buy_cost_pct": BUY_COST * 100,
            "sell_cost_pct": SELL_COST * 100,
        },
        "audit": dict(audit),
        "benchmark_comparison": _benchmark_comparison(records),
    }
    return records, metadata


def _csv_value(record: dict[str, Any], key: str) -> Any:
    if key.startswith("t") and key.endswith("_return_pct"):
        offset = key[1:key.index("_")]
        return record.get("horizon", {}).get(offset, {}).get("from_entry_pct")
    if key.startswith("high_"):
        _, window, field = key.split("_", 2)
        return record.get("high_factors", {}).get(window, {}).get(field)
    return record.get(key)


def write_csv(records: list[dict[str, Any]], output: Path) -> None:
    columns = [
        "signal_date", "entry_date", "symbol", "name", "board", "source_scope", "dc_rank", "ths_rank",
        "dc_previous_rank", "ths_previous_rank", "dc_absent_days", "ths_absent_days", "signal_close",
        "target_price", "entry_price", "fill_type", "fill_time", "entry_low_pct", "signal_amount_yi",
        "entry_candle", "entry_candle_pct",
        "entry_amount_yi", "adv20_yi", "entry_amount_vs_adv20", "t1_return_pct", "t2_return_pct",
        "t3_return_pct", "t5_return_pct", "rule_exit_date", "rule_exit_price", "rule_return_pct",
        "limit_hold_days",
        "benchmark_code", "benchmark_name", "benchmark_close", "benchmark_ma5",
        "benchmark_above_ma5", "benchmark_distance_pct",
        "high_20_distance_pct", "high_20_close_breakout", "high_60_distance_pct",
        "high_60_close_breakout", "high_120_distance_pct", "high_120_close_breakout",
        "high_250_distance_pct", "high_250_close_breakout",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for record in records:
            writer.writerow({column: _csv_value(record, column) for column in columns})


def render_html(
    records: list[dict[str, Any]],
    metadata: dict[str, Any],
    template_path: Path,
    output: Path,
    presentation: dict[str, Any] | None = None,
) -> None:
    template = template_path.read_text(encoding="utf-8")
    data_json = json.dumps(records, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    rendered_metadata = {**metadata, "presentation": presentation or {}}
    metadata_json = json.dumps(rendered_metadata, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    generated_at = date.today().isoformat()
    html = (
        template.replace("__DASHBOARD_DATA__", data_json)
        .replace("__DASHBOARD_METADATA__", metadata_json)
        .replace("__GENERATED_AT__", generated_at)
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成人气新进前十 T+1 成交记录可筛选 HTML")
    parser.add_argument("--start", default="2025-01-01")
    parser.add_argument("--end", default="2026-06-30")
    parser.add_argument("--min-adv20", type=float, default=1_000_000_000, help="入场日前20日平均成交额下限（元）")
    parser.add_argument("--buy-discount", type=float, default=0.02, help="相对T日收盘价的买入折价，例如0.02")
    parser.add_argument("--signal-scope", choices=("new", "all"), default="new")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--site-output", type=Path, default=DEFAULT_SITE_OUTPUT)
    parser.add_argument("--csv-output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records, metadata = build_records(
        args.start, args.end, args.min_adv20, args.buy_discount, args.signal_scope,
    )
    render_html(records, metadata, args.template, args.output)
    render_html(records, metadata, args.template, args.site_output)
    csv_output = args.csv_output or args.output.with_suffix(".csv")
    write_csv(records, csv_output)
    average_return = mean(
        row["rule_return_pct"] for row in records if row["rule_return_pct"] is not None
    ) if records else None
    print(json.dumps({
        "html": str(args.output),
        "site_html": str(args.site_output),
        "csv": str(csv_output),
        "records": len(records),
        "average_rule_return_pct": average_return,
        **metadata,
    }, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
