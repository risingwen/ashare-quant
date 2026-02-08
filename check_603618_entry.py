"""
Check 603618 entry signal on 2025-09-24
"""
import pandas as pd

# Load feature data
df = pd.read_parquet('data/processed/features/daily_features_v1.parquet')

# Get 603618 data around entry date
df_603618 = df[(df['code'] == '603618') & (df['date'] >= '2025-09-23') & (df['date'] <= '2025-09-26')].sort_values('date')

print("=== 603618 杭电股份 买入前后数据 ===")
print(df_603618[['date', 'open', 'high', 'low', 'close', 'close_prev', 'hot_rank']].to_string(index=False))

print("\n=== 买入触发条件检查 (2025-09-24) ===")
entry_row = df_603618[df_603618['date'] == '2025-09-24'].iloc[0]
prev_row = df_603618[df_603618['date'] == '2025-09-23'].iloc[0]

trigger_price = prev_row['close'] * 1.02

print(f"T-1 (2025-09-23) 收盘价: {prev_row['close']:.2f}")
print(f"T (2025-09-24) 开盘价: {entry_row['open']:.2f}")
print(f"T (2025-09-24) 最高价: {entry_row['high']:.2f}")
print(f"T (2025-09-24) 最低价: {entry_row['low']:.2f}")
print(f"T (2025-09-24) 收盘价: {entry_row['close']:.2f}")
print(f"\n触发价格 (+2%): {trigger_price:.4f}")
print(f"\n买入条件检查:")
print(f"  条件1 - high >= trigger: {entry_row['high']:.2f} >= {trigger_price:.4f} = {entry_row['high'] >= trigger_price}")
print(f"  条件2 - low <= trigger:  {entry_row['low']:.2f} <= {trigger_price:.4f} = {entry_row['low'] <= trigger_price}")
print(f"\n结论: 应该买入 = {entry_row['high'] >= trigger_price and entry_row['low'] <= trigger_price}")

# Check if it was limit up day before
print(f"\nT-1 是否涨停: {prev_row['is_limit_up']}")

# Calculate actual trigger used in backtest
backtest_trigger = prev_row['close'] * 1.02
print(f"\n回测中使用的触发价: {backtest_trigger:.4f}")
print(f"回测记录的买入价: 12.4746")
print(f"差异: {abs(12.4746 - backtest_trigger):.4f}")
