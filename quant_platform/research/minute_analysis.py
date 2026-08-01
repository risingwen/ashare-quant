from __future__ import annotations

from collections import defaultdict, deque
from datetime import date, timedelta
from statistics import mean, median
from typing import Any

from sqlalchemy import text

from ..db import engine


BUY_COST = 0.0002 + 0.0005
SELL_COST = 0.0002 + 0.0005 + 0.0005


def _signal_rows(start: str, end: str, rank_max: int) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(text("""WITH preopen_snapshot AS (
            SELECT DISTINCT ON (endpoint,trade_date) id,endpoint,trade_date
            FROM popularity.snapshot
            WHERE status='success' AND category IN ('人气榜盘中','热股盘中')
              AND trade_date BETWEEN :start AND :end
              AND (snapshot_time AT TIME ZONE 'Asia/Shanghai')::time < time '09:30'
            ORDER BY endpoint,trade_date,snapshot_time DESC),
          signals AS (
            SELECT 'final' mode,s.endpoint,s.trade_date,i.symbol,i.name,i.rank
            FROM popularity.snapshot s JOIN popularity.snapshot_item i ON i.snapshot_id=s.id
            WHERE s.status='success' AND s.category IN ('人气榜','热股')
              AND s.trade_date BETWEEN :start AND :end AND i.rank<=:rank_max
            UNION ALL
            SELECT 'preopen' mode,s.endpoint,s.trade_date,i.symbol,i.name,i.rank
            FROM preopen_snapshot s JOIN popularity.snapshot_item i ON i.snapshot_id=s.id
            WHERE i.rank<=:rank_max)
          SELECT mode,endpoint,trade_date,symbol,max(name) name,min(rank) rank
          FROM signals GROUP BY mode,endpoint,trade_date,symbol
          ORDER BY mode,endpoint,trade_date,rank,symbol"""), {
            "start": start,
            "end": end,
            "rank_max": rank_max,
        }).mappings()
        return [dict(row) for row in rows]


def _load_market(symbols: list[str], start: str, end: str):
    padded_start = (date.fromisoformat(start) - timedelta(days=80)).isoformat()
    padded_end = (date.fromisoformat(end) + timedelta(days=20)).isoformat()
    with engine.connect() as conn:
        calendar = [row[0].isoformat() for row in conn.execute(text("""SELECT trade_date
          FROM market.trade_calendar WHERE is_open AND trade_date BETWEEN :start AND :end
          ORDER BY trade_date"""), {"start": padded_start, "end": padded_end})]
        daily_rows = list(conn.execute(text("""SELECT symbol,trade_date,open,high,low,close,amount
          FROM market.daily_bar WHERE symbol=ANY(:symbols) AND trade_date BETWEEN :start AND :end
          ORDER BY symbol,trade_date"""), {"symbols": symbols, "start": padded_start, "end": padded_end}).mappings())
        minute_rows = list(conn.execute(text("""SELECT symbol,trade_date,min(low) low,count(*) row_count
          FROM market.minute_bar WHERE freq='1min' AND symbol=ANY(:symbols)
            AND trade_date BETWEEN :start AND :end GROUP BY symbol,trade_date"""), {
            "symbols": symbols, "start": start, "end": padded_end,
        }).mappings())
        limit_rows = list(conn.execute(text("""SELECT symbol,trade_date,up_limit
          FROM market.price_limit WHERE symbol=ANY(:symbols) AND trade_date BETWEEN :start AND :end"""), {
            "symbols": symbols, "start": start, "end": padded_end,
        }).mappings())
    daily: dict[tuple[str, str], dict[str, float]] = {}
    adv20: dict[tuple[str, str], float | None] = {}
    history: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=20))
    for row in daily_rows:
        key = (row["symbol"], row["trade_date"].isoformat())
        values = {field: float(row[field]) for field in ("open", "high", "low", "close", "amount")}
        # Tushare's daily endpoint declares amount in 千元; strategy liquidity
        # thresholds are expressed in yuan.
        values["amount"] *= 1000
        daily[key] = values
        prior = history[row["symbol"]]
        adv20[key] = mean(prior) if len(prior) == 20 else None
        prior.append(values["amount"])
    minute = {(row["symbol"], row["trade_date"].isoformat()): {
        "low": float(row["low"]), "rows": int(row["row_count"]),
    } for row in minute_rows}
    limits = {(row["symbol"], row["trade_date"].isoformat()): float(row["up_limit"]) for row in limit_rows}
    return calendar, daily, adv20, minute, limits


