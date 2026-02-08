#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
特征工程脚本：从原始日线数据生成回测所需特征

功能：
1. 读取原始Parquet数据（data/parquet/ashare_daily）
2. 计算T-1信息（前日收盘价、成交额、人气排名等）
3. 计算涨停价、跌停价（根据股票代码判断板块）
4. 生成标记字段（是否可交易、是否ST等）
5. 输出到 data/processed/features/

使用示例：
    # 全量处理
    python scripts/prepare_features.py --config config/data_config.yaml
    
    # 指定日期范围
    python scripts/prepare_features.py --start-date 2025-01-01 --end-date 2025-12-31
    
    # 增量更新
    python scripts/prepare_features.py --incremental
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import duckdb
import pandas as pd
import yaml

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(PROJECT_ROOT / 'logs' / f'prepare_features_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    ]
)
logger = logging.getLogger(__name__)


class LimitPriceCalculator:
    """涨跌停价格计算器"""
    
    def __init__(self, config: dict):
        """
        初始化涨跌停规则
        
        Args:
            config: 涨跌停规则配置
        """
        self.rules = config.get('limit_up_rules', {})
        self.main_board = self.rules.get('main_board', 0.10)
        self.gem_board = self.rules.get('gem_board', 0.20)
        self.star_board = self.rules.get('star_board', 0.20)
        self.bse_board = self.rules.get('bse_board', 0.30)
        self.st_stock = self.rules.get('st_stock', 0.05)
        self.precision = self.rules.get('price_precision', 0.01)
        
        logger.info(f"Limit price rules loaded: main={self.main_board}, gem={self.gem_board}, "
                   f"star={self.star_board}, bse={self.bse_board}, st={self.st_stock}")
    
    def get_limit_pct(self, code: str, is_st: bool = False) -> float:
        """
        根据股票代码判断涨跌幅限制
        
        Args:
            code: 股票代码（6位字符串）
            is_st: 是否ST股票
            
        Returns:
            涨跌幅限制比例
        """
        if is_st:
            return self.st_stock
        
        # 科创板（688/689开头）
        if code.startswith('688') or code.startswith('689'):
            return self.star_board
        
        # 创业板（300/301开头）
        if code.startswith('300') or code.startswith('301'):
            return self.gem_board
        
        # 北交所（8/4开头）
        if code.startswith('8') or code.startswith('4'):
            return self.bse_board
        
        # 主板/中小板（默认）
        return self.main_board
    
    def calc_limit_up_price(self, prev_close: float, code: str, is_st: bool = False) -> float:
        """计算涨停价"""
        limit_pct = self.get_limit_pct(code, is_st)
        limit_price = prev_close * (1 + limit_pct)
        return round(limit_price / self.precision) * self.precision
    
    def calc_limit_down_price(self, prev_close: float, code: str, is_st: bool = False) -> float:
        """计算跌停价"""
        limit_pct = self.get_limit_pct(code, is_st)
        limit_price = prev_close * (1 - limit_pct)
        return round(limit_price / self.precision) * self.precision


