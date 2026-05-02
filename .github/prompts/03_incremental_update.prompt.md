---
agent: "copilot"
---

请实现“每日增量更新”脚本：只拉取缺失的最新交易日数据，追加写入相应的 Parquet 分区，并更新 manifest。

脚本名称：
- scripts/update_daily_incremental.py
- scripts/update_daily_incremental.sh（可选：封装一键运行）

要求：
1) 读取 manifest，找出每只股票最新 date
2) 对每只股票只拉取缺失区间（例如 latest_date+1 到 today）
3) 更新后做去重合并；仍按 year/month 分区写入
4) 若当日非交易日或数据为空：打印说明并退出 0
5) 生成一个简短日报：新增股票数、更新行数、失败列表


