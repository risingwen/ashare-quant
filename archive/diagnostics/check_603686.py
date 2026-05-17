import pandas as pd

# 读取特征数据
df = pd.read_parquet('data/processed/features/daily_features_v1.parquet')
df['date'] = pd.to_datetime(df['date'])

# 查看603686在9/23-9/26的数据
code = '603686'
start = pd.Timestamp('2025-09-23')
end = pd.Timestamp('2025-09-26')

stock_data = df[(df['code'] == code) & (df['date'] >= start) & (df['date'] <= end)].copy()
stock_data = stock_data.sort_values('date')

# 显示关键字段
cols = ['date', 'code', 'name', 'open', 'high', 'low', 'close', 
        'hot_rank', 'amount', 'max_drop_5d', 'is_new_ipo']

print('=== 603686 福龙马 9/23-9/26 详细数据 ===\n')
pd.set_option('display.max_columns', None)
pd.set_option('display.width', 300)
print(stock_data[cols].to_string(index=False))

# 计算每日跌幅
print('\n=== 日内跌幅分析 ===')
prev_close = None
for idx, row in stock_data.iterrows():
    if prev_close is not None:
        drop_from_prev = (row['low'] - prev_close) / prev_close * 100
        close_chg = (row['close'] - prev_close) / prev_close * 100
        print(f"{row['date'].date()}: 前收{prev_close:.2f} → 最低{row['low']:.2f}({drop_from_prev:.2f}%), 收盘{row['close']:.2f}({close_chg:.2f}%), max_drop_5d={row['max_drop_5d']:.2%}")
    else:
        print(f"{row['date'].date()}: 收盘{row['close']:.2f}, max_drop_5d={row['max_drop_5d']:.2%}")
    prev_close = row['close']

# 查看更早的数据（前5个交易日）
print('\n=== 前5个交易日数据 ===')
early_start = pd.Timestamp('2025-09-16')
early_data = df[(df['code'] == code) & (df['date'] >= early_start) & (df['date'] < start)].copy()
early_data = early_data.sort_values('date')
print(early_data[['date', 'close', 'low', 'high']].to_string(index=False))
