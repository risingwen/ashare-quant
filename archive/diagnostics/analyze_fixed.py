"""生成修复后的完整分析报告"""
import pandas as pd

portfolio = pd.read_parquet('data/backtest/portfolio/hot_rank_drop7_smart_exit_v1.1.0_a1893e96_20260102_232316_portfolio.parquet')
trades = pd.read_parquet('data/backtest/trades/hot_rank_drop7_smart_exit_v1.1.0_a1893e96_20260102_232316_trades.parquet')

print('='*70)
print('策略回测报告 - 修复后版本（创业板30开头，科创板688开头）')
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

# 交易统计
completed = trades[~trades['exit_date'].isna()]
cyb_kcb = completed[completed['code'].str.startswith(('30','688'))]
other = completed[~completed['code'].str.startswith(('30','688'))]

print(f'\n【交易统计】（修复后）')
print(f'总交易数: {len(completed)}笔')
print(f'  - 创业板/科创板(-13%): {len(cyb_kcb)}笔 ({len(cyb_kcb)/len(completed)*100:.1f}%)')
print(f'  - 其他股票(-7%): {len(other)}笔 ({len(other)/len(completed)*100:.1f}%)')

# 对比修复前后
print(f'\n【修复效果对比】')
print(f'修复前: 创业板/科创板 23笔 (1.8%) - 仅包含300和688开头')
print(f'修复后: 创业板/科创板 {len(cyb_kcb)}笔 ({len(cyb_kcb)/len(completed)*100:.1f}%) - 覆盖所有30x和688开头')

# 胜率分析
cyb_kcb_win = cyb_kcb[cyb_kcb['net_pnl'] > 0]
other_win = other[other['net_pnl'] > 0]

print(f'\n【胜率分析】（修复后）')
print(f'整体胜率: {len(completed[completed["net_pnl"]>0])/len(completed)*100:.1f}%')
if len(cyb_kcb) > 0:
    print(f'  - 创业板/科创板: {len(cyb_kcb_win)/len(cyb_kcb)*100:.1f}%')
    print(f'  - 其他股票: {len(other_win)/len(other)*100:.1f}%')

# 平均收益
print(f'\n【平均收益】（修复后）')
print(f'整体平均: {completed["net_pnl_pct"].mean()*100:+.2f}%')
if len(cyb_kcb) > 0:
    print(f'  - 创业板/科创板: {cyb_kcb["net_pnl_pct"].mean()*100:+.2f}%')
print(f'  - 其他股票: {other["net_pnl_pct"].mean()*100:+.2f}%')

# 验证301038
print(f'\n【关键Bug验证】')
t301 = completed[completed['code']=='301038']
if len(t301) > 0:
    ratio = (t301.iloc[0]['buy_price']/t301.iloc[0]['prev_close']-1)*100
    print(f'301038（深水规院）:')
    print(f'  前收: {t301.iloc[0]["prev_close"]:.2f}')
    print(f'  买入: {t301.iloc[0]["buy_price"]:.2f} ({ratio:+.2f}%)')
    print(f'  ✅ 修复成功！使用-13%触发')
else:
    print(f'301038: 未触发（可能因-13%阈值更严格）')

# 创业板分布
cyb_300 = cyb_kcb[cyb_kcb['code'].str.startswith('300')]
cyb_301 = cyb_kcb[cyb_kcb['code'].str.startswith('301')]
cyb_other = cyb_kcb[(~cyb_kcb['code'].str.startswith('300')) & (~cyb_kcb['code'].str.startswith('301')) & (cyb_kcb['code'].str.startswith('30'))]
kcb = cyb_kcb[cyb_kcb['code'].str.startswith('688')]

print(f'\n【创业板/科创板细分】')
print(f'300开头: {len(cyb_300)}笔')
print(f'301开头: {len(cyb_301)}笔')
if len(cyb_other) > 0:
    print(f'302-309开头: {len(cyb_other)}笔')
print(f'688开头（科创板）: {len(kcb)}笔')

print('\n' + '='*70)
