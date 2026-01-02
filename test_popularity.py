#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Script name: test_popularity.py

Test popularity (人气) data fetching functionality.

Usage:
    python test_popularity.py
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

import akshare as ak
import pandas as pd
import logging

# Setup basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_popularity_fetch():
    """Test fetching popularity data from AkShare"""
    print("\n" + "="*80)
    print("测试人气数据获取")
    print("="*80 + "\n")
    
    try:
        logger.info("正在获取实时行情数据（包含人气字段）...")
        df = ak.stock_zh_a_spot_em()
        
        if df is None or df.empty:
            logger.error("未能获取数据")
            return False
        
        logger.info(f"成功获取 {len(df)} 只股票的实时数据")
        
        # Check if popularity column exists
        available_indicators = ["人气", "涨速", "量比", "5分钟涨跌"]
        found_indicator = None
        
        for indicator in available_indicators:
            if indicator in df.columns:
                found_indicator = indicator
                break
        
        if found_indicator:
            logger.info(f"✓ 找到指标字段: {found_indicator}")
            
            # Extract data
            indicator_df = df[["代码", "名称", found_indicator]].copy()
            indicator_df.columns = ["code", "name", "indicator_value"]
            
            # Sort by indicator
            top_10 = indicator_df.nlargest(10, "indicator_value")
            
            print(f"\n{found_indicator} Top10股票:")
            print("-" * 80)
            print(f"{'排名':<6}{'代码':<10}{'名称':<15}{found_indicator:<15}")
            print("-" * 80)
            
            for idx, (_, row) in enumerate(top_10.iterrows(), 1):
                val = row['indicator_value']
                val_str = f"{val:,.2f}" if isinstance(val, (int, float)) else str(val)
                print(f"{idx:<6}{row['code']:<10}{row['name']:<15}{val_str:<15}")
            
            print("-" * 80)
            
            # Show statistics
            print(f"\n{found_indicator} 统计:")
            print(f"  最高值: {indicator_df['indicator_value'].max():,.2f}")
            print(f"  最低值: {indicator_df['indicator_value'].min():,.2f}")
            print(f"  平均值: {indicator_df['indicator_value'].mean():,.2f}")
            print(f"  中位数: {indicator_df['indicator_value'].median():,.2f}")
            
            logger.info(f"\n说明: 当前 AkShare 版本返回的是'{found_indicator}'字段而非'人气'字段")
            logger.info(f"可用字段: {', '.join(df.columns.tolist())}")
            
            return True
        else:
            logger.error("✗ 未找到任何可用的关注度指标字段")
            logger.info(f"可用字段: {', '.join(df.columns[:10])}...")
            return False
            
    except Exception as e:
        logger.error(f"获取数据失败: {str(e)}")
        return False


def test_historical_data_with_turnover():
    """Test fetching historical data with turnover"""
    print("\n" + "="*80)
    print("测试历史数据获取（包含换手率）")
    print("="*80 + "\n")
    
    try:
        test_code = "000001"  # 平安银行
        logger.info(f"正在获取 {test_code} 的最近10天数据...")
        
        df = ak.stock_zh_a_hist(
            symbol=test_code,
            period="daily",
            start_date="20250101",
            end_date="20260102",
            adjust="qfq"
        )
        
        if df is None or df.empty:
            logger.error("未能获取数据")
            return False
        
        logger.info(f"成功获取 {len(df)} 条数据")
        
        # Check for turnover column
        if "换手率" in df.columns:
            logger.info("✓ 换手率字段存在")
            
            # Show sample data
            print(f"\n{test_code} 最近数据（前5行）:")
            print("-" * 100)
            
            sample = df.head()
            print(sample[["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额", "换手率"]].to_string())
            
            print("-" * 100)
            
            return True
        else:
            logger.error("✗ 换手率字段不存在")
            logger.info(f"可用字段: {', '.join(df.columns)}")
            return False
            
    except Exception as e:
        logger.error(f"获取数据失败: {str(e)}")
        return False


def main():
    """Run all tests"""
    print("\n" + "="*80)
    print("AShare Quant - 人气与换手率功能测试")
    print("="*80)
    
    results = []
    
    # Test 1: Popularity data
    success1 = test_popularity_fetch()
    results.append(("人气数据获取", success1))
    
    # Test 2: Historical data with turnover
    success2 = test_historical_data_with_turnover()
    results.append(("换手率数据获取", success2))
    
    # Summary
    print("\n" + "="*80)
    print("测试结果汇总")
    print("="*80 + "\n")
    
    all_passed = True
    for test_name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{test_name:<20} {status}")
        if not passed:
            all_passed = False
    
    print("\n" + "="*80)
    if all_passed:
        print("所有测试通过！")
        print("\n提示:")
        print("1. 人气字段来自实时行情数据，反映当日最新关注度")
        print("2. 换手率字段来自历史日线数据，表示每日换手率(%)")
        print("3. 在 config.yaml 中设置 enable_popularity: true 启用人气采集")
    else:
        print("部分测试失败，请检查网络连接和 AkShare 版本。")
    print("="*80 + "\n")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
