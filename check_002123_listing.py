"""
Check 002123 listing information
"""
import pandas as pd

df = pd.read_parquet('data/processed/features/daily_features_v1.parquet')

# Get 002123 data
df_002123 = df[df['code'] == '002123'].sort_values('date')

print("=== 002123 上市信息 ===")
print(f"股票名称: {df_002123.iloc[0]['name']}")
print(f"\n数据中出现的日期范围:")
print(f"  最早: {df_002123['date'].min()}")
print(f"  最晚: {df_002123['date'].max()}")
print(f"  总交易日数: {len(df_002123)}")

print(f"\ndays_since_listing变化:")
print(df_002123[['date', 'days_since_listing']].head(20).to_string(index=False))

print(f"\n2月初的days_since_listing:")
feb_data = df_002123[(df_002123['date'] >= '2025-02-01') & (df_002123['date'] <= '2025-02-15')]
print(feb_data[['date', 'days_since_listing']].to_string(index=False))

# Check if days_since_listing resets
min_days = df_002123['days_since_listing'].min()
max_days = df_002123['days_since_listing'].max()
print(f"\ndays_since_listing统计:")
print(f"  最小值: {min_days}")
print(f"  最大值: {max_days}")

# Check for anomalies
if min_days < 100:
    print(f"\n⚠️ 警告: days_since_listing最小值仅{min_days}天，但数据最早出现在{df_002123['date'].min()}")
    print("这表明days_since_listing可能存在计算错误或数据重置问题")
