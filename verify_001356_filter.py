import duckdb
import glob
import os

# 找到最新的交易文件
trades_files = glob.glob(r'data\backtest\trades\*_trades.parquet')
latest_file = max(trades_files, key=os.path.getmtime)
print(f"检查文件: {latest_file}\n")

conn = duckdb.connect()

# 查询 001356
query = f"""
SELECT *
FROM read_parquet('{latest_file}')
WHERE code = '001356';
"""

df = conn.execute(query).df()

if len(df) == 0:
    print("✅ 001356 已被正确过滤（新股上市10天内不交易）")
else:
    print(f"❌ 001356 仍有 {len(df)} 条交易记录")
    print(df.to_string(index=False))

# 查看 001356 的特征数据
features_path = r'C:\Users\14737\OneDrive\06AKshare\ashare-quant\data\processed\features\daily_features_v1.parquet'

query2 = """
SELECT 
    date,
    code,
    name,
    days_since_listing,
    amplitude_prev,
    pct_change_prev,
    hot_rank
FROM read_parquet(?)
WHERE code = '001356'
  AND date >= '2025-01-23'
  AND date <= '2025-01-24'
ORDER BY date;
"""

df2 = conn.execute(query2, [features_path]).df()
print("\n001356 特征数据:")
print(df2.to_string(index=False))
