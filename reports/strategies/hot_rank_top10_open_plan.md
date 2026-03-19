# Top20 NewEntry 策略说明（首次进入前20，开盘买）

## 策略逻辑

1. 选股：首次进入人气榜前20的股票。
2. 买入：T+1 开盘价买入（可跳过一字涨停不可成交场景）。
3. 卖出：次日不涨停或人气跌破阈值时卖出。

## 关键参数

- `hot_top_n=20`
- `filter_new_entry=true`
- `entry_time=open`
- `rank_threshold=50`
- `cash_splits=3`

## 对应文件

- 配置：`config/strategies/hot_rank_top10_open.yaml`
- 回测脚本：`scripts/backtest_hot_rank_top10_open_strategy.py`

## 本次复现产物（2026-03-19）

- [复现报告](../reproduce_top20_newentry_20260319.md)
- [买卖记录（可筛选）](../trades/top20_newentry_trades_latest.html)
- [买卖记录CSV](../trades/top20_newentry_trades_latest.csv)
