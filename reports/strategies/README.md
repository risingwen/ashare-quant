# 策略说明总览

本目录用于展示策略说明文档（会随 Pages 发布）。

## 策略文档

- [人气回撤买入策略（主板-7%，创业板/科创板-13%）](./hot_rank_drop7_plan.md)
- [人气榜 +2% 追涨策略](./hot_rank_rise2_plan.md)
- [首次入榜前20开盘买策略](./hot_rank_top10_open_plan.md)
- [首次前10 + 低开或+2%买策略](./hot_rank_first_top10_rise2_or_gapdown_plan.md)

## 配置文件

策略配置 YAML 在仓库 `config/strategies/`：

- `hot_rank_drop7.yaml`
- `hot_rank_rise2.yaml`
- `hot_rank_top10_open.yaml`
- `hot_rank_first_top10_rise2_or_gapdown.yaml`

## 复现入口

- 本地完整复现与发布说明：`docs/LOCAL_REPRODUCTION.md`
- 本地构建 Pages 产物脚本：`scripts/build_pages_local.sh`
