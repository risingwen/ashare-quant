# A股量化平台

基于 Python、AkShare、SQLite、nginx、systemd 和 GitHub Actions 的 A 股量化研究平台。生产环境部署在 Oracle Cloud，按交易日更新数据并生成静态报告，同时提供 Flask API 查询和运行监控页面。

## 在线入口

生产地址：

```text
http://140.245.53.52:8080/
```

主要页面：

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
| [架构设计](docs/ARCHITECTURE.md) | 数据分层、生产架构、页面/API/数据库关系 |
| [数据流水线](docs/DATA_PIPELINE.md) | 每日任务顺序、脚本职责、降级策略 |
| [运维手册](docs/OPERATIONS_RUNBOOK.md) | Oracle 路径、systemd、GitHub Actions、部署、日志、回滚 |
| [事故记录](docs/INCIDENT_LOG.md) | 已发生问题、根因、修复、验证与预防 |
| [运行监控与兜底决策](docs/adr/0001-runtime-monitoring-and-fallbacks.md) | 关键架构决策记录 |
| [开发环境](docs/dev-setup.md) | 本地环境、生产环境和部署细节补充 |

## 生产基准

当前文档以 2026-05-17 的生产状态为基准：

| 项目 | 值 |
| --- | --- |
| 生产目录 | `/data/quant_research` |
| Python 虚拟环境 | `/data/quant_research_venv` |
| SQLite 数据库 | `/data/quant_research/data/quant.db` |
| 最新有效交易日 | `2026-05-15` |
| 线上健康状态 | `/api/health status=ok` |
| 基准 Git commit | `358dc20` |

## 常用命令

查看线上健康状态：

```bash
curl http://140.245.53.52:8080/api/health
```

手动部署最新代码并重新生成报告：

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

- 新增功能或修改主链路时，同步更新 [数据流水线](docs/DATA_PIPELINE.md) 或 [架构设计](docs/ARCHITECTURE.md)。
- 线上故障、数据异常、部署异常必须补充到 [事故记录](docs/INCIDENT_LOG.md)。
- 影响长期行为的技术决策必须新增 ADR，放在 `docs/adr/`。
- 文档只记录 secret 名称和配置方式，不记录私钥、token、密码或任何 secret 原文。
