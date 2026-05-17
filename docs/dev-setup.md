# 开发环境与开发流程指南

本文档重新定义本项目的推荐工作方式：

- **代码放 GitHub**
- **日常开发在本机完成**
- **云主机保存正式数据库与生产任务**
- **本机默认不直接维护全量生产库**

适用场景：

- 新机器初始化开发环境
- 本机调试脚本 / 策略 / 页面
- 验证本机到云端 API / SSH / 数据库访问链路
- 统一本机开发与云端生产的边界

---

## 1. 推荐架构

### 1.1 角色划分

| 环境 | 作用 | 保存内容 |
|---|---|---|
| 本机 | 写代码、调试、轻量分析、小样本回测 | 源码、虚拟环境、少量测试数据、裁剪版数据库（可选） |
| GitHub | 代码协作与版本管理 | `src/`、`scripts/`、`config/`、`docs/`、测试代码 |
| Oracle 云主机 | 正式数据库、正式更新任务、正式报表/API | `quant.db`、systemd、nginx、生产日志、正式 reports |

### 1.2 默认原则

1. **不要在云主机上直接改代码作为日常开发方式**。
2. **不要把数据库、Parquet 全量数据、reports 生成物提交到 Git**。
3. **本机开发优先调用云端 API 或使用裁剪版数据集**。
4. **正式增量更新、正式报表发布仍在云主机执行**。

---

## 2. 当前已知环境

### 2.1 GitHub 仓库

```bash
git@github.com:risingwen/ashare-quant.git
```

### 2.2 云主机

| 项目 | 值 |
|---|---|
| 主机 IP | `140.245.53.52` |
| API 入口 | `http://140.245.53.52:8080/api/` |
| 正式数据库 | `/data/quant_research/data/quant.db` |
| Python 环境 | `/data/quant_research_venv` |
| 部署目录 | `/data/quant_research` |

### 2.3 本机推荐虚拟环境

当前已验证可用的本机虚拟环境路径：

```bash
/LocalRun/xiwen.xing/01_envs/ashare-quant
```

启动方式：

```bash
source /LocalRun/xiwen.xing/01_envs/ashare-quant/bin/activate
```

或直接调用：

```bash
/LocalRun/xiwen.xing/01_envs/ashare-quant/bin/python
```

---

## 3. 已验证的连通性结论

以下结论基于本机实测。

| 检查项 | 结果 | 说明 |
|---|---|---|
| `GET /api/health` | ✅ 已验证 | 公网 API 可达，返回 `200 OK` |
| `GET /api/daily`（无 API Key） | ✅ 已验证 | 返回 `401 unauthorized`，说明鉴权生效 |
| `GET /api/daily`（携带有效 API Key） | ✅ 已验证 | 已返回 `600519` 的实际日线数据 |
| SSH 到 `ubuntu@140.245.53.52` | ✅ 已验证 | 可通过本机已存在的 SSH key 登录 |
| 云端裁剪版数据库导出到本机 | ✅ 已验证 | 已成功导出 `quant_dev.db` 并在本机完成健康检查 |

### 3.1 已验证成功的 API 健康检查

```bash
curl http://140.245.53.52:8080/api/health
```

返回示例：

```json
{"latest":{"daily_bars":"2026-05-15","lhb_records":"2026-05-15","market_daily":"2026-05-15","zt_pool":"2026-05-15"},"status":"ok"}
```

### 3.2 已验证的鉴权行为

未携带 `X-API-Key` 请求受保护接口：

```bash
curl "http://140.245.53.52:8080/api/daily?code=600519&start=2026-05-01&limit=5"
```

返回：

```json
{"error":"unauthorized"}
```

这说明：

- 公网 API 服务在线
- 受保护接口需要 API Key
- 当前本机**尚未配置 `QUANT_API_KEY`**

### 3.3 已验证成功的受保护接口访问

使用本机保存的有效 `QUANT_API_KEY` 后，已实测成功访问：

