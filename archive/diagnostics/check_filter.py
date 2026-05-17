import pandas as pd

# 查看9/25买入时603686的过滤数据
df = pd.read_parquet('data/processed/features/daily_features_v1.parquet')
df['date'] = pd.to_datetime(df['date'])

code = '603686'
# T日 = 9/25, T-1日 = 9/24
t_minus_1 = pd.Timestamp('2025-09-24')
t_day = pd.Timestamp('2025-09-25')

print('=== T-1日（9/24）数据 - 买入决策时用这天的数据过滤 ===')
data_t1 = df[(df['code'] == code) & (df['date'] == t_minus_1)]
if not data_t1.empty:
    row = data_t1.iloc[0]
    print(f"hot_rank: {row['hot_rank']}")
    print(f"intraday_drop: {row['intraday_drop']:.2f}% (从T-2收盘到T-1最低)")
    print(f"max_drop_5d: {row['max_drop_5d']:.2f}% (T-2至T-6的最大跌幅)")
    print(f"过滤条件:")
    print(f"  - max_drop_5d > -7: {row['max_drop_5d']:.2f} > -7 = {row['max_drop_5d'] > -7}")
    print(f"  - intraday_drop > -7: {row['intraday_drop']:.2f} > -7 = {row['intraday_drop'] > -7}")
    should_pass = (row['max_drop_5d'] > -7) and (row['intraday_drop'] > -7)
    print(f"  - 是否通过过滤: {should_pass}")

print('\n=== T日（9/25）数据 ===')
data_t = df[(df['code'] == code) & (df['date'] == t_day)]
if not data_t.empty:
    row = data_t.iloc[0]
    print(f"intraday_drop: {row['intraday_drop']:.2f}% (从T-1收盘到T最低)")
    print(f"max_drop_5d: {row['max_drop_5d']:.2f}% (T-1至T-5的最大跌幅)")
