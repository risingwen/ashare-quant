#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Script name: manual_download.py

手动下载A股数据的便捷脚本

功能：
1. 自动计算下载日期范围（默认最近一年）
2. 使用配置文件中的设置
3. 简化命令行参数

Usage:
    python manual_download.py                    # 下载最近一年数据
    python manual_download.py --months 6         # 下载最近6个月数据
    python manual_download.py --days 30          # 下载最近30天数据
    python manual_download.py --start 2024-01-01 --end 2025-12-31  # 指定日期范围
"""

import sys
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "scripts"))

from download_ashare_3y_to_parquet import AShareDownloader


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="手动下载A股历史数据到Parquet",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s                          # 下载最近一年数据
  %(prog)s --months 6               # 下载最近6个月数据
  %(prog)s --days 30                # 下载最近30天数据
  %(prog)s --start 2024-01-01 --end 2025-12-31  # 指定日期范围
  %(prog)s --no-popularity          # 不下载热度排名数据
        """
    )
    
    # Date range options (mutually exclusive)
    date_group = parser.add_mutually_exclusive_group()
    date_group.add_argument(
        "--months",
        type=int,
        help="下载最近N个月的数据"
    )
    date_group.add_argument(
        "--days",
        type=int,
        help="下载最近N天的数据"
    )
    date_group.add_argument(
        "--start",
        help="开始日期 (YYYY-MM-DD)，需配合 --end 使用"
    )
    
    parser.add_argument(
        "--end",
        help="结束日期 (YYYY-MM-DD)，默认为今天"
    )
    
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="配置文件路径 (默认: config.yaml)"
    )
    
    parser.add_argument(
        "--no-popularity",
        action="store_true",
        help="不下载热度排名数据（加快下载速度）"
    )
    
    parser.add_argument(
        "--workers",
        type=int,
        help="并发下载数量（覆盖配置文件设置）"
    )
    
    return parser.parse_args()


def calculate_date_range(args):
    """Calculate start and end dates based on arguments"""
    today = datetime.now()
    
    # If explicit dates provided
    if args.start:
        if not args.end:
            end_date = today
        else:
            end_date = datetime.strptime(args.end, "%Y-%m-%d")
        start_date = datetime.strptime(args.start, "%Y-%m-%d")
    
    # If months specified
    elif args.months:
        end_date = today
        start_date = today - timedelta(days=args.months * 30)
    
    # If days specified
    elif args.days:
        end_date = today
        start_date = today - timedelta(days=args.days)
    
    # Default: 1 year
    else:
        end_date = today
        start_date = today - timedelta(days=365)  # ~1 year
    
    return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")


def main():
    """Main entry point"""
    args = parse_args()
    
    # Calculate date range
    start_date, end_date = calculate_date_range(args)
    
    print("="*80)
    print("AShare Quant - 手动数据下载")
    print("="*80)
    print(f"\n配置文件: {args.config}")
    print(f"日期范围: {start_date} 至 {end_date}")
    print(f"热度排名: {'禁用' if args.no_popularity else '启用（如配置文件设置）'}")
    if args.workers:
        print(f"并发数: {args.workers}")
    print("\n" + "="*80 + "\n")
    
    # Confirm
    response = input("确认开始下载？(y/N): ")
    if response.lower() not in ['y', 'yes', '是']:
        print("已取消下载。")
        return 0
    
    print("\n开始下载...\n")
    
    # Create downloader
    try:
        downloader = AShareDownloader(
            config_path=args.config,
            workers=args.workers,
            enable_popularity=not args.no_popularity
        )
        
        # Run download
        downloader.run(start_date, end_date)
        
        print("\n" + "="*80)
        print("下载完成！")
        print("="*80)
        print(f"\n数据保存位置: {downloader.base_dir}")
        print(f"进度文件: {downloader.manifest.manifest_path}")
        print("\n可使用以下命令查看数据:")
        print("  python view_data.py")
        print("  python view_parquet_simple.py")
        print("\n或使用 VS Code Data Wrangler 扩展查看")
        print("="*80 + "\n")
        
        return 0
        
    except Exception as e:
        print(f"\n❌ 下载失败: {str(e)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
