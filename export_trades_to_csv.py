import pandas as pd

# 读取最新交易记录
trades = pd.read_parquet('data/backtest/trades/hot_rank_drop7_smart_exit_v1.1.0_2fadcb79_20260103_011251_trades.parquet')

print(f'总交易笔数: {len(trades)}')
print(f'收益率: {((trades["net_pnl_pct"] + 1).prod() - 1) * 100:.2f}%')
print(f'胜率: {(trades["net_pnl_pct"] > 0).sum() / len(trades) * 100:.1f}%')

# 添加收益率百分比列（方便阅读）
trades_export = trades.copy()
trades_export['net_pnl_pct_display'] = (trades_export['net_pnl_pct'] * 100).round(2)

# 重命名列，使其更易读
column_rename = {
    'code': '股票代码',
    'name': '股票名称',
    'entry_date': '买入日期',
    'exit_date': '卖出日期',
    'rank_t': 'T日人气排名',
    'rank_t1': 'T-1日人气排名',
    'rank_t2': 'T-2日人气排名',
    'amount_t': 'T日成交额(亿)',
    'amount_t1': 'T-1日成交额(亿)',
    'amount_t2': 'T-2日成交额(亿)',
    'prev_close': '前收盘价',
    'trigger_low': '触发最低价',
    'buy_price': '买入价',
    'buy_exec': '实际买入价',
    'buy_shares': '买入股数',
    'buy_cost': '买入成本',
    'cash_after_buy': '买入后现金',
    'exit_reason': '卖出原因',
    'hold_days': '持仓天数',
    'sell_price': '卖出价',
    'sell_exec': '实际卖出价',
    'sell_proceed': '卖出收入',
    'cash_after_sell': '卖出后现金',
    'gross_pnl': '毛盈亏',
    'net_pnl': '净盈亏',
    'net_pnl_pct': '收益率',
    'net_pnl_pct_display': '收益率(%)'
}

trades_export = trades_export.rename(columns=column_rename)

# 保存为CSV
csv_path = 'data/backtest/trades/latest_trades_with_details.csv'
trades_export.to_csv(csv_path, index=False, encoding='utf-8-sig')

print(f'\n✓ CSV文件已保存: {csv_path}')
print(f'✓ 包含所有字段：T/T-1/T-2的人气排名和成交额')

# 显示前5笔交易
print('\n前5笔交易预览:')
display_cols = ['股票代码', '股票名称', '买入日期', '卖出日期', 'T-1日人气排名', 'T-1日成交额(亿)', '收益率(%)']
print(trades_export[display_cols].head().to_string(index=False))