def _build_events(
    signals: list[dict[str, Any]],
    calendar: list[str],
    daily: dict[tuple[str, str], dict[str, float]],
    adv20: dict[tuple[str, str], float | None],
    minute: dict[tuple[str, str], dict[str, float]],
    limits: dict[tuple[str, str], float],
    min_adv20: float,
    buy_cost: float,
    sell_cost: float,
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], dict[str, int]]]:
    calendar_index = {value: index for index, value in enumerate(calendar)}
    events = []
    audit: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for signal in signals:
        group = (signal["mode"], signal["endpoint"])
        audit[group]["signals"] += 1
        signal_date = signal["trade_date"].isoformat()
        index = calendar_index.get(signal_date)
        if index is None:
            continue
        if signal["mode"] == "final":
            if index + 2 >= len(calendar):
                continue
            reference_date, entry_date, first_exit_date = signal_date, calendar[index + 1], calendar[index + 2]
        else:
            if index == 0 or index + 1 >= len(calendar):
                continue
            reference_date, entry_date, first_exit_date = calendar[index - 1], signal_date, calendar[index + 1]
        reference = daily.get((signal["symbol"], reference_date))
        entry_daily = daily.get((signal["symbol"], entry_date))
        entry_minute = minute.get((signal["symbol"], entry_date))
        liquidity = adv20.get((signal["symbol"], entry_date))
        if "ST" in str(signal.get("name") or "").upper() or reference is None or entry_daily is None:
            continue
        audit[group]["eligible_market_data"] += 1
        if liquidity is None or liquidity < min_adv20:
            continue
        audit[group]["liquid"] += 1
        if entry_minute is None:
            continue
        audit[group]["minute_covered"] += 1
        target = reference["close"] * 0.98
        if entry_daily["open"] <= target:
            entry_price = entry_daily["open"]
            fill_type = "gap"
        elif entry_minute["low"] <= target:
            entry_price = target
            fill_type = "touch"
        else:
            continue
        audit[group]["filled"] += 1
        first_exit_index = calendar_index[first_exit_date]
        exit_date = None
        exit_price = None
        limit_holds = 0
        complete_limits = True
        for candidate_date in calendar[first_exit_index:]:
            exit_daily = daily.get((signal["symbol"], candidate_date))
            if exit_daily is None:
                continue
            up_limit = limits.get((signal["symbol"], candidate_date))
            if up_limit is None:
                complete_limits = False
                break
            if exit_daily["close"] >= up_limit - 0.005:
                limit_holds += 1
                continue
            exit_date = candidate_date
            exit_price = exit_daily["close"]
            break
        if not complete_limits or exit_date is None or exit_price is None:
            continue
        net_return = exit_price * (1 - sell_cost) / (entry_price * (1 + buy_cost)) - 1
        events.append({
            **signal,
            "signal_date": signal_date,
            "entry_date": entry_date,
            "exit_date": exit_date,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "fill_type": fill_type,
            "minute_rows": entry_minute["rows"],
            "adv20": liquidity,
            "limit_holds": limit_holds,
            "net_return": net_return,
        })
        audit[group]["complete_trades"] += 1
    return events, audit


