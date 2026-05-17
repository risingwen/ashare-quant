"""
测试不同人气排名阈值和持仓数量的组合效果
"""
import subprocess
import re
import json
import pandas as pd
from datetime import datetime
from pathlib import Path

from src.test_helpers import build_rise2_cmd, run_cmd_capture_tail


PROJECT_ROOT = Path(__file__).resolve().parent

def run_backtest(hot_rank_limit, num_positions):
    """运行回测，使用CLI参数覆盖hot_top_n"""
    cash_fraction = 1.0 / num_positions
    cmd = build_rise2_cmd(
        PROJECT_ROOT,
        hot_top_n=hot_rank_limit,
        max_positions=num_positions,
        per_trade_cash_frac=cash_fraction,
    )
    return run_cmd_capture_tail(cmd, cwd=PROJECT_ROOT)

def extract_results(output):
    """从回测输出中提取关键指标"""
    results = {}
    
    for line in output.split('\n'):
        if '成交买入:' in line:
            match = re.search(r'成交买入: (\d+)', line)
            if match:
                results['买入次数'] = int(match.group(1))
        
        if '成交卖出:' in line:
            match = re.search(r'成交卖出: (\d+)', line)
            if match:
                results['卖出次数'] = int(match.group(1))
        
        if '最终现金:' in line:
            match = re.search(r'最终现金: ([\d.]+)', line)
            if match:
                results['最终现金'] = float(match.group(1))
        
        if '最终持仓:' in line:
            match = re.search(r'最终持仓: (\d+)只', line)
            if match:
                results['最终持仓'] = int(match.group(1))
        
        if '跳过-资金不足:' in line:
            match = re.search(r'跳过-资金不足: (\d+)', line)
            if match:
                results['资金不足'] = int(match.group(1))
        
        # 从2025-12-31的净值记录提取
        if '持仓:' in line and '净值:' in line and '2025-12-31' in line:
            match = re.search(r'净值: ([\d.]+)', line)
            if match:
                results['最终净值'] = float(match.group(1))
    
    return results

def format_csv_trades(csv_path):
    """格式化CSV中的数字为小数点后两位"""
    df = pd.read_csv(csv_path)
    
    # 浮点数列保留2位小数
    float_columns = ['buy_price', 'buy_exec', 'commission', 'total_cost', 'cash_after',
                     'sell_price', 'sell_exec', 'stamp_tax', 'sell_proceed', 'pnl', 
                     'pnl_pct', 'close', 'limit_up']
    
    for col in float_columns:
        if col in df.columns:
            df[col] = df[col].round(2)
    
    df.to_csv(csv_path, index=False, float_format='%.2f')
    return csv_path

def find_latest_csv():
    """找到最新生成的CSV文件"""
    trades_dir = Path('data/backtest/trades')
    csv_files = list(trades_dir.glob('*_trades.csv'))
    if csv_files:
        latest = max(csv_files, key=lambda p: p.stat().st_mtime)
        return str(latest)
    return None

def main():
    results_summary = []
    init_cash = 100000
    
    # 人气阈值: 10, 20, 30
    hot_rank_limits = [10, 20, 30]
    
    # 持仓数: 1-5
    position_counts = [1, 2, 3, 4, 5]
    
    total_tests = len(hot_rank_limits) * len(position_counts)
    current_test = 0
    
    for hot_rank_limit in hot_rank_limits:
        for num_positions in position_counts:
            current_test += 1
            
            print(f"\n{'='*70}")
            print(f"测试 {current_test}/{total_tests}: 人气前{hot_rank_limit}名 + {num_positions}只持仓 ({100/num_positions:.2f}%资金)")
            print(f"{'='*70}\n")
            
            print(f"已配置: {num_positions}只持仓 {100/num_positions:.2f}%资金, 人气前{hot_rank_limit}名")
            
            # 运行回测
            print("运行回测中...")
            output = run_backtest(hot_rank_limit, num_positions)
            
            # 提取结果
            results = extract_results(output)
            results['人气阈值'] = hot_rank_limit
            results['持仓数'] = num_positions
            results['资金比例'] = f"{100/num_positions:.2f}%"
            
            # 计算收益率
            if '最终净值' in results:
                final_value = results['最终净值']
                returns = (final_value - init_cash) / init_cash * 100
                results['收益率%'] = round(returns, 2)
            
            # 找到并格式化最新的CSV
            csv_path = find_latest_csv()
            if csv_path:
                format_csv_trades(csv_path)
                results['CSV文件'] = csv_path
                print(f"CSV已格式化: {csv_path}")
            
            results_summary.append(results)
            
            print(f"✓ 完成! 买入{results.get('买入次数', 0)}笔, "
                  f"净值{results.get('最终净值', 0):.2f}元, "
                  f"收益率{results.get('收益率%', 0):.2f}%")
    
    # 生成汇总表格
    print(f"\n\n{'='*100}")
    print("回测结果汇总")
    print(f"{'='*100}\n")
    
    # 按人气阈值分组显示
    for hot_rank_limit in hot_rank_limits:
        print(f"\n【人气前{hot_rank_limit}名】")
        print(f"{'-'*100}")
        print(f"{'持仓数':^8} {'资金比例':^12} {'买入次数':^10} {'最终净值':^15} {'收益率%':^10} {'资金不足':^10}")
        print(f"{'-'*100}")
        
        group_results = [r for r in results_summary if r['人气阈值'] == hot_rank_limit]
        for r in group_results:
            净值 = r.get('最终净值', 0)
            收益 = r.get('收益率%', 0)
            资金不足 = r.get('资金不足', 0)
            print(f"{r.get('持仓数', 0):^8} "
                  f"{r.get('资金比例', 'N/A'):^12} "
                  f"{r.get('买入次数', 0):^10} "
                  f"{净值:^15,.2f} "
                  f"{收益:^10.2f} "
                  f"{资金不足:^10}")
        
        # 找出该组最佳配置
        best = max(group_results, key=lambda x: x.get('最终净值', 0))
        print(f"\n  最佳: {best['持仓数']}只持仓, 净值{best.get('最终净值', 0):,.2f}元, 收益率{best.get('收益率%', 0):.2f}%")
    
    # 全局最佳配置
    if results_summary:
        best_overall = max(results_summary, key=lambda x: x.get('最终净值', 0))
        
        print(f"\n\n{'='*100}")
        print("🏆 全局最佳配置")
        print(f"{'='*100}")
        print(f"人气阈值: 前{best_overall['人气阈值']}名")
        print(f"持仓数量: {best_overall['持仓数']}只 (每只{best_overall['资金比例']})")
        print(f"最终净值: {best_overall.get('最终净值', 0):,.2f}元")
        print(f"收益率: {best_overall.get('收益率%', 0):.2f}%")
        print(f"买入次数: {best_overall.get('买入次数', 0)}笔")
        print(f"资金不足: {best_overall.get('资金不足', 0)}次")
        print(f"{'='*100}\n")
    
    # 保存结果
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # 保存JSON
    json_file = f"hot_rank_combinations_test_{timestamp}.json"
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(results_summary, f, ensure_ascii=False, indent=2)
    print(f"详细结果已保存至: {json_file}")
    
    # 保存CSV汇总
    df_summary = pd.DataFrame(results_summary)
    csv_file = f"hot_rank_combinations_test_{timestamp}.csv"
    df_summary.to_csv(csv_file, index=False, encoding='utf-8-sig')
    print(f"CSV汇总已保存至: {csv_file}")

if __name__ == '__main__':
    main()
