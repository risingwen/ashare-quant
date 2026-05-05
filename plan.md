# A股量化研究平台运营计划

更新时间：2026-05-04

## 1. 总目标

- Oracle 云主机（140.245.53.52:8080）持续运行 A 股量化研究平台
- 每个工作日 19:45（北京时间）自动采集当日数据并更新报告
- 通过 nginx 对外提供：行情分析、情绪指数、ETF 雷达、龙虎榜等页面

## 2. 技术架构

| 组件 | 说明 |
|------|------|
| 数据库 | SQLite WAL 模式，`/data/quant_research/data/quant.db` |
| 行情来源 | 沪深：mootdx TCP（119.147.212.81:7709）；BSE：akshare/东财 |
| ETF 来源 | akshare 东财 |
| 龙虎榜 | akshare 东财 |
| 人气榜 | 东财 `stock_hot_rank_em` |
| 报告生成 | `generate_report.py` → 静态 HTML → nginx |
| 定时任务 | `quant-daily.timer`，Mon-Fri UTC 11:45 |
| Python 环境 | `/data/quant_research_venv`，akshare 1.18.60，mootdx 0.11.7 |

## 3. 数据范围约定

- **时间范围**：2025-01-01 至今（不保留更早历史）
- **股票市场**：沪深主板、创业板、科创板、北交所（BSE）
- **北交所代码规则**：2024 年 4 月起全部迁移为 `92xxxx` 格式

## 4. 数据库 stocks 表现状（2026-05-04）

| 市场 | 数量 | 说明 |
|------|------|------|
| Mainboard | 3354 | 沪深主板 |
| ChiNext | 1429 | 创业板 |
| STAR | 610 | 科创板 |
| BSE | 312 | 北交所，全部为 `92xxxx` 新代码 |
| Other | 2 | 其他 |

## 5. BSE 数据采集方案

- **可用接口**：`akshare.stock_zh_a_hist(symbol=92xxxx, adjust="")`
  - 底层映射 `secid=0.92xxxx`，东财正确识别
  - 数据范围：2025-01-01 至今，最新至上一个交易日
- **路由逻辑**（`update_sqlite_data.py`）：
  - `--daily-source mootdx` + market=BSE + code 以 `9` 开头 → `fetch_daily_akshare`
  - 其他前缀（已无）→ skip
- **代码迁移历史**：
  - 北交所于 2024 年 4 月将 `43xxxx/83xxxx/87xxxx` 全部迁移为 `92xxxx`
  - 2026-05-04 已完成 stocks 表和 daily_bars 全量迁移，246 只旧代码替换为新代码

## 6. daily_bars 现状（2026-05-04）

- 数据范围：2025-01-01 ~ 2026-04-30
- 沪深（mootdx 来源）：覆盖 Mainboard/ChiNext/STAR 全量
- BSE（akshare 来源）：312 只，全部有 2025-01-01 起数据

## 7. 关键文件

| 文件 | 说明 |
|------|------|
| `src/update_sqlite_data.py` | 日线数据采集主脚本；含 `fetch_daily_mootdx`、`fetch_daily_akshare`、`fetch_daily_df` 路由 |
| `src/generate_report.py` | HTML 报告生成；情绪分、ETF 雷达、龙虎榜、行情汇总 |
| `src/update_etf.py` | ETF 专项采集，`--min-amount 5000`（万） |
| `src/backfill_lhb.py` | 龙虎榜历史补采 |
| `src/quant_db.py` | DB schema 定义 |
| `logs/quant-daily-run.sh` | 定时任务执行脚本 |
| `/etc/systemd/system/quant-daily.timer` | `OnCalendar=Mon..Fri 11:45` (UTC) |

## 8. 报告页面

| 页面 | URL |
|------|-----|
| 首页/行情 | http://140.245.53.52:8080/ |
| 情绪指数 | http://140.245.53.52:8080/emotion.html |
| ETF 雷达 | http://140.245.53.52:8080/etf.html |
| 龙虎榜 | http://140.245.53.52:8080/longhu.html |

## 9. 关键配置参数

- **情绪分公式**：`score = ADR×40 + min(lu_rate/0.03,1)×40 - min(ld_rate/0.02,1)×20`
- **涨跌家数**：展示用全量口径，情绪分 ADR 用 eligible 口径
- **ETF 展示过滤**：采集 ≥5000 万成交额；页面展示 ≥5 亿；30 天价格区间 <1% 自动剔除
- **A 股配色**：涨红 `#e84c3d`，跌绿 `#07a071`

## 10. 下一步方向

1. 龙虎榜页面增强：席位明细展开、营业部维度页、多日切换
2. ETF 持仓 Top10 展示（待采集完成）
3. 板块轮动热力图（emotion.html 扩展）
