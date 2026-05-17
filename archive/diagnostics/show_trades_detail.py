import pandas as pd
pd.set_option('display.max_columns', None)
pd.set_option('display.width', 300)

df = pd.read_parquet('data/backtest/trades/hot_rank_drop7_smart_exit_v1.1.0_4cc96acd_20260103_002945_trades.parquet')

print('=== 交易记录（前15笔）- T, T-1, T-2 人气和成交额 ===\n')
result = df[[
    'code', 'name', 'entry_date', 
    'rank_t', 'rank_t1', 'rank_t2',
    'amount_t', 'amount_t1', 'amount_t2',
    'net_pnl_pct'
]].head(15).copy()

# 格式化
result['amount_t_display'] = result['amount_t']
result['amount_t1_display'] = result['amount_t1']
result['amount_t2_display'] = result['amount_t2']
result['net_pnl_pct'] = result['net_pnl_pct'] * 100

result = result[[
    'code', 'name', 'entry_date',
    'rank_t', 'rank_t1', 'rank_t2',
    'amount_t_display', 'amount_t1_display', 'amount_t2_display',
    'net_pnl_pct'
]]

result.columns = ['代码', '名称', '买入日期', 
                  '人气T', '人气T-1', '人气T-2',
                  '成交额T(亿)', '成交额T-1(亿)', '成交额T-2(亿)',
                  '收益率(%)']

print(result.to_string(index=False, float_format='%.2f'))

print('\n=== 统计信息 ===')
print(f'总交易笔数: {len(df)}')
print(f'T-2数据缺失: {df["rank_t2"].isna().sum()} 笔')
print(f'平均人气排名: T={df["rank_t"].mean():.1f}, T-1={df["rank_t1"].mean():.1f}, T-2={df["rank_t2"].mean():.1f}')
print(f'平均成交额(亿): T={df["amount_t"].mean():.2f}, T-1={df["amount_t1"].mean():.2f}, T-2={df["amount_t2"].mean():.2f}')
