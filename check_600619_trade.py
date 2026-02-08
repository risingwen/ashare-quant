"""
Check 600619 trade details on 2025-08-08 to 2025-08-14
"""
import pandas as pd
import duckdb

# Load feature data
df = pd.read_parquet('data/processed/features/daily_features_v1.parquet')

# Get 600619 data from 2025-08-08 to 2025-08-14
df_600619 = df[(df['code'] == '600619') & (df['date'] >= '2025-08-08') & (df['date'] <= '2025-08-14')].sort_values('date')

print("=== 600619 海立股份 持仓期间数据 ===")
print(df_600619[['date', 'open', 'high', 'low', 'close', 'close_prev', 'is_limit_up', 'is_limit_down']].to_string(index=False))

print("\n=== 计算每日跌停触发条件 ===")
for idx, row in df_600619.iterrows():
    if pd.notna(row['close_prev']):
        trigger_price = row['close_prev'] * (1 - 0.07)
        is_triggered = row['low'] <= trigger_price
        print(f"{row['date'].date()}: low={row['low']:.2f}, close_prev={row['close_prev']:.2f}, "
              f"trigger(-7%)={trigger_price:.2f}, triggered={is_triggered}")

# Check trades file
trades_df = pd.read_parquet('data/backtest/trades/hot_rank_rise2_smart_exit_v1.0.0_28931f2a_20260103_225614_trades.parquet')
trade_600619 = trades_df[trades_df['code'] == '600619']

print("\n=== 回测交易记录 ===")
if len(trade_600619) > 0:
    print(trade_600619[['entry_date', 'exit_date', 'buy_price', 'sell_price', 'exit_reason', 'hold_days', 'net_pnl_pct']].to_string(index=False))
else:
    print("未找到600619的交易记录")

# Check if there are multiple trades
print(f"\n600619共有{len(trade_600619)}笔交易")
