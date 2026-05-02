import pandas as pd

df = pd.read_parquet('data/processed/features/daily_features_v1.parquet')
df['date'] = pd.to_datetime(df['date'])

# 查看11/5-11/7数据
code = '603686'
start = pd.Timestamp('2025-11-04')
end = pd.Timestamp('2025-11-07')

stock_data = df[(df['code'] == code) & (df['date'] >= start) & (df['date'] <= end)].copy()
stock_data = stock_data.sort_values('date')

print('=== 603686 福龙马 11/4-11/7 详细数据 ===\n')
print(stock_data[['date', 'close', 'low', 'hot_rank']].to_string(index=False))

print('\n=== 买入触发分析（11/6）===')
if len(stock_data) >= 2:
    row_11_5 = stock_data[stock_data['date'] == pd.Timestamp('2025-11-05')].iloc[0]
    row_11_6 = stock_data[stock_data['date'] == pd.Timestamp('2025-11-06')].iloc[0]
    
    prev_close = row_11_5['close']
    today_low = row_11_6['low']
    drop_pct = (today_low - prev_close) / prev_close * 100
    
    print(f'11/5收盘: {prev_close:.2f}')
    print(f'11/6最低: {today_low:.2f}')
    print(f'跌幅: {drop_pct:.2f}%')
    print(f'触发条件: 跌幅在[-10%, -7%]区间')
    print(f'  跌幅 <= -7%: {drop_pct <= -7}')
    print(f'  跌幅 >= -10%: {drop_pct >= -10}')
    print(f'结论: {"✓ 满足买入条件" if (drop_pct <= -7 and drop_pct >= -10) else "✗ 不满足买入条件"}')