```bash
curl -H "X-API-Key: ${QUANT_API_KEY}" \
  "http://140.245.53.52:8080/api/daily?code=600519&start=2026-05-01&limit=5"
```

实测返回 `200 OK`，并返回 `600519` 的真实日线数据。

说明：

- 本机到云端受保护 API 的完整调用链路已打通
- 当前 API Key 可正常用于业务接口
- 真实 key 仍只应保存在本机 `.env` 或 CI secrets 中，不应写入仓库

### 3.4 已验证成功的 SSH 信息

本机 `~/.ssh/config` 中已有可用配置：

```sshconfig
Host oracle-free
    HostName 140.245.53.52
    User ubuntu
    IdentityFile ~/.ssh/oracle-free-2026-04-05
```

已实测成功的连接方式：

```bash
ssh oracle-free
```

或：

```bash
ssh -i ~/.ssh/oracle-free-2026-04-05 ubuntu@140.245.53.52
```

本机实测成功返回：

- hostname: `instance-20260406-1138`
- user: `ubuntu`

额外说明：当前目录下其他常见 key（如 `id_ed25519`、`id_rsa`、`id_ed25519_ashare_quant` 等）对该主机验证失败；当前确认可用的是：

```bash
~/.ssh/oracle-free-2026-04-05
```

### 3.5 云端运行态实测结果

已通过 SSH 在云主机上完成以下核验：

- 代码目录存在：`/data/quant_research`
- 数据库文件存在：`/data/quant_research/data/quant.db`
- 当前数据库文件大小约：`537M`
- 云端仓库分支状态：`master...origin/master`
- 服务状态：
  - `quant-api` = `active`
  - `quant-daily.timer` = `active`
  - `nginx` = `active`
- 云端 Python 环境可用：`Python 3.12.3`
- 云端健康检查 dry-run 结果：`[HEALTHY] 所有表数据均已更新到最新交易日，无需补全。`

### 3.6 云端裁剪版数据库导出实测结果

已完成以下实测：

1. 在云端从正式库 `/data/quant_research/data/quant.db` 导出裁剪版 SQLite
2. 成功生成临时文件：`/tmp/quant_dev.db`
3. 成功拉回本机：`data/quant_dev.db`
4. 本机完成健康检查 dry-run，结果为 `HEALTHY`

本次裁剪范围：

- `stocks`：全表
- `daily_bars`：`2026-01-01` 至今
- `market_daily`：`2026-01-01` 至今
- `zt_pool`：`2026-01-01` 至今（实际数据起始为 `2026-04-10`）
- `lhb_records`：`2026-01-01` 至今

本机实测结果：

- 文件大小约：`55M`
- `stocks`：`5707` 行
- `daily_bars`：`438894` 行
- `market_daily`：`84` 行
- `zt_pool`：`1516` 行
- `lhb_records`：`5993` 行

### 3.7 当前仍待补充验证的部分

以下问题仍建议后续继续核验：

- 云端定时任务与 API 服务是否与当前仓库代码完全一致
- 是否需要进一步扩展裁剪脚本支持更多表
- 是否需要进一步补充 `zt_previous`、`etf_daily`、`etf_holdings`、`screen_results` 等表

---

## 4. 本机开发模式

推荐分为两种模式。

### 模式 A：API 优先（默认）

适用于：

- 页面开发
- API 客户端开发
- 小范围策略验证
- 不需要完整生产数据库的调试

特点：

- 本机只保留代码和小量缓存
- 通过云端 API 获取数据
- 不要求本机持有 `quant.db`

### 模式 B：裁剪库 / 小样本数据

适用于：

- 本地跑脚本
- 本地复现部分回测
- 本地生成实验报告

特点：

- 从云端导出裁剪版 SQLite
- 或仅同步需要的 Parquet 分区
- 不建议同步整份生产数据库到本机长期维护

---

## 5. 本机初始化步骤

### 5.1 Clone 仓库

