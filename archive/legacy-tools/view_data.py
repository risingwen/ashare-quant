#!/usr/bin/env python3
"""
View downloaded data with DuckDB

This script provides a convenient way to explore the downloaded data.
"""
import sys
from pathlib import Path
import duckdb


def main():
    # Check if data exists
    data_path = Path("data/parquet/ashare_daily")
    if not data_path.exists() or not list(data_path.glob("**/*.parquet")):
        print("No data found. Please run the download script first.")
        print("Quick test: python test_one_month.py")
        return 1
    
    # Connect to DuckDB
    con = duckdb.connect()
    
    print("="*70)
    print("AShare Data Viewer")
    print("="*70)
    
    # Query 1: Show data structure
    print("\n1. Data Structure (Sample 5 rows):")
    print("-"*70)
    query1 = """
    SELECT * 
    FROM read_parquet('data/parquet/ashare_daily/**/*.parquet')
    LIMIT 5
    """
    df1 = con.execute(query1).df()
    print(df1.to_string(index=False))
    
    # Query 2: Show columns and types
    print("\n\n2. Column Information:")
    print("-"*70)
    query2 = """
    DESCRIBE 
    SELECT * FROM read_parquet('data/parquet/ashare_daily/**/*.parquet')
    """
    df2 = con.execute(query2).df()
    print(df2.to_string(index=False))
    
    # Query 3: Data statistics
    print("\n\n3. Data Statistics:")
    print("-"*70)
    query3 = """
    SELECT 
        COUNT(*) as total_rows,
        COUNT(DISTINCT code) as stock_count,
        MIN(date) as earliest_date,
        MAX(date) as latest_date,
        COUNT(DISTINCT date) as trading_days
    FROM read_parquet('data/parquet/ashare_daily/**/*.parquet')
    """
    df3 = con.execute(query3).df()
    print(df3.to_string(index=False))
    
    # Query 4: Sample stock data
    print("\n\n4. Sample: Stock 000001 (Recent 10 days):")
    print("-"*70)
    query4 = """
    SELECT 
        date,
        code,
        open,
        high,
        low,
        close,
        volume,
        amount
    FROM read_parquet('data/parquet/ashare_daily/**/*.parquet')
    WHERE code = '000001'
    ORDER BY date DESC
    LIMIT 10
    """
    df4 = con.execute(query4).df()
    if not df4.empty:
        print(df4.to_string(index=False))
    else:
        print("No data for stock 000001")
    
    # Query 5: Top 10 stocks by volume (latest date)
    print("\n\n5. Top 10 Stocks by Volume (Latest Trading Day):")
    print("-"*70)
    query5 = """
    WITH latest_date AS (
        SELECT MAX(date) as max_date
        FROM read_parquet('data/parquet/ashare_daily/**/*.parquet')
    )
    SELECT 
        code,
        date,
        close,
        volume,
        amount
    FROM read_parquet('data/parquet/ashare_daily/**/*.parquet')
    WHERE date = (SELECT max_date FROM latest_date)
    ORDER BY volume DESC
    LIMIT 10
    """
    df5 = con.execute(query5).df()
    if not df5.empty:
        print(df5.to_string(index=False))
    
    print("\n" + "="*70)
    print("Data exploration completed!")
    print("="*70)
    print("\nCustom Query:")
    print("You can run custom queries using DuckDB:")
    print("  con = duckdb.connect()")
    print("  df = con.execute(\"SELECT * FROM read_parquet('data/parquet/ashare_daily/**/*.parquet') WHERE code = 'YOUR_CODE'\").df()")
    print()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
