# 生产运维手册

本文档记录 A 股量化平台生产环境的常用运维动作。所有命令默认在 Oracle Cloud 主机执行，除非特别说明。

## 1. 生产环境基线

| 项目 | 值 |
| --- | --- |
| 公网地址 | `http://140.245.53.52:8080/` |
| 生产目录 | `/data/quant_research` |
| Python 虚拟环境 | `/data/quant_research_venv` |
| SQLite 数据库 | `/data/quant_research/data/quant.db` |
| 静态报告目录 | `/data/quant_research/reports/latest` |
| 运行日志目录 | `/data/quant_research/logs` |
| 日更日志 | `/data/quant_research/logs/daily-run-YYYYMMDD.log` |
| nginx 配置 | `/etc/nginx/sites-available/quant_research_8080` |

## 2. systemd 服务

| 服务 | 用途 |
| --- | --- |
| `quant-api.service` | Flask API 服务，提供 `/api/*` |
| `quant-daily.service` | 每日数据更新流水线 |
| `quant-daily.timer` | 工作日定时触发 `quant-daily.service` |

常用命令：

```bash
sudo systemctl status quant-api.service
sudo systemctl status quant-daily.service
sudo systemctl status quant-daily.timer
systemctl list-timers --all | grep quant-daily
```

重启 API：

```bash
sudo systemctl restart quant-api.service
sudo systemctl is-active quant-api.service
```

手动触发日更：

```bash
sudo systemctl start quant-daily.service
sudo journalctl -u quant-daily.service -f
```

查看当天日更日志：

```bash
tail -f /data/quant_research/logs/daily-run-$(date +%Y%m%d).log
```

## 3. GitHub Actions 部署

工作流文件：

```text
.github/workflows/deploy.yml
```

必需 Actions Secrets：

| Secret | 用途 |
| --- | --- |
| `ORACLE_HOST` | Oracle 主机公网 IP，例如 `140.245.53.52` |
| `ORACLE_USER` | SSH 用户，例如 `ubuntu` |
| `ORACLE_SSH_KEY` | 可登录生产机的 SSH 私钥内容 |

安全要求：

- 只在 GitHub Actions Secrets 中保存 `ORACLE_SSH_KEY`。
- 文档和日志不得记录私钥、token、密码或 secret 原文。
- 如果更换云主机或 SSH key，先本地验证 SSH 登录，再更新 GitHub Secrets。

## 4. 手动部署

推荐使用仓库内脚本：

```bash
cd /data/quant_research
REFRESH_HOT_RANK_FALLBACK=0 RESTART_API=1 RUN_FULL_PIPELINE=0 bash deploy/scripts/deploy_oracle.sh
```

脚本名称：`deploy/scripts/deploy_oracle.sh`

脚本职责：

- `git fetch` 并 `git pull --ff-only origin master`
- 安装最新版日更脚本到 `/data/quant_research/logs/quant-daily-run.sh`
- 重新生成 `reports/latest`
- 可选重启 `quant-api.service`
- 可选触发完整日更流水线

常用参数：

```bash
# 只部署代码、重建报告、重启 API
REFRESH_HOT_RANK_FALLBACK=0 RESTART_API=1 RUN_FULL_PIPELINE=0 bash deploy/scripts/deploy_oracle.sh

# 部署后触发完整生产流水线
RUN_FULL_PIPELINE=1 bash deploy/scripts/deploy_oracle.sh

# 只重建静态报告，不重启 API
RESTART_API=0 bash deploy/scripts/deploy_oracle.sh
```

## 5. 健康检查

公网健康接口：

```bash
curl http://140.245.53.52:8080/api/health
```

关键字段：

| 字段 | 含义 |
| --- | --- |
| `status` | 总体状态，`ok` 表示必需模块已更新 |
| `expected_trade_date` | 当前应当检查的最新有效交易日 |
| `modules` | 每个数据模块的状态、最新日期和行数 |
| `errors` | 必需模块错误 |
| `warnings` | 非阻塞告警，例如 legacy 表异常 |
| `git.short_commit` | 当前线上代码短 commit |
| `git.dirty` | 是否存在代码/配置层未提交变更，运行产物不计入 |

页面级验证：

```bash
curl 'http://140.245.53.52:8080/monitor.html?v=manual-check'
curl 'http://140.245.53.52:8080/summary.json?v=manual-check'
```

## 6. 回滚

仅在新版本导致 API、报告生成或日更任务不可用时回滚。

回滚到指定 commit：

```bash
cd /data/quant_research
git fetch origin
git checkout <commit>
REFRESH_HOT_RANK_FALLBACK=0 RESTART_API=1 RUN_FULL_PIPELINE=0 bash deploy/scripts/deploy_oracle.sh
```

恢复到 `master` 最新版本：

```bash
cd /data/quant_research
git checkout master
git pull --ff-only origin master
REFRESH_HOT_RANK_FALLBACK=0 RESTART_API=1 RUN_FULL_PIPELINE=0 bash deploy/scripts/deploy_oracle.sh
```

回滚后必须验证：

```bash
curl http://140.245.53.52:8080/api/health
sudo systemctl is-active quant-api.service
```

## 7. 常见问题定位

查看 API 日志：

```bash
tail -200 /data/quant_research/logs/api_server.log
```

查看日更日志：

```bash
ls -lt /data/quant_research/logs/daily-run-*.log | head
tail -200 /data/quant_research/logs/daily-run-$(date +%Y%m%d).log
```

检查是否存在异常长跑任务：

```bash
ps -eo pid,ppid,stat,etime,cmd | grep -E 'update_sqlite_data|update_etf|generate_report|quant-daily' | grep -v grep
```

检查生产仓库代码状态：

```bash
cd /data/quant_research
git status -sb
git log --oneline -5
```

运行产物如 `data/experiments/`、`reports/*.csv` 可能让 `git status` 显示 dirty，但不代表线上代码版本不一致。以 `/api/health` 中的 `git.dirty` 为准。