```bash
git clone git@github.com:risingwen/ashare-quant.git
cd ashare-quant
```

### 5.2 创建虚拟环境

推荐把虚拟环境放在工作区外：

```bash
python3 -m venv /LocalRun/xiwen.xing/01_envs/ashare-quant
source /LocalRun/xiwen.xing/01_envs/ashare-quant/bin/activate
pip install -r requirements.txt
```

### 5.3 补齐当前开发依赖

当前仓库实际运行还依赖：

```bash
pip install pytest pyyaml
```

> 说明：这两个依赖目前未完整体现在 `requirements.txt` 中，但本机实测运行需要它们。

### 5.4 创建运行目录

部分脚本默认写日志到 `logs/`，首次运行前建议创建：

```bash
mkdir -p logs data
```

### 5.5 生成本地配置

```bash
cp config.example.yaml config.yaml
```

如果你走 API 优先模式，`config.yaml` 主要用于本地脚本默认配置；
如果你走裁剪库模式，还需要根据实际数据路径调整相关配置。

---

## 6. API 模式的本机配置

在项目根目录创建 `.env`：

```bash
QUANT_API_BASE=http://140.245.53.52:8080
QUANT_API_KEY=<向项目管理员获取或保存在你本机的现有 key>
```

> 不要把真实 `QUANT_API_KEY` 写入仓库文档、配置样例或提交到 Git。真实 key 只应保存在本机 `.env`、密码管理器或 CI secrets 中。

建议先确认环境变量是否就绪：

```bash
python3 -c "import os; print(bool(os.environ.get('QUANT_API_KEY')))"
```

如果你已经拿到真实 key，可以在本机 shell 中临时验证：

```bash
export QUANT_API_KEY='<你的真实 key>'
curl -H "X-API-Key: ${QUANT_API_KEY}" "http://140.245.53.52:8080/api/daily?code=600519&start=2026-05-01&limit=5"
```

> 上面的命令只演示使用方式。不要把真实 key 回写进文档文件。

如果你使用 `python-dotenv`：

```python
import os
from dotenv import load_dotenv

load_dotenv()
base = os.environ["QUANT_API_BASE"]
api_key = os.environ["QUANT_API_KEY"]
```

---

## 7. 数据访问方式

### 7.1 方式一：访问云端 API（推荐默认）

优点：

- 最轻量
- 不依赖数据库文件同步
- 本机磁盘压力小

示例：

```python
import os
import requests
from dotenv import load_dotenv

load_dotenv()

BASE = os.environ["QUANT_API_BASE"]
HEADERS = {"X-API-Key": os.environ["QUANT_API_KEY"]}

resp = requests.get(
    f"{BASE}/api/daily",
    params={"code": "600519", "start": "2026-01-01", "limit": 20},
    headers=HEADERS,
)
resp.raise_for_status()
print(resp.json())
```

### 7.2 方式二：从云端导出裁剪版 SQLite

前提：

- 当前机器具备 SSH 权限
- 云主机存在 `sqlite3`

推荐直接使用仓库脚本：

```bash
python scripts/export_trimmed_oracle_db.py
```

常用参数：

```bash
python scripts/export_trimmed_oracle_db.py --start-date 2026-01-01
python scripts/export_trimmed_oracle_db.py --host oracle-free --output data/quant_dev.db
```

脚本默认行为：

- 从 `oracle-free` 主机导出
- 读取云端正式库 `/data/quant_research/data/quant.db`
- 导出 `stocks` 全表
- 导出 `daily_bars`、`market_daily`、`zt_pool`、`lhb_records` 的指定日期范围子集
- 自动复制到本机 `data/quant_dev.db`

如果你需要理解脚本内部流程，可以把它理解为：

1. SSH 到云主机生成 `/tmp/quant_dev.db`
2. 通过 `scp` 拉回本机

当前这条脚本链路已经实测通过。

### 7.3 方式三：同步局部 Parquet

适用于：

