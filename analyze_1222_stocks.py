"""分析2025-12-22人气前10股票为何只买了3只"""

import pandas as pd

# 读取特征数据
features = pd.read_parquet('data/processed/features/daily_features_v1.parquet')

# 读取交易数据
trades = pd.read_parquet('data/backtest/trades/hot_rank_top20_newentry_v1.0.0_0ab7bc01_20260105_235746_trades.parquet')

date_t = '2025-12-22'

# 获取T日数据
df_t = features[features['date'] == date_t].copy()

# 筛选人气前10
df_top10 = df_t[df_t['is_tradable'] == True]
df_top10 = df_top10[df_top10['hot_rank'] <= 10].copy()

# 计算开盘涨跌幅
df_top10['open_change_pct'] = (df_top10['open'] - df_top10['close_prev']) / df_top10['close_prev']

# 按开盘涨跌幅排序
df_top10 = df_top10.sort_values('open_change_pct').reset_index(drop=True)

print("=" * 120)
print(f"📊 2025-12-22 (T日) 人气前10股票完整分析")
print("=" * 120)

print(f"\n人气前10股票 (按开盘涨跌幅从小到大排序):")
print("-" * 120)

for idx, row in df_top10.iterrows():
    # 检查是否被买入
    bought = trades[(trades['code']==row['code']) & (trades['entry_date']==date_t)]
    status = "✅ 已买入" if len(bought) > 0 else "❌ 未买入"
    
    # 计算买入所需资金
    initial_cash = 100000
    per_trade_cash = initial_cash / 3
    buy_exec = row['open'] * 1.0005  # 滑点
    shares = int(per_trade_cash / buy_exec / 100) * 100
    cost = shares * buy_exec if shares > 0 else 0
    
    print(f"{idx+1}. {row['code']:6s} {row['name']:8s} | "
          f"人气:{row['hot_rank']:2.0f} | "
          f"开盘涨跌:{row['open_change_pct']:+7.2%} | "
          f"开盘:{row['open']:7.2f} | "
          f"ST:{str(row['is_st']):5s} | "
          f"可买股数:{shares:5d} | "
          f"成本:{cost:8.0f} | "
          f"{status}")

# 分析未买入原因
print("\n" + "=" * 120)
print("❌ 未买入的7只股票分析:")
print("-" * 120)

unbought = df_top10.iloc[3:].copy()  # 前3只已买入，分析后7只

reasons = []
for idx, row in unbought.iterrows():
    per_trade_cash = 100000 / 3
    buy_exec = row['open'] * 1.0005
    shares = int(per_trade_cash / buy_exec / 100) * 100
    
    reason = []
    if row['is_st']:
        reason.append("ST股票")
    if shares == 0:
        reason.append(f"价格太高(开盘{row['open']:.2f}元，买不起100股)")
    
    if not reason:
        reason.append("未知原因(可能是T-1日排名不在前10)")
    
    reasons.append({
        'code': row['code'],
        'name': row['name'],
        'hot_rank': row['hot_rank'],
        'open_change_pct': row['open_change_pct'],
        'open': row['open'],
        'reason': '; '.join(reason)
    })

for i, r in enumerate(reasons, 1):
    print(f"{i}. {r['code']:6s} {r['name']:8s} | "
          f"开盘涨跌:{r['open_change_pct']:+7.2%} | "
          f"原因: {r['reason']}")

print("\n" + "=" * 120)
print("✅ 实际买入的3只:")
print("-" * 120)

bought_trades = trades[trades['entry_date'] == date_t].sort_values('open_change_pct')
for idx, row in bought_trades.iterrows():
    print(f"  {row['code']:6s} {row['name']:8s} | "
          f"T-1排名:{row.rank_t1:2.0f} | "
          f"T排名:{row.rank_t:2.0f} | "
          f"开盘涨跌:{row.open_change_pct:+7.2%} | "
          f"收益:{row.net_pnl_pct:+7.2%}")

print("\n" + "=" * 120)
print("🎯 结论:")
print("-" * 120)
print("策略逻辑: 在T日开盘时，筛选人气前10（看T日实时排名），买入开盘跌幅最大的3只")
print("但你提供的数据显示 rank_t1=10, rank_t=8，说明策略实际是：")
print("  → 在T-1日收盘后看人气前10，次日T日开盘买入开盘跌幅最大的3只")
print("\n如果T-1日人气前10与T日人气前10完全不同，那就解释了为什么只有部分股票被买入。")
print("=" * 120)
