# 策略说明总览

本目录聚合每个策略的详细说明、复现报告与买卖记录入口。

## Drop7（主板-7%，创业板/科创板-13%）

- [策略说明](./hot_rank_drop7_plan.md)
- [复现报告](../reproduce_drop7_20260319.md)
- [买卖记录](../trades/drop7_trades_latest.html)

## Rise2（盘中+2%追涨）

- [策略说明](./hot_rank_rise2_plan.md)
- [复现报告](../reproduce_rise2_20260319.md)
- [买卖记录](../trades/rise2_trades_latest.html)

## Top20 NewEntry（首次入榜前20开盘买）

- [策略说明](./hot_rank_top10_open_plan.md)
- [复现报告](../reproduce_top20_newentry_20260319.md)
- [买卖记录](../trades/top20_newentry_trades_latest.html)

## First Top10（首次前10，低开或+2%买）

- [策略说明](./hot_rank_first_top10_rise2_or_gapdown_plan.md)
- [复现报告](../reproduce_first_top10_20260319.md)
- [买卖记录](../trades/first_top10_trades_latest.html)

## 自动化更新说明

- 交易记录发布脚本：`scripts/publish_strategy_trades.py`
- 本地构建脚本：`scripts/build_pages_local.sh`
- GitHub Pages 工作流：`.github/workflows/static.yml`
