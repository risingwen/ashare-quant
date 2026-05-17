#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Simple Parquet Viewer - 无需 Jupyter 的轻量级数据查看工具

Usage:
    python view_parquet_simple.py data/test/test_000001.parquet
    python view_parquet_simple.py data/parquet/ashare_daily/year=2024/month=01
"""

import argparse
import sys
from pathlib import Path
import pandas as pd


def view_parquet_file(file_path: Path):
    """查看单个 Parquet 文件"""
    print(f"\n{'='*80}")
    print(f"文件: {file_path}")
    print(f"{'='*80}\n")
    
    df = pd.read_parquet(file_path)
    
    print(f"📊 数据概览")
    print(f"-" * 80)
    print(f"总行数: {len(df):,}")
    print(f"总列数: {len(df.columns)}")
    print(f"字段: {', '.join(df.columns)}")
    print(f"日期范围: {df['date'].min()} ~ {df['date'].max()}")
    if 'code' in df.columns:
        print(f"股票代码: {df['code'].unique()[:10].tolist()}")  # 显示前10个
    print()
    
    print(f"📈 前5行数据")
    print(f"-" * 80)
    print(df.head().to_string())
    print()
    
    print(f"📊 统计信息")
    print(f"-" * 80)
    print(df.describe().to_string())
    print()
    
    # 如果有成交量，显示最大成交量的5只股票
    if 'volume' in df.columns and 'code' in df.columns:
        print(f"🔥 成交量Top5")
        print(f"-" * 80)
        top5 = df.nlargest(5, 'volume')[['date', 'code', 'close', 'volume', 'amount']]
        print(top5.to_string())
        print()


def view_directory(dir_path: Path):
    """查看目录下所有 Parquet 文件"""
    parquet_files = list(dir_path.glob("**/*.parquet"))
    
    if not parquet_files:
        print(f"❌ 目录下没有找到 .parquet 文件: {dir_path}")
        return
    
    print(f"\n找到 {len(parquet_files)} 个 Parquet 文件:")
    for i, f in enumerate(parquet_files[:10], 1):  # 最多显示10个
        print(f"  {i}. {f.relative_to(dir_path)}")
    if len(parquet_files) > 10:
        print(f"  ... 还有 {len(parquet_files) - 10} 个文件")
    
    # 合并所有文件查看
    print(f"\n正在加载所有文件...")
    df_all = pd.concat([pd.read_parquet(f) for f in parquet_files], ignore_index=True)
    
    print(f"\n{'='*80}")
    print(f"目录: {dir_path}")
    print(f"{'='*80}\n")
    
    print(f"📊 数据概览")
    print(f"-" * 80)
    print(f"总行数: {len(df_all):,}")
    print(f"总列数: {len(df_all.columns)}")
    print(f"字段: {', '.join(df_all.columns)}")
    print(f"日期范围: {df_all['date'].min()} ~ {df_all['date'].max()}")
    if 'code' in df_all.columns:
        print(f"股票数量: {df_all['code'].nunique()}")
        print(f"股票代码示例: {df_all['code'].unique()[:10].tolist()}")
    print()
    
    print(f"📈 样例数据（前10行）")
    print(f"-" * 80)
    print(df_all.head(10).to_string())
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Simple Parquet Viewer - 轻量级 Parquet 文件查看工具"
    )
    parser.add_argument(
        "path",
        help="Parquet 文件路径或包含 Parquet 文件的目录"
    )
    
    args = parser.parse_args()
    path = Path(args.path)
    
    if not path.exists():
        print(f"❌ 路径不存在: {path}")
        sys.exit(1)
    
    if path.is_file():
        if path.suffix == '.parquet':
            view_parquet_file(path)
        else:
            print(f"❌ 不是 .parquet 文件: {path}")
            sys.exit(1)
    elif path.is_dir():
        view_directory(path)
    else:
        print(f"❌ 无效路径: {path}")
        sys.exit(1)


if __name__ == "__main__":
    main()
