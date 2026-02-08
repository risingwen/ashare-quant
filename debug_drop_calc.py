import pandas as pd

df = pd.read_parquet('data/processed/features/daily_features_v1.parquet')
df['date'] = pd.to_datetime(df['date'])

code = '603686'
start = pd.Timestamp('2025-09-20')
end = pd.Timestamp('2025-09-26')

stock = df[(df['code'] == code) & (df['date'] >= start) & (df['date'] <= end)].copy()
stock = stock.sort_values('date')

print('=== 详细计算过程 ===\n')
for idx, row in stock.iterrows():
    print(f"日期: {row['date'].date()}")
    print(f"  收盘价: {row['close']:.2f}")
    print(f"  最低价: {row['low']:.2f}")
    print(f"  close_prev: {row['close_prev']}")
    print(f"  intraday_drop: (low - close_prev) / close_prev * 100")
    if pd.notna(row['close_prev']):
        calc_drop = (row['low'] - row['close_prev']) / row['close_prev'] * 100
        print(f"            = ({row['low']:.2f} - {row['close_prev']:.2f}) / {row['close_prev']:.2f} * 100")
        print(f"            = {calc_drop:.2f}%")
    print(f"  max_drop_5d: {row['max_drop_5d']:.4f}")
    print()
