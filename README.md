# A股量化平台

基于 Python、AkShare、SQLite、nginx、systemd 和 GitHub Actions 的 A 股量化研究平台。生产环境部署在 Oracle Cloud，核心链路是按交易日更新数据、生成静态报告，并通过 Flask API 暴露健康检查和运行监控。

## 在线入口

生产地址：

```text
http://140.245.53.52:8080/
```

| 页面 | 地址 | 用途 |
| --- | --- | --- |
| 首页 | `/` | 平台入口、模块导航、最新数据与 Git commit |
| 综合报告 | `/report.html` | 每日综合报告、榜单、回测、数据质量 |
| 人气热榜 | `/hot_rank_iframe.html` | 人气榜页面 |
| 龙虎榜 | `/longhu.html` | 龙虎榜查询 |
| ETF雷达 | `/etf.html` | ETF 快照、技术信号和持仓展示 |
| 运行监控 | `/monitor.html` | 数据更新状态、运行日志路径、Git commit |
| 健康接口 | `/api/health` | 模块级数据新鲜度和部署版本 |

## 文档入口

| 文档 | 内容 |
| --- | --- |
| [架构设计](docs/ARCHITECTURE.md) | 线上架构、数据流、API、SQLite 表、静态报告生成链路 |
| [数据流水线](docs/DATA_PIPELINE.md) | 每日任务顺序、脚本职责、ETF 快照和报告生成 |
| [运维手册](docs/OPERATIONS_RUNBOOK.md) | Oracle 路径、systemd、GitHub Actions、部署、日志、回滚 |
| [开发记录](docs/DEVELOPMENT_LOG.md) | 按日期记录已完成事项、验证命令和后续动作 |
| [仓库清理清单](docs/REPO_CLEANUP.md) | 根目录整理原则、已删除内容、下一批清理候选 |
| [事故记录](docs/INCIDENT_LOG.md) | 线上问题、根因、修复、验证与预防 |
| [ADR 0001](docs/adr/0001-runtime-monitoring-and-fallbacks.md) | 运行监控、ETF spot-only、人气榜 fallback 等决策 |
| [开发环境](docs/dev-setup.md) | 本地环境、生产环境和部署细节补充 |

## 仓库结构

根目录只保留工程入口和核心目录。旧工具、历史文档和一次性排查材料集中放入 `archive/`，运行产物不再提交。

| 路径 | 用途 |
| --- | --- |
| `src/` | 生产代码：数据更新、报告生成、API、健康检查 |
| `scripts/` | 可复用 CLI：回测、导出、生产辅助脚本 |
| `deploy/` | Oracle 部署、systemd、nginx 配置 |
| `config/` | 当前 YAML 配置和策略模板 |
| `tests/` | pytest 测试入口 |
| `docs/` | 当前有效工程文档 |
| `archive/` | 历史脚本、旧文档、一次性诊断材料 |
| `data/`、`reports/`、`logs/` | 运行时目录，默认不提交运行产物 |

## 生产基准

当前工程文档以 2026-05-17 已确认的线上状态为基准。实际生产版本以 `/api/health` 返回的 `git.short_commit` 为准。

| 项目 | 值 |
| --- | --- |
| 生产目录 | `/data/quant_research` |
| Python 虚拟环境 | `/data/quant_research_venv` |
| SQLite 数据库 | `/data/quant_research/data/quant.db` |
| 最新有效交易日 | `2026-05-15` |
| 线上健康状态 | `/api/health status=ok` |
| 已确认健康基线 | `358dc20` |

## 常用命令

查看线上健康状态：

```bash
curl http://140.245.53.52:8080/api/health
```

手动部署最新代码并重启 API：

```bash
cd /data/quant_research
REFRESH_HOT_RANK_FALLBACK=0 RESTART_API=1 RUN_FULL_PIPELINE=0 bash deploy/scripts/deploy_oracle.sh
```

查看日更日志：

```bash
tail -f /data/quant_research/logs/daily-run-$(date +%Y%m%d).log
```

更多运维命令见 [运维手册](docs/OPERATIONS_RUNBOOK.md)。

## 维护规则

- 新增功能或修改主链路时，同步更新 [架构设计](docs/ARCHITECTURE.md)、[数据流水线](docs/DATA_PIPELINE.md) 或 [开发记录](docs/DEVELOPMENT_LOG.md)。
- 线上故障、数据异常、部署异常必须补到 [事故记录](docs/INCIDENT_LOG.md)。
- 一次性排查脚本不要继续堆在仓库根目录；有保留价值的放入 `archive/diagnostics/`，长期工具放入 `scripts/`。
- 影响长期行为的技术决策必须新增 ADR，放在 `docs/adr/`。
- 文档只记录 secret 名称和配置方式，不记录私钥、token、密码或任何 secret 原文。
