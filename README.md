# A股量化研究平台

基于 PostgreSQL、FastAPI、React 与 Tushare Replay 的 A 股日频研究平台。公网只读，数据采集、历史回补、策略回测和模拟组合由服务器 CLI 与 systemd 执行。

## 在线入口

- 平台：<http://140.245.53.52:8080/>
- 设计文档：<http://140.245.53.52:8080/docs.html#overview>
- 健康检查：<http://140.245.53.52:8080/api/v1/health>
- 回补状态：<http://140.245.53.52:8080/api/v1/backfill-status>

## 数据范围

- 起始日期：2025-01-01
- 市场：A 股
- 日线：Replay `daily`
- 人气榜：Replay `dc_hot`（东方财富）与 `ths_hot`（同花顺），均使用 `is_new=Y` 只保存每日最终 Top100；查询页可切换并明确显示来源
- 龙虎榜：Replay `top_list` / `top_inst`，覆盖个股记录与机构/营业部明细
- 主数据库：PostgreSQL 16，数据库名 `quant_platform`

旧 AkShare、新浪、东方财富直连、问财、mootdx、远程 SSH 分片和 SQLite 日更采集链路均已停用并删除。

## 工程结构

| 路径 | 用途 |
| --- | --- |
| `quant_platform/` | Provider、PostgreSQL 迁移、采集、回测、模拟组合与 FastAPI |
| `apps/web/` | React 数据平台 |
| `deploy/systemd/` | API、日更和历史回补服务 |
| `deploy/nginx/` | nginx 站点配置 |
| `docs/REBUILD_PLAN.md` | 当前架构和实施计划真源 |

## 常用命令

```bash
quant migrate
quant probe-replay --date 2025-01-02
quant sync-popularity --date latest-market
quant backfill-popularity --start 2025-01-01 --end 2026-07-31 --sleep 0.15
quant backfill-two-years --start 2025-01-01 --end 2026-07-12 --sleep 0.6
quant run-strategy --start 2025-01-01 --end 2026-07-12
quant advance-portfolio --date 2026-07-10
```

15000 积分官方接口频率上限为每分钟 500 次；最终榜单回补主动限制在约每分钟 400 次的请求间隔内，并对网络错误、429 和 5xx 使用指数退避。

## 验证

```bash
PYTHONPATH=. /data/quant_research_venv/bin/pytest -q -m 'not network'
cd apps/web && npm run build && npm audit --omit=dev
```

密钥只从 `config/quant-platform.env` 或 systemd EnvironmentFile 注入，不进入 Git、数据库、日志和网页响应。
