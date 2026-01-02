#!/usr/bin/env python3
"""
Test script to verify AkShare and data pipeline

This script tests:
1. AkShare connection and API
2. Data fetching for a single stock
3. Data validation
4. Parquet writing
5. DuckDB reading
"""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

import akshare as ak
import pandas as pd
import duckdb
from datetime import datetime, timedelta


def test_akshare_connection():
    """Test AkShare API connection"""
    print("Testing AkShare connection...")
    try:
        # Try to get stock list
        df = ak.stock_zh_a_spot_em()
        print(f"✓ Successfully retrieved {len(df)} stocks")
        return True
    except Exception as e:
        print(f"✗ Failed to connect to AkShare: {e}")
        return False


def test_single_stock_fetch():
    """Test fetching data for a single stock"""
    print("\nTesting single stock data fetch...")
    try:
        # Fetch Ping An Bank (000001) data for last 30 days
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)
        
        df = ak.stock_zh_a_hist(
            symbol="000001",
            period="daily",
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
            adjust="qfq"
        )
        
        if df is not None and not df.empty:
            print(f"✓ Fetched {len(df)} rows for stock 000001")
            print(f"  Columns: {list(df.columns)}")
            print(f"  Date range: {df['日期'].min()} to {df['日期'].max()}")
            return True, df
        else:
            print("✗ No data returned")
            return False, None
    except Exception as e:
        print(f"✗ Failed to fetch stock data: {e}")
        return False, None


def test_parquet_write_read(df):
    """Test writing and reading Parquet file"""
    print("\nTesting Parquet write/read...")
    try:
        # Create test directory
        test_dir = Path("data/test")
        test_dir.mkdir(parents=True, exist_ok=True)
        
        # Standardize columns
        df_clean = df.rename(columns={
            "日期": "date",
            "股票代码": "code",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount"
        })
        
        # Write to Parquet
        test_file = test_dir / "test_000001.parquet"
        df_clean.to_parquet(test_file, engine="pyarrow", compression="snappy", index=False)
        print(f"✓ Written to {test_file}")
        
        # Read back
        df_read = pd.read_parquet(test_file)
        print(f"✓ Read {len(df_read)} rows from Parquet")
        
        # Verify
        if len(df_read) == len(df_clean):
            print("✓ Data integrity verified")
            return True
        else:
            print("✗ Data mismatch after read")
            return False
    except Exception as e:
        print(f"✗ Failed Parquet operations: {e}")
        return False


def test_duckdb_query():
    """Test DuckDB query on Parquet file"""
    print("\nTesting DuckDB query...")
    try:
        con = duckdb.connect()
        
        # Query test Parquet file
        query = """
        SELECT 
            date,
            code,
            close,
            volume
        FROM read_parquet('data/test/test_000001.parquet')
        ORDER BY date DESC
        LIMIT 5
        """
        
        result = con.execute(query).df()
        print(f"✓ DuckDB query executed successfully")
        print(f"  Retrieved {len(result)} rows")
        print("\nSample data:")
        print(result.to_string(index=False))
        
        return True
    except Exception as e:
        print(f"✗ Failed DuckDB query: {e}")
        return False


def main():
    print("="*60)
    print("AShare Quant - System Test")
    print("="*60)
    
    results = {}
    
    # Test 1: AkShare connection
    results["akshare"] = test_akshare_connection()
    
    # Test 2: Single stock fetch
    success, df = test_single_stock_fetch()
    results["fetch"] = success
    
    if success and df is not None:
        # Test 3: Parquet operations
        results["parquet"] = test_parquet_write_read(df)
        
        # Test 4: DuckDB query
        results["duckdb"] = test_duckdb_query()
    else:
        results["parquet"] = False
        results["duckdb"] = False
    
    # Summary
    print("\n" + "="*60)
    print("Test Summary")
    print("="*60)
    for test_name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{test_name.ljust(15)}: {status}")
    
    all_pass = all(results.values())
    print("="*60)
    if all_pass:
        print("All tests passed! System is ready.")
        return 0
    else:
        print("Some tests failed. Please check the errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
