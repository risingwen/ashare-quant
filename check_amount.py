import pandas as pd

trades = pd.read_parquet('data/backtest/trades/hot_rank_drop7_smart_exit_v1.1.0_2fadcb79_20260103_005430_trades.parquet')

print('成交额统计:')
print(f'最小值: {trades["amount_t1"].min():.2e}')
print(f'最大值: {trades["amount_t1"].max():.2e}')
print(f'平均值: {trades["amount_t1"].mean():.2e}')
print(f'中位数: {trades["amount_t1"].median():.2e}')

print(f'\n前10行样本:')
print(trades[['code', 'name', 'rank_t1', 'amount_t', 'amount_t1', 'amount_t2', 'net_pnl_pct']].head(10))
