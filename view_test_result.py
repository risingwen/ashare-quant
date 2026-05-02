"""查看单次回测结果"""
import pandas as pd
import sys

if len(sys.argv) < 2:
    print("用法: python view_test_result.py <文件前缀>")
    sys.exit(1)

prefix = sys.argv[1]
portfolio_file = f"data/backtest/portfolio/{prefix}_portfolio.parquet"
trades_file = f"data/backtest/trades/{prefix}_trades.csv"

# 读取组合净值
df = pd.read_parquet(portfolio_file)
init_value = df.iloc[0]['nav']
final_value = df.iloc[-1]['nav']
ret_pct = (final_value / init_value - 1) * 100

# 读取交易记录
trades = pd.read_csv(trades_file)
n_buys = len(trades)  # CSV中每行都是完整交易

print(f"初始净值: {init_value:.2f}")
print(f"最终净值: {final_value:.2f}")
print(f"收益率: {ret_pct:.2f}%")
print(f"交易次数: {n_buys}")
print(f"\nCSV文件: {trades_file}")
print(f"前3行浮点数格式预览:")
print(trades[['buy_price', 'sell_price', 'gross_pnl', 'net_pnl_pct']].head(3))
