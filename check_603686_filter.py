import pandas as pd

df = pd.read_parquet('data/processed/features/daily_features_v1.parquet')
df['date'] = pd.to_datetime(df['date'])

code = '603686'
dates = ['2025-09-22', '2025-09-23', '2025-09-24', '2025-09-25']

print('=== 603686 连续4日数据 ===\n')
for date_str in dates:
    date = pd.Timestamp(date_str)
    data = df[(df['code'] == code) & (df['date'] == date)]
    if not data.empty:
        row = data.iloc[0]
        print(f"{date_str}:")
        print(f"  hot_rank: {row['hot_rank']}")
        print(f"  intraday_drop: {row['intraday_drop']:.2f}%")
        print(f"  max_drop_5d: {row['max_drop_5d']:.2f}%")
        if date_str == '2025-09-23':
            print(f"  --> 9/24买入时检查9/23数据:")
            pass_max = row['max_drop_5d'] > -7
            pass_intra = row['intraday_drop'] > -7
            should_pass = pass_max and pass_intra
            print(f"      max_drop_5d={row['max_drop_5d']:.2f} > -7: {pass_max}")
            print(f"      intraday_drop={row['intraday_drop']:.2f} > -7: {pass_intra}")
            print(f"      过滤结果: {should_pass}")
        print()
