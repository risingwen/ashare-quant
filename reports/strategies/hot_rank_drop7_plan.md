# Drop7 策略说明（主板-7%，创业板/科创板-13%）

## 策略逻辑

1. 选股：前一交易日人气榜前100，且满足成交额与基础过滤条件。
2. 买入：次日盘中回撤触发买入。
- 主板/深市：触发阈值 `-7%`
- 创业板(30)/科创板(688)：触发阈值 `-13%`
3. 卖出优先级：跌停卖出 > 涨停持有 > 正常收盘卖出。

## 关键参数

- `hot_top_n=100`
- `drop_trigger=0.07`
- `drop_trigger_cyb_kcb=0.13`
- `exit_on_limit_down=true`
- `max_positions=10`

## 对应文件

- 配置：`config/strategies/hot_rank_drop7.yaml`
- 回测脚本：`scripts/backtest_hot_rank_strategy.py`

## 本次复现产物（2026-03-19）

- [复现报告](../reproduce_drop7_20260319.md)
- [买卖记录（可筛选）](../trades/drop7_trades_latest.html)
- [买卖记录CSV](../trades/drop7_trades_latest.csv)
