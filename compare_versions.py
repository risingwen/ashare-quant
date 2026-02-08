import pandas as pd

t1 = pd.read_parquet('data/backtest/trades/hot_rank_drop7_smart_exit_v1.1.0_2fadcb79_20260103_005430_trades.parquet')
p1 = pd.read_parquet('data/backtest/portfolio/hot_rank_drop7_smart_exit_v1.1.0_2fadcb79_20260103_005430_portfolio.parquet')

print('00:54:30 版本（之前说47.02%的版本）:')
print(f'  交易笔数: {len(t1)}')
print(f'  总盈亏金额: {t1["net_pnl"].sum():.2f} 元')
print(f'  最终净值: {p1["nav"].iloc[-1]:.2f}')
print(f'  总收益率: {(p1["nav"].iloc[-1] - 100000) / 100000 * 100:.2f}%')
print(f'  累计复利收益: {((t1["net_pnl_pct"] + 1).prod() - 1) * 100:.2f}%')

print('\n---')

t2 = pd.read_parquet('data/backtest/trades/hot_rank_drop7_smart_exit_v1.1.0_2fadcb79_20260103_011251_trades.parquet')
p2 = pd.read_parquet('data/backtest/portfolio/hot_rank_drop7_smart_exit_v1.1.0_2fadcb79_20260103_011251_portfolio.parquet')

print('\n01:12:51 版本（最新版本）:')
print(f'  交易笔数: {len(t2)}')
print(f'  总盈亏金额: {t2["net_pnl"].sum():.2f} 元')
print(f'  最终净值: {p2["nav"].iloc[-1]:.2f}')
print(f'  总收益率: {(p2["nav"].iloc[-1] - 100000) / 100000 * 100:.2f}%')
print(f'  累计复利收益: {((t2["net_pnl_pct"] + 1).prod() - 1) * 100:.2f}%')
