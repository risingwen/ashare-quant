# hot_rank_first_top10_rise2_or_gapdown Buy/Sell Plan

- 资金规模：100万，分3份；单笔名义仓位约33.33万。
- 信号触发：个股在T日“首次进入人气前10”。
- 买入时机（T+1，二选一）：
  - 低开：`open < T日close`，按开盘价买入。
  - 动量触发：盘中触及 `T日close * 1.02`，按触发价买入。
- 卖出规则：持仓期间人气跌出前50（`hot_rank > 50`）即在当日收盘卖出。

对应文件：

- `config/strategies/hot_rank_first_top10_rise2_or_gapdown.yaml`
- `scripts/backtest_hot_rank_first_top10_strategy.py`
