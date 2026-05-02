#!/usr/bin/env python3
"""
Test script to download one month of data for validation

This script downloads recent 1 month data for a few stocks to verify:
1. Data fields are correct
2. Download pipeline works
3. Data quality is good
"""
import subprocess
import sys
from datetime import datetime, timedelta


def main():
    # Calculate last month
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")
    
    print("="*60)
    print("Test Download - One Month Data")
    print("="*60)
    print(f"Date range: {start_str} to {end_str}")
    print("This will download about 30 days of data for all A-share stocks")
    print("Estimated time: 5-10 minutes")
    print("="*60)
    
    # Run download script
    cmd = [
        sys.executable,
        "scripts/download_ashare_3y_to_parquet.py",
        "--start-date", start_str,
        "--end-date", end_str,
        "--config", "config.yaml",
        "--workers", "3"  # Use fewer workers for test
    ]
    
    print(f"\nCommand: {' '.join(cmd)}\n")
    print("Starting download...\n")
    
    result = subprocess.run(cmd)
    
    if result.returncode == 0:
        print("\n" + "="*60)
        print("Download completed successfully!")
        print("="*60)
        print("\nYou can now:")
        print("1. Check the data: python -c \"import pandas as pd; df = pd.read_parquet('data/parquet/ashare_daily/**/*.parquet'); print(df.head())\"")
        print("2. View with DuckDB: python view_data.py")
        print("3. Check logs: logs/ashare_quant_*.log")
    else:
        print("\n" + "="*60)
        print("Download failed. Check logs for details.")
        print("="*60)
    
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
