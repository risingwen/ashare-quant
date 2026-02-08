"""
测试不同资金分配份数的回测效果
"""
import subprocess
import re
import json
from datetime import datetime

def modify_backtest_script(num_positions):
    """修改回测脚本中的持仓数和资金比例"""
    script_path = r"scripts\backtest_hot_rank_rise2_strategy.py"
    
    with open(script_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 修改 max_positions
    content = re.sub(
        r'max_positions = \d+',
        f'max_positions = {num_positions}',
        content
    )
    
    # 修改 nominal_cash 比例
    cash_fraction = 1.0 / num_positions
    content = re.sub(
        r'nominal_cash = self\.init_cash \* [\d.]+',
        f'nominal_cash = self.init_cash * {cash_fraction:.4f}',
        content
    )
    
    with open(script_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"已修改脚本: {num_positions}只持仓, 每只{cash_fraction*100:.2f}%资金")

def run_backtest():
    """运行回测，返回最后100行输出"""
    cmd = [
        'python',
        'scripts/backtest_hot_rank_rise2_strategy.py',
        '--config', 'config/strategies/hot_rank_rise2.yaml'
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
    # 只保留最后100行，包含统计信息
    lines = result.stdout.split('\n')
    return '\n'.join(lines[-100:])

def extract_results(output):
    """从回测输出中提取关键指标"""
    results = {}
    
    # 提取统计信息
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
        
        # 从回测过程中的最后一个净值记录提取
        if '持仓:' in line and '净值:' in line and '2025-12-31' in line:
            match = re.search(r'净值: ([\d.]+)', line)
            if match:
                results['最终净值'] = float(match.group(1))
    
    return results

def main():
    results_summary = []
    init_cash = 100000
    
    for num_positions in [1, 2, 3, 4, 5]:
        print(f"\n{'='*60}")
        print(f"开始测试: {num_positions}只持仓 (每只{100/num_positions:.2f}%资金)")
        print(f"{'='*60}\n")
        
        # 修改脚本
        modify_backtest_script(num_positions)
        
        # 运行回测
        print("运行回测中，请稍候...")
        output = run_backtest()
        
        # 提取结果
        results = extract_results(output)
        results['持仓数'] = num_positions
        results['资金比例'] = f"{100/num_positions:.2f}%"
        
        # 计算收益率
        if '最终净值' in results:
            final_value = results['最终净值']
            returns = (final_value - init_cash) / init_cash * 100
            results['收益率%'] = round(returns, 2)
        
        results_summary.append(results)
        
        print(f"完成! 买入{results.get('买入次数', 0)}笔, "
              f"净值{results.get('最终净值', 0):.2f}元, "
              f"收益率{results.get('收益率%', 0):.2f}%")
    
    # 打印汇总表格
    print(f"\n\n{'='*90}")
    print("回测结果汇总")
    print(f"{'='*90}\n")
    print(f"{'持仓数':^8} {'资金比例':^12} {'买入次数':^10} {'最终净值':^15} {'收益率%':^10} {'最终现金':^15}")
    print(f"{'-'*90}")
    
    for r in results_summary:
        净值 = r.get('最终净值', 0)
        现金 = r.get('最终现金', 0)
        收益 = r.get('收益率%', 0)
        print(f"{r.get('持仓数', 0):^8} "
              f"{r.get('资金比例', 'N/A'):^12} "
              f"{r.get('买入次数', 0):^10} "
              f"{净值:^15,.2f} "
              f"{收益:^10.2f} "
              f"{现金:^15,.2f}")
    
    # 找出最佳配置
    if results_summary and all('最终净值' in r for r in results_summary):
        best = max(results_summary, key=lambda x: x.get('最终净值', 0))
        worst = min(results_summary, key=lambda x: x.get('最终净值', 0))
        
        print(f"\n{'='*90}")
        print(f"最佳配置: {best['持仓数']}只持仓 (每只{best['资金比例']}资金)")
        print(f"  最终净值: {best.get('最终净值', 0):,.2f}元")
        print(f"  收益率: {best.get('收益率%', 0):.2f}%")
        print(f"  买入次数: {best.get('买入次数', 0)}笔")
        
        print(f"\n最差配置: {worst['持仓数']}只持仓 (每只{worst['资金比例']}资金)")
        print(f"  最终净值: {worst.get('最终净值', 0):,.2f}元")
        print(f"  收益率: {worst.get('收益率%', 0):.2f}%")
        print(f"  买入次数: {worst.get('买入次数', 0)}笔")
        
        print(f"\n收益差距: {best.get('最终净值', 0) - worst.get('最终净值', 0):,.2f}元 "
              f"({best.get('收益率%', 0) - worst.get('收益率%', 0):.2f}%)")
        print(f"{'='*90}\n")
    
    # 保存结果
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_file = f"position_allocation_test_{timestamp}.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results_summary, f, ensure_ascii=False, indent=2)
    print(f"详细结果已保存至: {output_file}")

if __name__ == '__main__':
    main()
