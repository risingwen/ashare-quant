"""完整分析2025-12-22买入逻辑"""

import pandas as pd

# 读取数据
features = pd.read_parquet('data/processed/features/daily_features_v1.parquet')
trades = pd.read_parquet('data/backtest/trades/hot_rank_top20_newentry_v1.0.0_0ab7bc01_20260105_235746_trades.parquet')

# T-1日 = 2025-12-19 (周五)
# T日 = 2025-12-22 (周一)
date_t1 = '2025-12-19'
date_t = '2025-12-22'

# 获取T-1日人气前10
df_t1 = features[features['date'] == date_t1].copy()
df_t1_top10 = df_t1[df_t1['is_tradable'] == True]
df_t1_top10 = df_t1_top10[df_t1_top10['hot_rank'] <= 10].copy()
df_t1_top10 = df_t1_top10.sort_values('hot_rank')

print("=" * 120)
print(f"📅 T-1日 ({date_t1}) 人气前10股票")
print("=" * 120)
print(df_t1_top10[['code', 'name', 'hot_rank', 'close', 'is_st']].to_string(index=False))

# 获取这些股票在T日的数据
df_t = features[features['date'] == date_t].copy()
codes_t1 = df_t1_top10['code'].tolist()
df_t_selected = df_t[df_t['code'].isin(codes_t1)].copy()

# 合并数据
result = df_t1_top10[['code', 'name', 'hot_rank', 'close', 'is_st']].merge(
    df_t_selected[['code', 'open', 'hot_rank', 'is_tradable']], 
    on='code', 
    suffixes=('_t1', '_t')
)

# 计算开盘涨跌幅
result['open_change_pct'] = (result['open'] - result['close']) / result['close']

# 按开盘涨跌幅排序
result = result.sort_values('open_change_pct')

print(f"\n{'=' * 120}")
print(f"💰 T日 ({date_t}) 这10只股票的开盘情况 (按开盘涨跌幅排序)")
print("=" * 120)

# 检查每只是否被买入
for idx, row in result.iterrows():
    bought = trades[(trades['code']==row['code']) & (trades['entry_date']==date_t)]
    status = "✅ 买入" if len(bought) > 0 else "❌ 跳过"
    
    # 计算可买股数
    per_trade_cash = 100000 / 3
    buy_exec = row['open'] * 1.0005
    shares = int(per_trade_cash / buy_exec / 100) * 100
    
    # 分析原因
    reason = ""
    if len(bought) == 0:
        if row['is_st']:
            reason = "ST股票"
        elif shares == 0:
            reason = f"价格太高"
        elif not row['is_tradable']:
            reason = "不可交易"
        else:
            reason = "资金限制或其他"
    
    print(f"{row['code']:6s} {row['name']:8s} | "
          f"T-1排名:{row.hot_rank_t1:2.0f} | "
          f"T排名:{row.hot_rank_t:2.0f} | "
          f"开盘涨跌:{row.open_change_pct:+7.2%} | "
          f"开盘:{row['open']:7.2f} | "
          f"可买:{shares:4d}股 | "
          f"{status:8s} | {reason}")

print(f"\n{'=' * 120}")
print("🎯 另外7只股票 (不在T-1日前10):")
print("=" * 120)

# T日人气前10中，不在T-1前10的股票
df_t_top10 = df_t[df_t['is_tradable'] == True]
df_t_top10 = df_t_top10[df_t_top10['hot_rank'] <= 10].copy()
other_codes = set(df_t_top10['code'].tolist()) - set(codes_t1)

df_other = df_t_top10[df_t_top10['code'].isin(other_codes)].copy()
df_other['open_change_pct'] = (df_other['open'] - df_other['close_prev']) / df_other['close_prev']
df_other = df_other.sort_values('open_change_pct')

for idx, row in df_other.iterrows():
    print(f"{row['code']:6s} {row['name']:8s} | "
          f"T排名:{row.hot_rank:2.0f} | "
          f"开盘涨跌:{row.open_change_pct:+7.2%} | "
          f"开盘:{row['open']:7.2f} | "
          f"原因: T-1日排名>{row.hot_rank}，不在前10")

print("\n" + "=" * 120)
