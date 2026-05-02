"""验证修正后的301038交易"""
import pandas as pd

trades = pd.read_parquet('data/backtest/trades/hot_rank_drop7_smart_exit_v1.1.0_a1893e96_20260102_232316_trades.parquet')

# 检查301038
t = trades[trades['code']=='301038']
print('='*70)
print('验证301038（深水规院）- 创业板股票')
print('='*70)

if len(t)>0:
    row = t.iloc[0]
    ratio = (row['buy_price']/row['prev_close']-1)*100
    print(f"\n前收盘价: {row['prev_close']:.4f}")
    print(f"买入价格: {row['buy_price']:.4f}")
    print(f"实际比例: {ratio:.2f}%")
    print(f"\n预期-13%: {row['prev_close']*0.87:.4f}")
    print(f"实际买入: {row['buy_price']:.4f}")
    
    if abs(ratio - (-13)) < 0.1:
        print(f"\n✅ 修正成功！301开头创业板股票正确使用-13%触发")
    else:
        print(f"\n❌ 仍有问题：比例为{ratio:.2f}%")
else:
    print('\n⚠️  注意：修正后301038未触发买入信号（可能因为-13%阈值更严格）')

# 统计所有30开头的股票
cyb_trades = trades[trades['code'].str.startswith('30')]
print(f'\n创业板交易统计（30开头）:')
print(f'总交易数: {len(cyb_trades)}笔')

if len(cyb_trades) > 0:
    print(f'\n验证前5笔创业板交易的触发比例:')
    for idx, (_, row) in enumerate(cyb_trades.head(5).iterrows(), 1):
        ratio = (row['buy_price']/row['prev_close']-1)*100
        status = '✅' if abs(ratio - (-13)) < 0.1 else '❌'
        print(f"{status} {row['code']} {row['name']:10s} {ratio:+.2f}%")
