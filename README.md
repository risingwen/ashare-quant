# A股量化研究平台

基于 AkShare + SQLite 的 A 股数据研究平台，覆盖 1991 年至今全量日线数据，每个交易日自动更新并生成研究报告，通过 nginx 对外发布。

## 在线访问

```
http://140.245.53.52:8080/
```

| 页面 | 地址 | 说明 |
|---|---|---|
| 首页 | `/` | 情绪仪表盘 + 各模块入口 |
| 综合报告 | `/report.html` | 完整日报（榜单、回测、连板、人气） |
| 实时热榜 | `/hot_rank_iframe.html` | 四大平台人气热榜聚合 |

---

## 目录结构

```
/data/quant_research/
├── src/                        # 核心 Python 模块
│   ├── quant_core.py           # 涨跌停判断、通用工具
│   ├── quant_db.py             # SQLite 连接封装
│   ├── update_sqlite_data.py   # 每日数据更新（日线 + 人气榜 + 涨停池）
│   ├── backtest_new_high_volume.py  # 新高+量能策略回测引擎
│   ├── generate_report.py      # 报告生成（HTML / Markdown / JSON / CSV）
│   └── legacy_*/               # 旧 CSV/Parquet 脚本归档
├── scripts/
│   └── run_local_report.sh     # 手动触发报告生成
├── configs/
│   └── config.example.json     # 配置示例
├── docs/
│   └── IMPLEMENTATION_PLAN.md  # 实现规划文档
├── data/
│   └── quant.db                # SQLite 数据库（~2.6G，不上传 git）
├── reports/
│   ├── latest/                 # nginx 根目录，当前最新报告
│   │   ├── index.html
│   │   ├── report.html
│   │   ├── hot_rank_iframe.html
│   │   ├── summary.json
│   │   └── *.csv
│   └── YYYY-MM-DD/             # 历史归档
├── deploy/
│   └── scripts/
│       └── quant-daily-run.sh  # systemd 执行脚本模板，部署到 /data/quant_research/logs/
└── requirements.txt
```

---

## 服务器环境

| 项目 | 路径 / 说明 |
|---|---|
| 主机 | Oracle Cloud ARM64，新加坡区 |
| 公网 IP | `140.245.53.52` |
| Python 虚拟环境 | `/data/quant_research_venv` |
| 数据库 | `/data/quant_research/data/quant.db`（~2.6G） |
| nginx 配置 | `/etc/nginx/sites-available/quant_research_8080` |
| systemd service | `/etc/systemd/system/quant-daily.service` |
| systemd timer | `/etc/systemd/system/quant-daily.timer` |

---

## 数据库说明

| 表 | 内容 | 规模 |
|---|---|---|
| `daily_bars` | A 股全量日线（OHLCV + 换手率 + 涨跌幅） | ~1200 万行，1991 年至今 |
| `stocks` | 股票基础信息（名称、市场、ST 标记、可交易） | ~5900 只 |
| `popularity_rankings` | 东方财富每日人气 Top100 | 每日追加 |
| `limit_up_pool` | 东方财富每日涨停池 | 每日追加 |
| `strategy_backtests` | 策略回测汇总结果 | 3 条（每次回测覆盖） |
| `strategy_trades` | 策略回测逐笔交易明细 | ~4000 笔 |
| `data_quality_issues` | 数据质量问题记录 | ~6600 条 |

---

## 自动更新流程

每个工作日 **北京时间 19:45** 自动执行以下流水线：

```
1. update_sqlite_data.py    ← 增量拉取日线、人气榜、涨停池
2. backtest_new_high_volume.py  ← 重跑策略回测，更新 strategy_backtests
3. generate_report.py       ← 生成 HTML/MD/JSON/CSV 报告到 reports/latest/
```

nginx 直接服务 `reports/latest/`，报告更新后无需重启即可在线访问。

---

## 手动运维命令

### 查看 nginx

```bash
sudo systemctl status nginx
sudo nginx -t
sudo ss -ltnp | grep 8080
```

### 查看定时任务

```bash
systemctl list-timers --all | grep quant-daily
sudo systemctl status quant-daily.timer
sudo systemctl status quant-daily.service
```

### 手动触发整条流水线

```bash
sudo systemctl start quant-daily.service
sudo journalctl -u quant-daily.service -f
```

### 单独执行各步骤

```bash
# 1. 更新数据
/data/quant_research_venv/bin/python /data/quant_research/src/update_sqlite_data.py \
  --db /data/quant_research/data/quant.db \
  --daily-source sina --workers 8

# 2. 跑回测
/data/quant_research_venv/bin/python /data/quant_research/src/backtest_new_high_volume.py \
  --db /data/quant_research/data/quant.db \
  --report-dir /data/quant_research/reports/backtests \
  --start-date 2024-01-01

# 3. 生成报告
/data/quant_research_venv/bin/python /data/quant_research/src/generate_report.py \
  --db /data/quant_research/data/quant.db \
  --report-dir /data/quant_research/reports \
  --start-date 2024-01-01
```

### 历史数据回补

```bash
/data/quant_research_venv/bin/python /data/quant_research/src/update_sqlite_data.py \
  --db /data/quant_research/data/quant.db \
  --start-date 19900101 \
  --daily-source sina \
  --workers 8 \
  --backfill-history \
  --skip-popularity \
  --skip-limit-pool
```

---

## 策略回测说明

### 新高 + 量能策略（三个变体）

共同逻辑：信号日股价创历史新高 + 量能放大，次日开盘买入，跌破 5 日均线卖出或持有上限到期卖出。

| 策略 | 触发条件 | 市场过滤 | 最大持仓 | 当前结果（2024-2026） |
|---|---|---|---|---|
| `HH_VOL_MA5_BASE` | 近 20 日均量 2×，成交额 ≥5 亿 | 无 | 20 日 | 2505 笔，胜率 34.7%，批次总收益 **+3389%** |
| `HH_VOL_MA5_WARM_CYCLE` | 近 20 日均量 1.5×，成交额 ≥8 亿，涨幅 2%~9.5% | 暖/强市 | 20 日 | 1088 笔，胜率 34.3%，批次总收益 **-58%** |
| `HH_VOL_MA5_HOT_LEADER` | 近 60 日均量 1.2×，成交额 ≥10 亿，换手率 ≥3%，涨幅 ≥5% | 强市 | 30 日 | 526 笔，胜率 35.7%，批次总收益 **+68%** |

> 回测不含手续费、滑点，不处理涨跌停无法成交及资金重叠。`HH_VOL_MA5_HOT_LEADER` 回撤最小（-62%），最值得继续优化。

---

## 网络配置说明

Oracle 云端口 8080 已在 iptables 和 Security List 放行：

```bash
# 查看 iptables 规则
sudo iptables -L INPUT -n --line-numbers

# 规则持久化
sudo netfilter-persistent save
```

端口 80/443 由 `xray-linux-arm6`（代理服务）占用，nginx 使用 8080。

---

## Git 仓库

```
https://github.com/risingwen/ashare-quant
```

`.gitignore` 已排除 `data/*.db`（数据库大文件）和 `reports/*/`（生成内容）。代码变更后：

```bash
cd /data/quant_research
git add -A
git commit -m "描述变更内容"
git push origin master
```

---

## 后续规划

- [ ] 龙虎榜数据采集与展示页面
- [ ] 市场温度专题（历史情绪分走势、板块轮动热力图）
- [ ] 人气榜历史规律分析（上榜后次日表现统计）
