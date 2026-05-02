"""检查301038交易记录"""
import pandas as pd

trades = pd.read_parquet('data/backtest/trades/hot_rank_drop7_smart_exit_v1.1.0_a1893e96_20260102_231310_trades.parquet')
t = trades[trades['code']=='301038']

if len(t)>0:
    print('301038（深水规院）交易记录:')
    print('='*60)
    row = t.iloc[0]
    print(f"前收盘价: {row['prev_close']:.4f}")
    print(f"买入价格: {row['buy_price']:.4f}")
    ratio = (row['buy_price']/row['prev_close']-1)*100
    print(f"实际比例: {ratio:.2f}%")
    print(f"\n预期-13%价格: {row['prev_close']*0.87:.4f}")
    print(f"预期-7%价格:  {row['prev_close']*0.93:.4f}")
    print(f"实际买入价:  {row['buy_price']:.4f}")
    
    if abs(ratio - (-7)) < 0.1:
        print(f"\n❌ 错误: 301开头创业板股票使用了-7%触发，应该是-13%！")
    elif abs(ratio - (-13)) < 0.1:
        print(f"\n✅ 正确: 使用了-13%触发")
    else:
        print(f"\n⚠️  异常: 比例为{ratio:.2f}%")
else:
    print('未找到301038交易记录')
