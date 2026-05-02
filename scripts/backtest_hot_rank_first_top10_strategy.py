#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
首次进入人气前10策略回测引擎。

策略逻辑：
1) 个股首次进入人气前10（T日产生信号）。
2) T+1 买入条件满足其一：
   - 低开（open < T日close），按开盘价买入。
   - 盘中触及 T日close * (1 + 2%)，按触发价买入。
3) 持仓期间只要人气跌出前50（hot_rank > 50），当日收盘卖出。

使用示例：
python scripts/backtest_hot_rank_first_top10_strategy.py \
  --config config/strategies/hot_rank_first_top10_rise2_or_gapdown.yaml
"""

import argparse
import hashlib
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def deep_merge(base: dict, override: dict) -> dict:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_strategy_config(config_path: str) -> dict:
    config_path = Path(config_path)
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if "extends" in config:
        base_path = config_path.parent / config["extends"]
        with open(base_path, "r", encoding="utf-8") as f:
            base_config = yaml.safe_load(f)
        config = deep_merge(base_config, config)
        del config["extends"]

    return config


class Trade:
    def __init__(self, code: str, name: str, signal_date: pd.Timestamp, entry_date: pd.Timestamp):
        self.code = code
        self.name = name
        self.signal_date = signal_date
        self.entry_date = entry_date

        self.signal_rank = None
        self.signal_close = None
        self.entry_condition = None

        self.buy_price = None
        self.buy_exec = None
        self.buy_shares = 0
        self.buy_cost = 0

        self.exit_date = None
        self.exit_rank = None
        self.exit_reason = None
        self.sell_price = None
        self.sell_exec = None
        self.sell_proceed = 0

        self.hold_days = 0
        self.net_pnl = 0
        self.net_pnl_pct = 0

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "signal_date": self.signal_date,
            "entry_date": self.entry_date,
            "signal_rank": self.signal_rank,
            "signal_close": self.signal_close,
            "entry_condition": self.entry_condition,
            "buy_price": self.buy_price,
            "buy_exec": self.buy_exec,
            "buy_shares": self.buy_shares,
            "buy_cost": self.buy_cost,
            "exit_date": self.exit_date,
            "exit_rank": self.exit_rank,
            "exit_reason": self.exit_reason,
            "sell_price": self.sell_price,
            "sell_exec": self.sell_exec,
            "sell_proceed": self.sell_proceed,
            "hold_days": self.hold_days,
            "net_pnl": self.net_pnl,
            "net_pnl_pct": self.net_pnl_pct,
        }


class Position:
    def __init__(self, trade: Trade):
        self.trade = trade
        self.code = trade.code
        self.shares = trade.buy_shares
        self.days_held = 0


class BacktestEngine:
    def __init__(self, config: dict):
        self.config = config
        self.strategy = config["strategy"]
        self.params = config["params"]
        self.backtest_config = config["backtest"]

        self.hot_top_n = int(self.params.get("hot_top_n", 10))
        self.rise_trigger = float(self.params.get("rise_trigger", 0.02))
        self.buy_on_gap_down = bool(self.params.get("buy_on_gap_down", True))
        self.exit_rank_threshold = int(self.params.get("exit_rank_threshold", 50))
        self.cash_splits = int(self.params.get("cash_splits", 3))
        self.per_trade_cash_frac = float(self.params.get("per_trade_cash_frac", 1.0 / self.cash_splits))
        self.max_positions = int(self.params.get("max_positions", self.cash_splits))

        self.init_cash = float(self.backtest_config["init_cash"])
        self.fee_buy = float(self.backtest_config["fee_buy"])
        self.fee_sell = float(self.backtest_config["fee_sell"])
        self.stamp_tax = float(self.backtest_config["stamp_tax_sell"])
        self.slippage_bps = float(self.backtest_config["slippage_bps"])
        self.min_commission = float(self.backtest_config["min_commission"])
        self.min_lot_size = int(self.backtest_config["min_lot_size"])

        self.cash = self.init_cash
        self.positions: Dict[str, Position] = {}
        self.pending_signals: Dict[str, pd.Series] = {}
        self.trades: List[Trade] = []
        self.daily_portfolio = []
        self.stats = defaultdict(int)

        logger.info(
            "初始化: %s | init_cash=%.0f cash_splits=%d hot_top_n=%d rise_trigger=%.2f exit_rank=%d",
            self.strategy["name"],
            self.init_cash,
            self.cash_splits,
            self.hot_top_n,
            self.rise_trigger,
            self.exit_rank_threshold,
        )

    def load_features(self, features_path: str) -> pd.DataFrame:
        df = pd.read_parquet(features_path)
        df["date"] = pd.to_datetime(df["date"])
        return df

    def is_first_entry_top_n(self, row_today: pd.Series, row_prev: Optional[pd.Series]) -> bool:
        if pd.isna(row_today.get("hot_rank")):
            return False
        if int(row_today["hot_rank"]) > self.hot_top_n:
            return False
        if row_prev is None or pd.isna(row_prev.get("hot_rank")):
            return True
        return int(row_prev["hot_rank"]) > self.hot_top_n

    def check_buy_condition(self, row_t1: pd.Series, signal_close: float) -> Optional[tuple]:
        if self.buy_on_gap_down and row_t1["open"] < signal_close:
            return ("gap_down_open", float(row_t1["open"]))

        trigger_price = signal_close * (1.0 + self.rise_trigger)
        if row_t1["high"] >= trigger_price and row_t1["low"] <= trigger_price:
            return ("rise2_trigger", float(trigger_price))

        return None

    def execute_buy(self, signal_row: pd.Series, row_t1: pd.Series, condition: str, buy_price: float) -> Optional[Position]:
        nominal_cash = self.init_cash * self.per_trade_cash_frac
        buy_exec = buy_price * (1 + self.slippage_bps / 10000)
        shares = int(nominal_cash / buy_exec / self.min_lot_size) * self.min_lot_size
        if shares <= 0:
            self.stats["skip_lot_size"] += 1
            return None

        commission = max(shares * buy_exec * self.fee_buy, self.min_commission)
        total_cost = shares * buy_exec + commission
        if total_cost > self.cash:
            self.stats["skip_cash"] += 1
            return None

        self.cash -= total_cost
        trade = Trade(
            code=row_t1["code"],
            name=row_t1.get("name", ""),
            signal_date=signal_row["date"],
            entry_date=row_t1["date"],
        )
        trade.signal_rank = signal_row.get("hot_rank")
        trade.signal_close = signal_row.get("close")
        trade.entry_condition = condition
        trade.buy_price = buy_price
        trade.buy_exec = buy_exec
        trade.buy_shares = shares
        trade.buy_cost = total_cost

        if condition == "gap_down_open":
            self.stats["gap_down_buy_count"] += 1
        elif condition == "rise2_trigger":
            self.stats["rise2_trigger_count"] += 1

        self.stats["buy_success"] += 1
        return Position(trade)

    def execute_sell(self, row_today: pd.Series):
        code = row_today["code"]
        position = self.positions[code]
        trade = position.trade

        sell_price = float(row_today["close"])
        sell_exec = sell_price * (1 - self.slippage_bps / 10000)
        commission = max(position.shares * sell_exec * self.fee_sell, self.min_commission)
        stamp = position.shares * sell_exec * self.stamp_tax
        sell_proceed = position.shares * sell_exec - commission - stamp

        self.cash += sell_proceed

        trade.exit_date = row_today["date"]
        trade.exit_rank = row_today.get("hot_rank")
        trade.exit_reason = "rank_drop_below_50"
        trade.sell_price = sell_price
        trade.sell_exec = sell_exec
        trade.sell_proceed = sell_proceed
        trade.hold_days = position.days_held + 1
        trade.net_pnl = sell_proceed - trade.buy_cost
        trade.net_pnl_pct = trade.net_pnl / trade.buy_cost if trade.buy_cost else 0

        self.trades.append(trade)
        del self.positions[code]
        self.stats["sell_success"] += 1

    def run(self, features_df: pd.DataFrame, start_date: Optional[str] = None, end_date: Optional[str] = None):
        dates = sorted(features_df["date"].unique())
        if start_date:
            start_ts = pd.Timestamp(start_date)
            dates = [d for d in dates if d >= start_ts]
        if end_date:
            end_ts = pd.Timestamp(end_date)
            dates = [d for d in dates if d <= end_ts]
        if len(dates) < 2:
            raise ValueError("交易日数量不足，无法回测")

        for i, date in enumerate(dates):
            df_today = features_df[features_df["date"] == date]
            df_prev = features_df[features_df["date"] == dates[i - 1]] if i > 0 else pd.DataFrame()

            # 1) 卖出：持仓跌出前50
            to_sell: List[str] = []
            for code, pos in self.positions.items():
                row = df_today[df_today["code"] == code]
                if row.empty:
                    pos.days_held += 1
                    continue
                row = row.iloc[0]
                rank = row.get("hot_rank")
                if pd.notna(rank) and int(rank) > self.exit_rank_threshold:
                    to_sell.append(code)
                pos.days_held += 1

            for code in to_sell:
                row = df_today[df_today["code"] == code].iloc[0]
                self.execute_sell(row)

            # 2) 执行前一日 pending 信号买入
            pending_codes = list(self.pending_signals.keys())
            for code in pending_codes:
                if len(self.positions) >= self.max_positions:
                    break
                if code in self.positions:
                    del self.pending_signals[code]
                    continue

                signal_row = self.pending_signals[code]
                row_today = df_today[df_today["code"] == code]
                if row_today.empty:
                    del self.pending_signals[code]
                    continue
                row_today = row_today.iloc[0]

                if not bool(row_today.get("is_tradable", True)):
                    del self.pending_signals[code]
                    continue

                condition = self.check_buy_condition(row_today, float(signal_row["close"]))
                if condition is not None:
                    cond_name, buy_price = condition
                    pos = self.execute_buy(signal_row, row_today, cond_name, buy_price)
                    if pos is not None:
                        self.positions[code] = pos
                del self.pending_signals[code]

            # 3) 生成当日首次入榜前10信号（用于次日执行）
            if i > 0:
                for _, row in df_today.iterrows():
                    code = row["code"]

                    if code in self.positions or code in self.pending_signals:
                        continue

                    if not bool(row.get("is_tradable", True)):
                        continue
                    if bool(row.get("is_st", False)):
                        continue

                    prev_row_df = df_prev[df_prev["code"] == code]
                    prev_row = prev_row_df.iloc[0] if not prev_row_df.empty else None

                    if self.is_first_entry_top_n(row, prev_row):
                        self.pending_signals[code] = row.copy()
                        self.stats["first_entry_count"] += 1

            # 4) 每日净值
            pos_value = 0.0
            for code, pos in self.positions.items():
                row = df_today[df_today["code"] == code]
                if not row.empty:
                    pos_value += float(row.iloc[0]["close"]) * pos.shares

            nav = self.cash + pos_value
            self.daily_portfolio.append(
                {
                    "date": date,
                    "cash": self.cash,
                    "position_value": pos_value,
                    "nav": nav,
                    "n_positions": len(self.positions),
                }
            )

        logger.info(
            "回测结束: first_entry=%d buy=%d sell=%d gap_down_buy=%d rise2_buy=%d",
            self.stats["first_entry_count"],
            self.stats["buy_success"],
            self.stats["sell_success"],
            self.stats["gap_down_buy_count"],
            self.stats["rise2_trigger_count"],
        )

    def save_results(self, output_dir: str):
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        cfg_hash = hashlib.md5(json.dumps(self.params, sort_keys=True).encode()).hexdigest()[:8]
        prefix = f"{self.strategy['name']}_v{self.strategy['version']}_{cfg_hash}_{timestamp}"

        if self.trades:
            trades_df = pd.DataFrame([t.to_dict() for t in self.trades])
            trades_df = trades_df.sort_values("entry_date", ascending=False)

            trades_dir = out / "trades"
            trades_dir.mkdir(exist_ok=True)
            trades_df.to_parquet(trades_dir / f"{prefix}_trades.parquet", index=False)
            trades_df.to_csv(trades_dir / f"{prefix}_trades.csv", index=False, encoding="utf-8-sig")

        if self.daily_portfolio:
            portfolio_df = pd.DataFrame(self.daily_portfolio)
            portfolio_dir = out / "portfolio"
            portfolio_dir.mkdir(exist_ok=True)
            portfolio_df.to_parquet(portfolio_dir / f"{prefix}_portfolio.parquet", index=False)


def main():
    parser = argparse.ArgumentParser(description="首次进入人气前10策略回测引擎")
    parser.add_argument(
        "--config",
        default="config/strategies/hot_rank_first_top10_rise2_or_gapdown.yaml",
        help="策略配置文件路径",
    )
    parser.add_argument(
        "--features",
        default="data/processed/features/daily_features_v1.parquet",
        help="特征数据路径",
    )
    parser.add_argument("--start-date", default=None, help="回测开始日期，如 2025-01-15")
    parser.add_argument("--end-date", default=None, help="回测结束日期，如 2026-01-31")
    parser.add_argument("--output", default="data/backtest", help="输出目录")
    args = parser.parse_args()

    config = load_strategy_config(args.config)
    engine = BacktestEngine(config)
    features_df = engine.load_features(args.features)
    engine.run(features_df, start_date=args.start_date, end_date=args.end_date)
    engine.save_results(args.output)


if __name__ == "__main__":
    main()
