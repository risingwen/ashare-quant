"""
Check 002123 in raw parquet data
"""
import duckdb

con = duckdb.connect()

# Check 002123 in raw data
query = """
SELECT MIN(date) as first_date, MAX(date) as last_date, COUNT(*) as total_days 
FROM read_parquet('data/parquet/ashare_daily/**/*.parquet') 
WHERE code='002123'
"""

result = con.execute(query).fetchone()

print("=== 002123 in raw parquet data ===")
print(f"最早日期: {result[0]}")
print(f"最晚日期: {result[1]}")
print(f"总交易日数: {result[2]}")

# Check 2024 data
query_2024 = """
SELECT COUNT(*) as count_2024
FROM read_parquet('data/parquet/ashare_daily/**/*.parquet') 
WHERE code='002123' AND date >= '2024-01-01' AND date < '2025-01-01'
"""
count_2024 = con.execute(query_2024).fetchone()[0]
print(f"\n2024年的交易日数: {count_2024}")

# Check early 2025 data
query_early_2025 = """
SELECT date, close, volume, amount
FROM read_parquet('data/parquet/ashare_daily/**/*.parquet') 
WHERE code='002123' AND date >= '2025-01-01' AND date <= '2025-02-15'
ORDER BY date
"""
df = con.execute(query_early_2025).df()
print(f"\n2025年初数据 (前15天):")
print(df.to_string(index=False))