def _portfolio(
    events: list[dict[str, Any]],
    calendar: list[str],
    daily,
    max_positions: int,
    buy_cost: float,
    sell_cost: float,
) -> dict[str, Any]:
    by_entry: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        by_entry[event["entry_date"]].append(event)
    cash = 1.0
    positions: dict[str, dict[str, Any]] = {}
    last_price: dict[str, float] = {}
    equity = 1.0
    curve: list[tuple[str, float]] = []
    trades = 0
    for run_date in calendar:
        previous_equity = equity
        for event in sorted(by_entry.get(run_date, []), key=lambda item: (item["rank"], item["symbol"])):
            if len(positions) >= max_positions or event["symbol"] in positions:
                continue
            allocation = min(previous_equity / max_positions, cash)
            if allocation <= 0:
                continue
            quantity = allocation / (event["entry_price"] * (1 + buy_cost))
            cash -= allocation
            positions[event["symbol"]] = {**event, "quantity": quantity}
            last_price[event["symbol"]] = event["entry_price"]
            trades += 1
        for symbol, position in list(positions.items()):
            bar = daily.get((symbol, run_date))
            if bar is not None:
                last_price[symbol] = bar["close"]
            if position["exit_date"] == run_date:
                cash += position["quantity"] * position["exit_price"] * (1 - sell_cost)
                positions.pop(symbol)
                last_price.pop(symbol, None)
        equity = cash + sum(position["quantity"] * last_price[symbol] for symbol, position in positions.items())
        curve.append((run_date, equity))
    if not curve:
        return {}
    peak = curve[0][1]
    max_drawdown = 0.0
    month_end: dict[str, float] = {}
    for run_date, value in curve:
        peak = max(peak, value)
        max_drawdown = min(max_drawdown, value / peak - 1)
        month_end[run_date[:7]] = value
    monthly_returns = []
    prior = 1.0
    for month in sorted(month_end):
        value = month_end[month]
        monthly_returns.append((month, value / prior - 1))
        prior = value
    values = [value for _, value in monthly_returns]
    return {
        "trades": trades,
        "total_return_pct": (curve[-1][1] - 1) * 100,
        "max_drawdown_pct": max_drawdown * 100,
        "average_month_pct": mean(values) * 100 if values else None,
        "best_month_pct": max(values) * 100 if values else None,
        "worst_month_pct": min(values) * 100 if values else None,
        "months_ge_50pct": sum(value >= 0.5 for value in values),
        "months": len(values),
    }


def run_minute_popularity_analysis(
    start: str,
    end: str,
    rank_max: int = 10,
    max_positions: int = 10,
    min_adv20: float = 1_000_000_000,
    buy_cost: float = BUY_COST,
    sell_cost: float = SELL_COST,
) -> dict[str, Any]:
    signals = _signal_rows(start, end, rank_max)
    symbols = sorted({row["symbol"] for row in signals})
    calendar, daily, adv20, minute, limits = _load_market(symbols, start, end)
    events, audit = _build_events(
        signals, calendar, daily, adv20, minute, limits, min_adv20, buy_cost, sell_cost,
    )
    groups = []
    for mode, endpoint in sorted(audit):
        group_events = [event for event in events if event["mode"] == mode and event["endpoint"] == endpoint]
        returns = [event["net_return"] for event in group_events]
        group_audit = dict(audit[(mode, endpoint)])
        last_exit = max((event["exit_date"] for event in group_events), default=end)
        portfolio_calendar = [run_date for run_date in calendar if start <= run_date <= last_exit]
        groups.append({
            "mode": mode,
            "endpoint": endpoint,
            **group_audit,
            "fill_rate_of_liquid_pct": (
                group_audit.get("filled", 0) / group_audit.get("liquid", 1) * 100
                if group_audit.get("liquid", 0) else None
            ),
            "mean_trade_pct": mean(returns) * 100 if returns else None,
            "median_trade_pct": median(returns) * 100 if returns else None,
            "win_rate_pct": sum(value > 0 for value in returns) / len(returns) * 100 if returns else None,
            "average_limit_holds": mean(event["limit_holds"] for event in group_events) if group_events else None,
            "portfolio": _portfolio(
                group_events, portfolio_calendar, daily, max_positions, buy_cost, sell_cost,
            ),
        })
    return {
        "parameters": {
            "start": start,
            "end": end,
            "rank_max": rank_max,
            "max_positions": max_positions,
            "min_adv20": min_adv20,
            "buy_cost": buy_cost,
            "sell_cost": sell_cost,
        },
        "data": {
            "signals": len(signals),
            "symbols": len(symbols),
            "minute_stock_days": len(minute),
            "price_limit_stock_days": len(limits),
        },
        "groups": groups,
    }
