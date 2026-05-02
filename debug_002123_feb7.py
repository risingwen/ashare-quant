"""
Debug script: Check why 002123 was not bought on 2025-02-07
"""
import pandas as pd
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger()

# Load feature data
df = pd.read_parquet('data/processed/features/daily_features_v1.parquet')

# Get dates
dates = sorted(df['date'].unique())
target_date = pd.Timestamp('2025-02-07')
idx = dates.index(target_date)
date_t1 = dates[idx-1]  # 2025-02-06
date_t2 = dates[idx-2]  # 2025-02-05

logger.info(f"Target date: {target_date}")
logger.info(f"T-1: {date_t1}")
logger.info(f"T-2: {date_t2}")

# Get data for 002123
df_today = df[df['date'] == target_date]
df_prev = df[df['date'] == date_t1]
df_prev2 = df[df['date'] == date_t2]

code = '002123'
row_today = df_today[df_today['code'] == code]
row_prev = df_prev[df_prev['code'] == code]
row_prev2 = df_prev2[df_prev2['code'] == code]

logger.info(f"\n=== {code} Data ===")
if not row_prev.empty:
    r = row_prev.iloc[0]
    logger.info(f"T-1 ({date_t1}):")
    logger.info(f"  hot_rank: {r['hot_rank']}")
    logger.info(f"  is_limit_up: {r['is_limit_up']}")
    logger.info(f"  amount: {r['amount']:.2f}亿")
    logger.info(f"  is_st: {r['is_st']}")
    logger.info(f"  days_since_listing: {r['days_since_listing']}")
    logger.info(f"  amplitude_prev: {r['amplitude_prev']:.2f}%")
    logger.info(f"  pct_change_prev: {r['pct_change_prev']:.2f}%")
    logger.info(f"  max_drop_5d: {r['max_drop_5d']:.2f}%")
    logger.info(f"  intraday_drop: {r['intraday_drop']:.2f}%")
    logger.info(f"  cum_return_2d: {r['cum_return_2d']:.2f}%")
    logger.info(f"  one_word_board_5d: {r['one_word_board_5d']}")

if not row_prev2.empty:
    r2 = row_prev2.iloc[0]
    logger.info(f"\nT-2 ({date_t2}):")
    logger.info(f"  hot_rank: {r2['hot_rank']}")

if not row_today.empty:
    rt = row_today.iloc[0]
    logger.info(f"\nToday ({target_date}):")
    logger.info(f"  is_tradable: {rt['is_tradable']}")
    logger.info(f"  low: {rt['low']:.2f}")
    logger.info(f"  close_prev: {rt['close_prev']:.2f}")
    trigger = rt['close_prev'] * 1.02
    logger.info(f"  trigger_price (close_prev*1.02): {trigger:.4f}")
    logger.info(f"  low <= trigger: {rt['low'] <= trigger}")

# Apply filters step by step
logger.info(f"\n=== Filter Steps ===")

# Parameters from config
hot_top_n = 50
prev_amount_min = 100_000_000  # 1亿元
amount_min_billion = prev_amount_min / 1e8  # 转为亿
max_hot_rank_3d = 50

# Start with T-1 hot rank stocks
df_filtered = df_prev[df_prev['hot_rank'].notna()].copy()
df_filtered = df_filtered[df_filtered['hot_rank'] <= hot_top_n]
logger.info(f"1. Hot rank <= {hot_top_n}: {len(df_filtered)} stocks")
has_code = code in df_filtered['code'].values
logger.info(f"   002123 in pool: {has_code}")

if has_code:
    # 2. Amount filter
    before = len(df_filtered)
    df_filtered = df_filtered[df_filtered['amount'] >= amount_min_billion]
    logger.info(f"2. Amount >= {amount_min_billion}亿: {len(df_filtered)} stocks")
    has_code = code in df_filtered['code'].values
    logger.info(f"   002123 in pool: {has_code}")

if has_code:
    # 3. ST filter
    before = len(df_filtered)
    df_filtered = df_filtered[~df_filtered['is_st']]
    logger.info(f"3. Not ST: {len(df_filtered)} stocks")
    has_code = code in df_filtered['code'].values
    logger.info(f"   002123 in pool: {has_code}")

if has_code:
    # 4. New IPO filter
    before = len(df_filtered)
    df_filtered = df_filtered[df_filtered['days_since_listing'] > 10]
    logger.info(f"4. Days since listing > 10: {len(df_filtered)} stocks")
    has_code = code in df_filtered['code'].values
    logger.info(f"   002123 in pool: {has_code}")

