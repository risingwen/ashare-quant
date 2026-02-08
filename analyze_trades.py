import pandas as pd
import numpy as np

# 读取最新交易记录（前100的）
trades = pd.read_parquet('data/backtest/trades/hot_rank_drop7_smart_exit_v1.1.0_2fadcb79_20260103_005430_trades.parquet')

print('=' * 80)
print('交易记录分析 - 从成交量和人气角度')
print('=' * 80)

# 基本统计
print(f'\n【基本信息】')
print(f'总交易笔数: {len(trades)}')
print(f'盈利笔数: {(trades["net_pnl_pct"] > 0).sum()}')
print(f'亏损笔数: {(trades["net_pnl_pct"] < 0).sum()}')
print(f'胜率: {(trades["net_pnl_pct"] > 0).sum() / len(trades) * 100:.1f}%')

# 按人气排名分组分析
print(f'\n【人气排名分析】')
trades['rank_bucket'] = pd.cut(trades['rank_t1'], 
                                bins=[0, 20, 50, 100, 999],
                                labels=['1-20名', '21-50名', '51-100名', '100名外'])

rank_analysis = trades.groupby('rank_bucket', observed=True).agg({
    'net_pnl_pct': ['count', 'mean', lambda x: (x > 0).sum() / len(x) * 100],
    'amount_t1': 'mean'
}).round(4)
rank_analysis.columns = ['交易笔数', '平均收益率', '胜率%', '平均成交额(亿)']
rank_analysis['平均收益率'] = rank_analysis['平均收益率'] * 100
rank_analysis['平均成交额(亿)'] = rank_analysis['平均成交额(亿)'].round(2)
print(rank_analysis.to_string())

# 按成交额分组分析
print(f'\n【成交额分析】（单位：亿元）')
trades['amount_bucket'] = pd.cut(trades['amount_t1'], 
                                  bins=[0, 30, 60, 100, np.inf],
                                  labels=['<30亿', '30-60亿', '60-100亿', '>100亿'])

amount_analysis = trades.groupby('amount_bucket', observed=True).agg({
    'net_pnl_pct': ['count', 'mean', lambda x: (x > 0).sum() / len(x) * 100],
    'rank_t1': 'mean'
}).round(4)
amount_analysis.columns = ['交易笔数', '平均收益率', '胜率%', '平均人气排名']
amount_analysis['平均收益率'] = amount_analysis['平均收益率'] * 100
print(amount_analysis.to_string())

# 盈亏前10名详细分析
print(f'\n【最赚钱的10笔交易】')
top_winners = trades.nlargest(10, 'net_pnl_pct')[['code', 'name', 'entry_date', 'net_pnl_pct', 'rank_t1', 'amount_t1']]
top_winners['net_pnl_pct'] = (top_winners['net_pnl_pct'] * 100).round(2)
top_winners['amount_t1'] = top_winners['amount_t1'].round(2)
top_winners.columns = ['代码', '名称', '买入日期', '收益率%', 'T-1排名', 'T-1成交额(亿)']
print(top_winners.to_string(index=False))

print(f'\n【最亏钱的10笔交易】')
top_losers = trades.nsmallest(10, 'net_pnl_pct')[['code', 'name', 'entry_date', 'net_pnl_pct', 'rank_t1', 'amount_t1']]
top_losers['net_pnl_pct'] = (top_losers['net_pnl_pct'] * 100).round(2)
top_losers['amount_t1'] = top_losers['amount_t1'].round(2)
top_losers.columns = ['代码', '名称', '买入日期', '收益率%', 'T-1排名', 'T-1成交额(亿)']
print(top_losers.to_string(index=False))

# 人气排名与成交额的交叉分析
print(f'\n【人气排名 × 成交额 交叉分析】')
cross_analysis = trades.groupby(['rank_bucket', 'amount_bucket'], observed=True).agg({
    'net_pnl_pct': ['count', 'mean', lambda x: (x > 0).sum() / len(x) * 100 if len(x) > 0 else 0]
}).round(4)
cross_analysis.columns = ['笔数', '平均收益率', '胜率%']
cross_analysis['平均收益率'] = cross_analysis['平均收益率'] * 100
print(cross_analysis.to_string())

# 关键发现
print(f'\n【关键发现】')
# 1. 人气极热门 vs 一般热门
hot_top20 = trades[trades['rank_t1'] <= 20]
hot_other = trades[trades['rank_t1'] > 20]
print(f'1. 人气1-20名: 胜率{(hot_top20["net_pnl_pct"] > 0).sum() / len(hot_top20) * 100:.1f}%, 平均收益{hot_top20["net_pnl_pct"].mean() * 100:.2f}%')
print(f'   人气21+名: 胜率{(hot_other["net_pnl_pct"] > 0).sum() / len(hot_other) * 100:.1f}%, 平均收益{hot_other["net_pnl_pct"].mean() * 100:.2f}%')

# 2. 成交额
high_amount = trades[trades['amount_t1'] >= 60]
low_amount = trades[trades['amount_t1'] < 60]
print(f'\n2. 成交额≥60亿: 胜率{(high_amount["net_pnl_pct"] > 0).sum() / len(high_amount) * 100:.1f}%, 平均收益{high_amount["net_pnl_pct"].mean() * 100:.2f}%')
print(f'   成交额<60亿: 胜率{(low_amount["net_pnl_pct"] > 0).sum() / len(low_amount) * 100:.1f}%, 平均收益{low_amount["net_pnl_pct"].mean() * 100:.2f}%')

# 3. 黄金组合
golden = trades[(trades['rank_t1'] <= 30) & (trades['amount_t1'] >= 50)]
if len(golden) > 0:
    print(f'\n3. 黄金组合（人气≤30 & 成交额≥50亿）:')
    print(f'   笔数: {len(golden)}, 胜率{(golden["net_pnl_pct"] > 0).sum() / len(golden) * 100:.1f}%, 平均收益{golden["net_pnl_pct"].mean() * 100:.2f}%')
