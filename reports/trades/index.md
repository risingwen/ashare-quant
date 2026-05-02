# 策略买卖记录总览

> 已按策略拆分最新交易记录，支持网页筛选和点击表头排序。

## 1. Drop7（回撤买入）

- [交易记录（可筛选）](./drop7_trades_latest.html)
- [交易CSV](./drop7_trades_latest.csv)
- [对应复现报告](../reproduce_drop7_20260319.md)

## 2. Rise2（+2%追涨）

- [交易记录（可筛选）](./rise2_trades_latest.html)
- [交易CSV](./rise2_trades_latest.csv)
- [对应复现报告](../reproduce_rise2_20260319.md)

## 3. Top20 NewEntry（首次入榜前20开盘买）

- [交易记录（可筛选）](./top20_newentry_trades_latest.html)
- [交易CSV](./top20_newentry_trades_latest.csv)
- [对应复现报告](../reproduce_top20_newentry_20260319.md)

## 4. First Top10（首次前10，低开或+2%买）

- [交易记录（可筛选）](./first_top10_trades_latest.html)
- [交易CSV](./first_top10_trades_latest.csv)
- [对应复现报告](../reproduce_first_top10_20260319.md)

## 说明

- 最新交易记录由 `scripts/publish_strategy_trades.py` 生成。
- 如果你重新跑了回测，执行一次该脚本即可刷新以上链接指向的数据。
