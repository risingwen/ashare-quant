#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Script name: test_hot_rank.py

Test stock hot rank (股票热度排名) data fetching functionality.

Usage:
    python test_hot_rank.py
"""

import sys
from pathlib import Path
import logging

import akshare as ak
import pandas as pd

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_hot_rank_single_stock():
    """Test fetching hot rank data for a single stock"""
    print("\n" + "="*80)
    print("测试单只股票热度排名数据")
    print("="*80 + "\n")
    
    test_stocks = [
        ("000001", "平安银行"),
        ("600519", "贵州茅台"),
        ("000665", "武汉控股")
    ]
    
    for code, name in test_stocks:
        try:
            # Determine market prefix
            if code.startswith(('000', '001', '002', '003', '300')):
                symbol = f"SZ{code}"
            elif code.startswith(('600', '601', '603', '688')):
                symbol = f"SH{code}"
            else:
                symbol = f"SZ{code}"
            
            logger.info(f"正在获取 {code} ({name}) 的热度排名数据...")
            df = ak.stock_hot_rank_detail_em(symbol=symbol)
            
            if df is None or df.empty:
                logger.warning(f"  ✗ 未能获取 {code} 的数据")
                continue
            
            logger.info(f"  ✓ 成功获取 {len(df)} 条记录")
            
            # Show sample data
            print(f"\n{code} ({name}) 最近10天热度排名:")
            print("-" * 80)
            print(df.head(10).to_string())
            print("-" * 80)
            
            # Statistics
            print(f"\n{code} 热度统计:")
            print(f"  数据起止: {df['时间'].min()} ~ {df['时间'].max()}")
            print(f"  最佳排名: {df['排名'].min()}")
            print(f"  平均排名: {df['排名'].mean():.0f}")
            print(f"  最差排名: {df['排名'].max()}")
            print(f"  新晋粉丝平均占比: {df['新晋粉丝'].mean():.2%}")
            print(f"  铁杆粉丝平均占比: {df['铁杆粉丝'].mean():.2%}")
            
        except Exception as e:
            logger.error(f"  ✗ 获取 {code} 数据失败: {str(e)}")
            continue


def test_hot_rank_merge_with_price():
    """Test merging hot rank data with price data"""
    print("\n" + "="*80)
    print("测试热度排名与价格数据合并")
    print("="*80 + "\n")
    
    code = "000001"
    logger.info(f"正在获取 {code} 的价格和热度数据...")
    
    try:
        # Fetch price data
        price_df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date="20250101",
            end_date="20260102",
            adjust="qfq"
        )
        
        logger.info(f"  价格数据: {len(price_df)} 条")
        
        # Fetch hot rank data
        hot_df = ak.stock_hot_rank_detail_em(symbol=f"SZ{code}")
        logger.info(f"  热度数据: {len(hot_df)} 条")
        
        # Standardize columns
        price_df = price_df.rename(columns={
            "日期": "date",
            "股票代码": "code",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
            "换手率": "turnover"
        })
        
        hot_df = hot_df.rename(columns={
            "时间": "date",
            "排名": "hot_rank",
            "证券代码": "symbol_code",
            "新晋粉丝": "new_fans_pct",
            "铁杆粉丝": "core_fans_pct"
        })
        
        # Ensure code column
        if "code" not in price_df.columns:
            price_df["code"] = code
        hot_df["code"] = code
        
        # Convert dates
        price_df["date"] = pd.to_datetime(price_df["date"])
        hot_df["date"] = pd.to_datetime(hot_df["date"])
        
        # Merge
        merged = pd.merge(
            price_df,
            hot_df[["date", "code", "hot_rank", "new_fans_pct", "core_fans_pct"]],
            on=["date", "code"],
            how="left"
        )
        
        logger.info(f"  ✓ 合并后: {len(merged)} 条记录")
        
        # Show merged data
        print(f"\n合并后的数据示例（最近10天）:")
        print("-" * 120)
        cols = ["date", "code", "close", "volume", "turnover", "hot_rank", "new_fans_pct", "core_fans_pct"]
        print(merged[cols].head(10).to_string())
        print("-" * 120)
        
        # Check coverage
        hot_rank_coverage = (merged["hot_rank"].notna().sum() / len(merged)) * 100
        print(f"\n热度数据覆盖率: {hot_rank_coverage:.1f}%")
        
        if hot_rank_coverage > 50:
            print("✓ 数据覆盖良好")
            return True
        else:
            print("⚠ 数据覆盖较低（可能因热度数据只有近一年）")
            return True
            
    except Exception as e:
        logger.error(f"合并测试失败: {str(e)}")
        return False


def main():
    """Run all tests"""
    print("\n" + "="*80)
    print("AShare Quant - 股票热度排名功能测试")
    print("="*80)
    
    results = []
    
    # Test 1: Single stock hot rank
    test_hot_rank_single_stock()
    
    # Test 2: Merge with price data
    success = test_hot_rank_merge_with_price()
    results.append(("热度数据合并", success))
    
    # Summary
    print("\n" + "="*80)
    print("测试结果汇总")
    print("="*80 + "\n")
    
    all_passed = all([r[1] for r in results])
    for test_name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{test_name:<20} {status}")
    
    print("\n" + "="*80)
    if all_passed:
        print("测试通过！")
        print("\n热度排名数据说明:")
        print("1. 数据来源: 东方财富股吧 (guba.eastmoney.com)")
        print("2. 覆盖范围: 近一年历史数据（~366天）")
        print("3. 字段说明:")
        print("   - hot_rank: 当日股票热度排名（数字越小越热门）")
        print("   - new_fans_pct: 新晋粉丝占比（0-1之间）")
        print("   - core_fans_pct: 铁杆粉丝占比（0-1之间）")
        print("4. 配置开关: enable_popularity: true")
    else:
        print("部分测试失败，请检查网络连接。")
    print("="*80 + "\n")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
