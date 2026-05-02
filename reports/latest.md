# 最新统计（2026-03-19）

本次完成“已跑通策略”本地复现，并重新生成报告与页面产物。

## 复现结果总览

- [策略复现结果汇总](./reproduce_summary_20260319.md)
- [Drop7 策略复现报告](./reproduce_drop7_20260319.md)
- [Rise2 策略复现报告](./reproduce_rise2_20260319.md)
- [Top20 NewEntry 策略复现报告](./reproduce_top20_newentry_20260319.md)
- [First Top10 策略复现报告](./reproduce_first_top10_20260319.md)

## 页面入口

- [热度个股前100历史筛选](../hot_rank_top100_explorer.html)
- [交易记录列表](./trades/index.md)
- [策略说明列表](./strategies/index.md)

## 说明

- 本次复现基于本地当前数据与现有策略配置执行。
- 回测报告由 `scripts/generate_report.py` 自动生成。
- 页面产物可通过 `./scripts/build_pages_local.sh` 本地一键复现。
