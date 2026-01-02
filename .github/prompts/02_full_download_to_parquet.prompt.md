---
agent: "copilot"
---

请实现"全量拉取A股近两年日线数据并落地到本地数据湖(Parquet)"的核心脚本。

数据源：
- AkShare：用 stock_info_a_code_name 获取A股代码列表（注意该接口在某些版本可能异常，需做容错/降级策略）:contentReference[oaicite:6]{index=6}
- AkShare：用 stock_zh_a_hist 拉取历史行情（日频，支持 adjust=hfq/qfq/空）:contentReference[oaicite:7]{index=7}

输出：
- 写入 Parquet，按 year=YYYY/month=MM 分区，每月一个或少量文件，避免产生大量小文件
- 统一字段命名：date, code, open, high, low, close, volume, amount（若AkShare字段不同需映射）
- 写入前去重：以 (code,date) 作为唯一键
- 断点续跑：维护一个 manifest（json 或 csv），记录每个 code 的最新完成日期与失败原因

脚本名称：
- scripts/download_ashare_3y_to_parquet.py

功能要求：
1) 参数：--start-date --end-date --adjust --workers --rate-limit --onedrive-root
2) 限流与重试：对请求失败/封禁风险做指数退避
3) 数据校验：日期范围、重复行、空值、价格为负等异常要告警（记录到日志和 manifest）
4) 性能：并发拉取，但必须保证可控；写文件时按分区聚合后再落盘

请给出完整代码（可运行），并补充关键函数用途说明。
