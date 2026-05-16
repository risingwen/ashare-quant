# 开发环境搭建指南

本文档适用于在**新机器**上从零搭建开发环境，直接使用云主机 API 访问数据，无需在本地维护数据库。

---

## 前置条件

- Python 3.11+
- Git
- SSH 访问云主机的权限（可选，仅在需要直接操作数据库时）

---

## 1. Clone 项目

```bash
git clone git@github.com:risingwen/ashare-quant.git
cd ashare-quant
```

---

## 2. 创建虚拟环境

```bash
python -m venv venv
source venv/bin/activate        # Linux / macOS
# venv\Scripts\activate         # Windows

pip install -r requirements.txt
```

---

## 3. 配置环境变量

项目根目录创建 `.env` 文件（已在 `.gitignore` 中，不会上传）：

```bash
# .env
QUANT_API_BASE=http://140.245.53.52:8080
QUANT_API_KEY=<向项目管理员获取>
```

> **云主机地址**：`140.245.53.52`，API 通过 nginx 在 `8080` 端口对外暴露，路径前缀 `/api/`。

在代码中读取：

```python
import os
from dotenv import load_dotenv  # pip install python-dotenv

load_dotenv()
API_BASE = os.environ["QUANT_API_BASE"]
API_KEY  = os.environ["QUANT_API_KEY"]
```

---

## 4. 验证 API 连通性

```bash
# 健康检查（无需认证）
curl http://140.245.53.52:8080/api/health

# 期望返回类似：
# {"latest":{"daily_bars":"2026-05-15","lhb_records":"2026-05-15",
#   "market_daily":"2026-05-15","zt_pool":"2026-05-15"},"status":"ok"}
```

---

## 5. API 接口一览

所有接口需要在 Header 中携带 `X-API-Key`（或 URL 参数 `?api_key=`）。

### 5.1 健康检查

```
GET /api/health
```

无需认证，返回各表最新数据日期。

---

### 5.2 日 K 线

```
GET /api/daily?code=600519&start=2025-01-01&end=2026-05-15&limit=500
```

| 参数 | 说明 | 默认值 |
|---|---|---|
| `code` | 股票代码（必填） | - |
| `start` | 开始日期 | `2025-01-01` |
| `end` | 结束日期 | 今日 |
| `limit` | 最多返回条数 | `500`，上限 `2000` |

返回字段：`date, code, open, high, low, close, volume, amount, pct_chg, turnover, amplitude, change_amount`

---

### 5.3 市场情绪

```
GET /api/market?start=2025-01-01&end=2026-05-15
```

返回 `market_daily` 全部字段，包含涨跌停数量、情绪分等。

---

### 5.4 涨停池

```
# 单日（默认最新交易日）
GET /api/zt?date=2026-05-15

# 区间
GET /api/zt/range?start=2026-05-01&end=2026-05-15&limit=1000
```

---

### 5.5 ETF 行情

```
# 单只 ETF 历史
GET /api/etf?code=510300&start=2025-01-01&limit=250

# 最新一天所有 ETF
GET /api/etf
```

---

### 5.6 龙虎榜

```
# 个股历史龙虎榜（含席位）
GET /api/lhb/stock?code=600519&limit=50

# 营业部历史记录
GET /api/lhb/seat?name=华泰证券上海分公司&limit=200

# 搜索股票
GET /api/lhb/search/stock?q=平安

# 搜索营业部
GET /api/lhb/search/seat?q=华泰
```

---

### 5.7 选股结果

```
# 最新选股信号
GET /api/screen

# 指定日期
GET /api/screen?date=2026-05-15&rule=new_high_momentum
```

---

### 5.8 股票列表

```
# 搜索
GET /api/stocks?q=贵州茅台

# 前 200 只（按代码排序）
GET /api/stocks
```

---

## 6. Python 调用示例

```python
import os
import requests
from dotenv import load_dotenv

load_dotenv()

BASE = os.environ["QUANT_API_BASE"]
HEADERS = {"X-API-Key": os.environ["QUANT_API_KEY"]}


def get_daily(code: str, start: str = "2025-01-01") -> list[dict]:
    resp = requests.get(f"{BASE}/api/daily", params={"code": code, "start": start}, headers=HEADERS)
    resp.raise_for_status()
    return resp.json()["bars"]


def get_market(start: str = "2026-01-01") -> list[dict]:
    resp = requests.get(f"{BASE}/api/market", params={"start": start}, headers=HEADERS)
    resp.raise_for_status()
    return resp.json()


def get_zt(date: str | None = None) -> dict:
    params = {"date": date} if date else {}
    resp = requests.get(f"{BASE}/api/zt", params=params, headers=HEADERS)
    resp.raise_for_status()
    return resp.json()


# 示例
if __name__ == "__main__":
    bars = get_daily("600519", start="2026-01-01")
    print(f"茅台近期日K：{len(bars)} 条，最新收盘 {bars[0]['close']}")

    market = get_market("2026-05-01")
    print(f"市场情绪：最新 {market[0]}")
```

