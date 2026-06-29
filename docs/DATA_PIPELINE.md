# 数据流水线说明

本文档描述生产环境每日数据更新链路、脚本职责和降级策略。目标是让数据是否更新成功可以被追踪、复现和排障。

## 1. 主链路

生产日更由 systemd 触发：

```text
quant-daily.timer -> quant-daily.service -> /data/quant_research/logs/quant-daily-run.sh
```

仓库脚本模板：

```text
deploy/scripts/quant-daily-run.sh
```

部署脚本 `deploy/scripts/deploy_oracle.sh` 会把最新版模板安装到生产路径：

```text
/data/quant_research/logs/quant-daily-run.sh
```

## 2. 每日任务顺序

当前生产任务顺序：

```text
1. src/update_sqlite_data.py
2. src/update_etf.py --spot-only --skip-holdings
3. src/update_shares.py
4. src/update_zt_pool.py
5. src/health_check.py
6. src/audit_data_completeness.py
7. src/screener.py
8. src/backtest_new_high_volume.py
9. src/generate_report.py
```

主链路使用 `set -euo pipefail`，任一关键步骤失败会保留真实退出码，不再吞掉失败继续生成“看似成功”的报告。
`src/health_check.py` 先尝试补全缺失交易日，`src/audit_data_completeness.py` 再做硬性门禁；核心数据未通过完备性审计时会中断流水线，避免用缺失数据生成信号。

## 3. 脚本职责

| 脚本 | 职责 | 主要输出 |
| --- | --- | --- |
| `src/update_sqlite_data.py` | 更新 A 股日线、人气榜、涨停池、龙虎榜、市场温度 | `daily_bars`、`popularity_rankings`、`limit_up_pool`、`lhb_records`、`lhb_seats`、`market_daily` |
| `src/update_etf.py --spot-only --skip-holdings` | 用实时 ETF 快照更新最新交易日 ETF 数据 | `etf_daily` |
| `src/update_shares.py` | 更新股本等基础数据 | SQLite 基础表 |
| `src/audit_data_completeness.py` | 审计交易日连续性、日线覆盖、ETF/人气榜/涨停池新鲜度、重复、空值和 OHLC 异常 | 退出码、日志、可选 `data_quality_issues` |
| `src/update_zt_pool.py` | 更新涨停池兼容数据 | legacy `zt_pool` |
| `src/screener.py` | 生成选股信号 | `screen_results` |
| `src/backtest_new_high_volume.py` | 运行策略回测 | `strategy_backtests`、回测报告 |
| `src/generate_report.py` | 生成静态页面和摘要 | `reports/latest`、`summary.json`、`monitor.html` |
| `src/health_check.py` | 数据质量检查 | 日志和质量问题记录 |

## 3.1 完备性审计

生产日更在核心数据更新后运行：

```bash
python src/audit_data_completeness.py \
  --db data/quant.db \
  --audit-config config/audit_completeness.yaml \
  --lookback-days 20 \
  --record-issues \
  --socket-timeout 20
```

审计失败会返回非 0 退出码。当前硬性检查：

- `daily_bars`：最近交易日窗口内每日记录数不少于阈值，默认 `5000`；检查重复 `(code, date)`、必要字段空值、OHLC/成交量基础约束。
- `market_daily`：最近交易日窗口内每日必须有记录。
- `etf_daily`：最新预期交易日必须有记录，默认不少于 `300` 行。
- `popularity_rankings`：最新预期交易日至少一个来源不少于 `50` 行。
- `limit_up_pool`：最新预期交易日默认至少 `1` 行。
- `lhb_records`：默认不强制每日必须有记录；需要时可加 `--strict-lhb`。

默认阈值集中在 `config/audit_completeness.yaml`。命令行参数优先级更高，可用于临时调试或应急放宽。

可单独输出机器可读结果：

```bash
python src/audit_data_completeness.py \
  --db data/quant.db \
  --lookback-days 20 \
  --json-output reports/latest/data_completeness.json
```

## 4. 人气榜更新策略

`src/update_sqlite_data.py` 负责人气榜写入 `popularity_rankings`。

优先级：

```text
AkShare stock_hot_rank_em -> 东方财富 direct fallback -> 标准化 CSV fallback
```

降级说明：

- AkShare 接口可用时，使用 `stock_hot_rank_em`。
- AkShare 返回非 JSON、连接重置或空结果时，使用东方财富 direct fallback。
- direct fallback 会先获取 Top100 排名，再尝试补充股票名称和行情；行情补充失败时仍写入排名，名称可降级为代码。
- 如果接口都失败，再尝试读取运行时生成的标准化 CSV：`reports/hot_rank_multi_source_snapshot_latest.csv` 和 `reports/hot_rank_wencai_last30_normalized.csv`。`reports/` 属于运行产物，不再提交到 Git。

验收标准：

