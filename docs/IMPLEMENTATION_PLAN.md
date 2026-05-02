# A 股人气股量化研究优化方案

## 目标

把旧的临时脚本升级为一个可迁移到 Oracle ARM 主机的轻量量化研究系统，覆盖数据更新、数据质量检查、人气股统计、历史新高放量策略回测和日报发布。

## 核心决策

- 放弃 CSV 作为主数据层。
- 旧 CSV 只作为一次性导入源。
- 主数据库使用 `data/quant.db`。
- 报告、策略回测、候选股输出全部从 SQLite 读取。
- 2024、2025、2026 年作为当前重点统计区间。
- 历史新高基于数据库内已回补的前复权日线，目前覆盖 `1991-01-14` 到 `2026-04-30`。

## 当前已经实现

- `src/build_sqlite_from_csv.py`：把旧 CSV 导入 SQLite。
- `src/update_sqlite_data.py`：通过 AkShare 补全最新日线、人气榜和涨停池。
- `src/backtest_new_high_volume.py`：回测三套“历史新高 + 放量 + 跌破 5 日线卖出”策略。
- `src/generate_report.py`：从 SQLite 生成 HTML、Markdown、JSON、CSV 报告。
- `scripts/package_project.sh`：打包迁移到 Oracle 主机。

## 数据状态

- 数据库：`data/quant.db`。
- 日线范围：`1991-01-14` 到 `2026-04-30`。
- 日线总行数：约 `1202.9` 万行。
- 2024 年：约 `123.8` 万行，`5417` 只股票。
- 2025 年：约 `124.4` 万行，`5175` 只股票。
- 2026 年：约 `39.8` 万行，`5200` 只股票。
- 最新人气榜：东方财富人气榜 `100` 条。
- 最新涨停池：东方财富涨停池 `79` 条。

## 数据补全方案

### 日线数据

优先使用 AkShare 新浪日线接口 `stock_zh_a_daily`，原因是批量刷新时比东方财富 `stock_zh_a_hist` 更稳定。

增量更新：

```bash
/LocalRun/xiwen.xing/01_envs/quant_research/bin/python src/update_sqlite_data.py --db data/quant.db --daily-source sina --workers 8
```

历史回补：

```bash
/LocalRun/xiwen.xing/01_envs/quant_research/bin/python src/update_sqlite_data.py --db data/quant.db --start-date 19900101 --daily-source sina --workers 8 --backfill-history --skip-popularity --skip-limit-pool
```

### 人气股数据

当前使用 AkShare `stock_hot_rank_em` 写入 `popularity_rankings`。

注意：人气榜接口返回日期按自然日记录，报告会自动匹配最近交易日行情。

### 涨停池数据

使用 AkShare `stock_zt_pool_em` 写入 `limit_up_pool`，包含连板数、封板时间、封单资金、涨停原因。

## 市场周期定义

周期过滤基于每日全市场情绪分：

- 涨停数量。
- 跌停数量。
- 上涨家数占比。
- 综合情绪分。

周期状态：

- `cold`：弱周期，不适合追新高放量。
- `warm`：暖周期，可以做趋势型新高。
- `hot`：强周期，只做最强成交额/换手龙头。

## 策略股票池

- 纳入主板、创业板、科创板。
- 排除名称包含 ST、PT、退市的股票。
- 北交所暂不纳入第一版策略池，避免 30cm 涨跌幅规则影响主统计。
- 信号日收盘后选股，下一交易日开盘买入。
- 卖出规则为收盘跌破 5 日均线，设置最大持有日作为兜底。

## 三套历史新高放量策略

### 策略一：`HH_VOL_MA5_BASE`

定义：

- 可用历史收盘新高。
- 当日成交量大于过去 20 日均量 2 倍。
- 当日成交额不低于 5 亿。
- 当日涨幅不低于 1%。
- 每日最多选 10 只，按成交额、量比、周期分排序。
- 次日开盘买入，收盘跌破 5 日线卖出，最多持有 20 日。

2024-2026 回测结果：

- 交易数：2505。
- 信号日：481。
- 胜率：34.65%。
- 单笔平均收益：0.61%。
- 单笔中位数：-2.61%。
- 批次复利收益：3389.13%。
- 最大回撤：-97.58%。
- 平均持有：4.03 日。