---

## 7. 本地数据库（可选）

如果需要在本地跑完整的数据处理脚本（`update_sqlite_data.py` 等），可以从云主机拉取精简版数据库：

```bash
# 在云主机上生成精简库（2025-01-01 至今，约 150MB）
ssh ubuntu@140.245.53.52 << 'ENDSSH'
sqlite3 /data/quant_research/data/quant.db << 'EOF'
ATTACH '/tmp/quant_dev.db' AS dev;
CREATE TABLE dev.stocks AS SELECT * FROM stocks;
CREATE TABLE dev.daily_bars AS SELECT * FROM daily_bars WHERE date >= '2025-01-01';
CREATE TABLE dev.market_daily AS SELECT * FROM market_daily;
CREATE TABLE dev.zt_pool AS SELECT * FROM zt_pool;
CREATE TABLE dev.zt_previous AS SELECT * FROM zt_previous;
CREATE TABLE dev.lhb_records AS SELECT * FROM lhb_records;
CREATE TABLE dev.lhb_seats AS SELECT * FROM lhb_seats;
CREATE TABLE dev.etf_daily AS SELECT * FROM etf_daily WHERE date >= '2025-01-01';
CREATE TABLE dev.etf_holdings AS SELECT * FROM etf_holdings;
CREATE TABLE dev.screen_results AS SELECT * FROM screen_results;
EOF
ENDSSH

# 下载到本地
scp ubuntu@140.245.53.52:/tmp/quant_dev.db data/quant.db
```

> `data/*.db` 已在 `.gitignore` 中，不会被提交。

---

## 8. 开发工作流

```
本地写代码
    ↓
git push origin main
    ↓
GitHub Actions 自动 SSH 到云主机执行 git pull + 重启 API 服务
    ↓
约 30 秒后新代码生效
```

### 首次配置 GitHub Actions Secrets

在 GitHub 仓库 → Settings → Secrets and variables → Actions 中添加：

| Secret 名 | 值 |
|---|---|
| `ORACLE_HOST` | `140.245.53.52` |
| `ORACLE_USER` | `ubuntu` |
| `ORACLE_SSH_KEY` | 本机 SSH 私钥内容（`~/.ssh/id_rsa` 的完整文本） |

> 对应的公钥需要在云主机 `~/.ssh/authorized_keys` 中已存在。

---

## 9. 云主机运维参考

```bash
# 查看定时任务状态
systemctl status quant-daily.timer

# 手动触发一次数据更新
sudo systemctl start quant-daily

# 查看今日运行日志
tail -f /data/quant_research/logs/daily-run-$(date +%Y%m%d).log

# 查看 API 服务日志
tail -f /data/quant_research/logs/api_server.log

# 重启 API 服务
sudo systemctl restart quant-api

# 手动数据健康检查
cd /data/quant_research
/data/quant_research_venv/bin/python src/health_check.py --db data/quant.db --dry-run
```

---

## 10. 项目目录结构

```
ashare-quant/
├── src/
│   ├── api_server.py          # Flask API 服务（端口 8081，nginx 转发至 8080）
│   ├── health_check.py        # 每日数据健康检查 + 自动补全
│   ├── update_sqlite_data.py  # 主数据采集（日K、龙虎榜、市场情绪）
│   ├── update_zt_pool.py      # 涨停池采集
│   ├── update_etf.py          # ETF 行情采集
│   ├── update_shares.py       # 股本信息更新
│   ├── screener.py            # 选股引擎
│   ├── generate_report.py     # 静态报告生成
│   ├── quant_core.py          # 公共常量/工具
│   └── quant_db.py            # 数据库连接封装
├── deploy/
│   └── scripts/
│       └── quant-daily-run.sh # 每日定时脚本（同步到 logs/）
├── docs/
│   └── dev-setup.md           # 本文档
├── .github/
│   └── workflows/
│       └── deploy.yml         # 自动部署 CI/CD
├── data/                      # 数据库文件（不上传 Git）
│   ├── quant.db
│   └── README.md
└── reports/                   # 生成的静态 HTML 报告（不上传 Git）
```