- `popularity_rankings` 最新日期等于 `/api/health.expected_trade_date`。
- `/api/health.modules` 中「人气热榜」状态为 `fresh`。

### 历史人气榜回补

历史人气榜优先使用同花顺/问财按日期查询，东财个股历史仅用于补缺，不放入每日主链路。

同花顺按交易日回补：

```bash
python scripts/backfill_ths_popularity_history.py \
  --db data/quant.db \
  --start-date 2025-06-27 \
  --end-date 2026-06-26 \
  --rank-limit 100 \
  --request-budget 20 \
  --sleep 2.0
```

东财个股历史补缺：

```bash
python scripts/backfill_popularity_history.py \
  --db data/quant.db \
  --start-date 2025-06-27 \
  --end-date 2026-06-26 \
  --rank-limit 100 \
  --request-budget 300 \
  --sleep 2.0
```

东财全量历史排名使用独立来源，适合后续分析完整排名分布：

```bash
python scripts/backfill_popularity_history.py \
  --db data/quant.db \
  --start-date 2025-06-27 \
  --end-date 2026-06-26 \
  --all-ranks \
  --request-budget 50 \
  --sleep 3.0 \
  --timeout 20
```

东财全量历史也可以在云主机分片抓取 CSV，再由本机统一导入，避免多机直接写 SQLite：

```bash
REMOTE_HOST=aws BATCH_SIZE=50 SLEEP_SECONDS=3 TIMEOUT=20 \
  scripts/run_eastmoney_popularity_remote_batch.sh
```

注意：

- 两个脚本默认只写入 `daily_bars` 已存在的交易日，过滤周末/非交易日排名。
- 同花顺脚本以 `ths_pywencai_hot_rank` 写入 `popularity_rankings`，按日期请求 Top N，适合作为历史主源。
- 东财 Top100 默认以 `eastmoney_hot_rank_detail_em` 写入；`--all-ranks` 以 `eastmoney_hot_rank_detail_em_all` 写入，避免和 Top100 策略源混用。
- 东财个股历史回补仍需要逐股请求；全市场一次性回扫存在封 IP 风险，脚本默认拒绝无上限全量扫描。
- 建议按 `--request-budget` 或 `BATCH_SIZE` 小批量、低频、断点续跑；重复执行会跳过已完成股票并继续下一批。
- `--max-symbols` 仅用于小样本调试；仅在可控网络下显式使用 `--allow-full-scan`。
- 通达信当前未找到可靠历史人气榜接口，仍主要用于行情、盘口和 K 线。

## 5. ETF 更新策略

`src/update_etf.py --spot-only --skip-holdings` 负责每日 ETF 当日快照。

设计原则：

- 日更主链路只保证 ETF 最新交易日快照，不采集持仓。
- `--spot-only` 跳过历史 K 线接口，避免外部历史接口超时导致整条流水线阻塞。
- `--skip-holdings` 跳过持仓采集，避免季度持仓接口长时间运行。
- ETF 持仓属于低频数据，不放入每日主链路；需要时单独运行持仓任务。

验收标准：

- `etf_daily` 最新日期等于 `/api/health.expected_trade_date`。
- `/api/health.modules` 中「ETF雷达」状态为 `fresh`。
- 如果技术指标因为只使用快照而不足，报告可展示保守信号，但日期不能停留在旧交易日。

## 6. 报告生成

`src/generate_report.py` 负责生成静态报告和监控页。

主要输出：

| 文件 | 用途 |
| --- | --- |
| `reports/latest/index.html` | 首页 |
| `reports/latest/report.html` | 综合报告 |
| `reports/latest/summary.json` | 首页和监控页摘要数据 |
| `reports/latest/monitor.html` | 运行监控页 |
| `reports/YYYY-MM-DD/` | 历史归档 |

`summary.json` 包含 Git commit 信息，用于确认线上页面对应的代码版本。

## 7. 运行监控

运行监控由两部分组成：

| 入口 | 用途 |
| --- | --- |
| `/monitor.html` | 面向人的监控页，展示模块状态、报告时间、Git commit、日志路径 |
| `/api/health` | 面向脚本和排障的 JSON 健康接口 |

`/api/health` 以交易日历判断 expected trade date。必需模块未更新时返回 `error`；非必需 legacy 表异常保留在 `warnings`，但不影响总状态。

## 8. 日志与排障

日更日志路径：

```text
/data/quant_research/logs/daily-run-YYYYMMDD.log
```

常用排障命令：

```bash
tail -f /data/quant_research/logs/daily-run-$(date +%Y%m%d).log
curl http://140.245.53.52:8080/api/health
ps -eo pid,ppid,stat,etime,cmd | grep -E 'update_sqlite_data|update_etf|generate_report|quant-daily' | grep -v grep
```

如果 `/api/health` 显示某个模块 stale，优先查看该模块在日更日志中的 `START`、`OK`、`FAIL` 记录。
