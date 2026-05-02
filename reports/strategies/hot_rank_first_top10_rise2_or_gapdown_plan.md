# First Top10 策略说明（首次前10，低开或+2%买）

## 策略逻辑

1. 信号：个股在 T 日首次进入人气前10。
2. 买入（T+1 满足其一）：
- 低开：`open < T日close`，按开盘买入
- 动量：盘中触及 `T日close * 1.02`，按触发价买入
3. 卖出：持仓期间人气跌出前50即收盘卖出。

## 关键参数

- `hot_top_n=10`
- `require_first_entry=true`
- `rise_trigger=0.02`
- `buy_on_gap_down=true`
- `exit_rank_threshold=50`

## 对应文件

- 配置：`config/strategies/hot_rank_first_top10_rise2_or_gapdown.yaml`
- 回测脚本：`scripts/backtest_hot_rank_first_top10_strategy.py`

## 本次复现产物（2026-03-19）

- [复现报告](../reproduce_first_top10_20260319.md)
- [买卖记录（可筛选）](../trades/first_top10_trades_latest.html)
- [买卖记录CSV](../trades/first_top10_trades_latest.csv)
