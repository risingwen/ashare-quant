"""分析回测结果"""
import pandas as pd

# 读取数据
portfolio = pd.read_parquet('data/backtest/portfolio/hot_rank_drop7_smart_exit_v1.1.0_a1893e96_20260102_231310_portfolio.parquet')
trades = pd.read_parquet('data/backtest/trades/hot_rank_drop7_smart_exit_v1.1.0_a1893e96_20260102_231310_trades.parquet')

print('='*70)
print('策略表现总结 - 创业板/科创板-13%, 其他-7%')
print('='*70)

# 性能指标
init = portfolio.iloc[0]['nav']
final = portfolio.iloc[-1]['nav']
ret = (final/init-1)*100
max_dd = ((portfolio['nav']/portfolio['nav'].cummax()-1)*100).min()

print(f'\n【收益指标】')
print(f'初始资金: {init:,.2f}')
print(f'最终净值: {final:,.2f}')
print(f'总收益率: {ret:+.2f}%')
print(f'最大回撤: {max_dd:.2f}%')
print(f'交易日数: {len(portfolio)}天')

# 交易统计
completed = trades[~trades['exit_date'].isna()]
cyb_kcb = trades[trades['code'].str.startswith(('300','688'))]
cyb_kcb_completed = completed[completed['code'].str.startswith(('300','688'))]

print(f'\n【交易统计】')
print(f'总交易数: {len(completed)}笔')
print(f'  - 创业板/科创板(-13%): {len(cyb_kcb_completed)}笔 ({len(cyb_kcb_completed)/len(completed)*100:.1f}%)')
print(f'  - 其他股票(-7%): {len(completed)-len(cyb_kcb_completed)}笔 ({(len(completed)-len(cyb_kcb_completed))/len(completed)*100:.1f}%)')

# 胜率分析
win_trades = completed[completed['net_pnl'] > 0]
cyb_kcb_win = cyb_kcb_completed[cyb_kcb_completed['net_pnl'] > 0]
other_win = completed[(~completed['code'].str.startswith(('300','688'))) & (completed['net_pnl'] > 0)]

print(f'\n【胜率分析】')
print(f'整体胜率: {len(win_trades)/len(completed)*100:.1f}%')
print(f'  - 创业板/科创板: {len(cyb_kcb_win)/len(cyb_kcb_completed)*100:.1f}%' if len(cyb_kcb_completed) > 0 else '  - 创业板/科创板: N/A')
print(f'  - 其他股票: {len(other_win)/(len(completed)-len(cyb_kcb_completed))*100:.1f}%')

# 平均收益
print(f'\n【平均收益】')
print(f'整体平均: {completed["net_pnl_pct"].mean()*100:+.2f}%')
if len(cyb_kcb_completed) > 0:
    print(f'  - 创业板/科创板: {cyb_kcb_completed["net_pnl_pct"].mean()*100:+.2f}%')
else:
    print(f'  - 创业板/科创板: N/A (无交易)')
other_completed = completed[~completed['code'].str.startswith(('300','688'))]
print(f'  - 其他股票: {other_completed["net_pnl_pct"].mean()*100:+.2f}%')

# 最终持仓
open_pos = trades[trades['exit_date'].isna()]
print(f'\n【最终持仓】')
print(f'持仓数量: {len(open_pos)}只')
if len(open_pos) > 0:
    print(f'现金余额: {portfolio.iloc[-1]["cash"]:,.2f}')
    print('\n持仓明细:')
    for _, pos in open_pos.iterrows():
        board = '创业板' if pos['code'].startswith('300') else '科创板' if pos['code'].startswith('688') else '主板'
        print(f"  {pos['code']} {pos['name']:8s} [{board}] {pos['buy_shares']}股 @{pos['buy_exec']:.2f}")

print('\n' + '='*70)
