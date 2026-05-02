# Rise2 策略说明（盘中 +2% 动量买入）

## 策略逻辑

1. 选股：前一交易日人气榜前50，且通过流动性与风控过滤。
2. 买入：次日盘中触及 `+2%` 触发价时买入。
3. 卖出优先级：跌停卖出 > 涨停持有 > 正常收盘卖出。

## 关键参数

- `hot_top_n=50`
- `rise_trigger=0.02`
- `require_prev_limit_up=true`
- `max_positions=10`

## 对应文件

- 配置：`config/strategies/hot_rank_rise2.yaml`
- 回测脚本：`scripts/backtest_hot_rank_rise2_strategy.py`

## 本次复现产物（2026-03-19）

- [复现报告](../reproduce_rise2_20260319.md)
- [买卖记录（可筛选）](../trades/rise2_trades_latest.html)
- [买卖记录CSV](../trades/rise2_trades_latest.csv)
