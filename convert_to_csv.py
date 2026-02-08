import pandas as pd
import os
from pathlib import Path

# 读取最新的parquet交易记录
trades_parquet = 'data/backtest/trades/hot_rank_drop7_smart_exit_v1.1.0_2fadcb79_20260103_141827_trades.parquet'
trades = pd.read_parquet(trades_parquet)

# 生成CSV文件名（与parquet同名，只改扩展名）
csv_filename = trades_parquet.replace('.parquet', '.csv')

# 保存为CSV
trades.to_csv(csv_filename, index=False, encoding='utf-8-sig')

print(f'✓ 交易记录已保存为CSV格式')
print(f'  文件路径: {csv_filename}')
print(f'  交易笔数: {len(trades)}')
print(f'  文件大小: {os.path.getsize(csv_filename) / 1024:.2f} KB')

# 显示前5行
print(f'\n前5笔交易:')
display_cols = ['code', 'name', 'entry_date', 'exit_date', 'rank_t1', 'amount_t1', 'net_pnl_pct']
print(trades[display_cols].head().to_string(index=False))
