import pandas as pd

portfolio = pd.read_parquet('data/backtest/portfolio/hot_rank_drop7_smart_exit_v1.1.0_a1893e96_20260103_000450_portfolio.parquet')
trades = pd.read_parquet('data/backtest/trades/hot_rank_drop7_smart_exit_v1.1.0_a1893e96_20260103_000450_trades.parquet')

print('=' * 60)
print('回测结果摘要')
print('=' * 60)
print(f'回测期间: {portfolio.iloc[0]["date"].date()} 至 {portfolio.iloc[-1]["date"].date()}')
print(f'初始资金: {portfolio.iloc[0]["nav"]:,.2f}')
print(f'最终净值: {portfolio.iloc[-1]["nav"]:,.2f}')
ret = (portfolio.iloc[-1]["nav"] / portfolio.iloc[0]["nav"] - 1) * 100
print(f'总收益率: {ret:+.2f}%')
print(f'最大净值: {portfolio["nav"].max():,.2f}')
max_dd = ((portfolio["nav"].cummax() - portfolio["nav"]) / portfolio["nav"].cummax() * 100).max()
print(f'最大回撤: {max_dd:.2f}%')

print('\n' + '=' * 60)
print('交易统计')
print('=' * 60)
print(f'总交易数: {len(trades)}')
win = (trades["net_pnl"] > 0).sum()
loss = (trades["net_pnl"] < 0).sum()
print(f'盈利交易: {win} ({win / len(trades) * 100:.1f}%)')
print(f'亏损交易: {loss} ({loss / len(trades) * 100:.1f}%)')
print(f'胜率: {win / len(trades) * 100:.1f}%')

total_win = trades[trades["net_pnl"] > 0]["net_pnl"].sum()
total_loss = trades[trades["net_pnl"] < 0]["net_pnl"].sum()
print(f'\n总盈利: {total_win:,.2f}')
print(f'总亏损: {total_loss:,.2f}')
print(f'净利润: {total_win + total_loss:,.2f}')

avg_win = trades[trades["net_pnl"] > 0]["net_pnl"].mean()
avg_loss = trades[trades["net_pnl"] < 0]["net_pnl"].abs().mean()
print(f'\n平均单笔盈利: {avg_win:.2f}')
print(f'平均单笔亏损: {avg_loss:.2f}')
print(f'盈亏比: {avg_win / avg_loss:.2f}')

print(f'\n平均持仓天数: {trades["hold_days"].mean():.1f}')
print(f'最长持仓: {trades["hold_days"].max():.0f} 天')

# 按退出原因统计
print('\n' + '=' * 60)
print('退出原因分布')
print('=' * 60)
exit_reasons = trades['exit_reason'].value_counts()
for reason, count in exit_reasons.items():
    pnl = trades[trades['exit_reason'] == reason]['net_pnl'].sum()
    avg_pnl = trades[trades['exit_reason'] == reason]['net_pnl'].mean()
    print(f'{reason}: {count} 笔 ({count/len(trades)*100:.1f}%), 累计: {pnl:+,.0f}, 平均: {avg_pnl:+.2f}')

# 月度收益
print('\n' + '=' * 60)
print('月度收益率')
print('=' * 60)
portfolio['month'] = pd.to_datetime(portfolio['date']).dt.to_period('M')
monthly = portfolio.groupby('month')['nav'].agg(['first', 'last'])
monthly['return'] = (monthly['last'] / monthly['first'] - 1) * 100
for month, row in monthly.iterrows():
    print(f'{month}: {row["return"]:+.2f}%')

