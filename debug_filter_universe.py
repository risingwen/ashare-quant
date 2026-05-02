"""
验证filter_universe的输出
"""
import pandas as pd
from pathlib import Path

# 加载数据
PROJECT_ROOT = Path(__file__).parent
df = pd.read_parquet(PROJECT_ROOT / 'data' / 'processed' / 'features' / 'daily_features_v1.parquet')

# 12-19 (T-1), 12-22 (T)
df_1219 = df[df['date'] == '2025-12-19'].copy()
df_1222 = df[df['date'] == '2025-12-22'].copy()

# 模拟filter_universe
# 1. 从T-1日筛选人气前10
df_prev_hot = df_1219[df_1219['is_tradable']].copy()
df_prev_hot = df_prev_hot[df_prev_hot['hot_rank'] <= 10]
hot_codes = df_prev_hot['code'].tolist()

print("T-1日(12-19)人气前10:")
print(df_prev_hot[['code', 'name', 'hot_rank', 'close']].sort_values('hot_rank').to_string(index=False))

# 2. 在T日找到这些股票
df_today_selected = df_1222[df_1222['code'].isin(hot_codes)].copy()

# 3. 过滤ST
df_today_selected = df_today_selected[df_today_selected['is_tradable']]
df_today_selected = df_today_selected[~df_today_selected['is_st']]

# 4. 计算T日开盘跌幅
df_today_selected['open_change_pct'] = (df_today_selected['open'] - df_today_selected['close_prev']) / df_today_selected['close_prev']

# 5. 排序
df_today_selected = df_today_selected.sort_values('open_change_pct', ascending=True)

print("\nT日(12-22)这些股票的开盘跌幅:")
print(df_today_selected[['code', 'name', 'open', 'close_prev', 'open_change_pct']].to_string(index=False))

# 6. 取前3只
df_selected = df_today_selected.head(3)
print("\n选中的前3只:")
print(df_selected[['code', 'name', 'open_change_pct']].to_string(index=False))
