#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
人气榜策略回测引擎

策略逻辑：
1. 前一交易日人气榜前N名
2. 次日跌破-X%触发买入
3. 智能卖出：跌停卖出 > 涨停持有 > 正常收盘卖

使用示例：
    # 使用配置文件
    python scripts/backtest_hot_rank_strategy.py \\
        --config config/strategies/hot_rank_drop7.yaml
    
    # CLI覆盖参数
    python scripts/backtest_hot_rank_strategy.py \\
        --config config/strategies/hot_rank_drop7.yaml \\
        --param.hot_top_n=50 \\
        --param.drop_trigger=0.06
"""

import argparse
import hashlib
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import yaml

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def deep_merge(base: dict, override: dict) -> dict:
    """深度合并字典"""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_strategy_config(config_path: str) -> dict:
    """
    加载策略配置（支持继承）
    
    Args:
        config_path: 策略配置文件路径
        
    Returns:
        合并后的配置字典
    """
    config_path = Path(config_path)
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    # 处理继承
    if 'extends' in config:
        base_path = config_path.parent / config['extends']
        with open(base_path, 'r', encoding='utf-8') as f:
            base_config = yaml.safe_load(f)
        config = deep_merge(base_config, config)
        del config['extends']
    
    return config


def apply_cli_overrides(config: dict, overrides: dict) -> dict:
    """
    应用CLI参数覆盖
    
    Args:
        config: 原配置
        overrides: CLI覆盖参数（如 {'param.hot_top_n': 50}）
        
    Returns:
        覆盖后的配置
    """
    for key, value in overrides.items():
        if key.startswith('param.'):
            param_name = key[6:]  # 去掉 'param.' 前缀
            if 'params' not in config:
                config['params'] = {}
            config['params'][param_name] = value
            logger.info(f"CLI override: {param_name} = {value}")
    return config


class Trade:
    """交易记录"""
    
    def __init__(self, code: str, entry_date: str):
        self.code = code
        self.entry_date = entry_date
        self.rank_t1 = None
        self.amount_t1 = None
        self.prev_close = None
        self.trigger_low = None
        
        self.buy_price = None
        self.buy_exec = None
        self.buy_shares = 0
        self.buy_cost = 0
        self.cash_after_buy = 0
        
        self.exit_date = None
        self.exit_reason = None
        self.hold_days = 0
        
        self.sell_price = None
        self.sell_exec = None
        self.sell_proceed = 0
        self.cash_after_sell = 0
        
        self.gross_pnl = 0
        self.net_pnl = 0
        self.net_pnl_pct = 0
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'code': self.code,
            'entry_date': self.entry_date,
            'rank_t1': self.rank_t1,
            'amount_t1': self.amount_t1,
            'prev_close': self.prev_close,
            'trigger_low': self.trigger_low,
            'buy_price': self.buy_price,
            'buy_exec': self.buy_exec,
            'buy_shares': self.buy_shares,
            'buy_cost': self.buy_cost,
            'cash_after_buy': self.cash_after_buy,
            'exit_date': self.exit_date,
            'exit_reason': self.exit_reason,
            'hold_days': self.hold_days,
            'sell_price': self.sell_price,
            'sell_exec': self.sell_exec,
            'sell_proceed': self.sell_proceed,
            'cash_after_sell': self.cash_after_sell,
            'gross_pnl': self.gross_pnl,
            'net_pnl': self.net_pnl,
            'net_pnl_pct': self.net_pnl_pct
        }


class Position:
    """持仓"""
    
    def __init__(self, trade: Trade):
        self.trade = trade
        self.entry_date = trade.entry_date
        self.code = trade.code
        self.shares = trade.buy_shares
        self.cost_basis = trade.buy_exec
        self.days_held = 0


class BacktestEngine:
    """回测引擎"""
    
    def __init__(self, config: dict):
        """初始化回测引擎"""
        self.config = config
        self.strategy = config['strategy']
        self.params = config['params']
        self.backtest_config = config['backtest']
        
        # 策略参数
        self.hot_top_n = self.params['hot_top_n']
        self.prev_amount_min = self.params['prev_amount_min']
        self.drop_trigger = self.params['drop_trigger']
        self.per_trade_cash_frac = self.params['per_trade_cash_frac']
        self.hold_on_limit_up = self.params['hold_on_limit_up']
        self.exit_on_limit_down = self.params['exit_on_limit_down']
        self.limit_down_trigger = self.params['limit_down_trigger']
        self.max_hold_days = self.params['max_hold_days']
        
        # 回测参数
        self.init_cash = self.backtest_config['init_cash']
        self.fee_buy = self.backtest_config['fee_buy']
        self.fee_sell = self.backtest_config['fee_sell']
        self.stamp_tax = self.backtest_config['stamp_tax_sell']
        self.slippage_bps = self.backtest_config['slippage_bps']
        self.min_commission = self.backtest_config['min_commission']
        self.min_lot_size = self.backtest_config['min_lot_size']
        
        # 状态
        self.cash = self.init_cash
        self.positions: Dict[str, Position] = {}
        self.trades: List[Trade] = []
        self.daily_portfolio = []
        
        # 统计
        self.stats = defaultdict(int)
        
        # 配置日志
        self._setup_logging()
        
        logger.info(f"策略初始化: {self.strategy['name']} v{self.strategy['version']}")
        logger.info(f"参数: hot_top_n={self.hot_top_n}, drop_trigger={self.drop_trigger}, "
                   f"limit_down_trigger={self.limit_down_trigger}")
        logger.info(f"初始资金: {self.init_cash:,.0f}")
    
    def _setup_logging(self):
        """设置日志"""
        # 创建日志目录
        log_dir = PROJECT_ROOT / 'data' / 'backtest' / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        
        # JSON日志文件
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_file = log_dir / f"trades_{self.strategy['name']}_{timestamp}.log"
        
        # 添加文件处理器
        self.json_logger = logging.getLogger('trades')
        self.json_logger.setLevel(logging.INFO)
        fh = logging.FileHandler(log_file, encoding='utf-8')
        fh.setFormatter(logging.Formatter('%(message)s'))
        self.json_logger.addHandler(fh)
        
        logger.info(f"交易日志: {log_file}")
    
    def log_trade_event(self, event: str, **kwargs):
        """记录交易事件（JSON格式）"""
        # 转换Timestamp到字符串
        for key, value in kwargs.items():
            if hasattr(value, 'isoformat'):
                kwargs[key] = value.isoformat()
        
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'event': event,
            **kwargs
        }
        self.json_logger.info(json.dumps(log_entry, ensure_ascii=False))
    
    def load_features(self, features_path: str) -> pd.DataFrame:
        """加载特征数据"""
        logger.info(f"加载特征数据: {features_path}")
        df = pd.read_parquet(features_path)
        df['date'] = pd.to_datetime(df['date'])
        logger.info(f"加载完成: {len(df):,}行, {df['code'].nunique()}只股票")
        return df
    
    def filter_universe(self, df_today: pd.DataFrame, df_prev: pd.DataFrame) -> pd.DataFrame:
        """
        过滤选股池（使用T-1信息）
        
        Args:
            df_today: 今日数据
            df_prev: 昨日数据（T-1）
            
        Returns:
            过滤后的股票池
        """
        # 1. 人气榜前N名（使用昨日T-1的hot_rank）
        df_prev_hot = df_prev[df_prev['hot_rank'].notna()].copy()
        df_prev_hot = df_prev_hot[df_prev_hot['hot_rank'] <= self.hot_top_n]
        self.stats['signal_hot_rank'] += len(df_prev_hot)
        
        # 2. 过滤成交额（使用昨日T-1的amount，注意单位是亿元）
        amount_min_billion = self.prev_amount_min / 1e9  # 转换为亿元
        df_prev_hot = df_prev_hot[df_prev_hot['amount'] >= amount_min_billion]
        self.stats['filter_amount'] += (len(df_prev_hot))
        
        # 3. 过滤ST股票（使用昨日判断）
        if self.backtest_config.get('filter_st', True):
            before = len(df_prev_hot)
            df_prev_hot = df_prev_hot[~df_prev_hot['is_st']]
            self.stats['filter_st'] += (before - len(df_prev_hot))
        
        # 4. 今日必须有行情且可交易
        df_today_tradable = df_today[df_today['is_tradable']].copy()
        codes_tradable = set(df_today_tradable['code'])
        df_prev_hot = df_prev_hot[df_prev_hot['code'].isin(codes_tradable)]
        
        # 5. 按昨日hot_rank排序（越小越优先）
        df_prev_hot = df_prev_hot.sort_values('hot_rank')
        
        return df_prev_hot
    
    def check_entry_signal(self, row_today: pd.Series, row_prev: pd.Series) -> bool:
        """
        检查买入信号（今日low触及昨日收盘价 * (1-drop_trigger)）
        
        Args:
            row_today: 今日行情
            row_prev: 昨日行情（T-1）
            
        Returns:
            是否触发买入
        """
        trigger_price = row_prev['close'] * (1 - self.drop_trigger)
        return row_today['low'] <= trigger_price
    
    def execute_buy(self, date: str, row_today: pd.Series, row_prev: pd.Series) -> Optional[Trade]:
        """
        执行买入
        
        Args:
            date: 交易日期
            row_today: 今日行情
            row_prev: 昨日行情（T-1）
            
        Returns:
            交易记录或None
        """
        code = row_today['code']
        
        # 计算买入价格（基于昨日收盘价）
        buy_price = row_prev['close'] * (1 - self.drop_trigger)
        buy_exec = buy_price * (1 + self.slippage_bps / 10000)
        
        # 计算名义资金
        nominal_cash = self.init_cash * self.per_trade_cash_frac
        
        # 计算股数（向下取整到100股）
        shares = int(nominal_cash / buy_exec / self.min_lot_size) * self.min_lot_size
        
        if shares == 0:
            self.stats['skip_lot_size'] += 1
            self.log_trade_event('SKIP_BUY', date=date, code=code, 
                               reason='lot_size_insufficient', nominal_cash=nominal_cash)
            return None
        
        # 计算费用
        commission = max(shares * buy_exec * self.fee_buy, self.min_commission)
        total_cost = shares * buy_exec + commission
        
        # 检查现金
        if total_cost > self.cash:
            self.stats['skip_cash'] += 1
            self.log_trade_event('SKIP_BUY', date=date, code=code,
                               reason='insufficient_cash', required=total_cost, available=self.cash)
            return None
        
        # 扣除现金
        self.cash -= total_cost
        
        # 创建交易记录
        trade = Trade(code, date)
        trade.rank_t1 = row_prev['hot_rank']  # 使用昨日的hot_rank
        trade.amount_t1 = row_prev['amount']
        trade.prev_close = row_prev['close']
        trade.trigger_low = row_today['low']
        trade.buy_price = buy_price
        trade.buy_exec = buy_exec
        trade.buy_shares = shares
        trade.buy_cost = total_cost
        trade.cash_after_buy = self.cash
        
        # 添加持仓
        self.positions[code] = Position(trade)
        
        # 记录日志
        self.log_trade_event('BUY', date=date, code=code,
                           rank_t1=trade.rank_t1,
                           buy_price=buy_price,
                           buy_exec=buy_exec,
                           shares=shares,
                           commission=commission,
                           total_cost=total_cost,
                           cash_after=self.cash,
                           reason='trigger_drop')
        
        self.stats['buy_success'] += 1
        logger.info(f"买入: {date} {code} @{buy_exec:.2f} x{shares}股 成本{total_cost:.2f} 余额{self.cash:.2f}")
        
        return trade
    
    def check_exit_signal(self, position: Position, row_today: pd.Series) -> Tuple[bool, str]:
        """
        检查卖出信号
        
        优先级：
        1. 跌停卖出
        2. 最大持仓天数
        3. 涨停持有
        4. 正常收盘卖出
        
        Args:
            position: 持仓
            row_today: 今日行情
            
        Returns:
            (是否卖出, 卖出原因)
        """
        # 1. 跌停卖出（优先级最高）- 使用今日跌停价
        if self.exit_on_limit_down and row_today['is_limit_down']:
            return True, 'sell_limitdown'
        
        # 2. 最大持仓天数
        if position.days_held >= self.max_hold_days:
            return True, 'sell_max_hold_days'
        
        # 3. 涨停持有
        if self.hold_on_limit_up and row_today['is_limit_up']:
            return False, 'hold_limitup'
        
        # 4. 正常收盘卖出
        if position.days_held >= 1:  # T+1
            return True, 'sell_t1_close'
        
        return False, 'hold'
    
    def execute_sell(self, date: str, position: Position, row_today: pd.Series, reason: str):
        """
        执行卖出
        
        Args:
            date: 交易日期
            position: 持仓
            row_today: 今日行情
            reason: 卖出原因
        """
        code = position.code
        trade = position.trade
        
        # 计算卖出价格
        if reason == 'sell_limitdown':
            # 跌停卖出，使用跌停价
            sell_price = row_today['limit_down_price']
        else:
            # 其他情况使用收盘价
            sell_price = row_today['close']
        
        sell_exec = sell_price * (1 - self.slippage_bps / 10000)
        
        # 计算费用
        commission = max(position.shares * sell_exec * self.fee_sell, self.min_commission)
        stamp = position.shares * sell_exec * self.stamp_tax
        total_fee = commission + stamp
        
        # 计算收益
        sell_proceed = position.shares * sell_exec - total_fee
        self.cash += sell_proceed
        
        trade.exit_date = date
        trade.exit_reason = reason
        trade.hold_days = position.days_held + 1
        trade.sell_price = sell_price
        trade.sell_exec = sell_exec
        trade.sell_proceed = sell_proceed
        trade.cash_after_sell = self.cash
        trade.gross_pnl = sell_proceed - trade.buy_cost
        trade.net_pnl = trade.gross_pnl
        trade.net_pnl_pct = trade.net_pnl / trade.buy_cost
        
        # 记录日志
        self.log_trade_event('SELL', date=date, code=code,
                           exit_reason=reason,
                           sell_price=sell_price,
                           sell_exec=sell_exec,
                           shares=position.shares,
                           commission=commission,
                           stamp_tax=stamp,
                           sell_proceed=sell_proceed,
                           pnl=trade.net_pnl,
                           pnl_pct=trade.net_pnl_pct,
                           hold_days=trade.hold_days,
                           cash_after=self.cash)
        
        self.stats['sell_success'] += 1
        logger.info(f"卖出: {date} {code} @{sell_exec:.2f} x{position.shares}股 "
                   f"收益{trade.net_pnl:.2f}({trade.net_pnl_pct:.2%}) {reason}")
        
        # 移除持仓
        del self.positions[code]
        
        # 添加到已完成交易
        self.trades.append(trade)
    
    def run(self, features_df: pd.DataFrame):
        """
        运行回测
        
        Args:
            features_df: 特征数据
        """
        logger.info("="*80)
        logger.info("开始回测")
        logger.info("="*80)
        
        # 按日期分组
        dates = sorted(features_df['date'].unique())
        logger.info(f"回测期间: {dates[0]} 至 {dates[-1]}, 共{len(dates)}个交易日")
        
        for i, date in enumerate(dates):
            if i == 0:
                continue  # 第一天没有T-1数据
            
            prev_date = dates[i-1]
            df_today = features_df[features_df['date'] == date]
            df_prev = features_df[features_df['date'] == prev_date]
            
            logger.info(f"\n--- {date} ---")
            
            # 1. 检查卖出信号（先卖后买）
            positions_to_sell = []
            for code, position in list(self.positions.items()):
                row_today = df_today[df_today['code'] == code]
                if row_today.empty or not row_today.iloc[0]['is_tradable']:
                    # 停牌，继续持有
                    self.log_trade_event('HOLD', date=date, code=code, reason='suspended')
                    position.days_held += 1
                    continue
                
                row_today = row_today.iloc[0]
                should_sell, reason = self.check_exit_signal(position, row_today)
                
                if should_sell:
                    positions_to_sell.append((position, row_today, reason))
                elif reason == 'hold_limitup':
                    self.log_trade_event('HOLD', date=date, code=code, reason='limitup',
                                       close=row_today['close'], limit_up=row_today['limit_up_price'])
                position.days_held += 1
            
            # 执行卖出
            for position, row_today, reason in positions_to_sell:
                self.execute_sell(date, position, row_today, reason)
            
            # 2. 检查买入信号
            universe = self.filter_universe(df_today, df_prev)
            logger.info(f"选股池: {len(universe)}只")
            
            for _, row_prev in universe.iterrows():
                code = row_prev['code']
                
                # 检查是否已持仓
                if code in self.positions:
                    continue
                
                # 获取今日行情
                row_today = df_today[df_today['code'] == code]
                if row_today.empty:
                    continue
                row_today = row_today.iloc[0]
                
                # 检查买入信号
                if self.check_entry_signal(row_today, row_prev):
                    trade = self.execute_buy(date, row_today, row_prev)
                    if trade is None:
                        break  # 资金不足，跳过后续信号
            
            # 3. 记录每日组合状态
            position_value = sum(
                df_today[df_today['code'] == code].iloc[0]['close'] * pos.shares
                if not df_today[df_today['code'] == code].empty else 0
                for code, pos in self.positions.items()
            )
            nav = self.cash + position_value
            
            self.daily_portfolio.append({
                'date': date,
                'cash': self.cash,
                'position_value': position_value,
                'nav': nav,
                'n_positions': len(self.positions)
            })
            
            logger.info(f"持仓: {len(self.positions)}只, 现金: {self.cash:.2f}, "
                       f"市值: {position_value:.2f}, 净值: {nav:.2f}")
        
        logger.info("="*80)
        logger.info("回测完成")
        logger.info("="*80)
        self.print_stats()
    
    def print_stats(self):
        """打印统计信息"""
        logger.info(f"\n统计信息:")
        logger.info(f"  信号数: {self.stats['signal_hot_rank']}")
        logger.info(f"  成交买入: {self.stats['buy_success']}")
        logger.info(f"  成交卖出: {self.stats['sell_success']}")
        logger.info(f"  跳过-资金不足: {self.stats['skip_cash']}")
        logger.info(f"  跳过-不足一手: {self.stats['skip_lot_size']}")
        logger.info(f"  最终现金: {self.cash:.2f}")
        logger.info(f"  最终持仓: {len(self.positions)}只")
    
    def save_results(self, output_dir: str):
        """保存回测结果"""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        config_hash = hashlib.md5(json.dumps(self.params, sort_keys=True).encode()).hexdigest()[:8]
        prefix = f"{self.strategy['name']}_v{self.strategy['version']}_{config_hash}_{timestamp}"
        
        # 保存交易明细
        if self.trades:
            trades_df = pd.DataFrame([t.to_dict() for t in self.trades])
            trades_file = output_dir / 'trades' / f"{prefix}_trades.parquet"
            trades_file.parent.mkdir(exist_ok=True)
            trades_df.to_parquet(trades_file, index=False)
            logger.info(f"交易明细已保存: {trades_file}")
        
        # 保存组合净值
        if self.daily_portfolio:
            portfolio_df = pd.DataFrame(self.daily_portfolio)
            portfolio_file = output_dir / 'portfolio' / f"{prefix}_portfolio.parquet"
            portfolio_file.parent.mkdir(exist_ok=True)
            portfolio_df.to_parquet(portfolio_file, index=False)
            logger.info(f"组合净值已保存: {portfolio_file}")


def main():
    parser = argparse.ArgumentParser(
        description='人气榜策略回测引擎',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        '--config',
        required=True,
        help='策略配置文件路径'
    )
    parser.add_argument(
        '--features',
        default='data/processed/features/daily_features_v1.parquet',
        help='特征数据路径'
    )
    parser.add_argument(
        '--output',
        default='data/backtest',
        help='输出目录'
    )
    
    # CLI参数覆盖
    parser.add_argument('--param.hot_top_n', type=int, dest='param_hot_top_n')
    parser.add_argument('--param.drop_trigger', type=float, dest='param_drop_trigger')
    parser.add_argument('--param.limit_down_trigger', type=float, dest='param_limit_down_trigger')
    
    args = parser.parse_args()
    
    # 加载配置
    config = load_strategy_config(args.config)
    
    # 应用CLI覆盖
    cli_overrides = {}
    if args.param_hot_top_n:
        cli_overrides['param.hot_top_n'] = args.param_hot_top_n
    if args.param_drop_trigger:
        cli_overrides['param.drop_trigger'] = args.param_drop_trigger
    if args.param_limit_down_trigger:
        cli_overrides['param.limit_down_trigger'] = args.param_limit_down_trigger
    
    if cli_overrides:
        config = apply_cli_overrides(config, cli_overrides)
    
    # 初始化回测引擎
    engine = BacktestEngine(config)
    
    # 加载特征数据
    features_df = engine.load_features(args.features)
    
    # 运行回测
    engine.run(features_df)
    
    # 保存结果
    engine.save_results(args.output)


if __name__ == '__main__':
    main()