if has_code:
    # 5. Volatility filter
    before = len(df_filtered)
    df_filtered = df_filtered[
        (df_filtered['amplitude_prev'].notna()) &
        (df_filtered['amplitude_prev'] <= 30) &
        (df_filtered['pct_change_prev'].notna()) &
        (df_filtered['pct_change_prev'] >= -20)
    ]
    logger.info(f"5. Volatility check (amplitude<=30%, pct_change>=-20%): {len(df_filtered)} stocks")
    has_code = code in df_filtered['code'].values
    logger.info(f"   002123 in pool: {has_code}")

if has_code:
    # 6. Max drop 5d filter
    before = len(df_filtered)
    df_filtered = df_filtered[
        (
            (df_filtered['max_drop_5d'].isna()) | 
            (df_filtered['max_drop_5d'] > -7)
        ) & (
            (df_filtered['intraday_drop'].isna()) |
            (df_filtered['intraday_drop'] > -7)
        )
    ]
    logger.info(f"6. Max drop 5d > -7%: {len(df_filtered)} stocks")
    has_code = code in df_filtered['code'].values
    logger.info(f"   002123 in pool: {has_code}")

if has_code:
    # 7. 2d surge filter
    before = len(df_filtered)
    df_filtered = df_filtered[
        (df_filtered['cum_return_2d'].isna()) | 
        (df_filtered['cum_return_2d'] <= 40)
    ]
    logger.info(f"7. Cumulative return 2d <= 40%: {len(df_filtered)} stocks")
    has_code = code in df_filtered['code'].values
    logger.info(f"   002123 in pool: {has_code}")

if has_code:
    # 8. One word board filter
    before = len(df_filtered)
    df_filtered = df_filtered[df_filtered['one_word_board_5d'] < 1]
    logger.info(f"8. One word board 5d < 1: {len(df_filtered)} stocks")
    has_code = code in df_filtered['code'].values
    logger.info(f"   002123 in pool: {has_code}")

if has_code:
    # 9. Dynamic hot rank 2d filter
    before = len(df_filtered)
    codes = df_filtered['code'].values
    df_t2 = df_prev2[df_prev2['code'].isin(codes)][['code', 'hot_rank']].rename(columns={'hot_rank': 'hot_rank_t2'})
    df_filtered = df_filtered.merge(df_t2, on='code', how='left')
    df_filtered['max_hot_rank_2d'] = df_filtered[['hot_rank', 'hot_rank_t2']].max(axis=1)
    
    # Show 002123's values
    if code in df_filtered['code'].values:
        row = df_filtered[df_filtered['code'] == code].iloc[0]
        logger.info(f"9. Dynamic hot rank 2d calculation:")
        logger.info(f"   hot_rank (T-1): {row['hot_rank']}")
        logger.info(f"   hot_rank_t2 (T-2): {row['hot_rank_t2']}")
        logger.info(f"   max_hot_rank_2d: {row['max_hot_rank_2d']}")
        logger.info(f"   Threshold: {max_hot_rank_3d}")
    
    df_filtered = df_filtered[
        df_filtered['hot_rank'].isna() |
        (df_filtered['max_hot_rank_2d'] <= max_hot_rank_3d)
    ]
    logger.info(f"   After filter: {len(df_filtered)} stocks")
    has_code = code in df_filtered['code'].values
    logger.info(f"   002123 in pool: {has_code}")

if has_code:
    # 10. Limit up filter
    before = len(df_filtered)
    df_filtered = df_filtered[df_filtered['is_limit_up'] == True]
    logger.info(f"10. Require prev limit up: {len(df_filtered)} stocks")
    has_code = code in df_filtered['code'].values
    logger.info(f"    002123 in pool: {has_code}")

if has_code:
    # 11. Today tradable filter
    df_today_tradable = df_today[df_today['is_tradable']].copy()
    codes_tradable = set(df_today_tradable['code'])
    df_filtered = df_filtered[df_filtered['code'].isin(codes_tradable)]
    logger.info(f"11. Today tradable: {len(df_filtered)} stocks")
    has_code = code in df_filtered['code'].values
    logger.info(f"    002123 in pool: {has_code}")

if not has_code:
    logger.info(f"\n=== 002123 was FILTERED OUT ===")
else:
    logger.info(f"\n=== 002123 PASSED all filters ===")
