import pandas as pd

# 读取最新的交易记录
trades = pd.read_parquet('data/backtest/trades/hot_rank_drop7_smart_exit_v1.1.0_7daf501c_20260103_010540_trades.parquet')

print('=== 人气前60回测结果 ===\n')
print(f'交易笔数: {len(trades)}')
print(f'平均收益率: {trades["net_pnl_pct"].mean()*100:.2f}%')
print(f'累计收益率: {((trades["net_pnl_pct"] + 1).prod() - 1)*100:.2f}%')
print(f'胜率: {(trades["net_pnl_pct"] > 0).sum() / len(trades) * 100:.1f}%')
print(f'最大盈利: {trades["net_pnl_pct"].max()*100:.2f}%')
print(f'最大亏损: {trades["net_pnl_pct"].min()*100:.2f}%')

print('\n=== 前10笔交易 ===')
print(trades[['code', 'name', 'entry_date', 'exit_date', 'net_pnl_pct']].head(10).to_string(index=False))
