# 事故记录

本文档用于记录生产问题、根因、修复和预防措施。新增线上故障或重要排障结论时，按固定模板追加。

## 记录模板

```markdown
## YYYY-MM-DD 标题

- 日期：
- 现象：
- 根因：
- 修复：
- 验证命令：
- 后续预防：
```

## 2026-05-17 运行监控与数据更新修复

- 日期：2026-05-17
- 现象：线上页面只显示「最新数据：2026-05-15」，但无法判断每个模块是否更新成功，也无法确认页面对应的 Git commit。
- 根因：缺少模块级健康检查和版本元数据；`summary.json` 和页面没有暴露 Git commit。
- 修复：新增 `/api/health` 模块级健康接口，新增 `monitor.html` 运行监控页，在 `summary.json` 和页面中写入 Git commit、分支、提交时间和 dirty 状态。
- 验证命令：

```bash
curl http://140.245.53.52:8080/api/health
curl 'http://140.245.53.52:8080/monitor.html?v=manual-check'
curl 'http://140.245.53.52:8080/summary.json?v=manual-check'
```

- 后续预防：后续所有数据模块必须进入 `/api/health.modules`，新增页面必须在监控页能追踪到数据日期和版本。

## 2026-05-17 日更脚本吞失败

- 日期：2026-05-17
- 现象：日更任务中间步骤失败后，后续报告仍可能继续生成，线上看起来像更新成功。
- 根因：`deploy/scripts/quant-daily-run.sh` 的 `run_step()` 在失败时没有返回真实退出码。
- 修复：`run_step()` 失败时返回原始退出码，配合 `set -euo pipefail` 阻止错误继续被覆盖。
- 验证命令：

```bash
bash -n deploy/scripts/quant-daily-run.sh
grep -n 'return "$rc"' /data/quant_research/logs/quant-daily-run.sh
```

- 后续预防：生产主链路不得吞掉关键步骤失败；非关键兜底任务必须明确使用 `|| true` 或 `timeout`。

## 2026-05-17 systemd 跑旧脚本副本

- 日期：2026-05-17
- 现象：仓库里的 `deploy/scripts/quant-daily-run.sh` 已修复，但 `quant-daily.service` 仍执行 `/data/quant_research/logs/quant-daily-run.sh` 的旧副本。
- 根因：systemd 的 `ExecStart` 指向生产日志目录下的脚本副本，部署时没有同步覆盖该副本。
- 修复：`deploy/scripts/deploy_oracle.sh` 在每次部署时执行 `install -m 0755 deploy/scripts/quant-daily-run.sh /data/quant_research/logs/quant-daily-run.sh`。
- 验证命令：

```bash
sudo systemctl cat quant-daily.service --no-pager
grep -n -- '--spot-only\|--skip-holdings\|return "$rc"' /data/quant_research/logs/quant-daily-run.sh
```

- 后续预防：修改日更脚本后必须运行部署脚本，不能只 `git pull`。

## 2026-05-17 ETF 旧持仓循环进程长期运行

- 日期：2026-05-17
- 现象：服务器存在 `/tmp/run_etf_loop.sh`，反复启动 `src/update_etf.py --holdings-only --all-holdings`，进程运行超过 10 天。
- 根因：临时 ETF 持仓回补脚本脱离 systemd 管理，长期循环执行，且日更脚本旧版本也把 ETF 步骤放在持仓路径上。
- 修复：终止 `/tmp/run_etf_loop.sh` 和子进程；日更主链路改为 `src/update_etf.py --spot-only --skip-holdings`。
- 验证命令：

```bash
ps -eo pid,ppid,stat,etime,cmd | grep -E 'update_etf|run_etf_loop' | grep -v grep
curl http://140.245.53.52:8080/api/health
```

- 后续预防：ETF 持仓采集不进入每日主链路；长跑任务必须由 systemd 管理并设置超时。

## 2026-05-17 ETF 历史 K 线接口异常

- 日期：2026-05-17
- 现象：`etf_daily` 停留在 `2026-04-30`，`/api/health` 报 ETF 雷达落后 8 个交易日。
- 根因：东方财富历史 K 线接口 `push2his.eastmoney.com` 连接超时或远端断开，逐只 ETF 拉历史数据导致任务慢且不稳定。
- 修复：`src/update_etf.py` 增加实时快照兜底，并新增 `--spot-only` 参数；日更使用 `--spot-only --skip-holdings`。
- 验证命令：

```bash
/data/quant_research_venv/bin/python src/update_etf.py --db /data/quant_research/data/quant.db --min-amount 5000 --spot-only --skip-holdings --sleep 0
curl http://140.245.53.52:8080/api/health
```

- 后续预防：历史指标和持仓作为增强数据，不能阻塞最新交易日快照。

## 2026-05-17 人气热榜接口失败

- 日期：2026-05-17
- 现象：`popularity_rankings` 停留在 `2026-05-13`，`/api/health` 报人气热榜落后 2 个交易日。
- 根因：AkShare `stock_hot_rank_em()` 调用东方财富接口时出现非 JSON、连接重置或 502。
- 修复：`src/update_sqlite_data.py` 增加东方财富 direct fallback；AkShare 失败后直接请求排名接口，必要时股票名称降级为代码，确保 Top100 排名写入当天。
- 验证命令：

```bash
/data/quant_research_venv/bin/python src/update_sqlite_data.py --db /data/quant_research/data/quant.db --end-date 20260515 --skip-daily --skip-limit-pool --skip-lhb --socket-timeout 20 --retries 3
curl http://140.245.53.52:8080/api/health
```

- 后续预防：外部数据源必须至少有一个直接 API 或文件兜底路径；失败原因写入日志和健康检查。

## 2026-05-17 GitHub Actions 缺少 Oracle SSH key

- 日期：2026-05-17
- 现象：GitHub Actions `Deploy to Oracle Cloud` 失败，日志显示无法连接 SSH。
- 根因：仓库 Actions Secrets 缺少 `ORACLE_SSH_KEY`，早期还缺少 `ORACLE_HOST`。
- 修复：配置 `ORACLE_SSH_KEY`、`ORACLE_HOST`、`ORACLE_USER`；重新运行失败 workflow 后成功。
- 验证命令：

```bash
curl http://140.245.53.52:8080/api/health
```

GitHub Actions 页面确认 `Deploy to Oracle Cloud` 结论为 `success`。

- 后续预防：迁移主机或更换 key 时，同步更新 GitHub Actions Secrets；文档只记录 secret 名称，不记录 secret 原文。

## 2026-05-17 legacy zt_pool 未来日期告警

- 日期：2026-05-17
- 现象：legacy `zt_pool` 表最新日期显示 `2026-05-17`，这是周日，晚于最新有效交易日 `2026-05-15`。
- 根因：legacy 表保留了自然日写入逻辑，不适合作为必需模块健康状态依据。
- 修复：`/api/health` 保留 legacy warning，但非必需 legacy 模块不影响总状态；必需模块全部 fresh 时 `status=ok`。
- 验证命令：

```bash
curl http://140.245.53.52:8080/api/health
```

- 后续预防：逐步清理 legacy 表或迁移到交易日感知写入逻辑；健康检查默认只用必需模块决定总状态。
