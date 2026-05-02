#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
回测报告生成器

功能：
1. 读取交易明细和组合净值数据
2. 计算策略指标（收益率、夏普比、最大回撤等）
3. 生成Markdown报告
4. 生成可视化图表（净值曲线、收益分布、持仓分析等）

使用示例：
    python scripts/generate_report.py \\
        --trades data/backtest/trades/xxx_trades.parquet \\
        --portfolio data/backtest/portfolio/xxx_portfolio.parquet \\
        --output data/backtest/reports/report_20260102.md
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib
matplotlib.use('Agg')  # 非交互式后端
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# 设置中文字体（Windows）
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PerformanceAnalyzer:
    """策略表现分析器"""
    
    def __init__(self, trades_df: pd.DataFrame, portfolio_df: pd.DataFrame):
        """初始化分析器"""
        self.trades = trades_df
        self.portfolio = portfolio_df
        
        # 转换日期格式
        if not pd.api.types.is_datetime64_any_dtype(self.trades['entry_date']):
            self.trades['entry_date'] = pd.to_datetime(self.trades['entry_date'])
        if not pd.api.types.is_datetime64_any_dtype(self.trades['exit_date']):
            self.trades['exit_date'] = pd.to_datetime(self.trades['exit_date'])
        if not pd.api.types.is_datetime64_any_dtype(self.portfolio['date']):
            self.portfolio['date'] = pd.to_datetime(self.portfolio['date'])
        
        self.metrics = {}
        
    def calculate_metrics(self) -> Dict:
        """计算所有指标"""
        logger.info("计算策略指标...")
        
        # 基础统计
        self.metrics['total_trades'] = len(self.trades)
        self.metrics['winning_trades'] = (self.trades['net_pnl'] > 0).sum()
        self.metrics['losing_trades'] = (self.trades['net_pnl'] < 0).sum()
        self.metrics['win_rate'] = self.metrics['winning_trades'] / self.metrics['total_trades']
        
        # 收益统计
        self.metrics['total_pnl'] = self.trades['net_pnl'].sum()
        self.metrics['avg_pnl'] = self.trades['net_pnl'].mean()
        self.metrics['avg_pnl_pct'] = self.trades['net_pnl_pct'].mean()
        self.metrics['median_pnl_pct'] = self.trades['net_pnl_pct'].median()
        self.metrics['max_win'] = self.trades['net_pnl'].max()
        self.metrics['max_loss'] = self.trades['net_pnl'].min()
        self.metrics['max_win_pct'] = self.trades['net_pnl_pct'].max()
        self.metrics['max_loss_pct'] = self.trades['net_pnl_pct'].min()
        
        # 持仓统计
        self.metrics['avg_hold_days'] = self.trades['hold_days'].mean()
        self.metrics['median_hold_days'] = self.trades['hold_days'].median()
        self.metrics['max_hold_days'] = self.trades['hold_days'].max()
        
        # 净值统计
        self.metrics['init_nav'] = self.portfolio['nav'].iloc[0]
        self.metrics['final_nav'] = self.portfolio['nav'].iloc[-1]
        self.metrics['max_nav'] = self.portfolio['nav'].max()
        self.metrics['min_nav'] = self.portfolio['nav'].min()
        
        # 收益率
        self.metrics['total_return'] = (self.metrics['final_nav'] / self.metrics['init_nav']) - 1
        
        # 最大回撤
        running_max = self.portfolio['nav'].cummax()
        drawdown = (self.portfolio['nav'] / running_max) - 1
        self.metrics['max_drawdown'] = drawdown.min()
        
        # 夏普比率（假设无风险利率=0，年化252个交易日）
        self.portfolio['daily_return'] = self.portfolio['nav'].pct_change()
        daily_returns = self.portfolio['daily_return'].dropna()
        if len(daily_returns) > 0 and daily_returns.std() > 0:
            self.metrics['sharpe_ratio'] = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)
        else:
            self.metrics['sharpe_ratio'] = 0
        
        # 卖出原因统计
        exit_reason_counts = self.trades['exit_reason'].value_counts()
        self.metrics['exit_reasons'] = exit_reason_counts.to_dict()
        
        logger.info(f"指标计算完成: 总交易{self.metrics['total_trades']}笔, "
                   f"胜率{self.metrics['win_rate']:.2%}, "
                   f"收益率{self.metrics['total_return']:.2%}")
        
        return self.metrics
    
    def generate_markdown_report(self, output_path: str):
        """生成Markdown报告"""
        logger.info(f"生成Markdown报告: {output_path}")
        
        report_lines = []
        
        # 标题
        report_lines.append(f"# 回测报告\n")
        report_lines.append(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        report_lines.append(f"---\n")
        
        # 策略概览
        report_lines.append(f"## 策略概览\n")
        report_lines.append(f"- 回测期间：{self.portfolio['date'].iloc[0].date()} 至 "
                          f"{self.portfolio['date'].iloc[-1].date()}\n")
        report_lines.append(f"- 交易天数：{len(self.portfolio)} 天\n")
        report_lines.append(f"- 总交易笔数：{self.metrics['total_trades']} 笔\n")
        report_lines.append(f"\n")
        
        # 收益表现
        report_lines.append(f"## 收益表现\n")
        report_lines.append(f"| 指标 | 数值 |\n")
        report_lines.append(f"|------|------|\n")
        report_lines.append(f"| 初始资金 | {self.metrics['init_nav']:,.2f} |\n")
        report_lines.append(f"| 最终净值 | {self.metrics['final_nav']:,.2f} |\n")
        report_lines.append(f"| **总收益率** | **{self.metrics['total_return']:.2%}** |\n")
        report_lines.append(f"| 最高净值 | {self.metrics['max_nav']:,.2f} |\n")
        report_lines.append(f"| 最低净值 | {self.metrics['min_nav']:,.2f} |\n")
        report_lines.append(f"| **最大回撤** | **{self.metrics['max_drawdown']:.2%}** |\n")
        report_lines.append(f"| **夏普比率** | **{self.metrics['sharpe_ratio']:.2f}** |\n")
        report_lines.append(f"\n")
        
        # 交易统计
        report_lines.append(f"## 交易统计\n")
        report_lines.append(f"| 指标 | 数值 |\n")
        report_lines.append(f"|------|------|\n")
        report_lines.append(f"| 盈利笔数 | {self.metrics['winning_trades']} |\n")
        report_lines.append(f"| 亏损笔数 | {self.metrics['losing_trades']} |\n")
        report_lines.append(f"| **胜率** | **{self.metrics['win_rate']:.2%}** |\n")
        report_lines.append(f"| 平均收益率 | {self.metrics['avg_pnl_pct']:.2%} |\n")
        report_lines.append(f"| 中位数收益率 | {self.metrics['median_pnl_pct']:.2%} |\n")
        report_lines.append(f"| 最大单笔盈利 | {self.metrics['max_win']:,.2f} ({self.metrics['max_win_pct']:.2%}) |\n")
        report_lines.append(f"| 最大单笔亏损 | {self.metrics['max_loss']:,.2f} ({self.metrics['max_loss_pct']:.2%}) |\n")
        report_lines.append(f"\n")
        
        # 持仓分析
        report_lines.append(f"## 持仓分析\n")
        report_lines.append(f"| 指标 | 数值 |\n")
        report_lines.append(f"|------|------|\n")
        report_lines.append(f"| 平均持仓天数 | {self.metrics['avg_hold_days']:.1f} 天 |\n")
        report_lines.append(f"| 中位数持仓天数 | {self.metrics['median_hold_days']:.0f} 天 |\n")
        report_lines.append(f"| 最长持仓天数 | {self.metrics['max_hold_days']} 天 |\n")
        report_lines.append(f"\n")
        
        # 卖出原因
        report_lines.append(f"## 卖出原因分析\n")
        report_lines.append(f"| 原因 | 笔数 | 占比 |\n")
        report_lines.append(f"|------|------|------|\n")
        for reason, count in self.metrics['exit_reasons'].items():
            pct = count / self.metrics['total_trades']
            report_lines.append(f"| {reason} | {count} | {pct:.2%} |\n")
        report_lines.append(f"\n")
        
        # 收益分布
        report_lines.append(f"## 收益分布\n")
        pnl_pct_desc = self.trades['net_pnl_pct'].describe()
        report_lines.append(f"| 统计量 | 数值 |\n")
        report_lines.append(f"|--------|------|\n")
        report_lines.append(f"| 最小值 | {pnl_pct_desc['min']:.2%} |\n")
        report_lines.append(f"| 25分位 | {pnl_pct_desc['25%']:.2%} |\n")
        report_lines.append(f"| 50分位（中位数） | {pnl_pct_desc['50%']:.2%} |\n")
        report_lines.append(f"| 75分位 | {pnl_pct_desc['75%']:.2%} |\n")
        report_lines.append(f"| 最大值 | {pnl_pct_desc['max']:.2%} |\n")
        report_lines.append(f"| 标准差 | {pnl_pct_desc['std']:.2%} |\n")
        report_lines.append(f"\n")
        
        # 写入文件
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.writelines(report_lines)
        
        logger.info(f"报告已保存: {output_path}")
    
    def generate_charts(self, output_dir: str):
        """生成图表"""
        logger.info(f"生成图表...")
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. 净值曲线
        self._plot_nav_curve(output_dir / 'nav_curve.png')
        
        # 2. 收益分布
        self._plot_pnl_distribution(output_dir / 'pnl_distribution.png')
        
        # 3. 持仓天数分布
        self._plot_hold_days(output_dir / 'hold_days.png')
        
        # 4. 月度收益
        self._plot_monthly_returns(output_dir / 'monthly_returns.png')
        
        logger.info(f"图表已保存: {output_dir}")
    
    def _plot_nav_curve(self, output_path: Path):
        """绘制净值曲线"""
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
        
        # 净值曲线
        ax1.plot(self.portfolio['date'], self.portfolio['nav'], 
                linewidth=1.5, color='#2E86AB', label='净值')
        ax1.axhline(y=self.metrics['init_nav'], color='gray', 
                   linestyle='--', linewidth=0.8, label='初始净值')
        ax1.fill_between(self.portfolio['date'], self.portfolio['nav'], 
                         self.metrics['init_nav'], 
                         where=(self.portfolio['nav'] >= self.metrics['init_nav']),
                         alpha=0.3, color='green', interpolate=True)
        ax1.fill_between(self.portfolio['date'], self.portfolio['nav'], 
                         self.metrics['init_nav'],
                         where=(self.portfolio['nav'] < self.metrics['init_nav']),
                         alpha=0.3, color='red', interpolate=True)
        ax1.set_ylabel('净值', fontsize=12)
        ax1.set_title(f'净值曲线 (收益率: {self.metrics["total_return"]:.2%})', 
                     fontsize=14, fontweight='bold')
        ax1.legend(loc='best')
        ax1.grid(True, alpha=0.3)
        
        # 回撤曲线
        running_max = self.portfolio['nav'].cummax()
        drawdown = (self.portfolio['nav'] / running_max) - 1
        ax2.fill_between(self.portfolio['date'], drawdown * 100, 0, 
                         color='#A23B72', alpha=0.6)
        ax2.set_ylabel('回撤 (%)', fontsize=12)
        ax2.set_xlabel('日期', fontsize=12)
        ax2.set_title(f'回撤曲线 (最大回撤: {self.metrics["max_drawdown"]:.2%})', 
                     fontsize=14, fontweight='bold')
        ax2.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()
        
    def _plot_pnl_distribution(self, output_path: Path):
        """绘制收益分布"""
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
        
        # 直方图
        pnl_pct = self.trades['net_pnl_pct'] * 100
        ax1.hist(pnl_pct, bins=50, color='#2E86AB', alpha=0.7, edgecolor='black')
        ax1.axvline(x=pnl_pct.mean(), color='red', linestyle='--', 
                   linewidth=2, label=f'均值: {pnl_pct.mean():.2f}%')
        ax1.axvline(x=pnl_pct.median(), color='orange', linestyle='--', 
                   linewidth=2, label=f'中位数: {pnl_pct.median():.2f}%')
        ax1.set_xlabel('收益率 (%)', fontsize=12)
        ax1.set_ylabel('交易笔数', fontsize=12)
        ax1.set_title('收益率分布', fontsize=14, fontweight='bold')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # 箱线图
        box_data = [
            pnl_pct[self.trades['net_pnl'] > 0],
            pnl_pct[self.trades['net_pnl'] < 0]
        ]
        bp = ax2.boxplot(box_data, labels=['盈利', '亏损'], 
                        patch_artist=True, widths=0.6)
        bp['boxes'][0].set_facecolor('#90EE90')
        bp['boxes'][1].set_facecolor('#FFB6C1')
        ax2.set_ylabel('收益率 (%)', fontsize=12)
        ax2.set_title(f'盈亏分布 (胜率: {self.metrics["win_rate"]:.2%})', 
                     fontsize=14, fontweight='bold')
        ax2.grid(True, alpha=0.3, axis='y')
        
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()
    
    def _plot_hold_days(self, output_path: Path):
        """绘制持仓天数分布"""
        fig, ax = plt.subplots(figsize=(10, 6))
        
        hold_days_counts = self.trades['hold_days'].value_counts().sort_index()
        ax.bar(hold_days_counts.index, hold_days_counts.values, 
              color='#2E86AB', alpha=0.7, edgecolor='black')
        ax.axvline(x=self.metrics['avg_hold_days'], color='red', 
                  linestyle='--', linewidth=2, 
                  label=f'平均: {self.metrics["avg_hold_days"]:.1f}天')
        ax.set_xlabel('持仓天数', fontsize=12)
        ax.set_ylabel('交易笔数', fontsize=12)
        ax.set_title('持仓天数分布', fontsize=14, fontweight='bold')
        ax.legend()
        ax.grid(True, alpha=0.3, axis='y')
        
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()
    
    def _plot_monthly_returns(self, output_path: Path):
        """绘制月度收益"""
        # 计算月度收益
        portfolio_monthly = self.portfolio.copy()
        portfolio_monthly['year_month'] = portfolio_monthly['date'].dt.to_period('M')
        
        monthly_stats = []
        for ym, group in portfolio_monthly.groupby('year_month'):
            start_nav = group['nav'].iloc[0]
            end_nav = group['nav'].iloc[-1]
            monthly_return = (end_nav / start_nav) - 1
            monthly_stats.append({
                'year_month': str(ym),
                'return': monthly_return * 100
            })
        
        monthly_df = pd.DataFrame(monthly_stats)
        
        fig, ax = plt.subplots(figsize=(14, 6))
        colors = ['green' if r >= 0 else 'red' for r in monthly_df['return']]
        ax.bar(range(len(monthly_df)), monthly_df['return'], 
              color=colors, alpha=0.7, edgecolor='black')
        ax.axhline(y=0, color='black', linewidth=0.8)
        ax.set_xticks(range(len(monthly_df)))
        ax.set_xticklabels(monthly_df['year_month'], rotation=45, ha='right')
        ax.set_ylabel('收益率 (%)', fontsize=12)
        ax.set_title('月度收益率', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3, axis='y')
        
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()


def main():
    parser = argparse.ArgumentParser(
        description='回测报告生成器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        '--trades',
        required=True,
        help='交易明细parquet文件路径'
    )
    parser.add_argument(
        '--portfolio',
        required=True,
        help='组合净值parquet文件路径'
    )
    parser.add_argument(
        '--output',
        help='输出报告路径（Markdown）'
    )
    parser.add_argument(
        '--charts-dir',
        help='图表输出目录'
    )
    
    args = parser.parse_args()
    
    # 加载数据
    logger.info(f"加载交易数据: {args.trades}")
    trades_df = pd.read_parquet(args.trades)
    logger.info(f"加载完成: {len(trades_df)}笔交易")
    
    logger.info(f"加载组合数据: {args.portfolio}")
    portfolio_df = pd.read_parquet(args.portfolio)
    logger.info(f"加载完成: {len(portfolio_df)}个交易日")
    
    # 初始化分析器
    analyzer = PerformanceAnalyzer(trades_df, portfolio_df)
    
    # 计算指标
    metrics = analyzer.calculate_metrics()
    
    # 生成报告
    if args.output:
        analyzer.generate_markdown_report(args.output)
    else:
        # 默认路径
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = PROJECT_ROOT / 'data' / 'backtest' / 'reports' / f'report_{timestamp}.md'
        analyzer.generate_markdown_report(output_path)
    
    # 生成图表
    if args.charts_dir:
        analyzer.generate_charts(args.charts_dir)
    else:
        # 默认路径
        charts_dir = PROJECT_ROOT / 'data' / 'backtest' / 'reports' / 'charts'
        analyzer.generate_charts(charts_dir)


if __name__ == '__main__':
    main()
