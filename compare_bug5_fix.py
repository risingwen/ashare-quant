import pandas as pd
import numpy as np

# 读取修复前的文件（Bug5修复前：人气过滤）
before_bug5 = pd.read_parquet('data/backtest/trades/hot_rank_drop7_smart_exit_v1.1.0_4cc96acd_20260103_002945_trades.parquet')

# 读取修复后的文件（Bug5修复：T-1日当天跌幅检查）
after_bug5 = pd.read_parquet('data/backtest/trades/hot_rank_drop7_smart_exit_v1.1.0_4cc96acd_20260103_004920_trades.parquet')

def analyze(df, name):
    # 新格式：每行是一个完整的交易
    trades = df[df['exit_date'].notna()].copy()
    
    initial_cash = 100000
    total_pnl = trades['net_pnl'].sum()
    final_value = initial_cash + total_pnl
    total_return = total_pnl / initial_cash * 100
    
    # 计算胜率
    win_rate = (trades['net_pnl'] > 0).sum() / len(trades) * 100 if len(trades) > 0 else 0
    avg_pnl = trades['net_pnl'].mean() if len(trades) > 0 else 0
    avg_pnl_pct = trades['net_pnl_pct'].mean() * 100 if len(trades) > 0 else 0
    avg_hold = trades['hold_days'].mean() if len(trades) > 0 else 0
    
    print(f'\n=== {name} ===')
    print(f'交易笔数: {len(trades)}')
    print(f'总收益率: {total_return:.2f}%')
    print(f'胜率: {win_rate:.2f}%')
    print(f'平均收益率: {avg_pnl_pct:.2f}%')
    print(f'平均收益额: {avg_pnl:.2f}')
    print(f'平均持仓天数: {avg_hold:.1f}')
    print(f'最终总资产: {final_value:,.2f}')
    
    return total_return, win_rate, len(trades), avg_pnl_pct

ret1, wr1, trades1, avg1 = analyze(before_bug5, 'Bug5修复前（人气≤100，未检查T-1当天跌幅）')
ret2, wr2, trades2, avg2 = analyze(after_bug5, 'Bug5修复后（人气≤100 + T-1当天跌幅检查）')

print(f'\n=== 对比变化 ===')
print(f'交易笔数: {trades1} → {trades2} ({(trades2-trades1)/trades1*100:+.1f}%)')
print(f'总收益率: {ret1:.2f}% → {ret2:.2f}% ({ret2-ret1:+.2f}%)')
print(f'胜率: {wr1:.2f}% → {wr2:.2f}% ({wr2-wr1:+.2f}%)')
print(f'平均收益率: {avg1:.2f}% → {avg2:.2f}% ({avg2-avg1:+.2f}%)')

# 检查603686是否还在
print(f'\n=== 验证Bug修复 ===')
if '603686' in before_bug5['code'].values:
    print('Bug5修复前: 603686福龙马 被买入 ✗（应被过滤）')
else:
    print('Bug5修复前: 603686福龙马 未被买入')
    
if '603686' in after_bug5['code'].values:
    print('Bug5修复后: 603686福龙马 被买入 ✗（修复失败）')
else:
    print('Bug5修复后: 603686福龙马 未被买入 ✓（修复成功）')