- DuckDB 分析
- 特征工程
- 本地数据探索

建议只同步需要的日期范围或分区，不要默认同步全量历史数据。

---

## 8. 日常开发流程

### 8.1 推荐工作流

```text
本机开发代码
    ↓
本机运行基础校验 / 小样本验证
    ↓
提交到 GitHub
    ↓
GitHub Actions 部署到云主机
    ↓
云主机重启 API 或继续执行定时任务
```

### 8.2 本机开发建议顺序

1. 激活虚拟环境
2. `git pull`
3. 修改代码 / 配置 / 文档
4. 跑本地校验命令
5. 提交 Git
6. 推送 GitHub

### 8.3 推荐本地校验命令

```bash
# 语法检查
python -m compileall src scripts

# 测试收集
python -m pytest --collect-only -q

# 基础环境检查
python -m pytest tests/integration/test_system.py -m "integration and network"

# 查看脚本 CLI 是否能正常启动
python scripts/prepare_features.py --help
python src/update_sqlite_data.py --help
```

注意：

- `tests/integration/test_system.py` 中的 AkShare 连通性可能受外部源波动影响
- 如果单股抓取、Parquet、DuckDB 都通过，而 AkShare 总体探测失败，通常更像是外部源不稳定，不是本机环境损坏

---

## 9. GitHub 与云端部署流程

当前仓库已有自动部署工作流：

文件：

```text
.github/workflows/deploy.yml
```

核心行为：

1. 监听 `master` 分支 push
2. 通过 `appleboy/ssh-action` 登录云主机
3. 在 `/data/quant_research` 执行 `git pull origin master`
4. 重启 `quant-api`

### 9.1 需要的 GitHub Secrets

| Secret | 说明 |
|---|---|
| `ORACLE_HOST` | 云主机地址，当前为 `140.245.53.52` |
| `ORACLE_USER` | 登录用户，当前文档示例为 `ubuntu` |
| `ORACLE_SSH_KEY` | 拥有云主机权限的私钥内容 |

### 9.2 当前注意事项

当前已统一为：

- workflow 监听 `master`
- 远端执行 `git pull origin master`

与当前仓库真实默认分支保持一致。

### 9.3 当前已验证可用的手动部署流程

除了 GitHub Actions 外，当前已经实测通过一套可直接落地的手动部署流程，适合以下场景：

- GitHub 已 push，但云端仓库尚未自动同步
- 页面改动需要立即上线
- 需要手动确认生产目录与线上页面是否一致

#### 步骤 1：登录云主机并更新代码

```bash
ssh oracle-free

cd /data/quant_research
git fetch origin
git pull --ff-only origin master
git rev-parse HEAD
```

#### 步骤 2：按改动类型执行对应动作

推荐优先使用仓库内的一键部署脚本：

```bash
ssh oracle-free 'bash /data/quant_research/deploy/scripts/deploy_oracle.sh'
```

常用变体：

```bash
# 启动整条生产流水线
ssh oracle-free 'RUN_FULL_PIPELINE=1 bash /data/quant_research/deploy/scripts/deploy_oracle.sh'

# 页面刷新但不重启 API
ssh oracle-free 'RESTART_API=0 bash /data/quant_research/deploy/scripts/deploy_oracle.sh'
```

脚本默认会：

1. 在 `/data/quant_research` 执行 `git fetch` + `git pull --ff-only origin master`
2. 重新生成 `report.html`、`summary.json`、`index.html`
3. 默认重启 `quant-api.service`
4. 自动打印关键验证信息

与当前线上环境相关的补充说明：

