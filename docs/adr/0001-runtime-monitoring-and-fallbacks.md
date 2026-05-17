# ADR 0001: 运行监控与数据源兜底策略

## Status

Accepted

## Date

2026-05-17

## Context

平台已经从单纯静态报告演进为生产服务：包含 SQLite 数据库、AkShare/东方财富等外部数据源、systemd 日更、GitHub Actions 部署、Flask API 和 nginx 静态页面。

此前主要问题：

- 页面只显示一个最新日期，无法判断每个模块是否更新成功。
- 线上页面无法直接确认对应 Git commit。
- ETF 历史 K 线接口异常会导致 ETF 雷达长期停留在旧日期。
- 人气榜 AkShare 接口偶发返回非 JSON、连接重置或 502。
- legacy 表可能出现自然日日期，不应影响整体健康状态。
- 日更脚本和 systemd 实际执行脚本可能不一致。

## Decision

采用以下策略：

- 新增 `/api/health`，按模块返回最新日期、行数、状态、错误和 Git commit。
- 新增 `monitor.html`，面向人展示数据更新结论、报告生成时间、Git commit、分支和生产日志路径。
- `summary.json` 写入 Git commit 元数据，首页和监控页都能确认版本。
- ETF 日更主链路使用 `src/update_etf.py --spot-only --skip-holdings`，优先保证最新交易日快照。
- ETF 历史 K 线和持仓采集视为增强数据，不阻塞每日主链路。
- 人气榜在 AkShare 失败后使用东方财富 direct fallback，再失败才使用标准化 CSV fallback。
- `/api/health` 只用必需模块决定总状态；非必需 legacy warning 保留在详情中，但不让总状态变成 `warn/error`。
- `deploy/scripts/deploy_oracle.sh` 每次部署都安装最新版 `deploy/scripts/quant-daily-run.sh` 到 systemd 实际执行路径。

## Consequences

正向影响：

- 线上状态可以通过 `/monitor.html` 和 `/api/health` 快速判断。
- 用户能直接看到页面对应的 Git commit。
- 外部数据源短时异常不会让 ETF 和人气榜长期停在旧日期。
- 日更失败不再被吞掉，问题更容易暴露。
- systemd 执行脚本和仓库脚本保持一致。

代价：

- ETF `--spot-only` 场景下，技术指标可能不如完整历史 K 线更新准确。
- 人气榜 direct fallback 在行情补充接口失败时，股票名称可能降级为代码。
- legacy 表仍可能产生 warning，需要后续逐步清理。

## Validation

验收命令：

```bash
curl http://140.245.53.52:8080/api/health
curl 'http://140.245.53.52:8080/monitor.html?v=manual-check'
curl 'http://140.245.53.52:8080/summary.json?v=manual-check'
```

基准结果：

- `/api/health status=ok`
- `errors=[]`
- 最新有效交易日为 `2026-05-15`
- `popularity_rankings` 最新日期为 `2026-05-15`
- `etf_daily` 最新日期为 `2026-05-15`
- `git.short_commit=358dc20`

## Follow-up

- 后续新增数据模块时必须加入 `/api/health.modules`。
- 后续线上事故必须追加到 `docs/INCIDENT_LOG.md`。
- 影响长期行为的决策必须继续写入 `docs/adr/`。