class FeatureEngineer:
    """特征工程处理器"""
    
    def __init__(self, config_path: str):
        """
        初始化特征工程处理器
        
        Args:
            config_path: 配置文件路径
        """
        self.config_path = Path(config_path)
        self.config = self._load_config()
        
        # 路径配置
        self.raw_dir = PROJECT_ROOT / self.config['data']['raw_dir']
        self.features_dir = PROJECT_ROOT / self.config['data']['features_dir']
        self.features_dir.mkdir(parents=True, exist_ok=True)
        
        # DuckDB配置
        self.duckdb_config = self.config.get('duckdb', {})
        self.con = self._init_duckdb()
        
        # 涨跌停计算器
        backtest_config = self._load_backtest_config()
        self.limit_calculator = LimitPriceCalculator(backtest_config)
        
        # Manifest路径
        self.manifest_path = self.features_dir / 'manifest.json'
        self.manifest = self._load_manifest()
        
        logger.info(f"FeatureEngineer initialized. Raw dir: {self.raw_dir}")
        logger.info(f"Features output: {self.features_dir}")
    
    def _load_config(self) -> dict:
        """加载数据配置"""
        with open(self.config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def _load_backtest_config(self) -> dict:
        """加载回测配置（获取涨跌停规则）"""
        backtest_config_path = PROJECT_ROOT / 'config' / 'backtest_base.yaml'
        with open(backtest_config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def _init_duckdb(self) -> duckdb.DuckDBPyConnection:
        """初始化DuckDB连接"""
        con = duckdb.connect()
        
        # 设置内存限制
        memory_limit = self.duckdb_config.get('memory_limit', '4GB')
        con.execute(f"SET memory_limit='{memory_limit}'")
        
        # 设置线程数
        threads = self.duckdb_config.get('threads', 4)
        con.execute(f"SET threads={threads}")
        
        logger.info(f"DuckDB initialized: memory_limit={memory_limit}, threads={threads}")
        return con
    
    def _load_manifest(self) -> dict:
        """加载manifest"""
        if self.manifest_path.exists():
            with open(self.manifest_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {
            'version': '1.0.0',
            'last_update': None,
            'date_range': {'start': None, 'end': None},
            'stats': {}
        }
    
    def _save_manifest(self):
        """保存manifest"""
        self.manifest['last_update'] = datetime.now().isoformat()
        with open(self.manifest_path, 'w', encoding='utf-8') as f:
            json.dump(self.manifest, f, indent=2, ensure_ascii=False)
        logger.info(f"Manifest saved: {self.manifest_path}")
    
    def load_raw_data(self, start_date: Optional[str] = None, 
                     end_date: Optional[str] = None) -> pd.DataFrame:
        """
        从Parquet数据湖加载原始数据
        
        Args:
            start_date: 开始日期（YYYY-MM-DD）
            end_date: 结束日期（YYYY-MM-DD）
            
        Returns:
            原始数据DataFrame
        """
        logger.info("Loading raw data from Parquet...")
        
        # 构建查询SQL
        parquet_path = str(self.raw_dir / '**/*.parquet').replace('\\', '/')
        
        sql = f"""
        SELECT 
            date,
            code,
            name,
            open,
            high,
            low,
            close,
            volume,
            amount,
            turnover,
            hot_rank
        FROM read_parquet('{parquet_path}', hive_partitioning=true)
        """
        
        if start_date or end_date:
            conditions = []
            if start_date:
                conditions.append(f"date >= '{start_date}'")
            if end_date:
                conditions.append(f"date <= '{end_date}'")
            sql += " WHERE " + " AND ".join(conditions)
        
        sql += " ORDER BY code, date"
        
        logger.info(f"Executing DuckDB query...")
        df = self.con.execute(sql).df()
        
        logger.info(f"Loaded {len(df):,} rows, {df['code'].nunique()} unique stocks")
        logger.info(f"Date range: {df['date'].min()} to {df['date'].max()}")
        
        return df
    
    def calculate_prev_values(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        计算T-1（前一交易日）的值
        
        Args:
            df: 原始数据
            
        Returns:
            包含前值的DataFrame
        """
        logger.info("Calculating T-1 values...")
        
        # 按股票代码分组，计算前值
        df = df.sort_values(['code', 'date'])
        
        for col in ['close', 'amount', 'hot_rank', 'turnover']:
            df[f'{col}_prev'] = df.groupby('code')[col].shift(1)
        
        # 统计
        n_with_prev = df['close_prev'].notna().sum()
        logger.info(f"T-1 values calculated: {n_with_prev:,} rows with prev values")
        
        return df
    
    def add_limit_prices(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        添加涨停价、跌停价
        
        Args:
            df: 包含前值的DataFrame
            
        Returns:
            包含涨跌停价的DataFrame
        """
        logger.info("Calculating limit up/down prices...")
        
        # 判断是否ST股票
        df['is_st'] = df['name'].str.contains('ST|退', na=False, regex=True)
        
        # 计算涨停价和跌停价
        df['limit_up_price'] = df.apply(
            lambda row: self.limit_calculator.calc_limit_up_price(
                row['close_prev'], row['code'], row['is_st']
            ) if pd.notna(row['close_prev']) else None,
            axis=1
        )
        
        df['limit_down_price'] = df.apply(
            lambda row: self.limit_calculator.calc_limit_down_price(
                row['close_prev'], row['code'], row['is_st']
            ) if pd.notna(row['close_prev']) else None,
            axis=1
        )
        
        # 判断是否涨停/跌停
        # 涨幅>=9.9%认为涨停，跌幅<=-9.9%认为跌停（简化判断，避免精度问题）
        df['pct_change_from_prev'] = (df['close'] / df['close_prev'] - 1) * 100
        df['is_limit_up'] = (
            (df['pct_change_from_prev'] >= 9.9) & 
            df['close_prev'].notna()
        )
        df['is_limit_down'] = (
            (df['pct_change_from_prev'] <= -9.9) & 
            df['close_prev'].notna()
        )
        
        # 统计
        n_limit_up = df['is_limit_up'].sum()
        n_limit_down = df['is_limit_down'].sum()
        logger.info(f"Limit prices calculated: {n_limit_up:,} limit up, {n_limit_down:,} limit down")
        
        return df
    
    def add_trading_flags(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        添加交易标记
        
        Args:
            df: DataFrame
            
        Returns:
            包含交易标记的DataFrame
        """
        logger.info("Adding trading flags...")
        
        # 是否可交易（成交量>0）
        df['is_tradable'] = df['volume'] > 0
        
        # 是否新股（上市天数）
        df['days_since_listing'] = df.groupby('code').cumcount() + 1
        df['is_new_ipo'] = df['days_since_listing'] <= 60
        
        # 计算T-1日振幅和跌幅（用于过滤极端波动）
        # 重要：必须按股票分组后再shift，否则会拿到其他股票的数据
        df['amplitude_prev'] = df.groupby('code', group_keys=False).apply(
            lambda x: ((x['high'] - x['low']) / x['close_prev'] * 100).shift(1)
        ).values
        df['pct_change_prev'] = df.groupby('code', group_keys=False).apply(
            lambda x: ((x['close'] - x['close_prev']) / x['close_prev'] * 100).shift(1)
        ).values
        
        # 风险过滤特征1：前5个交易日盘中最大跌幅（检测是否有单日大跌超7%）
        # 使用最低价相对于前收盘价的跌幅，而非收盘价跌幅
        # 注意：shift(1)确保T日决策时用的是T-1日及之前的数据，不包含T日当天
        logger.info("Calculating max intraday drop in past 5 days...")
        df['intraday_drop'] = (df['low'] - df['close_prev']) / df['close_prev'] * 100
        df['max_drop_5d'] = df.groupby('code', group_keys=False)['intraday_drop'].apply(
            lambda x: x.shift(1).rolling(window=5, min_periods=1).min()
        ).values
        
        # 风险过滤特征2：连续2日累计涨幅（检测异常暴涨）
        # 使用收盘价计算累计涨幅
        # 注意：计算T-1和T-2两日的累计收益率
        logger.info("Calculating 2-day cumulative return...")
        df['pct_change'] = (df['close'] - df['close_prev']) / df['close_prev'] * 100
        df['cum_return_2d'] = df.groupby('code', group_keys=False)['pct_change'].apply(
            lambda x: x.shift(1).rolling(window=2, min_periods=2).apply(
                lambda y: (1 + y/100).prod() - 1, raw=True
            ) * 100
        ).values
        
        # 风险过滤特征3：前5日一字板天数（开=收=高=低）
        # 注意：shift(1)确保不包含当天
        logger.info("Calculating one-word board days in past 5 days...")
        df['is_one_word_board'] = (
            (df['open'] == df['close']) & 
            (df['close'] == df['high']) & 
            (df['high'] == df['low'])
        )
        df['one_word_board_5d'] = df.groupby('code', group_keys=False)['is_one_word_board'].apply(
            lambda x: x.shift(1).rolling(window=5, min_periods=1).sum()
        ).values
        
        # 注意:max_hot_rank_3d将在回测时动态计算,避免跨越缺失日期
        # 这里不再预先计算,以确保只看实际连续的2天数据
        
        # 统计
        n_tradable = df['is_tradable'].sum()
        n_new_ipo = df['is_new_ipo'].sum()
        n_risk_drop = (df['max_drop_5d'] <= -7).sum()
        n_risk_surge = (df['cum_return_2d'] > 40).sum()
        n_risk_board = (df['one_word_board_5d'] >= 2).sum()
        logger.info(f"Trading flags added: {n_tradable:,} tradable, {n_new_ipo:,} new IPO")
        logger.info(f"Volatility features added: amplitude_prev, pct_change_prev")
        logger.info(f"Risk features: {n_risk_drop:,} with 5d drop<=-7%, {n_risk_surge:,} with 2d surge>40%, {n_risk_board:,} with 2+ one-word boards")
        
        return df
    
    def save_features(self, df: pd.DataFrame, version: str = 'v1'):
        """
        保存特征数据
        
        Args:
            df: 特征DataFrame
            version: 版本号
        """
        output_file = self.features_dir / f'daily_features_{version}.parquet'
        
        logger.info(f"Saving features to {output_file}...")
        
        # 选择最终列
        columns = [
            'date', 'code', 'name',
            'open', 'high', 'low', 'close', 'volume', 'amount', 'turnover',
            'close_prev', 'amount_prev', 'turnover_prev',
            'hot_rank', 'hot_rank_prev',
            'limit_up_price', 'limit_down_price',
            'is_limit_up', 'is_limit_down',
            'is_st', 'is_tradable', 'is_new_ipo',
            'days_since_listing',
            'amplitude_prev', 'pct_change_prev',
            'intraday_drop', 'max_drop_5d', 'cum_return_2d', 'one_word_board_5d'
        ]
        
        df_output = df[columns].copy()
        
        # 保存为Parquet
        df_output.to_parquet(
            output_file,
            engine='pyarrow',
            compression='snappy',
            index=False
        )
        
        # 更新manifest
        self.manifest['date_range'] = {
            'start': str(df['date'].min()),
            'end': str(df['date'].max())
        }
        self.manifest['stats'] = {
            'total_rows': len(df_output),
            'unique_stocks': df_output['code'].nunique(),
            'unique_dates': df_output['date'].nunique(),
            'version': version,
            'output_file': str(output_file.name)
        }
        self._save_manifest()
        
        logger.info(f"Features saved: {len(df_output):,} rows")
        logger.info(f"File size: {output_file.stat().st_size / 1024 / 1024:.2f} MB")
    
    def run(self, start_date: Optional[str] = None, 
            end_date: Optional[str] = None,
            version: str = 'v1'):
        """
        运行完整特征工程流程
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            version: 版本号
        """
        logger.info("="*80)
        logger.info("Starting feature engineering pipeline")
        logger.info("="*80)
        
        try:
            # 1. 加载原始数据
            df = self.load_raw_data(start_date, end_date)
            
            # 2. 计算前值
            df = self.calculate_prev_values(df)
            
            # 3. 添加涨跌停价
            df = self.add_limit_prices(df)
            
            # 4. 添加交易标记
            df = self.add_trading_flags(df)
            
            # 5. 保存特征
            self.save_features(df, version)
            
            logger.info("="*80)
            logger.info("Feature engineering completed successfully!")
            logger.info("="*80)
            
        except Exception as e:
            logger.error(f"Feature engineering failed: {str(e)}", exc_info=True)
            raise


def main():
    parser = argparse.ArgumentParser(
        description='Prepare features for backtesting',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        '--config',
        default='config/data_config.yaml',
        help='Path to data config file (default: config/data_config.yaml)'
    )
    parser.add_argument(
        '--start-date',
        help='Start date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--end-date',
        help='End date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--version',
        default='v1',
        help='Feature version (default: v1)'
    )
    parser.add_argument(
        '--incremental',
        action='store_true',
        help='Incremental update (only process new data)'
    )
    
    args = parser.parse_args()
    
    # 创建日志目录
    (PROJECT_ROOT / 'logs').mkdir(exist_ok=True)
    
    # 运行特征工程
    engineer = FeatureEngineer(args.config)
    
    # 增量更新逻辑
    start_date = args.start_date
    if args.incremental and engineer.manifest['date_range']['end']:
        start_date = engineer.manifest['date_range']['end']
        logger.info(f"Incremental mode: starting from {start_date}")
    
    engineer.run(
        start_date=start_date,
        end_date=args.end_date,
        version=args.version
    )


if __name__ == '__main__':
    main()