- Oracle 生产环境已实测 `AkShare.stock_hot_rank_em` 可用
- 同时 `stock_hot_rank_wc` 不存在
- 因此仓库中的人气榜更新逻辑已补充为：如果只有 `stock_hot_rank_em` 可用，则即使在非交易日运行，也继续尝试该接口，避免首页/报告中的“人气热榜”长期停留在旧日期
- 如果 AkShare 人气接口本身返回异常，更新逻辑还会继续读取运行时 `reports/` 下的标准化多源热榜 CSV 作为兜底写入 `popularity_rankings`。`reports/` 属于运行产物，不再提交到 Git
- 一键部署脚本默认会先执行：
  - `scripts/try_hot_rank_multi_source.py`
  - `scripts/export_hot_rank_multi_source_pages.py`
  以刷新这些兜底 CSV

如果你不想用脚本，也可以继续按下面的手动步骤执行。

如果改动影响 **API 逻辑**：

```bash
sudo systemctl restart quant-api.service
sudo systemctl status quant-api.service
```

如果改动影响 **静态报告页面 / summary.json / report.html**：

```bash
/data/quant_research_venv/bin/python /data/quant_research/src/generate_report.py \
  --db /data/quant_research/data/quant.db \
  --report-dir /data/quant_research/reports \
  --start-date 2025-01-01
```

如果要验证整条生产链路，而不只是单独刷新报告：

```bash
sudo systemctl start quant-daily.service
sudo journalctl -u quant-daily.service -f
```

本次已实测确认：`quant-daily.service` 可以走到并完成 `generate_report`，线上报告能够刷新。

#### 步骤 3：验证线上实际生效

先看云端生成物：

```bash
python3 -c 'from pathlib import Path; p=Path("/data/quant_research/reports/latest/report.html"); text=p.read_text(encoding="utf-8"); print(text.split("<title>",1)[1].split("</title>",1)[0]); print("数据更新状态" in text)'
```

再看公网接口与页面：

```bash
curl http://140.245.53.52:8080/api/health
curl http://140.245.53.52:8080/report.html?v=manual-check
```

> 注意：如果服务器文件已经更新，但浏览器仍看到旧页面，通常是缓存问题。可以在 URL 后加查询参数强制刷新，例如 `report.html?v=20260517`。

---

## 10. 云端运维边界

以下动作应视为**生产动作**，优先在云主机完成：

- 正式日线增量更新
- 正式回测结果产出
- 正式静态报表生成
- nginx/API 服务重启
- 生产数据库维护

示例命令：

```bash
systemctl status quant-daily.timer
sudo systemctl restart quant-api
sudo systemctl start quant-daily
tail -f /data/quant_research/logs/api_server.log
```

---

## 11. 当前已知待补事项

这是本次整理后仍需要补齐的内容：

1. **在本机 `.env` 中配置可用的 `QUANT_API_KEY` 并完成受保护接口实测**
2. **视需要扩展裁剪脚本支持更多表和自定义表选择**
3. **如未来切换默认分支，需同步更新 workflow 与文档中的 `master` 引用**
4. **把 `pytest`、`pyyaml` 补进正式依赖清单**
5. **明确脚本首次运行所需目录（如 `logs/`）的初始化方式**

---

## 11. 开发流程实测结论

截至当前，本项目的开发流程已验证到以下程度：

1. **本机开发环境可用**
   - 外部虚拟环境已创建并可运行
   - `compileall` 通过
   - `pytest --collect-only` 通过
   - 主要脚本 CLI 可启动

2. **本机到云端 API 通路可用**
   - 健康检查接口可访问
   - 鉴权接口在无 key 时正确拒绝
   - 鉴权接口在有 key 时成功返回业务数据

3. **本机到云端 SSH 通路可用**
   - 可通过 `ssh oracle-free` 登录
   - 可检查云端仓库、数据库、服务和 Python 环境

4. **云端生产运行态正常**
   - 数据库存在
   - API / timer / nginx 服务均为 active
   - 健康检查为 healthy

5. **云端裁剪版 SQLite → 本机消费链路已验证完成**

---

## 12. 一句话结论

本项目今后的推荐工作方式是：

> **本机开发，GitHub 管代码，云端保留正式数据库与生产任务；本机默认通过 API 或裁剪数据集工作，而不是长期直接在云主机上改代码。**
