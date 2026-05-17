"""单次测试助手: 修改参数 -> 运行回测 -> 显示结果"""
import sys
import subprocess
import re
import pandas as pd
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent

def main():
    if len(sys.argv) != 4:
        print("用法: python run_one_test.py <hot_top_n> <max_positions> <nominal_pct>")
        print("示例: python run_one_test.py 10 2 0.5")
        sys.exit(1)
    
    hot_n = int(sys.argv[1])
    max_pos = int(sys.argv[2])
    nominal_pct = float(sys.argv[3])
    
    print(f"=== 测试配置 ===")
    print(f"人气前{hot_n}名 + {max_pos}只持仓 (资金{nominal_pct*100:.1f}%)\n")
    
    script_path = PROJECT_ROOT / "scripts" / "backtest_hot_rank_rise2_strategy.py"
    print(f"✓ 已设置参数: max_positions={max_pos}, nominal_cash={nominal_pct:.4f}\n")
    
    # 2. 运行回测
    print("正在运行回测...\n")
    cmd = [
        sys.executable,
        str(script_path),
        '--config',
        str(PROJECT_ROOT / 'config' / 'strategies' / 'hot_rank_rise2.yaml'),
        '--param.hot_top_n',
        str(hot_n),
        '--param.max_positions',
        str(max_pos),
        '--param.per_trade_cash_frac',
        str(nominal_pct),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
    
    # 3. 提取文件路径
    pattern = r'data[/\\]backtest[/\\]trades[/\\](.+?)_trades\.csv'
    match = re.search(pattern, result.stdout)
    
    if not match:
        print("错误: 无法找到输出文件")
        print(result.stderr)
        sys.exit(1)
    
    prefix = match.group(1)
    
    # 4. 读取结果
    portfolio_file = f"data/backtest/portfolio/{prefix}_portfolio.parquet"
    trades_file = f"data/backtest/trades/{prefix}_trades.csv"
    
    try:
        df = pd.read_parquet(portfolio_file)
        init_value = df.iloc[0]['nav']
        final_value = df.iloc[-1]['nav']
        ret_pct = (final_value / init_value - 1) * 100
        
        trades = pd.read_csv(trades_file)
        n_trades = len(trades)
        
        print("=== 测试结果 ===")
        print(f"初始净值: {init_value:,.2f}")
        print(f"最终净值: {final_value:,.2f}")
        print(f"收益率: {ret_pct:.2f}%")
        print(f"交易次数: {n_trades}")
        print(f"\nCSV文件: {trades_file}")
        print(f"\n格式化示例:")
        print(trades[['code', 'name', 'buy_price', 'sell_price', 'gross_pnl', 'net_pnl_pct']].head(3).to_string(index=False))
        
    except Exception as e:
        print(f"错误: 无法读取结果 - {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
