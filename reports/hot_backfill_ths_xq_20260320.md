# 同花顺/雪球人气数据补全结果（2026-03-20）

## 执行目标
- 按你的要求补全 `2025-01-01` 以来的人气数据。
- 覆盖来源：同花顺、雪球。

## 同花顺（已补齐）
- 数据文件：`data/hot_sources/ths/ths_hot_rank_top100_history.csv`
- 覆盖区间：`2025-01-01` ~ `2026-03-20`
- 日期数：`443`
- 总行数：`44,130`
- 排名范围：`1..100`
- 缺失队列：`data/hot_sources/ths/ths_hot_rank_failed_dates.csv` 当前为 `0` 行

> 说明：使用 `pywencai` 按日期查询“人气榜”并多轮重试补齐。

## 雪球（接口边界已确认）
- 数据文件：`data/hot_sources/xueqiu/xueqiu_hot_rank_snapshots.csv`
- 已采集快照次数：`4`
- 总行数：`88,086`
- 榜单类型：`follow_hot` / `follow_7d` / `tweet_hot` / `deal_hot`

> 说明：当前可用雪球接口返回“当前快照榜单”，不提供“指定历史日期回放”，因此无法直接补齐 2025-01 以来的历史日榜；现已建立快照库用于持续日更累计。
