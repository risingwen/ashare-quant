"""绘制回测净值曲线"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False

# 读取最新的两个策略的portfolio数据
portfolio_dir = Path('data/backtest/portfolio')

# 新策略（修改后：开盘卖出+T-2日人气）
new_strategy = 'hot_rank_top20_newentry_v1.0.0_a0c1e2bc_20260105_232212_portfolio.parquet'
# 旧策略（修改前：收盘卖出）
old_strategy = 'hot_rank_top20_newentry_v1.0.0_a0c1e2bc_20260105_231314_portfolio.parquet'

df_new = pd.read_parquet(portfolio_dir / new_strategy)
df_old = pd.read_parquet(portfolio_dir / old_strategy)

# 创建图表
fig, axes = plt.subplots(2, 1, figsize=(14, 10))

# === 图1：净值曲线对比 ===
ax1 = axes[0]
ax1.plot(df_new['date'], df_new['nav'], label='修改后：人气跌出前50开盘卖', 
         linewidth=2, color='#E74C3C', alpha=0.9)
ax1.plot(df_old['date'], df_old['nav'], label='修改前：收盘卖出', 
         linewidth=2, color='#3498DB', alpha=0.7)

# 添加基准线（初始资金）
ax1.axhline(y=100000, color='gray', linestyle='--', linewidth=1, alpha=0.5, label='初始资金')

ax1.set_title('策略净值曲线对比', fontsize=16, fontweight='bold', pad=20)
ax1.set_xlabel('日期', fontsize=12)
ax1.set_ylabel('净值（元）', fontsize=12)
ax1.legend(fontsize=11, loc='upper left')
ax1.grid(True, alpha=0.3)
ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{x/10000:.1f}万'))

# 添加最终净值标注
final_new = df_new['nav'].iloc[-1]
final_old = df_old['nav'].iloc[-1]
ax1.text(df_new['date'].iloc[-1], final_new, f'{final_new/10000:.1f}万', 
         fontsize=10, ha='left', va='bottom', color='#E74C3C')
ax1.text(df_old['date'].iloc[-1], final_old, f'{final_old/10000:.1f}万', 
         fontsize=10, ha='left', va='top', color='#3498DB')

# === 图2：收益率曲线对比 ===
ax2 = axes[1]

# 计算累计收益率
df_new['return_pct'] = (df_new['nav'] / 100000 - 1) * 100
df_old['return_pct'] = (df_old['nav'] / 100000 - 1) * 100

ax2.plot(df_new['date'], df_new['return_pct'], label='修改后：人气跌出前50开盘卖', 
         linewidth=2, color='#E74C3C', alpha=0.9)
ax2.plot(df_old['date'], df_old['return_pct'], label='修改前：收盘卖出', 
         linewidth=2, color='#3498DB', alpha=0.7)

# 添加0%基准线
ax2.axhline(y=0, color='gray', linestyle='--', linewidth=1, alpha=0.5)

ax2.set_title('策略累计收益率对比', fontsize=16, fontweight='bold', pad=20)
ax2.set_xlabel('日期', fontsize=12)
ax2.set_ylabel('累计收益率（%）', fontsize=12)
ax2.legend(fontsize=11, loc='upper left')
ax2.grid(True, alpha=0.3)

# 添加最终收益率标注
final_return_new = df_new['return_pct'].iloc[-1]
final_return_old = df_old['return_pct'].iloc[-1]
ax2.text(df_new['date'].iloc[-1], final_return_new, f'{final_return_new:.1f}%', 
         fontsize=10, ha='left', va='bottom', color='#E74C3C')
ax2.text(df_old['date'].iloc[-1], final_return_old, f'{final_return_old:.1f}%', 
         fontsize=10, ha='left', va='top', color='#3498DB')

# 格式化x轴日期
for ax in axes:
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')

plt.tight_layout()

# 保存图片
output_file = 'reports/backtest_curves_comparison.png'
plt.savefig(output_file, dpi=300, bbox_inches='tight')
print(f"\n✅ 曲线图已保存: {output_file}")

# 显示图表
plt.show()

# 打印关键指标对比
print("\n" + "="*60)
print("📊 关键指标对比")
print("="*60)

print(f"\n【修改后：人气跌出前50开盘卖】")
print(f"  初始净值: {df_new['nav'].iloc[0]:,.2f}")
print(f"  最终净值: {df_new['nav'].iloc[-1]:,.2f}")
print(f"  累计收益率: {final_return_new:.2f}%")
print(f"  最大净值: {df_new['nav'].max():,.2f}")
print(f"  最小净值: {df_new['nav'].min():,.2f}")

# 计算最大回撤
df_new['peak'] = df_new['nav'].cummax()
df_new['drawdown'] = (df_new['nav'] / df_new['peak'] - 1) * 100
max_dd_new = df_new['drawdown'].min()
print(f"  最大回撤: {max_dd_new:.2f}%")

print(f"\n【修改前：收盘卖出】")
print(f"  初始净值: {df_old['nav'].iloc[0]:,.2f}")
print(f"  最终净值: {df_old['nav'].iloc[-1]:,.2f}")
print(f"  累计收益率: {final_return_old:.2f}%")
print(f"  最大净值: {df_old['nav'].max():,.2f}")
print(f"  最小净值: {df_old['nav'].min():,.2f}")

# 计算最大回撤
df_old['peak'] = df_old['nav'].cummax()
df_old['drawdown'] = (df_old['nav'] / df_old['peak'] - 1) * 100
max_dd_old = df_old['drawdown'].min()
print(f"  最大回撤: {max_dd_old:.2f}%")

print(f"\n【改善幅度】")
print(f"  收益率提升: {final_return_new - final_return_old:.2f}个百分点")
print(f"  最大回撤改善: {max_dd_new - max_dd_old:.2f}个百分点")
print("="*60)
