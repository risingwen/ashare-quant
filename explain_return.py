import pandas as pd

# 读取交易记录
trades = pd.read_parquet('data/backtest/trades/hot_rank_drop7_smart_exit_v1.1.0_2fadcb79_20260103_011251_trades.parquet')

# 读取组合净值
portfolio = pd.read_parquet('data/backtest/portfolio/hot_rank_drop7_smart_exit_v1.1.0_2fadcb79_20260103_011251_portfolio.parquet')

print('=' * 80)
print('总收益率计算说明')
print('=' * 80)

# 初始和最终资金
init_cash = 100000
final_nav = portfolio['nav'].iloc[-1]
final_cash = portfolio['cash'].iloc[-1]
final_position_value = portfolio['position_value'].iloc[-1]

print(f'\n【资金情况】')
print(f'初始资金: {init_cash:,.2f} 元')
print(f'最终现金: {final_cash:,.2f} 元')
print(f'最终持仓市值: {final_position_value:,.2f} 元')
print(f'最终总资产(NAV): {final_nav:,.2f} 元')

# 总收益率计算方法
total_return = (final_nav - init_cash) / init_cash * 100

print(f'\n【总收益率计算】')
print(f'总收益率 = (最终总资产 - 初始资金) / 初始资金 × 100%')
print(f'总收益率 = ({final_nav:,.2f} - {init_cash:,.2f}) / {init_cash:,.2f} × 100%')
print(f'总收益率 = {final_nav - init_cash:,.2f} / {init_cash:,.2f} × 100%')
print(f'总收益率 = {total_return:.2f}%')

# 复利计算（每笔收益叠加）
trades_completed = trades[trades['exit_date'].notna()].copy()
compound_return = (trades_completed['net_pnl_pct'] + 1).prod() - 1

print(f'\n【复利收益率】（所有交易复利叠加）')
print(f'复利收益率 = ∏(1 + 每笔收益率) - 1')
print(f'复利收益率 = {compound_return * 100:.2f}%')

print(f'\n【收益明细】')
print(f'总盈亏金额: {final_nav - init_cash:,.2f} 元')
print(f'已完成交易: {len(trades_completed)} 笔')
print(f'盈利笔数: {(trades_completed["net_pnl_pct"] > 0).sum()} 笔')
print(f'亏损笔数: {(trades_completed["net_pnl_pct"] < 0).sum()} 笔')
print(f'平均每笔收益: {trades_completed["net_pnl"].mean():,.2f} 元')
print(f'平均收益率: {trades_completed["net_pnl_pct"].mean() * 100:.2f}%')
print(f'胜率: {(trades_completed["net_pnl_pct"] > 0).sum() / len(trades_completed) * 100:.1f}%')

print(f'\n【净值曲线】')
print(f'起始净值: {portfolio["nav"].iloc[0]:,.2f}')
print(f'最高净值: {portfolio["nav"].max():,.2f}')
print(f'最低净值: {portfolio["nav"].min():,.2f}')
print(f'最终净值: {portfolio["nav"].iloc[-1]:,.2f}')

# 最大回撤
portfolio['cum_max'] = portfolio['nav'].cummax()
portfolio['drawdown'] = (portfolio['nav'] - portfolio['cum_max']) / portfolio['cum_max']
max_drawdown = portfolio['drawdown'].min()

print(f'最大回撤: {max_drawdown * 100:.2f}%')
