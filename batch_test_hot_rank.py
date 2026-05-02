"""批量测试人气阈值+持仓数组合
测试矩阵: 人气前10/20/30 × 持仓1-5只 = 15种组合
"""
import subprocess
import pandas as pd
import re
from pathlib import Path
from datetime import datetime
import time

def modify_script_params(max_pos, nominal_pct):
    """修改回测脚本参数"""
    script_path = "scripts/backtest_hot_rank_rise2_strategy.py"
    
    # 读取脚本
    with open(script_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 替换max_positions
    content = re.sub(
        r'(# 限制最多持\d+只股票.*\n\s*)max_positions\s*=\s*\d+',
        f'\\1max_positions = {max_pos}',
        content
    )
    
    # 替换nominal_cash
    content = re.sub(
        r'(# 计算名义资金.*\n\s*)nominal_cash\s*=\s*self\.init_cash\s*\*\s*[\d.]+',
        f'\\1nominal_cash = self.init_cash * {nominal_pct:.4f}',
        content
    )
    
    # 写回文件
    with open(script_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"  修改参数: max_positions={max_pos}, nominal_cash={nominal_pct:.4f}")

def run_backtest(hot_top_n):
    """运行回测"""
    cmd = [
        'python',
        'scripts/backtest_hot_rank_rise2_strategy.py',
        '--config',
        'config/strategies/hot_rank_rise2.yaml',
        '--param.hot_top_n',
        str(hot_top_n)
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result

def extract_result_from_output(output_text):
    """从输出中提取结果"""
    # 查找最新生成的文件路径
    pattern = r'data\\backtest\\trades\\(hot_rank_rise2_smart_exit_v1\.0\.0_\w+_\d+_\d+)_trades\.csv'
    match = re.search(pattern, output_text)
    
    if not match:
        return None, None, None, None
    
    prefix = match.group(1)
    
    # 读取结果
    portfolio_file = f"data/backtest/portfolio/{prefix}_portfolio.parquet"
    trades_file = f"data/backtest/trades/{prefix}_trades.csv"
    
    try:
        df = pd.read_parquet(portfolio_file)
        init_value = df.iloc[0]['nav']
        final_value = df.iloc[-1]['nav']
        ret_pct = (final_value / init_value - 1) * 100
        
        trades = pd.read_csv(trades_file)
        n_trades = len(trades)
        
        return final_value, ret_pct, n_trades, trades_file
    except Exception as e:
        print(f"  错误: 无法读取结果文件 - {e}")
        return None, None, None, None

def main():
    # 测试矩阵
    hot_ranks = [10, 20, 30]
    positions = [
        (1, 1.0),      # 1只, 100%
        (2, 0.5),      # 2只, 50%
        (3, 0.3333),   # 3只, 33.33%
        (4, 0.25),     # 4只, 25%
        (5, 0.2)       # 5只, 20%
    ]
    
    results = []
    total = len(hot_ranks) * len(positions)
    current = 0
    
    print(f"开始批量测试: {total}种组合\n")
    print("=" * 80)
    
    for hot_n in hot_ranks:
        for max_pos, nominal_pct in positions:
            current += 1
            print(f"\n[{current}/{total}] 测试: 人气前{hot_n}名 + {max_pos}只持仓 (资金{nominal_pct*100:.1f}%)")
            
            # 修改脚本参数
            modify_script_params(max_pos, nominal_pct)
            
            # 运行回测
            print(f"  执行回测...")
            result = run_backtest(hot_n)
            
            # 提取结果
            final_val, ret, n_trades, csv_path = extract_result_from_output(result.stdout)
            
            if final_val is not None:
                results.append({
                    'hot_top_n': hot_n,
                    'max_positions': max_pos,
                    'nominal_pct': nominal_pct,
                    'final_value': final_val,
                    'return_pct': ret,
                    'n_trades': n_trades,
                    'csv_file': csv_path
                })
                print(f"  ✓ 最终净值: {final_val:.2f}, 收益率: {ret:.2f}%, 交易次数: {n_trades}")
            else:
                print(f"  ✗ 测试失败")
            
            # 短暂延迟
            time.sleep(0.5)
    
    # 保存结果
    print("\n" + "=" * 80)
    print("所有测试完成!\n")
    
    df_results = pd.DataFrame(results)
    
    # 保存到CSV
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    results_file = f"人气阈值测试结果_{timestamp}.csv"
    df_results.to_csv(results_file, index=False, encoding='utf-8-sig')
    print(f"结果已保存: {results_file}\n")
    
    # 打印汇总表
    print("=== 测试结果汇总 ===\n")
    for hot_n in hot_ranks:
        print(f"\n【人气前{hot_n}名】")
        subset = df_results[df_results['hot_top_n'] == hot_n]
        for _, row in subset.iterrows():
            print(f"  {row['max_positions']}只持仓: 净值={row['final_value']:.2f}, "
                  f"收益={row['return_pct']:.2f}%, 交易={row['n_trades']}次")
    
    # 找出最佳组合
    best = df_results.loc[df_results['return_pct'].idxmax()]
    print(f"\n【最佳组合】")
    print(f"  人气前{best['hot_top_n']}名 + {best['max_positions']}只持仓")
    print(f"  最终净值: {best['final_value']:.2f}")
    print(f"  收益率: {best['return_pct']:.2f}%")
    print(f"  交易次数: {best['n_trades']}")

if __name__ == '__main__':
    main()