结论：收益来自少数右尾大牛股，基础版回撤极大，不适合作为直接交易策略。

### 策略二：`HH_VOL_MA5_WARM_CYCLE`

定义：

- 可用历史收盘新高。
- 当日成交量大于过去 20 日均量 1.5 倍。
- 当日成交额不低于 8 亿。
- 当日涨幅在 2%-9.5%。
- 市场处于暖周期或强周期。
- 每日最多选 8 只。
- 次日开盘买入，收盘跌破 5 日线卖出，最多持有 20 日。

2024-2026 回测结果：

- 交易数：1088。
- 信号日：240。
- 胜率：34.28%。
- 单笔平均收益：0.42%。
- 单笔中位数：-2.50%。
- 批次复利收益：-58.25%。
- 最大回撤：-93.24%。
- 平均持有：3.86 日。

结论：暖周期过滤减少了机会，但没有改善收益/回撤结构，不建议作为主策略。

### 策略三：`HH_VOL_MA5_HOT_LEADER`

定义：

- 可用历史收盘新高。
- 当日成交量大于过去 60 日均量 1.2 倍。
- 当日成交额不低于 10 亿。
- 当日换手率不低于 3%。
- 当日涨幅不低于 5%。
- 市场处于强周期。
- 每日最多选 5 只。
- 次日开盘买入，收盘跌破 5 日线卖出，最多持有 30 日。

2024-2026 回测结果：

- 交易数：526。
- 信号日：126。
- 胜率：35.74%。
- 单笔平均收益：0.65%。
- 单笔中位数：-3.06%。
- 批次复利收益：68.08%。
- 最大回撤：-61.95%。
- 平均持有：4.24 日。

结论：这是当前三套里最值得继续优化的方向，收益为正且回撤显著小于基础版，但还不能直接实盘。

## 当前策略建议

- 暂不直接使用 `HH_VOL_MA5_BASE`，因为最大回撤过大。
- 放弃 `HH_VOL_MA5_WARM_CYCLE` 当前版本。
- 重点优化 `HH_VOL_MA5_HOT_LEADER`。
- 下一轮加入真实人气榜交集过滤，例如“历史新高放量 + 人气榜前 50 + 强周期”。
- 下一轮加入涨停池/连板题材过滤，例如“历史新高放量 + 所属题材有涨停扩散”。
- 必须加入交易成本、滑点、涨停无法买入、跌停无法卖出、持仓重叠资金占用。

## 报告内容

`report.html` 和 `report.md` 包含：

- 数据范围和生成时间。
- 最新市场情绪分。
- 涨停/跌停数量、上涨比例、成交额。
- 历史新高放量三策略回测摘要。
- 东方财富人气榜。
- 东方财富涨停池。
- 最新交易日热度候选股。
- 成交额 Top N 池历史次日表现。
- 涨停池历史次日表现。
- 连板高度对应的次日晋级率和收益。
- 数据质量摘要。

## 本机执行步骤

```bash
cd /home/xiwen.xing/quant_research
/LocalRun/xiwen.xing/01_envs/quant_research/bin/python src/backtest_new_high_volume.py --db data/quant.db --report-dir reports/backtests --start-date 2024-01-01
/LocalRun/xiwen.xing/01_envs/quant_research/bin/python src/generate_report.py --db data/quant.db --report-dir reports --start-date 2024-01-01
```

## Oracle 主机执行步骤

```bash
cd /opt
tar -xzf quant_research.tar.gz
cd quant_research
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python src/update_sqlite_data.py --db data/quant.db --daily-source sina --workers 8
.venv/bin/python src/backtest_new_high_volume.py --db data/quant.db --report-dir reports/backtests --start-date 2024-01-01
.venv/bin/python src/generate_report.py --db data/quant.db --report-dir reports --start-date 2024-01-01
```

## 成功标准

- CSV 只作为导入源，不再作为主分析数据层。
- SQLite 覆盖 2024、2025、2026 年主要 A 股日线。
- 本机可以完成三策略回测并把收益率写入报告。
- 人气榜和涨停池能写入报告。
- Oracle 主机只需解包、安装依赖、配置 cron/nginx 即可运行。
